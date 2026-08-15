"""M3 串行调度器（REQ-M3 §2.2 调度器、§3 执行流程、§4.6 用例结果汇总、§7 状态机/中断）.

引擎主循环（串行，引擎线程私有，无锁）::

    加载环境配置 → 打开端口 → [用例 setup→steps→teardown]×N → 关闭端口 → 聚合结果

极简控制：start/stop（§7.2）。stop(mode) 设置停止标志，在步骤边界响应。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from atprobe.domain.case.models import Case
from atprobe.domain.report.aggregator import aggregate
from atprobe.domain.report.models import (
    CaseResult,
    CaseStatus,
    ExecutionResult,
    StepResult,
    StepStatus,
    Summary,
)
from atprobe.engine.config import EngineConfig, EngineState, StopMode
from atprobe.engine.interfaces import (
    CaseResultEvent,
    CaseStartEvent,
    EngineFinishedEvent,
    PressureProgressEvent,
    StepResultEvent,
)
from atprobe.engine.pressure import run_pressure
from atprobe.engine.step_runner import CaseContext, StepExecResult, execute_step
from atprobe.infra.config.envconfig import EnvConfig
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import CancelToken, ICommandSender
from atprobe.infra.serial.portmanager import PortManager
from atprobe.infra.serial.rawlog import RawLogger

_log = logging.getLogger("atprobe.engine")


class Engine:
    """测试执行引擎（M3 §1）."""

    def __init__(
        self,
        sender_factory: Callable[[], ICommandSender] | None = None,
        raw_logger: RawLogger | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # 默认用 PortManager 作为 sender；测试可注入 FakeSender
        self._sender_factory = sender_factory
        # raw_logger 由外部注入时，生命周期由外部管理；为 None 时 start 时自动创建并管理
        self._raw_logger = raw_logger
        self._owns_raw_logger = raw_logger is None  # 未注入 → start 时自建
        self._clock = clock
        self._sleep = sleep

        self._state = EngineState.IDLE
        self._stop_mode: StopMode | None = None
        self._stop_flag = threading.Event()
        self._cancel_token: CancelToken | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # §7.2 接口
    # ------------------------------------------------------------------
    def state(self) -> EngineState:
        return self._state

    def stop(self, mode: StopMode = StopMode.CURRENT) -> None:
        with self._lock:
            self._stop_mode = mode
            self._stop_flag.set()
            if self._cancel_token is not None:
                self._cancel_token.cancel()

    # ------------------------------------------------------------------
    # start（阻塞执行）
    # ------------------------------------------------------------------
    def start(
        self, config: EngineConfig, handler: Callable[[object], None] | None = None
    ) -> ExecutionResult:
        self._state = EngineState.RUNNING
        self._stop_flag.clear()
        self._stop_mode = None

        # 记录执行起始时间（单调钟算耗时 + 墙钟记时间区间，供报告追溯）
        t_start = self._clock()
        dt_start = datetime.now()

        # 原始日志记录器：未注入则自建（REQ-M1 §7，运行时自动落盘 TX/RX 字节流）
        if self._owns_raw_logger and self._raw_logger is None:
            self._raw_logger = RawLogger()
        if self._raw_logger is not None:
            self._raw_logger.start()

        sender, port_manager = self._resolve_sender(config)
        cancel = CancelToken()
        self._cancel_token = cancel

        # §2.2 step 3: 打开端口
        # 记录本次执行前已连接的端口（外部已开，如 GUI 手动连接/监控的端口），
        # finally 只关闭本次新开的端口，避免破坏外部连接状态。
        ports_opened: list[str] = []
        try:
            for pc in config.ports:
                already_open = port_manager.is_connected(pc.name)  # type: ignore[union-attr]
                # M4 修复：仅当端口未在外部打开时才 open，避免对 GUI 已连端口复用时抛错。
                # （PortManager.open 已改为幂等，但跳过 open 更语义清晰且省一次锁。）
                if not already_open:
                    port_manager.open(pc)  # type: ignore[union-attr]
                    ports_opened.append(pc.name)
        except Exception as exc:  # 端口打开失败
            # 单端口失败不一定是致命；全部失败才是 ERROR（§7.5 场景C）
            if not any(port_manager.is_connected(p) for p in [pc.name for pc in config.ports]):  # type: ignore[union-attr]
                self._state = EngineState.ERROR
                if self._owns_raw_logger and self._raw_logger is not None:
                    self._raw_logger.stop()
                return self._error_result(config, f"端口打开失败：{exc}")

        default_port = config.ports[0].name if config.ports else ""

        case_results: list[CaseResult] = []
        session = config.session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(config.log_dir)
        engine_error: str = ""  # P1 修复：主循环兜底异常记录（见下方 except）

        try:
            # 套件级前置（REQ-M2 §12.2）：cases 循环前执行一次。用独立 CaseContext
            # （与用例变量池隔离，但 setup 各步共享同一 ctx 以便 extract 传递）。
            # cancel=cancel 响应停止；失败 → 不继续 cases（但仍执行 teardown）
            suite_setup_failed = False
            suite_setup_results: list[StepResult] = []
            suite_setup_ctx = CaseContext(
                env=config.env_config if isinstance(config.env_config, EnvConfig) else None
            )
            for i, step in enumerate(config.suite_setup, start=1):
                if self._stop_mode is StopMode.ALL:
                    suite_setup_failed = True
                    break
                if cancel.cancelled:  # P3 修复：suite_setup 也响应取消
                    suite_setup_failed = True
                    break
                r = execute_step(
                    step,
                    index=i,
                    phase="suite_setup",
                    ctx=suite_setup_ctx,
                    sender=sender,
                    default_port=default_port,
                    step_timeout_default=config.step_timeout_default,
                    clock=self._clock,
                    sleep=self._sleep,
                    cancel=cancel,
                )
                suite_setup_results.append(r.step_result)
                self._emit_step(handler, r)
                if (
                    r.abort_case
                ):  # suite_setup 失败 → 跳过 cases（StepResult 仅记录，不进 aggregate）
                    suite_setup_failed = True
                    break

            if not suite_setup_failed:
                # P1 修复（参数化下沉引擎入口）：GUI 路径绕过 CLI 的 _expand_parameters
                # 直接传原始 Case，旧实现 scheduler 只取 parameters[0]，多行参数静默
                # 丢弃（只跑第一行）。在引擎入口统一展开：多行 parameters 展开为带
                # param_index 的独立实例；CLI 已展开的单行实例（param_index 已置）
                # 原样通过，不重复展开。
                expanded_cases: list[Case] = []
                for c in config.cases:
                    if c.parameters and len(c.parameters) > 1:
                        for i, row in enumerate(c.parameters, start=1):
                            expanded_cases.append(
                                c.model_copy(update={"parameters": (row,), "param_index": i})
                            )
                    else:
                        expanded_cases.append(c)
                for idx, case in enumerate(expanded_cases, start=1):
                    if self._stop_mode is StopMode.ALL:
                        break
                    if self._stop_flag.is_set() and self._stop_mode is StopMode.CURRENT:
                        # B1 修复：中断当前用例后，重建 cancel token 让后续用例能正常执行。
                        # 旧实现只清 stop_flag/stop_mode，但 cancel token 仍 cancelled=True，
                        # 后续用例的 execute_step 一进 _run_retry/_run_poll 就 raise
                        # OperationCancelled → 所有后续用例被判 INTERRUPTED，"继续后续"
                        # 语义完全失效。重建 token 后传给 _run_case（需覆盖外层 cancel 变量）。
                        self._stop_flag.clear()
                        self._stop_mode = None
                        cancel = CancelToken()
                        self._cancel_token = cancel

                    if handler is not None:
                        handler(
                            CaseStartEvent(
                                case_name=case.name,
                                case_index=idx,
                                total_cases=len(expanded_cases),
                                case_type="pressure" if case.is_pressure else "regular",
                            )
                        )

                    cr = self._run_case(
                        case,
                        idx,
                        config,
                        sender,
                        port_manager,
                        default_port,
                        cancel,
                        log_dir,
                        session,
                        handler,
                    )
                    case_results.append(cr)
                    if handler is not None:
                        handler(
                            CaseResultEvent(
                                case_name=case.name,
                                status=cr.status.value,
                                duration_ms=cr.duration_ms,
                                error_msg=cr.error_msg,
                                case_index=idx,
                            )
                        )

            # 套件级后置（REQ-M2 §12.2）：cases 循环后执行一次（在 finally 关闭端口之前，
            # 确保 teardown 命令发往仍打开的端口）。无条件执行，失败仅记警告
            # （is_teardown=True + try/except 吞掉异常，与用例 teardown 语义一致）。
            # cancel=None（不响应取消）；StepResult 进 ExecutionResult 供报告诊断。
            suite_teardown_results: list[StepResult] = []
            suite_teardown_ctx = CaseContext(
                env=config.env_config if isinstance(config.env_config, EnvConfig) else None
            )
            for i, step in enumerate(config.suite_teardown, start=1):
                try:
                    r = execute_step(
                        step,
                        index=i,
                        phase="suite_teardown",
                        ctx=suite_teardown_ctx,
                        sender=sender,
                        default_port=default_port,
                        step_timeout_default=config.step_timeout_default,
                        clock=self._clock,
                        sleep=self._sleep,
                        cancel=None,
                        is_teardown=True,
                    )
                    suite_teardown_results.append(r.step_result)
                    self._emit_step(handler, r)
                except Exception:  # noqa: BLE001 - suite_teardown 失败仅记录，不影响结果
                    _log.debug("suite_teardown 步骤执行异常", exc_info=True)
        except Exception as exc:  # noqa: BLE001 - P1 修复：引擎主循环兜底
            # 旧实现此层只有 finally：任意非 OperationCancelled 异常（第三方 sender
            # 缺陷、渲染路径漏洞等）直接逃出 start() → _state 永久卡 RUNNING、
            # 无 EngineFinishedEvent、聚合结果丢失（GUI 永远显示"运行中"）。
            # 兜底后状态机必须终结：记错误 → 走统一结果构建（finally 已关端口）。
            engine_error = f"引擎内部错误：{exc!r}"
        finally:
            # 只关闭本次执行新打开的端口（外部已连接的端口保持不动，
            # 避免破坏 GUI 监控/手动调试的连接与订阅状态）
            try:
                for p in ports_opened:
                    port_manager.close(p)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            # 停止原始日志记录器，确保缓冲落盘（仅 Engine 自建的才停，外部注入的由外部管理）
            if self._owns_raw_logger and self._raw_logger is not None:
                self._raw_logger.stop()

        # 兜底路径：异常已记录 → 状态机终结 + 发结束事件 + 结果带 error 返回
        # （已完成的用例结果仍保留在报告里，不因兜底而丢弃）
        if engine_error:
            summary = aggregate(
                case_results,
                start_time=dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                duration_ms=(self._clock() - t_start) * 1000.0,
            )
            if handler is not None:
                handler(EngineFinishedEvent(summary=summary))
            self._state = EngineState.ERROR
            return ExecutionResult(
                summary=summary, case_results=tuple(case_results), error=engine_error
            )

        # 计算本次执行的耗时与时间区间（P1-1：之前始终为空/0，报告无法追溯执行时刻）
        dt_end = datetime.now()
        duration_ms = (self._clock() - t_start) * 1000.0
        summary = aggregate(
            case_results,
            start_time=dt_start.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=dt_end.strftime("%Y-%m-%d %H:%M:%S"),
            duration_ms=duration_ms,
        )
        env_snap = self._env_snapshot(config)
        # suite 前后置结果（try 块内收集；非套件执行或提前异常时为空）
        ss_results = tuple(locals().get("suite_setup_results", ()))
        st_results = tuple(locals().get("suite_teardown_results", ()))
        result = ExecutionResult(
            summary=summary,
            case_results=tuple(case_results),
            env_snapshot=env_snap,
            suite_setup_results=ss_results,
            suite_teardown_results=st_results,
        )
        if handler is not None:
            handler(EngineFinishedEvent(summary=summary))
        self._state = EngineState.FINISHED
        return result

    # ------------------------------------------------------------------
    # 单用例执行
    # ------------------------------------------------------------------
    def _run_case(
        self,
        case: Case,
        idx: int,
        config: EngineConfig,
        sender: ICommandSender,
        port_manager: Any,
        default_port: str,
        cancel: CancelToken,
        log_dir: Path,
        session: str,
        handler: Callable[[object], None] | None,
    ) -> CaseResult:
        t0 = self._clock()
        ctx = CaseContext(
            env=config.env_config if isinstance(config.env_config, EnvConfig) else None
        )
        # 参数化注入（M2 §10.2）：参数行注入用例级变量作用域（最高优先级）
        if case.parameters:
            for k, v in case.parameters[0].items():
                ctx.variables[k] = v

        ports_used: set[str] = set()
        setup_results: list[StepResult] = []
        step_results: list[StepResult] = []
        teardown_results: list[StepResult] = []
        error_msg = ""
        status = CaseStatus.PASS
        pressure_stats: Any = None  # 压测分支填充，统一在 finally 之后 build

        # 绑定用例日志文件
        self._bind_case_logs(case, port_manager, log_dir, session, default_port)

        try:
            # §3.2 流程A setup
            setup_failed = False
            for i, step in enumerate(case.setup, start=1):
                if cancel.cancelled:  # P3 修复：与 steps 循环一致的前置取消检查
                    break
                r = execute_step(
                    step,
                    index=i,
                    phase="setup",
                    ctx=ctx,
                    sender=sender,
                    default_port=default_port,
                    step_timeout_default=config.step_timeout_default,
                    case_on_failure=case.on_failure,
                    clock=self._clock,
                    sleep=self._sleep,
                    cancel=cancel,
                )
                setup_results.append(r.step_result)
                ports_used.add(r.step_result.port)
                self._emit_step(handler, r)
                # setup 步骤失败或被 skip（on_failure:skip）都视为前提未满足 → 跳过用例
                # （REQ-M2 §7：setup 失败一律跳过整个用例；skip 说明该前提步骤未成功）
                if r.status in (StepStatus.FAIL, StepStatus.SKIPPED):
                    setup_failed = True
                    # P3 修复：error_msg 带首个失败步骤的具体原因（旧实现只报"setup 失败"）
                    if r.step_result.error_msg:
                        error_msg = f"setup 失败（步骤 {i}）：{r.step_result.error_msg}"
                    break
                # §4.2 连续断连安全阀：达到阈值则放弃用例
                if self._hit_disconnect_safety(r.step_result, ctx, port_manager):
                    setup_failed = True
                    error_msg = "连续断连达到安全阀，放弃用例"
                    break

            if setup_failed:
                status = CaseStatus.SKIPPED
                # P3 修复：保留循环里已写的具体原因（步骤级错误/断连安全阀），
                # 仅无详情时用泛化文案
                if not error_msg:
                    error_msg = "setup 失败"
            elif case.is_pressure:
                # §3.3 流程B 压测
                def on_progress(rnd, total, suc, fail, avg):  # type: ignore[no-untyped-def]
                    if handler is not None:
                        handler(
                            PressureProgressEvent(
                                case_name=case.name,
                                current_round=rnd,
                                total_rounds=total,
                                success=suc,
                                fail=fail,
                                avg_ms=avg,
                            )
                        )

                pr = run_pressure(
                    case,
                    ctx=ctx,
                    sender=sender,
                    default_port=default_port,
                    step_timeout_default=config.step_timeout_default,
                    pass_threshold=config.pressure_pass_threshold,
                    clock=self._clock,
                    sleep=self._sleep,
                    cancel=cancel,
                    on_progress=on_progress,
                )
                if pr.aborted and cancel.cancelled:
                    status = CaseStatus.INTERRUPTED
                    error_msg = "被中断"
                elif pr.aborted and pr.abort_reason == "abort_on_failure":
                    # P2 修复：区分「按 abort_on_failure 主动中止」与「阈值不达标」
                    status = CaseStatus.FAIL
                    error_msg = (
                        f"压测按 abort_on_failure 中止（成功率 {pr.stats.success_rate:.1f}%，"
                        f"阈值 {pr.stats.pass_threshold:.1f}%）"
                    )
                elif pr.stats.passed:
                    status = CaseStatus.PASS
                else:
                    status = CaseStatus.FAIL
                    error_msg = f"压测成功率 {pr.stats.success_rate:.1f}% 低于阈值 {pr.stats.pass_threshold:.1f}%"
                # P1 修复：不再在 try 内 return——旧实现 CaseResult 快照在 finally
                # 的 teardown 之前求值，teardown 结果/端口/耗时不进报告（与常规
                # 路径行为不一致）。落空到函数末尾统一 build（finally 之后）。
                # 压测明细在 pressure_stats；step_results 保持空（见 stats）。
                pressure_stats = pr.stats
            else:
                # §3.2 流程A steps
                aborted = False
                for i, step in enumerate(case.steps, start=1):
                    if cancel.cancelled:
                        aborted = True
                        break
                    r = execute_step(
                        step,
                        index=i,
                        phase="steps",
                        ctx=ctx,
                        sender=sender,
                        default_port=default_port,
                        step_timeout_default=config.step_timeout_default,
                        case_on_failure=case.on_failure,
                        clock=self._clock,
                        sleep=self._sleep,
                        cancel=cancel,
                    )
                    step_results.append(r.step_result)
                    ports_used.add(r.step_result.port)
                    self._emit_step(handler, r)
                    # §4.2 连续断连安全阀：达到阈值则放弃用例
                    if self._hit_disconnect_safety(r.step_result, ctx, port_manager):
                        aborted = True
                        error_msg = "连续断连达到安全阀，放弃用例"
                        break
                    if r.status is StepStatus.FAIL and r.abort_case:
                        aborted = True
                        error_msg = r.step_result.error_msg
                        break
                if cancel.cancelled:
                    status = CaseStatus.INTERRUPTED
                    error_msg = "被中断"
                elif aborted:
                    status = CaseStatus.FAIL
                else:
                    any_fail = any(s.status is StepStatus.FAIL for s in step_results)
                    status = CaseStatus.FAIL if any_fail else CaseStatus.PASS

        except OperationCancelled:
            status = CaseStatus.INTERRUPTED
            error_msg = "被中断"
        finally:
            # §3.2 teardown（无条件执行，失败不影响结果）
            for i, step in enumerate(case.teardown, start=1):
                try:
                    r = execute_step(
                        step,
                        index=i,
                        phase="teardown",
                        ctx=ctx,
                        sender=sender,
                        default_port=default_port,
                        step_timeout_default=config.step_timeout_default,
                        clock=self._clock,
                        sleep=self._sleep,
                        cancel=None,  # teardown 不响应取消
                        is_teardown=True,
                    )
                    teardown_results.append(r.step_result)
                    ports_used.add(r.step_result.port)
                    # P2 修复：teardown 步骤也发 StepResultEvent（setup/steps 均发，
                    # 旧实现 GUI 进度面板看不到 teardown 执行）
                    self._emit_step(handler, r)
                except Exception:  # noqa: BLE001 - teardown 失败仅记录
                    _log.debug("teardown 步骤执行异常", exc_info=True)
            self._unbind_case_logs(port_manager)

        return self._build_case_result(
            case,
            idx,
            status,
            setup_results,
            step_results,
            teardown_results,
            t0,
            ports_used,
            error_msg,
            pressure=pressure_stats,
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _resolve_sender(self, config: EngineConfig) -> tuple[ICommandSender, Any]:
        if self._sender_factory is not None:
            sender = self._sender_factory()
            # 注入 sender 也需实现连接管理；测试用 FakePortManager
            return sender, sender
        pm = PortManager(raw_logger=self._raw_logger, clock=self._clock, sleep=self._sleep)
        return pm, pm

    def _bind_case_logs(
        self, case: Case, port_manager: Any, log_dir: Path, session: str, default_port: str
    ) -> None:
        if self._raw_logger is None or port_manager is None:
            return
        if not hasattr(port_manager, "set_case_log"):
            return
        # P2 修复：参数化实例的日志名带 #N 后缀（与报告 display_name 一致）——
        # 旧实现所有实例共用 case.name，多实例原始日志互相追加/覆盖污染。
        log_name = case.name
        if case.param_index is not None:
            log_name = f"{case.name}#{case.param_index}"
        for pc in self._case_ports(case, default_port):
            lf = self._raw_logger.begin_case(log_dir, session, pc, log_name)
            port_manager.set_case_log(pc, lf)

    def _unbind_case_logs(self, port_manager: Any) -> None:
        if port_manager is None or not hasattr(port_manager, "clear_case_log"):
            return
        # 清理由 _run_case 在下次 _bind 时覆盖；此处不强制清

    def _case_ports(self, case: Case, default_port: str = "") -> list[str]:
        """收集本用例实际执行会用到的端口（用于绑定用例级原始日志）.

        以 ``default_port``（执行配置端口，如 GUI 选的 / CLI --port）为基础，叠加步骤
        显式指定的 ``step.port``。**不使用 ``case.port``**——它在执行流里不影响实际发送
        端口（步骤用 ``step.port or default_port``），若用它会导致日志目录建到错误端口
        名下（如用例硬编码 COM5，实际执行 COM28 时日志目录错建为 COM5 且可能失败）。
        """
        ports: list[str] = []
        if default_port:
            ports.append(default_port)
        for s in case.steps:
            if s.port and s.port not in ports:
                ports.append(s.port)
        return ports

    def _emit_step(self, handler: Callable[[object], None] | None, r: StepExecResult) -> None:
        if handler is None:
            return
        sr = r.step_result
        handler(
            StepResultEvent(
                step_index=sr.step_index,
                phase=sr.phase,
                status=sr.status.value,
                duration_ms=sr.duration_ms,
                port=sr.port,
                command=sr.command,
                extracted_vars=dict(sr.extracted_vars),
                error_msg=sr.error_msg,
                retry_count=sr.retry_count,
                poll_iterations=sr.poll_iterations,
                response=sr.response,
            )
        )

    def _hit_disconnect_safety(self, sr: StepResult, ctx: CaseContext, port_manager: Any) -> bool:
        """§4.2 连续断连安全阀：维护 ctx.disconnect_streak，达阈值返回 True（应放弃用例）.

        判定依据：步骤失败且 error_kind == "DISCONNECT"（M3 修复：基于结构化错误分类，
        而非脆弱的 error_msg 中文字符串匹配）。阈值取该端口 PortConfig.reconnect_
        safety_threshold（默认 3）。成功步骤重置计数。
        """
        is_disconnect_err = sr.status is StepStatus.FAIL and sr.error_kind == "DISCONNECT"
        if not is_disconnect_err:
            if sr.status is not StepStatus.FAIL:
                ctx.disconnect_streak = 0
            return False
        ctx.disconnect_streak += 1
        threshold = 3  # 默认安全阀（REQ-M1 §4.2）
        try:
            cfg = port_manager.config_of(sr.port)  # type: ignore[union-attr]
            threshold = getattr(cfg, "reconnect_safety_threshold", threshold)
        except Exception:  # noqa: BLE001 - 无端口配置则用默认阈值
            pass
        return ctx.disconnect_streak >= threshold

    def _build_case_result(
        self,
        case: Case,
        idx: int,
        status: CaseStatus,
        setup_results: list[StepResult],
        step_results: list[StepResult],
        teardown_results: list[StepResult],
        t0: float,
        ports_used: set[str],
        error_msg: str,
        pressure: Any,
    ) -> CaseResult:
        duration_ms = (self._clock() - t0) * 1000.0
        display_name = case.name
        if case.param_index is not None:
            display_name = f"{case.name}#{case.param_index}"
        return CaseResult(
            case_name=display_name,
            case_file=case.source_file or "",
            tags=case.tags,
            ports=tuple(sorted(ports_used)),
            status=status,
            is_pressure=case.is_pressure,
            setup_results=tuple(setup_results),
            step_results=tuple(step_results),
            teardown_results=tuple(teardown_results),
            pressure_stats=pressure,
            duration_ms=duration_ms,
            error_msg=error_msg,
        )

    def _env_snapshot(self, config: EngineConfig) -> dict[str, dict[str, object]]:
        if not config.report_env_snapshot:
            return {}
        env = config.env_config
        if not isinstance(env, EnvConfig):
            return {}
        return {g: dict(p) for g, p in env.groups().items()}

    def _error_result(self, config: EngineConfig, msg: str) -> ExecutionResult:
        # 把启动错误原因写入 result.error，供 CLI/GUI 展示（否则用户看不到为何失败）
        summary = Summary(start_time="", end_time="", duration_ms=0.0)
        return ExecutionResult(summary=summary, case_results=(), error=msg)
