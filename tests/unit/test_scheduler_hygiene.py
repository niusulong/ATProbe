"""Scheduler 引擎卫生特征测试（批 3 Task 4，设计 §4.4/§4.6/§4.10）.

每个卫生项一个特征测试（先行于实现锁定行为）：
    - F-8  start 重入防护：RUNNING 中二次 start 抛 RuntimeError（check-and-set 原子）
    - F-9  EngineConfig.ports 非空校验（空元组 → ValueError）
    - F-10 _bind_case_logs 降级：begin_case 抛 OSError → 用例照常执行 PASS
    - F-11 finally 逐端口容错：close/clear_case_log 单端口失败不阻断其余端口
    - F-13 setup 断连安全阀检查前移：DISCONNECT FAIL + 阈值 1 → 安全阀文案
          （而非「setup 失败（步骤 N）」——安全阀处置优先于普通失败中止）
    - suite_teardown 步骤异常合成 FAIL StepResult（报告中不再消失）
    - 置态/发事件顺序统一：EngineFinishedEvent 回调内 engine.state() 已是终态

Engine 构造沿用 test_scheduler_fallback.py 模式：FakePortManager 既是
sender 也是 port_manager（引擎从 sender 上发现连接管理能力）。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from atprobe.domain.case.models import Case, FailureStrategy, Step
from atprobe.domain.report.models import CaseStatus, StepStatus
from atprobe.engine.config import EngineConfig, EngineState
from atprobe.engine.interfaces import EngineFinishedEvent
from atprobe.engine.scheduler import Engine
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import (
    ERROR_KIND_DISCONNECT,
    CancelToken,
    Response,
    ResponseStatus,
)


# ---------------------------------------------------------------------------
# 替身
# ---------------------------------------------------------------------------
class _BlockingFake(FakePortManager):
    """send_command 阻塞到 gate 放行——驱动引擎保持 RUNNING（F-8 测试）."""

    def __init__(self) -> None:
        super().__init__(sleep=lambda s: None)
        self.gate = threading.Event()

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        _ = expect
        self.gate.wait(timeout=10.0)
        return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)


class _ExplodeOnceFake(FakePortManager):
    """首条命令抛指定异常（驱动引擎内部错误兜底路径）."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__(sleep=lambda s: None)
        self._exc = exc

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        _ = expect
        raise self._exc


class _DisconnectFake(FakePortManager):
    """所有命令返回 DISCONNECT ERROR 响应（驱动断连安全阀）."""

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        _ = expect
        return Response(
            text="",
            status=ResponseStatus.ERROR,
            error="连接断开",
            error_kind=ERROR_KIND_DISCONNECT,
        )


class _TeardownExplodeFake(FakePortManager):
    """普通命令 OK；命中指定命令抛 RuntimeError（suite_teardown 步骤内部异常）."""

    def __init__(self, explode_cmd: str) -> None:
        super().__init__(sleep=lambda s: None)
        self._explode_cmd = explode_cmd

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        _ = expect
        if self._explode_cmd in command:
            raise RuntimeError("teardown boom")
        return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)


class _FirstPortFailsFake(FakePortManager):
    """close/clear_case_log 对指定端口抛异常，其余照常（记录成功名单）."""

    def __init__(self, fail_port: str) -> None:
        super().__init__(sleep=lambda s: None)
        self._fail_port = fail_port
        self.closed: list[str] = []
        self.cleared: list[str] = []

    def close(self, port: str) -> None:
        if port == self._fail_port:
            raise RuntimeError(f"close boom: {port}")
        self.closed.append(port)
        super().close(port)

    def clear_case_log(self, port: str) -> None:
        if port == self._fail_port:
            raise RuntimeError(f"clear boom: {port}")
        self.cleared.append(port)
        super().clear_case_log(port)


class _BrokenBeginCaseLogger:
    """begin_case 抛 OSError 的 raw_logger 替身（盘满/权限等 IO 故障）."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def begin_case(self, log_dir: Path, session: str, port: str, case_name: str) -> Path:
        raise OSError("disk full")


class _StubLogger:
    """begin_case 返回占位路径的 raw_logger 替身（绑定成功，不落盘）."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def begin_case(self, log_dir: Path, session: str, port: str, case_name: str) -> Path:
        return log_dir / session / f"{port}_{case_name}.log"


