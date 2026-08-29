"""两阶段悬置告警与 expect 无断言告警的特征测试（真机验收教训固化，2026-08-29）.

背景（COM5/N58 实证）：
    1. expect 命中提示符后设备进入等数据态；若声明的 data 步骤未执行（漏写/
       when 跳过/断言中止/装配失败），后续 AT 命令字节会被设备当作数据吞掉
       （teardown 前 16 字节被 FSWF 会话吞掉）。
    2. expect 单独使用不是严格闸门：超时回退业务码路径（TIMEOUT 三态），无断言
       则无条件放行（探针假 PASS 实证）。
"""

from __future__ import annotations

import logging

import pytest
from _fakes import FakeCommandSender

from atprobe.domain.case.models import Case, Step
from atprobe.engine.step_runner import CaseContext, execute_step
from atprobe.infra.serial.interfaces import Response, ResponseStatus


def _ok(text: str = "\r\nOK\r\n") -> Response:
    return Response(text=text, status=ResponseStatus.COMPLETE)


def _prompt() -> Response:
    """两阶段提示符响应（expect 命中形态，文本不以 OK 结尾）."""
    return Response(text="\r\n> ", status=ResponseStatus.COMPLETE)


# ===========================================================================
# 解析期告警（模型校验）
# ===========================================================================
class TestParseWarnings:
    """Step/Case 校验期的两类告警（caplog 捕获 _log.warning）."""

    def test_expect_without_assert_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            Step(command='AT+FSWF="t.txt",0,16,5000', expect="\\r\\n> ")
        assert any("expect 但无 assert" in r.message for r in caplog.records)

    def test_wait_urc_without_assert_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            Step(command="AT$MYGPSPOS=0,1", wait_urc="\\$MYGPSPOS")
        assert any("wait_urc 但无 assert" in r.message for r in caplog.records)

    def test_expect_with_assert_no_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            Step(
                command='AT+FSWF="t.txt",0,16,5000',
                expect="\\r\\n> ",
                assert_={"matches": "^\\r\\n> $"},
            )
        assert not any("无 assert" in r.message for r in caplog.records)

    def test_prompt_step_followed_by_command_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """expect 提示符步骤的直接后继是 command（漏写 data）→ 静态告警."""
        with caplog.at_level(logging.WARNING):
            Case(
                name="漏data",
                steps=(
                    Step(
                        command='AT+FSWF="t.txt",0,16,5000',
                        expect="\\r\\n> ",
                        assert_={"contains": ">"},
                    ),
                    Step(command='AT+FSFS="t.txt"', assert_={"contains": "OK"}),
                ),
            )
        assert any("直接后继不是 data" in r.message for r in caplog.records)

    def test_prompt_step_last_in_phase_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """expect 提示符步骤是阶段末步（无后继）→ 同款告警."""
        with caplog.at_level(logging.WARNING):
            Case(
                name="末步悬置",
                steps=(Step(command='AT+FSWF="t.txt",0,16,5000', expect="\\r\\n> "),),
            )
        assert any("直接后继不是 data" in r.message for r in caplog.records)

    def test_prompt_step_followed_by_data_no_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        """正常两阶段配对（expect → data）→ 不告警."""
        with caplog.at_level(logging.WARNING):
            Case(
                name="正常两阶段",
                steps=(
                    Step(
                        command='AT+FSWF="t.txt",0,16,5000',
                        expect="\\r\\n> ",
                        assert_={"contains": ">"},
                    ),
                    Step(
                        data={"inline": "0123456789abcdef"},
                        expect="\\+FSWF: Timeout!",
                        assert_={"contains": "OK"},
                    ),
                ),
            )
        assert not any("直接后继不是 data" in r.message for r in caplog.records)


# ===========================================================================
# 运行期悬置告警（step_runner）
# ===========================================================================
def _run(step: Step, ctx: CaseContext, sender: FakeCommandSender, index: int = 1):
    return execute_step(
        step,
        index=index,
        phase="steps",
        ctx=ctx,
        sender=sender,
        default_port="V0",
        step_timeout_default=5.0,
    )


