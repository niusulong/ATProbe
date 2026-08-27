"""引擎修复专项回归测试（本轮审查 P0/P1 修复）.

覆盖：
    1. P0：poll until 满足但断言失败 → 步骤 FAIL（旧实现假 PASS）
    2. P1：TIMEOUT 响应（部分缓冲）不参与断言 → 必 FAIL（旧实现 contains 假 PASS）
    3. P1：poll 临时作用域只合并 matched 变量（`x is not null` 不再首轮假成功）
    4. P1：模板渲染失败走 on_failure 决策（旧实现硬编码 abort_case）
    5. P1：extractor 可选捕获组未参与匹配 → matched=False（旧实现 None 毒化变量池）
    6. P1：evaluator 比较右操作数为括号子表达式 → ExpressionError（旧实现 AssertionError）

execute_step 是纯函数（sender/clock/sleep 注入），用脚本化 FakeSender 单测。
"""

from __future__ import annotations

import time

from atprobe.domain.case.evaluator import ExpressionError, evaluate
from atprobe.domain.case.extractor import extract_one
from atprobe.domain.case.models import (
    AssertElement,
    AssertionOp,
    FailureStrategy,
    PollConfig,
    Step,
)
from atprobe.domain.report.models import StepStatus
from atprobe.engine.step_runner import CaseContext, execute_step
from atprobe.infra.serial.interfaces import CancelToken, ICommandSender, Response, ResponseStatus