def _cfg(ports: tuple[PortConfig, ...] = (PortConfig(name="V0"),), **kw: Any) -> EngineConfig:
    return EngineConfig(ports=ports, **kw)


# ---------------------------------------------------------------------------
# F-8：start 重入防护
# ---------------------------------------------------------------------------
class TestStartReentryGuard:
    def test_second_start_raises_while_running(self, tmp_path: Path) -> None:
        fake = _BlockingFake()
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        cfg = _cfg(cases=(Case(name="重入", steps=(Step(command="AT"),)),), log_dir=str(tmp_path))
        t = threading.Thread(target=engine.start, args=(cfg,))
        t.start()
        try:
            deadline = time.monotonic() + 5.0
            while engine.state() is not EngineState.RUNNING and time.monotonic() < deadline:
                time.sleep(0.01)
            assert engine.state() is EngineState.RUNNING, "前置：引擎应已进入 RUNNING"
            with pytest.raises(RuntimeError, match="不可重入"):
                engine.start(cfg)
        finally:
            fake.gate.set()
            t.join(timeout=5.0)
        assert engine.state() is EngineState.FINISHED, "首次 start 应正常完成"


# ---------------------------------------------------------------------------
# F-9：EngineConfig.ports 非空校验
# ---------------------------------------------------------------------------
class TestEngineConfigPortsValidation:
    def test_empty_ports_rejected(self) -> None:
        with pytest.raises(ValueError, match="ports 不可为空"):
            EngineConfig(ports=(), cases=())


# ---------------------------------------------------------------------------
# F-10：_bind_case_logs OSError 降级
# ---------------------------------------------------------------------------
class TestBindCaseLogsDegrades:
    def test_begin_case_oserror_case_still_passes(self, tmp_path: Path, caplog: Any) -> None:
        fake = FakePortManager(sleep=lambda s: None)
        fake.script_text("V0", "OK\r\n", persistent=True)
        engine = Engine(
            sender_factory=lambda: fake,
            sleep=lambda s: None,
            raw_logger=_BrokenBeginCaseLogger(),
        )
        case = Case(name="日志降级", steps=(Step(command="AT", assert_={"contains": "OK"}),))
        with caplog.at_level(logging.WARNING, logger="atprobe.engine"):
            result = engine.start(_cfg(cases=(case,), log_dir=str(tmp_path)))
        assert len(result.case_results) == 1
        assert result.case_results[0].status is CaseStatus.PASS, "日志绑定失败不应影响用例执行"
        assert any("用例日志绑定失败" in r.message for r in caplog.records), "应记降级警告"


# ---------------------------------------------------------------------------
# F-11：finally 逐端口容错
# ---------------------------------------------------------------------------
class TestFinallyPerPortTolerance:
    def test_first_close_failure_does_not_block_second(self, tmp_path: Path) -> None:
        fake = _FirstPortFailsFake(fail_port="V0")
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        cfg = _cfg(
            ports=(PortConfig(name="V0"), PortConfig(name="V1")), cases=(), log_dir=str(tmp_path)
        )
        engine.start(cfg)
        assert fake.closed == ["V1"], "V0 close 抛错后 V1 仍应被 close"

    def test_first_clear_failure_does_not_block_second(self, tmp_path: Path) -> None:
        fake = _FirstPortFailsFake(fail_port="V0")
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None, raw_logger=_StubLogger())
        # 两步分别落默认端口 V0 与显式端口 V1 → bound_log_ports = {V0, V1}
        case = Case(
            name="清理容错",
            steps=(Step(command="AT", port="V0"), Step(command="AT+V1", port="V1")),
        )
        engine.start(_cfg(cases=(case,), log_dir=str(tmp_path)))
        assert fake.cleared == ["V1"], "V0 清理抛错后 V1 仍应被 clear"


