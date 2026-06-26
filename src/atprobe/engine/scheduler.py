"""M3 串行调度器（REQ-M3 §2.2 调度器、§3 执行流程、§4.6 用例结果汇总、§7 状态机/中断）.

引擎主循环（串行，引擎线程私有，无锁）::

    加载环境配置 → 打开端口 → [用例 setup→steps→teardown]×N → 关闭端口 → 聚合结果

极简控制：start/stop（§7.2）。stop(mode) 设置停止标志，在步骤边界响应。
"""

from __future__ import annotations

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
        self._raw_logger = raw_logger
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
    def start(self, config: EngineConfig, handler: Callable[[object], None] | None = None) -> ExecutionResult:
        self._state = EngineState.RUNNING
        self._stop_flag.clear()
        self._stop_mode = None

        sender, port_manager = self._resolve_sender(config)
        cancel = CancelToken()
        self._cancel_token = cancel

        # §2.2 step 3: 打开端口
        ports_opened: list[str] = []
        try:
            for pc in config.ports:
                port_manager.open(pc)  # type: ignore[union-attr]
                ports_opened.append(pc.name)
        except Exception as exc:  # 端口打开失败
            # 单端口失败不一定是致命；全部失败才是 ERROR（§7.5 场景C）
            if not any(port_manager.is_connected(p) for p in [pc.name for pc in config.ports]):  # type: ignore[union-attr]
                self._state = EngineState.ERROR
                return self._error_result(config, f"端口打开失败：{exc}")

        default_port = config.ports[0].name if config.ports else ""

        case_results: list[CaseResult] = []
        session = config.session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(config.log_dir)

        try:
            for idx, case in enumerate(config.cases, start=1):
                if self._stop_mode is StopMode.ALL:
                    break
                if self._stop_flag.is_set() and self._stop_mode is StopMode.CURRENT:
                    self._stop_flag.clear()
                    self._stop_mode = None

                if handler is not None:
                    handler(
                        CaseStartEvent(
                            case_name=case.name, case_index=idx,
                            total_cases=len(config.cases),
                            case_type="pressure" if case.is_pressure else "regular",
                        )
                    )

                cr = self._run_case(
                    case, idx, config, sender, port_manager, default_port,
                    cancel, log_dir, session, handler,
                )
                case_results.append(cr)
                if handler is not None:
                    handler(
                        CaseResultEvent(
                            case_name=case.name, status=cr.status.value,
                            duration_ms=cr.duration_ms, error_msg=cr.error_msg,
                        )
                    )
        finally:
            try:
                port_manager.close_all()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass

        summary = aggregate(case_results)
        env_snap = self._env_snapshot(config)
        result = ExecutionResult(summary=summary, case_results=tuple(case_results), env_snapshot=env_snap)
        if handler is not None:
            handler(EngineFinishedEvent(summary=summary))
        self._state = EngineState.FINISHED
        return result

    # ------------------------------------------------------------------
    # 单用例执行
    # ------------------------------------------------------------------
    def _run_case(
        self, case: Case, idx: int, config: EngineConfig,
        sender: ICommandSender, port_manager: Any, default_port: str,
        cancel: CancelToken, log_dir: Path, session: str,
        handler: Callable[[object], None] | None,
    ) -> CaseResult:
        t0 = self._clock()
        ctx = CaseContext(env=config.env_config if isinstance(config.env_config, EnvConfig) else None)

        # 参数化注入（M2 §10.2）—— 由上层展开，此处 case 已是单实例
        ports_used: set[str] = set()
        setup_results: list[StepResult] = []
        step_results: list[StepResult] = []
        teardown_results: list[StepResult] = []
        error_msg = ""
        status = CaseStatus.PASS

        # 绑定用例日志文件
        self._bind_case_logs(case, port_manager, log_dir, session)

        try:
            # §3.2 流程A setup
            setup_failed = False
            for i, step in enumerate(case.setup, start=1):
                r = execute_step(
                    step, index=i, phase="setup", ctx=ctx, sender=sender,
                    default_port=default_port, step_timeout_default=config.step_timeout_default,
                    case_on_failure=case.on_failure,
                    clock=self._clock, sleep=self._sleep, cancel=cancel,
                )
                setup_results.append(r.step_result)
                ports_used.add(r.step_result.port)
                self._emit_step(handler, r)
                if r.status is StepStatus.FAIL:
                    setup_failed = True
                    break
                # §4.2 连续断连安全阀：达到阈值则放弃用例
                if self._hit_disconnect_safety(r.step_result, ctx, port_manager):
                    setup_failed = True
                    error_msg = "连续断连达到安全阀，放弃用例"
                    break

            if setup_failed:
                status = CaseStatus.SKIPPED
                error_msg = "setup 失败"
            elif case.is_pressure:
                # §3.3 流程B 压测
                def on_progress(rnd, total, suc, fail, avg):  # type: ignore[no-untyped-def]
                    if handler is not None:
                        handler(
                            PressureProgressEvent(
                                case_name=case.name, current_round=rnd, total_rounds=total,
                                success=suc, fail=fail, avg_ms=avg,
                            )
                        )

                pr = run_pressure(
                    case, ctx=ctx, sender=sender, default_port=default_port,
                    step_timeout_default=config.step_timeout_default,
                    pass_threshold=config.pressure_pass_threshold,
                    clock=self._clock, sleep=self._sleep, cancel=cancel,
                    on_progress=on_progress,
                )
                if pr.aborted and cancel.cancelled:
                    status = CaseStatus.INTERRUPTED
                    error_msg = "被中断"
                elif pr.stats.passed:
                    status = CaseStatus.PASS
                else:
                    status = CaseStatus.FAIL
                    error_msg = f"压测成功率 {pr.stats.success_rate:.1f}% 低于阈值 {pr.stats.pass_threshold:.1f}%"
                # 压测用例把每步首轮结果作为 step_results 展示（简化）
                if not pr.aborted:
                    step_results = []  # 压测明细在 pressure_stats
                return self._build_case_result(
                    case, idx, status, setup_results, step_results, teardown_results,
                    t0, ports_used, error_msg, pressure=pr.stats,
                )
            else:
                # §3.2 流程A steps
                aborted = False
                for i, step in enumerate(case.steps, start=1):
                    if cancel.cancelled:
                        aborted = True
                        break
                    r = execute_step(
                        step, index=i, phase="steps", ctx=ctx, sender=sender,
                        default_port=default_port, step_timeout_default=config.step_timeout_default,
                        case_on_failure=case.on_failure,
                        clock=self._clock, sleep=self._sleep, cancel=cancel,
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
                        step, index=i, phase="teardown", ctx=ctx, sender=sender,
                        default_port=default_port, step_timeout_default=config.step_timeout_default,
                        clock=self._clock, sleep=self._sleep, cancel=None,  # teardown 不响应取消
                        is_teardown=True,
                    )
                    teardown_results.append(r.step_result)
                    ports_used.add(r.step_result.port)
                except Exception:  # noqa: BLE001 - teardown 失败仅记录
                    pass
            self._unbind_case_logs(port_manager)

        return self._build_case_result(
            case, idx, status, setup_results, step_results, teardown_results,
            t0, ports_used, error_msg, pressure=None,
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

    def _bind_case_logs(self, case: Case, port_manager: Any, log_dir: Path, session: str) -> None:
        if self._raw_logger is None or port_manager is None:
            return
        if not hasattr(port_manager, "set_case_log"):
            return
        for pc in self._case_ports(case):
            lf = self._raw_logger.begin_case(log_dir, session, pc, case.name)
            port_manager.set_case_log(pc, lf)

    def _unbind_case_logs(self, port_manager: Any) -> None:
        if port_manager is None or not hasattr(port_manager, "clear_case_log"):
            return
        # 清理由 _run_case 在下次 _bind 时覆盖；此处不强制清

    def _case_ports(self, case: Case) -> list[str]:
        ports: list[str] = []
        if case.port:
            ports.append(case.port)
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
                step_index=sr.step_index, phase=sr.phase, status=sr.status.value,
                duration_ms=sr.duration_ms, port=sr.port, command=sr.command,
                extracted_vars=dict(sr.extracted_vars), error_msg=sr.error_msg,
                retry_count=sr.retry_count, poll_iterations=sr.poll_iterations,
                response=sr.response,
            )
        )

    def _hit_disconnect_safety(self, sr: StepResult, ctx: CaseContext, port_manager: Any) -> bool:
        """§4.2 连续断连安全阀：维护 ctx.disconnect_streak，达阈值返回 True（应放弃用例）.

        判定依据：步骤失败且错误含「断连/重连失败」（与 M1 send_command 的断连信号一致）。
        阈值取该端口 PortConfig.reconnect_safety_threshold（默认 3）。成功步骤重置计数。
        """
        is_disconnect_err = (
            sr.status is StepStatus.FAIL
            and bool(sr.error_msg)
            and ("断连" in sr.error_msg or "重连失败" in sr.error_msg)
        )
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
        self, case: Case, idx: int, status: CaseStatus,
        setup_results: list[StepResult], step_results: list[StepResult],
        teardown_results: list[StepResult], t0: float, ports_used: set[str],
        error_msg: str, pressure: Any,
    ) -> CaseResult:
        duration_ms = (self._clock() - t0) * 1000.0
        return CaseResult(
            case_name=case.name, case_file=case.source_file or "",
            tags=case.tags, ports=tuple(sorted(ports_used)),
            status=status, is_pressure=case.is_pressure,
            setup_results=tuple(setup_results), step_results=tuple(step_results),
            teardown_results=tuple(teardown_results), pressure_stats=pressure,
            duration_ms=duration_ms, error_msg=error_msg,
        )

    def _env_snapshot(self, config: EngineConfig) -> dict[str, dict[str, object]]:
        if not config.report_env_snapshot:
            return {}
        env = config.env_config
        if not isinstance(env, EnvConfig):
            return {}
        return {g: dict(p) for g, p in env.groups().items()}

    def _error_result(self, config: EngineConfig, msg: str) -> ExecutionResult:
        summary = Summary(start_time="", end_time="", duration_ms=0.0)
        return ExecutionResult(summary=summary, case_results=())
