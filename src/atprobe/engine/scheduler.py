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
    InputType,
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
from atprobe.infra.serial.interfaces import ERROR_KIND_DISCONNECT, CancelToken, ICommandSender
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
        # F-8 重入防护：check-and-set 原子（锁只包状态检查/置位，不覆盖执行体）。
        # 旧实现无防护，二次 start 会重置 stop_flag/cancel_token，破坏首个执行的
        # 停止语义（GUI 双击/线程竞态下难复现）。
        with self._lock:
            if self._state is EngineState.RUNNING:
                raise RuntimeError("引擎正在运行，不可重入 start")
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

        # sender 解析收口（复审修复：第三方工厂异常不逃出 start，两分支均终结
        # 状态机 + 停 raw_logger + 补发 EngineFinishedEvent——P1-7）
        sender, port_manager, early_result = self._resolve_sender_safely(config, handler)
        if early_result is not None:
            return early_result
        cancel = CancelToken()
        self._cancel_token = cancel

        # §2.2 step 3: 打开端口差集（外部已开的跳过；全失败才 ERROR，§7.5 场景C）
        ports_opened, open_error = self._open_ports(port_manager, config)
        if open_error is not None:
            # 置态先于发事件（顺序统一，理由见下方兜底路径注释）
            self._state = EngineState.ERROR
            if self._owns_raw_logger and self._raw_logger is not None:
                self._raw_logger.stop()
            # 复审修复：补发 EngineFinishedEvent——GUI 进度面板以该事件收尾，
            # 旧实现此路径不发 → 面板悬挂（pre-existing，与兜底承诺对齐）
            if handler is not None:
                handler(
                    EngineFinishedEvent(
                        summary=Summary(start_time="", end_time="", duration_ms=0.0)
                    )
                )
            return self._error_result(config, open_error)

        default_port = config.ports[0].name

        case_results: list[CaseResult] = []
        session = config.session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(config.log_dir)
        engine_error: str = ""  # P1 修复：主循环兜底异常记录（见下方 except）
        interrupted = False  # KeyboardInterrupt：状态 FINISHED 而非 ERROR
        # C1 修复：本次执行实际绑定过用例日志的端口（default_port + 步骤显式端口，
        # 由 _bind_case_logs 累积）。用例循环内不清绑定（用例间 trailing 字节仍落
        # 上一用例日志），全作业结束在 finally 统一 clear——否则共享 PM 上残留的
        # _log_files 会让作业后的手动流量（MCP send_at / 持续 RX 噪声）追加进
        # 最后一个用例的日志文件。
        bound_log_ports: set[str] = set()
        # 套件前后置结果在 try 前显式初始化（消除 locals().get 反模式）——
        # 主循环异常中断时，已收集的部分结果仍随报告返回，不再依赖对 locals()
        # 的脆弱 introspection。
        suite_setup_results: list[StepResult] = []
        suite_teardown_results: list[StepResult] = []

        try:
            # 套件级前置（REQ-M2 §12.2）：失败 → 不继续 cases（但仍执行 teardown）
            suite_setup_failed = self._run_suite_setup(
                config, sender, default_port, cancel, handler, suite_setup_results
            )

            if not suite_setup_failed:
                expanded_cases = self._expand_cases(config.cases)
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
                        bound_log_ports,
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

            # 套件级后置（REQ-M2 §12.2）：cases 循环后执行一次（在 finally 关闭端口
            # 之前，确保 teardown 命令发往仍打开的端口）。无条件执行；cancel=None
            # （不响应取消）；StepResult 进 ExecutionResult 供报告诊断。
            self._run_suite_teardown(config, sender, default_port, handler, suite_teardown_results)
        except KeyboardInterrupt:
            # P1 修复补充：CLI Ctrl-C（BaseException，不被 except Exception 捕获）——
            # 转干净的中断结果（已完成用例的统计保留），状态 FINISHED 而非 ERROR。
            engine_error = "被用户中断（Ctrl-C）"
            interrupted = True
        except Exception as exc:  # noqa: BLE001 - P1 修复：引擎主循环兜底
            # 旧实现此层只有 finally：任意非 OperationCancelled 异常（第三方 sender
            # 缺陷、渲染路径漏洞等）直接逃出 start() → _state 永久卡 RUNNING、
            # 无 EngineFinishedEvent、聚合结果丢失（GUI 永远显示"运行中"）。
            # 兜底后状态机必须终结：记错误 → 走统一结果构建（finally 已关端口）。
            engine_error = f"引擎内部错误：{exc!r}"
        finally:
            # 只关闭本次执行新打开的端口（外部已连接的端口保持不动，
            # 避免破坏 GUI 监控/手动调试的连接与订阅状态）
            # F-11：逐端口 try/except——旧实现单 try 包整循环，首个端口 close 抛错
            # 会让后续端口全部泄漏（保持打开）。
            for p in ports_opened:
                try:
                    port_manager.close(p)  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001
                    _log.warning("端口关闭失败：%s", p, exc_info=True)
            # C1 修复：清除用例日志绑定（关端口之后做——外部保持连接的端口
            # 不会被 close 顺带清掉，必须显式 clear；沿用 _unbind_case_logs 的
            # hasattr 防御风格，不带 set_case_log 能力的 sender 不受影响）。
            # teardown/suite_teardown 已在前面执行完毕，此清理不影响其日志归属。
            # F-11：同上逐端口容错——单个 clear 失败不阻断其余端口清理。
            if port_manager is not None and hasattr(port_manager, "clear_case_log"):
                for p in bound_log_ports:
                    try:
                        port_manager.clear_case_log(p)  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        _log.warning("用例日志清理失败：%s", p, exc_info=True)
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
            # 置态/发事件顺序统一（先置态后发事件）：事件消费方在回调内查
            # engine.state() 可见终态，与 sender 解析/端口失败分支一致。
            self._state = EngineState.FINISHED if interrupted else EngineState.ERROR
            if handler is not None:
                handler(EngineFinishedEvent(summary=summary))
            # 复审修复：兜底结果补齐 env_snapshot 与套件前后置（与正常路径同构，
            # 旧实现三项落默认空 → 引擎内部错误时报告数据静默缺失）
            return ExecutionResult(
                summary=summary,
                case_results=tuple(case_results),
                env_snapshot=self._env_snapshot(config),
                suite_setup_results=tuple(suite_setup_results),
                suite_teardown_results=tuple(suite_teardown_results),
                error=engine_error,
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
        result = ExecutionResult(
            summary=summary,
            case_results=tuple(case_results),
            env_snapshot=env_snap,
            suite_setup_results=tuple(suite_setup_results),
            suite_teardown_results=tuple(suite_teardown_results),
        )
        # 置态/发事件顺序统一（先置态后发事件）：见上方兜底路径注释
        self._state = EngineState.FINISHED
        if handler is not None:
            handler(EngineFinishedEvent(summary=summary))
        return result

    # ------------------------------------------------------------------
    # 套件级前后置与参数化展开（start 的执行段拆分，行为保持）
    # ------------------------------------------------------------------
    def _run_suite_setup(
        self,
        config: EngineConfig,
        sender: Any,
        default_port: str,
        cancel: CancelToken,
        handler: Callable[[object], None] | None,
        results: list[StepResult],
    ) -> bool:
        """套件级前置（REQ-M2 §12.2）：cases 循环前执行一次.

        用独立 CaseContext（与用例变量池隔离，但 setup 各步共享同一 ctx 以便
        extract 传递）。cancel=cancel 响应停止；返回 True 表示失败/中止 →
        不继续 cases（但仍执行 teardown）。StepResult 经 results 收集
        （传入式累积——异常中断时已收集的部分仍可随报告返回）。
        """
        ctx = CaseContext(
            env=config.env_config if isinstance(config.env_config, EnvConfig) else None,
            # suite 前后置无 case 对象（case_dir=None）；此处用 data 步骤属边缘，
            # 锚集有 data_allowed_roots 兜底（S-8，设计 §5）
            case_dir=None,
            data_allowed_roots=tuple(Path(p) for p in config.data_allowed_roots),
        )
        for i, step in enumerate(config.suite_setup, start=1):
            if self._stop_mode is StopMode.ALL:
                return True
            if cancel.cancelled:  # P3 修复：suite_setup 也响应取消
                return True
            r = execute_step(
                step,
                index=i,
                phase="suite_setup",
                ctx=ctx,
                sender=sender,
                default_port=default_port,
                step_timeout_default=config.step_timeout_default,
                clock=self._clock,
                sleep=self._sleep,
                cancel=cancel,
            )
            results.append(r.step_result)
            self._emit_step(handler, r)
            # 批 5 T6-7：断连安全阀——suite_setup 步骤 DISCONNECT 失败时立即终止
            # （返回 True → 跳过 cases，但仍执行 suite_teardown）。默认策略
            # （ABORT）下 r.abort_case 已正确终止；缺口在 on_failure: continue/skip
            # 显式配置——continue 下 FAIL 不置 abort_case，skip 下状态是 SKIPPED
            # 而非 FAIL（T6 审查 M-1：skip 分支曾绕过本阀），两种显式配置都会让
            # 循环继续向已断开的端口发剩余 setup 步骤（每步都超时重试，白白拖满
            # n×步骤超时）。与用例级 setup 的 F-13 安全阀同族，但 suite 级无变量
            # 池连续计数，断连即弃。
            if r.step_result.status in (StepStatus.FAIL, StepStatus.SKIPPED) and (
                r.step_result.error_kind == ERROR_KIND_DISCONNECT
            ):
                return True
            if r.abort_case:  # 失败 → 跳过 cases（StepResult 仅记录，不进 aggregate）
                return True
        return False

    def _run_suite_teardown(
        self,
        config: EngineConfig,
        sender: Any,
        default_port: str,
        handler: Callable[[object], None] | None,
        results: list[StepResult],
    ) -> None:
        """套件级后置（REQ-M2 §12.2）：cases 循环后执行一次（在 finally 关闭端口
        之前，确保 teardown 命令发往仍打开的端口）。无条件执行，失败仅记警告
        （is_teardown=True + try/except 吞掉异常，与用例 teardown 语义一致）。
        cancel=None（不响应取消）；StepResult 进 ExecutionResult 供报告诊断。
        """
        ctx = CaseContext(
            env=config.env_config if isinstance(config.env_config, EnvConfig) else None,
            # 同 suite_setup：无 case 对象，data 步骤属边缘，锚集靠 data_allowed_roots
            case_dir=None,
            data_allowed_roots=tuple(Path(p) for p in config.data_allowed_roots),
        )
        for i, step in enumerate(config.suite_teardown, start=1):
            try:
                r = execute_step(
                    step,
                    index=i,
                    phase="suite_teardown",
                    ctx=ctx,
                    sender=sender,
                    default_port=default_port,
                    step_timeout_default=config.step_timeout_default,
                    clock=self._clock,
                    sleep=self._sleep,
                    cancel=None,
                    is_teardown=True,
                )
                results.append(r.step_result)
                self._emit_step(handler, r)
            except Exception as exc:  # noqa: BLE001 - suite_teardown 失败仅记录，不影响结果
                _log.debug("suite_teardown 步骤执行异常", exc_info=True)
                # F-13 配套：异常步骤不再从报告中消失——合成 FAIL StepResult
                # （request 未及渲染，用原始 command 占位，保诊断信息）
                results.append(
                    StepResult(
                        step_index=i,
                        phase="suite_teardown",
                        input_type=InputType.DATA if step.data is not None else InputType.COMMAND,
                        command=step.command or "",
                        port=step.port or default_port,
                        status=StepStatus.FAIL,
                        request=step.command or "",
                        response="",
                        error_msg=f"步骤执行异常：{exc!r}",
                    )
                )

    def _expand_cases(self, cases: tuple[Case, ...]) -> list[Case]:
        """参数化下沉引擎入口（P1 修复）.

        GUI 路径绕过收集层（domain/suite/collect）直接传原始 Case，旧实现
        scheduler 只取 parameters[0]，多行参数静默丢弃（只跑第一行）。在引擎
        入口统一展开：多行 parameters 展开为带 param_index 的独立实例；
        CLI 已展开的单行实例（param_index 已置）原样通过，不重复展开。
        """
        expanded: list[Case] = []
        for c in cases:
            if c.parameters and len(c.parameters) > 1:
                for i, row in enumerate(c.parameters, start=1):
                    expanded.append(c.model_copy(update={"parameters": (row,), "param_index": i}))
            else:
                expanded.append(c)
        return expanded

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
        bound_log_ports: set[str],
    ) -> CaseResult:
        t0 = self._clock()
        ctx = CaseContext(
            env=config.env_config if isinstance(config.env_config, EnvConfig) else None,
            # S-8：data.file 相对路径的默认锚根 = 用例文件所在目录
            case_dir=Path(case.source_file).parent if case.source_file else None,
            data_allowed_roots=tuple(Path(p) for p in config.data_allowed_roots),
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

        # 绑定用例日志文件（bound_log_ports 累积实际绑定端口，供 start 的
        # finally 在全作业结束时统一 clear）
        self._bind_case_logs(case, port_manager, log_dir, session, default_port, bound_log_ports)

        try:
            setup_failed, setup_err = self._run_setup_phase(
                case,
                ctx,
                config,
                sender,
                port_manager,
                default_port,
                cancel,
                handler,
                setup_results,
                ports_used,
            )
            if setup_failed:
                status = CaseStatus.SKIPPED
                # P3 修复：保留循环里已写的具体原因（步骤级错误/断连安全阀），
                # 仅无详情时用泛化文案
                error_msg = setup_err or "setup 失败"
            elif case.is_pressure:
                # §3.3 流程B 压测。P1 修复：不在 try 内 return——CaseResult 统一
                # 在 finally 之后 build（teardown 结果/端口/耗时不丢）。
                status, error_msg, pressure_stats = self._run_pressure_phase(
                    case, ctx, config, sender, default_port, cancel, handler
                )
            else:
                # §3.2 流程A steps
                status, error_msg = self._run_steps_phase(
                    case,
                    ctx,
                    config,
                    sender,
                    port_manager,
                    default_port,
                    cancel,
                    handler,
                    step_results,
                    ports_used,
                )
        except OperationCancelled:
            status = CaseStatus.INTERRUPTED
            error_msg = "被中断"
        finally:
            # §3.2 teardown（无条件执行，失败不影响结果）
            self._run_teardown_phase(
                case, ctx, config, sender, default_port, handler, teardown_results, ports_used
            )
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
    # 单用例各执行段（_run_case 拆分，行为保持；results/ports_used 传入式累积）
    # ------------------------------------------------------------------
    def _run_setup_phase(
        self,
        case: Case,
        ctx: CaseContext,
        config: EngineConfig,
        sender: ICommandSender,
        port_manager: Any,
        default_port: str,
        cancel: CancelToken,
        handler: Callable[[object], None] | None,
        results: list[StepResult],
        ports_used: set[str],
    ) -> tuple[bool, str]:
        """§3.2 流程A setup。返回 (setup_failed, error_msg)——error_msg 无详情时
        由调用方兜底「setup 失败」文案。前置取消（cancel 已置位）直接让位，
        中止判定交给后续 steps 段（与旧行为一致）。
        """
        error_msg = ""
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
            results.append(r.step_result)
            ports_used.add(r.step_result.port)
            self._emit_step(handler, r)
            # F-13：断连安全阀检查前移——每步先判安全阀再判 FAIL/SKIPPED 中止。
            # 旧顺序下 DISCONNECT FAIL 先命中「setup 失败（步骤 N）」分支 break，
            # 阈值已到却报普通步骤失败文案，掩盖「连续断连放弃用例」的处置语义。
            if self._hit_disconnect_safety(r.step_result, ctx, port_manager):
                return True, "连续断连达到安全阀，放弃用例"
            # setup 步骤失败或被 skip（on_failure:skip）都视为前提未满足 → 跳过用例
            # （REQ-M2 §7：setup 失败一律跳过整个用例；skip 说明该前提步骤未成功）
            if r.status in (StepStatus.FAIL, StepStatus.SKIPPED):
                # P3 修复：error_msg 带首个失败步骤的具体原因（旧实现只报"setup 失败"）
                if r.step_result.error_msg:
                    error_msg = f"setup 失败（步骤 {i}）：{r.step_result.error_msg}"
                return True, error_msg
        return False, error_msg

    def _run_steps_phase(
        self,
        case: Case,
        ctx: CaseContext,
        config: EngineConfig,
        sender: ICommandSender,
        port_manager: Any,
        default_port: str,
        cancel: CancelToken,
        handler: Callable[[object], None] | None,
        results: list[StepResult],
        ports_used: set[str],
    ) -> tuple[CaseStatus, str]:
        """§3.2 流程A steps。返回 (status, error_msg)。"""
        error_msg = ""
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
            results.append(r.step_result)
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
            return CaseStatus.INTERRUPTED, "被中断"
        if aborted:
            return CaseStatus.FAIL, error_msg
        any_fail = any(s.status is StepStatus.FAIL for s in results)
        return (CaseStatus.FAIL if any_fail else CaseStatus.PASS), ""

    def _run_pressure_phase(
        self,
        case: Case,
        ctx: CaseContext,
        config: EngineConfig,
        sender: ICommandSender,
        default_port: str,
        cancel: CancelToken,
        handler: Callable[[object], None] | None,
    ) -> tuple[CaseStatus, str, Any]:
        """§3.3 流程B 压测。返回 (status, error_msg, stats)；step_results 保持空
        （压测明细在 stats，见 _build_case_result）。"""

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
        # 复审修复：abort_on_failure 与用户取消同帧并发时，先报真实中止
        # 原因（旧实现 INTERRUPTED 分支优先，掩盖"失败即中止"信息）
        if pr.aborted and pr.abort_reason == "abort_on_failure":
            return (
                CaseStatus.FAIL,
                f"压测按 abort_on_failure 中止（成功率 {pr.stats.success_rate:.1f}%，"
                f"阈值 {pr.stats.pass_threshold:.1f}%）",
                pr.stats,
            )
        if pr.aborted and cancel.cancelled:
            return CaseStatus.INTERRUPTED, "被中断", pr.stats
        if pr.stats.passed:
            return CaseStatus.PASS, "", pr.stats
        return (
            CaseStatus.FAIL,
            f"压测成功率 {pr.stats.success_rate:.1f}% 低于阈值 {pr.stats.pass_threshold:.1f}%",
            pr.stats,
        )

    def _run_teardown_phase(
        self,
        case: Case,
        ctx: CaseContext,
        config: EngineConfig,
        sender: ICommandSender,
        default_port: str,
        handler: Callable[[object], None] | None,
        results: list[StepResult],
        ports_used: set[str],
    ) -> None:
        """§3.2 teardown（无条件执行，失败不影响结果；异常仅记 debug）。"""
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
                results.append(r.step_result)
                ports_used.add(r.step_result.port)
                # P2 修复：teardown 步骤也发 StepResultEvent（setup/steps 均发，
                # 旧实现 GUI 进度面板看不到 teardown 执行）
                self._emit_step(handler, r)
            except Exception:  # noqa: BLE001 - teardown 失败仅记录
                _log.debug("teardown 步骤执行异常", exc_info=True)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _resolve_sender_safely(
        self, config: EngineConfig, handler: Callable[[object], None] | None
    ) -> tuple[Any, Any, ExecutionResult | None]:
        """sender 解析收口：第三方工厂抛异常时旧实现直接逃出 start()（状态卡
        RUNNING），与「引擎内部错误不逃逸」承诺不符。两异常分支均终结状态机、
        停 raw_logger、补发 EngineFinishedEvent（P1-7——否则 GUI 进度面板永久
        显示"运行中"），返回非 None 的第三元素即提前返回的 ExecutionResult。
        """
        try:
            sender, port_manager = self._resolve_sender(config)
        except KeyboardInterrupt:
            # 置态先于发事件（顺序统一，理由见 start 兜底路径注释）
            self._state = EngineState.FINISHED
            if self._owns_raw_logger and self._raw_logger is not None:
                self._raw_logger.stop()
            if handler is not None:
                handler(
                    EngineFinishedEvent(
                        summary=Summary(start_time="", end_time="", duration_ms=0.0)
                    )
                )
            return (
                None,
                None,
                ExecutionResult(
                    summary=Summary(start_time="", end_time="", duration_ms=0.0),
                    case_results=(),
                    error="被用户中断（Ctrl-C）",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            # 置态先于发事件（顺序统一，理由见 start 兜底路径注释）
            self._state = EngineState.ERROR
            if self._owns_raw_logger and self._raw_logger is not None:
                self._raw_logger.stop()
            if handler is not None:
                handler(
                    EngineFinishedEvent(
                        summary=Summary(start_time="", end_time="", duration_ms=0.0)
                    )
                )
            return None, None, self._error_result(config, f"sender 解析失败：{exc!r}")
        return sender, port_manager, None

    def _open_ports(self, port_manager: Any, config: EngineConfig) -> tuple[list[str], str | None]:
        """§2.2 step 3：打开端口差集——外部已连接的端口（GUI 手动连接/监控）跳过
        open，返回 (本次新开端口, 失败原因|None)。finally 只关闭新开端口，避免
        破坏外部连接状态。单端口失败不一定是致命；全部失败才是 ERROR（§7.5 场景C）。
        """
        ports_opened: list[str] = []
        try:
            for pc in config.ports:
                already_open = port_manager.is_connected(pc.name)  # type: ignore[union-attr]
                # M4 修复：仅当端口未在外部打开时才 open，避免对 GUI 已连端口复用时抛错。
                # （PortManager.open 已改为幂等，但跳过 open 更语义清晰且省一次锁。）
                if not already_open:
                    port_manager.open(pc)  # type: ignore[union-attr]
                    ports_opened.append(pc.name)
        except Exception as exc:  # noqa: BLE001 - 端口打开失败
            if not any(
                port_manager.is_connected(p)
                for p in [q.name for q in config.ports]  # type: ignore[union-attr]
            ):
                return ports_opened, f"端口打开失败：{exc}"
        return ports_opened, None

    def _resolve_sender(self, config: EngineConfig) -> tuple[ICommandSender, Any]:
        if self._sender_factory is not None:
            sender = self._sender_factory()
            # 注入 sender 也需实现连接管理；测试用 FakePortManager
            return sender, sender
        pm = PortManager(raw_logger=self._raw_logger, clock=self._clock, sleep=self._sleep)
        return pm, pm

    def _bind_case_logs(
        self,
        case: Case,
        port_manager: Any,
        log_dir: Path,
        session: str,
        default_port: str,
        bound_log_ports: set[str],
    ) -> None:
        if self._raw_logger is None or port_manager is None:
            return
        if not hasattr(port_manager, "set_case_log"):
            return
        # F-10：日志绑定整体 best-effort——盘满/权限等 OSError 不应炸掉用例执行
        # （降级为无原始日志继续跑）；bound_log_ports 只累积绑定成功的端口。
        try:
            # P2 修复：参数化实例的日志名带 #N 后缀（与报告 display_name 一致）——
            # 旧实现所有实例共用 case.name，多实例原始日志互相追加/覆盖污染。
            log_name = case.name
            if case.param_index is not None:
                log_name = f"{case.name}#{case.param_index}"
            for pc in self._case_ports(case, default_port):
                lf = self._raw_logger.begin_case(log_dir, session, pc, log_name)
                port_manager.set_case_log(pc, lf)
                # 累积实际绑定的端口（default_port + 步骤显式端口，不用 config.ports
                # ——会漏掉步骤里显式指定的其他端口），start 的 finally 据此统一清理
                bound_log_ports.add(pc)
        except OSError as exc:
            _log.warning("用例日志绑定失败（降级为无原始日志）：%s", exc)

    def _unbind_case_logs(self, port_manager: Any) -> None:
        if port_manager is None or not hasattr(port_manager, "clear_case_log"):
            return
        # C1 修复说明：用例级清理不再在此处做，也**有意不在用例间做**——用例循环
        # 内保持绑定可让用例间的 trailing 字节（晚到响应等）仍落上一用例日志；
        # 统一移到 start 的 finally（对 bound_log_ports 一次性 clear），消除作业
        # 结束后共享 PM 残留 _log_files 的污染（手动流量追加进最后用例日志）。

    def _case_ports(self, case: Case, default_port: str = "") -> list[str]:
        """收集本用例实际执行会用到的端口（用于绑定用例级原始日志）.

        以 ``default_port``（执行配置端口，如 GUI 选的 / CLI --port）为基础，叠加
        **setup/steps/teardown 全部阶段**步骤显式指定的 ``step.port``。**不使用
        ``case.port``**——它在执行流里不影响实际发送端口（步骤用
        ``step.port or default_port``），若用它会导致日志目录建到错误端口名下
        （如用例硬编码 COM5，实际执行 COM28 时日志目录错建为 COM5 且可能失败）。
        批 5 T6-6：旧实现只遍历 steps——setup/teardown 显式端口的原始日志不落
        用例目录（该端口的 begin_case 未建立，流量走不到用例级日志）。
        """
        ports: list[str] = []
        if default_port:
            ports.append(default_port)
        for s in (*case.setup, *case.steps, *case.teardown):
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
