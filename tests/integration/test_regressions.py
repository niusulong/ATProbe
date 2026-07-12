"""回归测试：锁定本次深度审查修复的关键行为。

覆盖的修复点：
    - B1：StopMode.CURRENT 中断当前用例后，后续用例正常执行（非全 INTERRUPTED）
    - M1：取消时统一 raise OperationCancelled（真实串口与 Fake 一致）
    - M3：断连判定基于 error_kind 枚举（非字符串匹配）
    - M4：PortManager.open 幂等（已开端口同配置不抛错）
    - M7：poll until 表达式错误时报错（非静默当超时）
    - L5：not_contains/matches 空字符串校验
    - L9：between min>max 校验
"""

from __future__ import annotations

import threading
import time

import pytest

from atprobe.domain.case import parse_case
from atprobe.domain.case.models import AssertElement, AssertionOp
from atprobe.domain.report.models import CaseStatus, StepStatus
from atprobe.engine import Engine, EngineConfig
from atprobe.engine.config import StopMode
from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import CancelToken, Response, ResponseStatus


def _engine_with_fake(fake: FakePortManager) -> Engine:
    return Engine(sender_factory=lambda: fake, sleep=lambda s: None)


def _cfg(cases, env=None) -> EngineConfig:  # type: ignore[no-untyped-def]
    return EngineConfig(
        ports=(PortConfig(name="COM3"),),
        cases=tuple(cases),
        step_timeout_default=5.0,
        env_config=env,
    )