# ---------------------------------------------------------------------------
# F-13：setup 断连安全阀检查前移
# ---------------------------------------------------------------------------
class TestSetupSafetyValvePriority:
    def test_disconnect_fail_with_threshold1_reports_valve(self, tmp_path: Path) -> None:
        fake = _DisconnectFake()
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        case = Case(
            name="安全阀前移",
            setup=(Step(command="AT+CGATT?"),),
            steps=(Step(command="AT"),),
        )
        cfg = _cfg(
            ports=(PortConfig(name="V0", reconnect_safety_threshold=1),),
            cases=(case,),
            log_dir=str(tmp_path),
        )
        result = engine.start(cfg)
        cr = result.case_results[0]
        assert cr.status is CaseStatus.SKIPPED
        assert cr.error_msg == "连续断连达到安全阀，放弃用例", (
            "安全阀处置应优先于普通 setup 失败中止（旧顺序报『setup 失败（步骤 1）』）"
        )


# ---------------------------------------------------------------------------
# T6-6：_case_ports 覆盖 setup/teardown 显式端口（用例日志绑定完整性）
# ---------------------------------------------------------------------------
class _RecordingLogFake(FakePortManager):
    """记录 set_case_log 绑定过的端口（驱动用例日志绑定断言）."""

    def __init__(self) -> None:
        super().__init__(sleep=lambda s: None)
        self.bound_ports: list[str] = []

    def set_case_log(self, port: str, log_file: Path | None) -> None:
        self.bound_ports.append(port)
        super().set_case_log(port, log_file)


class TestCasePortsCoverSetupTeardown:
    def test_setup_teardown_explicit_ports_bound(self, tmp_path: Path) -> None:
        """setup/teardown 显式端口的原始日志也落用例目录.

        旧实现 _case_ports 只遍历 steps——setup/teardown 显式端口不建
        begin_case，该端口的流量落不进用例级日志。
        """
        fake = _RecordingLogFake()
        for p in ("V0", "V1", "V2"):
            fake.script_text(p, "OK\r\n", persistent=True)
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None, raw_logger=_StubLogger())
        case = Case(
            name="端口绑定",
            setup=(Step(command="AT+SETUP", port="V1"),),
            steps=(Step(command="AT"),),
            teardown=(Step(command="AT+TEARDOWN", port="V2"),),
        )
        engine.start(
            _cfg(
                ports=(PortConfig(name="V0"), PortConfig(name="V1"), PortConfig(name="V2")),
                cases=(case,),
                log_dir=str(tmp_path),
            )
        )
        assert set(fake.bound_ports) == {"V0", "V1", "V2"}, (
            "setup/teardown 显式端口应纳入用例日志绑定（旧实现只绑 default+steps 端口）"
        )