class TestRuntimePendingPrompt:
    def test_prompt_then_command_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """expect 命中提示符后直接执行 command → 入口告警（设备等数据态吞命令）."""
        ctx = CaseContext()
        sender = FakeCommandSender([_prompt(), _ok()])
        prompt_step = Step(
            command='AT+FSWF="t.txt",0,16,5000',
            expect="\\r\\n> ",
            assert_={"contains": ">"},
        )
        _run(prompt_step, ctx, sender)
        assert ctx.pending_prompt == "\\r\\n> "

        with caplog.at_level(logging.WARNING, logger="atprobe.engine.step_runner"):
            _run(Step(command='AT+FSFS="t.txt"', assert_={"contains": "OK"}), ctx, sender, index=2)
        assert any("两阶段悬置" in r.message for r in caplog.records)
        assert ctx.pending_prompt is None  # 一次性告警后清除

    def test_prompt_assert_fail_still_sets_pending_then_teardown_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """COM5 实证形态：expect 步骤断言失败中止（提示符已到）→ data 不发
        → 后续（teardown）命令入口告警."""
        ctx = CaseContext()
        sender = FakeCommandSender([_prompt(), _ok()])
        prompt_step = Step(
            command='AT+FSWF="t.txt",0,16,5000',
            expect="\\r\\n> ",
            assert_={"contains": "不会出现的文本"},  # 断言失败 → abort 路径
        )
        r = _run(prompt_step, ctx, sender)
        assert r.status.value == "FAIL"
        assert ctx.pending_prompt == "\\r\\n> "  # 提示符已到，悬置成立

        with caplog.at_level(logging.WARNING, logger="atprobe.engine.step_runner"):
            _run(Step(command='AT+FSDF="t.txt"'), ctx, sender, index=2)
        assert any("两阶段悬置" in r.message for r in caplog.records)

    def test_data_completes_clears_pending_no_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        """data 步骤收尾 OK → 悬置清除，后续命令不告警（正常路径零噪音）."""
        ctx = CaseContext()
        sender = FakeCommandSender([_prompt(), _ok(), _ok()])
        _run(
            Step(command='AT+FSWF="t.txt",0,16,5000', expect="\\r\\n> ", assert_={"contains": ">"}),
            ctx,
            sender,
        )
        _run(
            Step(data={"inline": "0123456789abcdef"}, assert_={"contains": "OK"}),
            ctx,
            sender,
            index=2,
        )
        assert ctx.pending_prompt is None

        with caplog.at_level(logging.WARNING, logger="atprobe.engine.step_runner"):
            _run(Step(command='AT+FSFS="t.txt"', assert_={"contains": "OK"}), ctx, sender, index=3)
        assert not any("两阶段悬置" in r.message for r in caplog.records)

    def test_data_without_device_ok_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """data 已发送但设备未回 OK（非 COMPLETE）→ 立即告警（会话状态不明）."""
        ctx = CaseContext()
        err = Response(text="\r\nERROR\r\n", status=ResponseStatus.ERROR, error="设备错误")
        sender = FakeCommandSender([_prompt(), err])
        _run(
            Step(command='AT+FSWF="t.txt",0,16,5000', expect="\\r\\n> ", assert_={"contains": ">"}),
            ctx,
            sender,
        )
        with caplog.at_level(logging.WARNING, logger="atprobe.engine.step_runner"):
            _run(Step(data={"inline": "0123456789abcdef"}), ctx, sender, index=2)
        assert any("未回 OK" in r.message for r in caplog.records)
        assert ctx.pending_prompt is None

    def test_cme_error_terminated_command_does_not_set_pending(self) -> None:
        """m-2 收窄：设备拒绝两阶段命令（+CME ERROR 终结，COMPLETE 状态）
        ——expect 从未命中提示符，不得置悬置（否则下一步收到误导性告警）."""
        ctx = CaseContext()
        cme = Response(text="\r\n+CME ERROR: 53\r\n", status=ResponseStatus.COMPLETE)
        sender = FakeCommandSender([cme])
        _run(
            Step(
                command='AT+FSWF="t.txt",0,16,240000', expect="\r\n> ", assert_={"contains": "OK"}
            ),
            ctx,
            sender,
        )
        assert ctx.pending_prompt is None

    def test_ok_terminated_command_does_not_set_pending(self) -> None:
        """expect 已设但设备回了 OK 终结（非提示符等待）→ 不置悬置."""
        ctx = CaseContext()
        sender = FakeCommandSender([_ok()])  # OK 结尾
        _run(
            Step(command="AT+XIIC=1", expect="\\+XIIC: 1", assert_={"contains": "OK"}),
            ctx,
            sender,
        )
        assert ctx.pending_prompt is None