# ---------------------------------------------------------------------------
# B1：StopMode.CURRENT 中断当前用例后，后续用例正常执行
# ---------------------------------------------------------------------------
class TestStopCurrentContinuesNext:
    """B1 回归：中断当前用例后，后续用例不应被误判 INTERRUPTED。"""

    def test_stop_current_next_case_executes_normally(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        """stop(CURRENT) 中断用例 A 后，用例 B 应正常执行（PASS），而非 INTERRUPTED。

        旧 bug：stop() 把 cancel token 永久 cancel，CURRENT 分支不重建 token，
        后续用例一进 execute_step 就 raise OperationCancelled → 全 INTERRUPTED。
        """
        # 用例 B 预设响应（能正常 PASS）
        fake_port.script_text("COM3", "OK\r\n", match="AT+B", persistent=True)
        case_a = parse_case("""
name: case-A
port: COM3
steps:
  - command: AT+A
    assert: { contains: "OK" }
""")
        case_b = parse_case("""
name: case-B
port: COM3
steps:
  - command: AT+B
    assert: { contains: "OK" }
""")
        engine = _engine_with_fake(fake_port)

        # 在引擎线程启动后、用例 A 执行期间触发 stop(CURRENT)
        def _stop_soon() -> None:
            time.sleep(0.05)  # 等引擎进入用例 A
            engine.stop(mode=StopMode.CURRENT)

        threading.Thread(target=_stop_soon, daemon=True).start()
        result = engine.start(_cfg([case_a, case_b]))

        # 两个用例都应有结果
        assert len(result.case_results) == 2
        # A 的状态取决于 stop 时序（INTERRUPTED 或 FAIL），不强制
        cr_b = result.case_results[1]
        # B1 核心：B 不应是 INTERRUPTED（旧 bug 下 B 会是 INTERRUPTED）
        assert cr_b.status is CaseStatus.PASS, (
            f"B1 回归：中断 A 后 B 应正常执行并 PASS，实际 {cr_b.status}"
        )


# ---------------------------------------------------------------------------
# M1：取消时 raise OperationCancelled（真实串口与 Fake 一致）
# ---------------------------------------------------------------------------
class TestCancelRaisesOperationCancelled:
    """M1 回归：SerialConnection.send_command cancel 时 raise，而非返回 CANCELLED Response。"""

    def test_pre_cancelled_raises(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """预先 cancel 的 token 传入 send_command，应 raise OperationCancelled。"""

        class _StubSerial:
            def write(self, data: bytes) -> None:
                pass

            def flush(self) -> None:
                pass

        cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
        conn = SerialConnection(cfg)
        monkeypatch.setattr(conn, "_serial", _StubSerial())
        monkeypatch.setattr(conn, "_connected", True)

        cancel = CancelToken()
        cancel.cancel()
        with pytest.raises(OperationCancelled):
            conn.send_command("AT", timeout=2.0, cancel=cancel)


# ---------------------------------------------------------------------------
# M3：断连判定基于 error_kind 枚举
# ---------------------------------------------------------------------------
class TestDisconnectErrorKind:
    """M3 回归：断连 Response 带 error_kind=DISCONNECT，非断连带 SEND/NONE。"""

    def test_disconnect_response_has_error_kind(self) -> None:
        """断连 Response 的 error_kind 应为 DISCONNECT。"""
        resp = Response(
            text="",
            status=ResponseStatus.ERROR,
            error="端口断连",
            error_kind="DISCONNECT",
        )
        assert resp.error_kind == "DISCONNECT"
        assert not resp.ok

    def test_send_error_response_has_error_kind(self) -> None:
        """发送失败 Response 的 error_kind 应为 SEND。"""
        resp = Response(
            text="",
            status=ResponseStatus.ERROR,
            error="发送失败",
            error_kind="SEND",
        )
        assert resp.error_kind == "SEND"

    def test_success_response_error_kind_none(self) -> None:
        """成功 Response 的 error_kind 默认为 NONE。"""
        resp = Response(text="OK\r\n")
        assert resp.error_kind == "NONE"
        assert resp.ok


# ---------------------------------------------------------------------------
# M4：PortManager.open 幂等
# ---------------------------------------------------------------------------
class TestOpenIdempotent:
    """M4 回归：同配置 open 幂等，不同配置才抛错。"""

    def test_same_config_open_is_idempotent(self) -> None:
        """已用相同配置打开的端口，再次 open 应幂等返回（不抛错）。"""
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        cfg = PortConfig(name="COM9", baudrate=115200)
        # 模拟已开连接（避免真实串口）
        pm._configs["COM9"] = cfg
        pm._connections["COM9"] = object()  # 占位
        # 同配置再次 open → 幂等返回（不抛错）
        pm.open(cfg)

    def test_different_config_open_raises(self) -> None:
        """已用配置 A 打开的端口，用配置 B open 应抛错。"""
        from atprobe.infra.serial.exceptions import PortOpenError
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        cfg1 = PortConfig(name="COM9", baudrate=9600)
        cfg2 = PortConfig(name="COM9", baudrate=115200)
        pm._configs["COM9"] = cfg1
        pm._connections["COM9"] = object()  # 占位
        with pytest.raises(PortOpenError, match="不同配置"):
            pm.open(cfg2)


# ---------------------------------------------------------------------------
# M7：poll until 表达式错误时报错（非静默当超时）
# ---------------------------------------------------------------------------
class TestPollExpressionError:
    """M7 回归：poll until 表达式语法错误应报错，而非静默当超时。"""

    def test_poll_bad_expression_reports_error(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        """poll.until 含语法错误 → 超时后 step_error 应含"表达式错误"。"""
        fake_port.script_text("COM3", "OK\r\n", persistent=True)
        case = parse_case("""
name: poll-bad-expr
port: COM3
steps:
  - command: AT
    poll:
      until: 'x ==='   # 语法错误（不完整比较）
      timeout: 0.3
      interval: 50
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.FAIL
        assert cr.step_results[0].status is StepStatus.FAIL
        assert "表达式错误" in cr.step_results[0].error_msg, (
            f"M7：应报告表达式错误，实际：{cr.step_results[0].error_msg!r}"
        )


# ---------------------------------------------------------------------------
# L5：not_contains/matches 空字符串校验
# ---------------------------------------------------------------------------
class TestAssertEmptyStringValidation:
    """L5 回归：not_contains/matches 空字符串应在建模时报错。"""

    def test_not_contains_empty_rejected(self) -> None:
        with pytest.raises(Exception, match="not_contains"):
            AssertElement(not_contains="")

    def test_matches_empty_rejected(self) -> None:
        with pytest.raises(Exception, match="matches"):
            AssertElement(matches="")

    def test_equals_empty_allowed(self) -> None:
        """equals='' 是合法语义（断言响应为空），不应报错。"""
        el = AssertElement(equals="")
        assert el.equals == ""


# ---------------------------------------------------------------------------
# L9：between min > max 校验
# ---------------------------------------------------------------------------
class TestBetweenMinMaxValidation:
    """L9 回归：between min>max 应在建模时报错（否则断言恒失败但原因晦涩）。"""

    def test_min_greater_than_max_rejected(self) -> None:
        with pytest.raises(Exception, match=r"min.*max|不应大于"):
            AssertElement(var="x", op=AssertionOp.BETWEEN, min=10, max=1)

    def test_min_equal_max_allowed(self) -> None:
        """min==max 是合法的（断言恰好等于某值）。"""
        el = AssertElement(var="x", op=AssertionOp.BETWEEN, min=5, max=5)
        assert el.min == 5