class FakeSender(ICommandSender):
    """脚本化发送器：按序返回预设响应."""

    def __init__(self, responses: list[Response]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        self.calls += 1
        return self._responses.pop(0) if self._responses else Response(text="\r\nOK\r\n")


def _ok(text: str = "\r\nOK\r\n") -> Response:
    return Response(text=text, status=ResponseStatus.COMPLETE)


def _timeout(text: str = "\r\n+CSQ: 12,9") -> Response:
    return Response(text=text, status=ResponseStatus.TIMEOUT, error="响应超时")


class TestPollAssertionIntegrity:
    """P0：poll 不吞断言."""

    def test_poll_until_met_but_assert_failed_is_fail(self) -> None:
        """until 满足 + 断言失败 → FAIL 且保留断言原因（旧实现翻转为 PASS）."""
        step = Step(
            command="AT+CSQ?",
            extract={"rssi": r"\+CSQ: (\d+)"},
            assert_=[{"name": "rssi上限", "var": "rssi", "op": "lt", "value": "5"}],
            poll=PollConfig(until="rssi is not null", timeout=3.0, interval=10),
        )
        # rssi=12：until（非空）满足，但断言 12<5 失败
        sender = FakeSender([_ok("\r\n+CSQ: 12,99\r\nOK\r\n")])
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=sender,
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "FAIL"
        assert r.step_result.error_msg is not None and "rssi" in r.step_result.error_msg
        # 报告里的断言明细保留失败记录（供诊断），不因 poll 被清空
        assert any(not a.passed for a in r.step_result.assertions)

    def test_poll_until_met_and_assert_passed_is_pass(self) -> None:
        """正常路径：until 满足 + 断言通过 → PASS（确保修复未破坏正向行为）."""
        step = Step(
            command="AT+CSQ?",
            extract={"rssi": r"\+CSQ: (\d+)"},
            assert_=[{"name": "rssi范围", "var": "rssi", "op": "lt", "value": "31"}],
            poll=PollConfig(until="rssi is not null", timeout=3.0, interval=10),
        )
        sender = FakeSender([_ok("\r\n+CSQ: 12,99\r\nOK\r\n")])
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=sender,
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "PASS"

    def test_poll_unmatched_extract_not_null_keeps_polling(self) -> None:
        """P1：extract 未匹配的变量在 until 里是 null（非空串）——首轮不再假成功."""
        step = Step(
            command="AT+CREG?",
            extract={"stat": r"\+CEREG: \d,(\d)"},
            poll=PollConfig(until="stat is not null", timeout=0.05, interval=10),
        )
        # 响应永远不含 CEREG → extract 不匹配 → stat 未定义 → until 不满足 → 轮询到超时
        sender = FakeSender([_ok("\r\nOK\r\n")] * 50)
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=sender,
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "FAIL"
        assert "超时" in (r.step_result.error_msg or "")
        assert sender.calls > 1  # 确实轮询了多轮


class TestTimeoutNoAssertion:
    """TIMEOUT 响应三态语义（真机测试修正）."""

    def test_timeout_partial_text_fails_even_if_contains_matches(self) -> None:
        """超时半截文本（不以 \\r\\n 结尾，如 "\\r\\nOK"）不能通过 contains（假 PASS）."""
        step = Step(command="AT+SLOW", assert_={"contains": "OK"})
        sender = FakeSender([_timeout("\r\nOK")])  # 半截 OK（无终结行）
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=sender,
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "FAIL"
        assert r.step_result.error_kind == "TIMEOUT"

    def test_timeout_empty_fails(self) -> None:
        """超时且完全无数据 → 失败."""
        step = Step(command="AT+SLOW", assert_={"contains": "OK"})
        sender = FakeSender([_timeout("")])
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=sender,
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "FAIL"
        assert "无任何数据" in (r.step_result.error_msg or "")

    def test_timeout_business_code_assertable(self) -> None:
        """业务码模式：超时交付的完整行（以 \\r\\n 结尾）参与严格断言 → PASS.

        真机回归：N58 用例 +UPDATETIME: No PPP Link 不以 OK 终结，框架按设计
        经超时交付完整响应，用例在其上做 ^...$ 严格断言（存量 43 用例依赖）。
        """
        step = Step(
            command="AT+UPDATETIME=1,1.2.3.4,10",
            assert_={"matches": r"^\r\n\+UPDATETIME: No PPP Link\r\n$"},
        )
        sender = FakeSender([_timeout("\r\n+UPDATETIME: No PPP Link\r\n")])
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=sender,
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "PASS"

    def test_timeout_business_code_strict_mismatch_fails(self) -> None:
        """业务码模式但严格断言不匹配 → 失败（防伪机制仍有效）."""
        step = Step(
            command="AT+UPDATETIME=1,1.2.3.4,10",
            assert_={"matches": r"^\r\n\+UPDATETIME: Other Code\r\n$"},
        )
        sender = FakeSender([_timeout("\r\n+UPDATETIME: No PPP Link\r\n")])
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=sender,
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "FAIL"


class TestRenderFailureOnFailure:
    """P1：渲染失败走 on_failure 决策."""

    def test_render_error_with_continue_does_not_abort(self) -> None:
        """on_failure: continue 的步骤渲染失败 → FAIL 但 abort_case=False."""
        step = Step(command="AT+X={{missing_var}}", on_failure=FailureStrategy.CONTINUE)
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=FakeSender([]),
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "FAIL"
        assert r.abort_case is False  # 旧实现恒 True

    def test_render_error_default_aborts(self) -> None:
        """未配置 on_failure 时渲染失败仍中止（默认 ABORT 语义保留）."""
        step = Step(command="AT+X={{missing_var}}")
        r = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=FakeSender([]),
            default_port="COM9",
            step_timeout_default=5.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert r.status.value == "FAIL"
        assert r.abort_case is True


class TestExtractorOptionalGroup:
    """P1：捕获组未参与匹配（跳过）的处理."""

    def test_alternation_first_group_skipped(self) -> None:
        """交替分支：(a)|(b) 匹配 b 时 group(1) 为 None → 取首个参与组 "b".

        旧实现固定取 group(1)=None 且 matched=True → None 毒化变量池。
        """
        r = extract_one(r"(\+CSQ)|(\+CREG)", "+CREG: 1")
        assert r.matched is True
        assert r.value == "+CREG"

    def test_all_optional_groups_skipped_not_matched(self) -> None:
        """全可选组都被跳过 → matched=False（旧实现 matched=True + 空值）."""
        r = extract_one(r"(\d+)?-x", "-x")
        assert r.matched is False
        assert r.value == ""

    def test_participating_empty_group_keeps_empty_semantics(self) -> None:
        """「参与但匹配空串」的首组（如 (\\+?) 在无 + 输入）仍是合法值 ""（文档语义）."""
        r = extract_one(r"(\+?)(\d+)", "123")
        assert r.matched is True
        assert r.value == ""


class TestEvaluatorParenOperand:
    """P1：比较右操作数括号子表达式 → ExpressionError（非 AssertionError）."""

    def test_rhs_paren_raises_expression_error(self) -> None:
        try:
            evaluate("x == (a == 1)", {"x": "1", "a": "1"})
        except ExpressionError:
            pass  # 预期：领域异常，可被 step_runner 捕获
        except AssertionError:  # pragma: no cover
            raise AssertionError("旧 bug：裸 AssertionError 逃逸（应抛 ExpressionError）") from None
        else:
            raise AssertionError("应抛 ExpressionError") from None


class TestUnmatchedExtractNotInAssertionScope:
    """P1-5：常规步骤断言作用域只合并 matched 变量（与 poll 口径统一）."""

    def test_ne_assert_fails_when_extract_unmatched(self) -> None:
        """extract 未匹配 → 变量未定义 → ne 断言 FAIL（旧实现 "" != "ERROR" 假 PASS）."""
        step = Step(
            command="AT+CSQ",
            extract={"csq": r"NEVERMATCH-(\d+)"},
            assert_=[AssertElement(var="csq", op=AssertionOp.NE, value="ERROR")],
        )
        result = execute_step(
            step,
            index=1,
            phase="steps",
            ctx=CaseContext(),
            sender=FakeSender([_ok("\r\n+CSQ: 12,9\r\n\r\nOK\r\n")]),
            default_port="FAKE",
            step_timeout_default=1.0,
            clock=time.monotonic,
            sleep=lambda s: None,
        )
        assert result.status is StepStatus.FAIL
        assert "未定义" in (result.step_result.error_msg or "")