# ---------------------------------------------------------------------------
# T6-7：suite_setup 断连安全阀（on_failure: continue 缺口）
# ---------------------------------------------------------------------------
class TestSuiteSetupDisconnectValve:
    def test_disconnect_with_continue_stops_remaining_setup(self, tmp_path: Path) -> None:
        """suite_setup 步骤 DISCONNECT 且 on_failure: continue 时立即终止.

        旧实现该组合下 abort_case=False，循环继续向已断开的端口发剩余 setup
        步骤（每步都超时，白白拖满 n×步骤超时）；安全阀断连即弃（返回 True →
        跳过 cases，仍执行 suite_teardown）。
        """
        fake = _DisconnectFake()
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        cfg = _cfg(
            cases=(Case(name="不应执行", steps=(Step(command="AT"),)),),
            suite_setup=(
                Step(command="AT+S1", on_failure=FailureStrategy.CONTINUE),
                Step(command="AT+S2"),
            ),
            log_dir=str(tmp_path),
        )
        result = engine.start(cfg)
        assert len(result.suite_setup_results) == 1, "断连后不应继续执行剩余 suite_setup 步骤"
        assert result.suite_setup_results[0].error_kind == ERROR_KIND_DISCONNECT
        assert result.case_results == (), "suite_setup 断连终止 → cases 跳过"

    def test_disconnect_default_abort_still_stops(self, tmp_path: Path) -> None:
        """默认策略（ABORT）下断连照旧终止——既有正确路径回归钉住."""
        fake = _DisconnectFake()
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        cfg = _cfg(
            cases=(Case(name="默认中止", steps=(Step(command="AT"),)),),
            suite_setup=(Step(command="AT+S1"), Step(command="AT+S2")),
            log_dir=str(tmp_path),
        )
        result = engine.start(cfg)
        assert len(result.suite_setup_results) == 1
        assert result.case_results == ()

    def test_disconnect_with_skip_stops_remaining_setup(self, tmp_path: Path) -> None:
        """suite_setup 步骤 DISCONNECT 且 on_failure: skip 时同样立即终止.

        T6 审查 M-1：skip 策略下步骤状态是 SKIPPED 而非 FAIL，旧阀条件
        （仅判 FAIL）被绕过——剩余 setup 步骤照发向已断端口。断连即弃不区分
        continue/skip 显式配置。
        """
        fake = _DisconnectFake()
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        cfg = _cfg(
            cases=(Case(name="不应执行", steps=(Step(command="AT"),)),),
            suite_setup=(
                Step(command="AT+S1", on_failure=FailureStrategy.SKIP),
                Step(command="AT+S2"),
            ),
            log_dir=str(tmp_path),
        )
        result = engine.start(cfg)
        assert len(result.suite_setup_results) == 1, "断连后不应继续执行剩余 suite_setup 步骤"
        assert result.suite_setup_results[0].error_kind == ERROR_KIND_DISCONNECT
        assert result.case_results == (), "suite_setup 断连终止 → cases 跳过"


# ---------------------------------------------------------------------------
# suite_teardown 步骤异常合成 StepResult
# ---------------------------------------------------------------------------
class TestSuiteTeardownSynthesizesResult:
    def test_step_exception_appends_fail_result(self, tmp_path: Path) -> None:
        fake = _TeardownExplodeFake("AT+TEARDOWN")
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        cfg = _cfg(
            cases=(Case(name="套件后置", steps=(Step(command="AT"),)),),
            suite_teardown=(Step(command="AT+TEARDOWN"),),
            log_dir=str(tmp_path),
        )
        result = engine.start(cfg)
        assert len(result.suite_teardown_results) == 1, "异常步骤不应从报告中消失"
        sr = result.suite_teardown_results[0]
        assert sr.status is StepStatus.FAIL
        assert sr.phase == "suite_teardown"
        assert sr.step_index == 1
        assert sr.port == "V0"
        assert "teardown boom" in sr.error_msg


# ---------------------------------------------------------------------------
# 置态/发事件顺序统一（先置态后发事件）
# ---------------------------------------------------------------------------
class TestStateBeforeFinishedEvent:
    def test_normal_path_state_visible_in_callback(self, tmp_path: Path) -> None:
        fake = FakePortManager(sleep=lambda s: None)
        fake.script_text("V0", "OK\r\n", persistent=True)
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        states_at_event: list[EngineState] = []

        def handler(ev: object) -> None:
            if isinstance(ev, EngineFinishedEvent):
                states_at_event.append(engine.state())

        cfg = _cfg(cases=(Case(name="顺序", steps=(Step(command="AT"),)),), log_dir=str(tmp_path))
        engine.start(cfg, handler=handler)
        assert states_at_event == [EngineState.FINISHED], (
            "事件回调内应已可见终态（旧顺序回调时仍为 RUNNING）"
        )

    def test_error_path_state_visible_in_callback(self, tmp_path: Path) -> None:
        fake = _ExplodeOnceFake(RuntimeError("boom"))
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        states_at_event: list[EngineState] = []

        def handler(ev: object) -> None:
            if isinstance(ev, EngineFinishedEvent):
                states_at_event.append(engine.state())

        cfg = _cfg(cases=(Case(name="顺序错", steps=(Step(command="AT"),)),), log_dir=str(tmp_path))
        engine.start(cfg, handler=handler)
        assert states_at_event == [EngineState.ERROR]
