"""step_runner 语义收敛测试（批 3 Task 3，设计 §4.1/§4.2 + 2b 终审⑧② + P3 两项）.

覆盖：
    1. 提取并入作用域口径唯一（_filter_matched/_merged_scope）：未匹配变量在
       「提交变量池 / poll until 判定 / 断言作用域」三处均为「未定义→null」；
    2. on_failure 唯一决策点（_failure_strategy）：step > case > 默认 ABORT，
       普通失败与作者错误两条路径行为等价；
    3. poll 循环头 deadline（P3）：贴 deadline 的下一轮不再向设备发命令，
       超时文案/返回结构与循环尾一致；
    4. teardown 忽略 when/poll 告警（P3，不再静默）；
    5. interval 钳制 poll 剩余预算（2b②）：step.interval 前置延迟不再无条件
       睡满，retry/单次路径（无预算概念）不受影响；
    6. PortBusyError 步骤级分类（2b 终审⑧）：端口互斥撞锁走 on_failure 决策，
       而非逃逸为 scheduler 兜底的「引擎内部错误」。

FakePortManager 驱动（script_text 预设 + sent/data_sent 计数，参照
test_step_runner_data.py）；时钟用可推进的 MutableClock 注入。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import pytest

from atprobe.domain.case.models import (
    AssertElement,
    AssertionOp,
    DataInput,
    FailureStrategy,
    PollConfig,
    Step,
)
from atprobe.domain.report.models import StepStatus
from atprobe.engine.step_runner import CaseContext, StepExecResult, execute_step
from atprobe.infra.serial.config import DataStreamSpec
from atprobe.infra.serial.exceptions import PortBusyError
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import (
    CancelToken,
    Response,
    ResponseStatus,
)

PORT = "COM9"
_STEP_RUNNER_LOGGER = "atprobe.engine.step_runner"


def _no_sleep(_seconds: float) -> None:
    """零休眠（interval/poll 间隔不真等）。"""


class MutableClock:
    """可推进假时钟：clock() 读 now，advance_sleep 推进（供 sleep 注入）。"""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_sleep(self, seconds: float) -> None:
        self.now += seconds


class BusyPortManager(FakePortManager):
    """撞端口命令锁替身（2b 终审⑧）：可分别设定 send_command/send_data 抛 PortBusyError."""

    def __init__(self) -> None:
        super().__init__(sleep=_no_sleep)
        self.busy_command = False
        self.busy_data = False

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
        pre_check: Callable[[], None] | None = None,
    ) -> Response:
        if self.busy_command:
            raise PortBusyError(port, "端口正忙：并发发送不支持")
        return super().send_command(
            port,
            command,
            timeout=timeout,
            wait_urc=wait_urc,
            expect=expect,
            cancel=cancel,
            pre_check=pre_check,
        )

    def send_data(
        self,
        port: str,
        spec: DataStreamSpec,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        if self.busy_data:
            raise PortBusyError(port, "端口正忙：并发发送不支持")
        return super().send_data(
            port, spec, timeout=timeout, wait_urc=wait_urc, expect=expect, cancel=cancel
        )


def _run(
    step: Step,
    ctx: CaseContext,
    sender: FakePortManager,
    *,
    case_on_failure: FailureStrategy | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = _no_sleep,
    is_teardown: bool = False,
) -> StepExecResult:
    return execute_step(
        step,
        index=1,
        phase="steps",
        ctx=ctx,
        sender=sender,
        default_port=PORT,
        step_timeout_default=5.0,
        case_on_failure=case_on_failure,
        clock=clock,
        sleep=sleep,
        is_teardown=is_teardown,
    )


# ---------------------------------------------------------------------------
# 1. 提取并入作用域：三处消费点共用 _filter_matched 单一口径（设计 §4.1）
# ---------------------------------------------------------------------------
class TestUnifiedExtractScope:
    def test_pool_commit_filters_unmatched_keeps_matched(self) -> None:
        """提交变量池：匹配的变量入池、未匹配的不入池（未定义→null）."""
        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\n+CSQ: 12,9\r\nOK\r\n")
        step = Step(
            command="AT+CSQ?",
            extract={"csq": r"\+CSQ: (\d+)", "miss": r"NEVER-(\d+)"},
        )
        ctx = CaseContext()
        r = _run(step, ctx, fake)
        assert r.status is StepStatus.PASS
        assert ctx.variables["csq"] == "12"
        assert "miss" not in ctx.variables  # 未匹配=不提交=保持未定义

    def test_until_treats_unmatched_as_null_keeps_polling(self) -> None:
        """poll until 判定：extract 未匹配 → `x is not null` 不满足 → 轮询到超时."""
        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\nOK\r\n", persistent=True)
        step = Step(
            command="AT+CREG?",
            extract={"stat": r"\+CEREG: \d,(\d)"},
            poll=PollConfig(until="stat is not null", timeout=0.05, interval=10),
        )
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.FAIL
        assert "超时" in (r.step_result.error_msg or "")
        assert len(fake.sent) > 1  # 未定义≠空串：没有假成功，确实多轮轮询

    def test_assertion_scope_treats_unmatched_as_undefined(self) -> None:
        """断言作用域：extract 未匹配 → 变量未定义 → 断言失败并报告「未定义」."""
        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\n+CSQ: 12,9\r\nOK\r\n")
        step = Step(
            command="AT+CSQ?",
            extract={"csq": r"NEVER-(\d+)"},
            assert_=[AssertElement(var="csq", op=AssertionOp.EQ, value="12")],
        )
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.FAIL
        assert "未定义" in (r.step_result.error_msg or "")


# ---------------------------------------------------------------------------
# 2. on_failure 唯一决策点（step > case > 默认 ABORT），普通失败/作者错误两路等价
# ---------------------------------------------------------------------------
class TestFailureStrategyDecisionPoint:
    @staticmethod
    def _failing_run(step: Step, case_on_failure: FailureStrategy | None) -> StepExecResult:
        fake = FakePortManager(sleep=_no_sleep)
        fake.script(PORT, Response(text="", status=ResponseStatus.ERROR, error="设备拒绝"))
        return _run(step, CaseContext(), fake, case_on_failure=case_on_failure)

    def test_step_level_wins_over_case_level(self) -> None:
        """step.on_failure=continue 优先于 case 级 abort → 不中止."""
        step = Step(command="AT", on_failure=FailureStrategy.CONTINUE)
        r = self._failing_run(step, FailureStrategy.ABORT)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False

    def test_case_level_used_when_step_silent(self) -> None:
        """step 未配置 → 用 case 级 continue → 不中止."""
        step = Step(command="AT")
        r = self._failing_run(step, FailureStrategy.CONTINUE)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False

    def test_default_abort_when_both_silent(self) -> None:
        """两级均未配置 → 默认 ABORT → 中止用例."""
        step = Step(command="AT")
        r = self._failing_run(step, None)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is True

    def test_author_error_respects_case_level_continue(self) -> None:
        """作者错误路径（模板渲染失败）与普通失败同一决策点：case 级 continue 生效."""
        step = Step(command="AT+X={{missing_var}}")  # step 级未配置
        fake = FakePortManager(sleep=_no_sleep)
        r = _run(step, CaseContext(), fake, case_on_failure=FailureStrategy.CONTINUE)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False  # 旧实现硬编码 True，绕过 case 级配置
        assert fake.sent == []  # 渲染失败未发送


# ---------------------------------------------------------------------------
# 3. poll 循环头 deadline（P3）：贴 deadline 的下一轮不再向设备发命令
# ---------------------------------------------------------------------------
class TestPollHeadDeadline:
    def test_no_send_past_deadline(self) -> None:
        """间隔等待越过 deadline 后，循环头直接判超时——不再向设备发第二条查询."""
        clock = MutableClock()

        def jump_sleep(seconds: float) -> None:
            clock.now += max(seconds, 1.0)  # 首次间隔等待直接越过 deadline

        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\nOK\r\n", persistent=True)
        step = Step(
            command="AT+CREG?",
            extract={"stat": r"\+CEREG: \d,(\d)"},
            poll=PollConfig(until="stat is not null", timeout=0.2, interval=10),
        )
        r = _run(step, CaseContext(), fake, clock=clock, sleep=jump_sleep)
        assert len(fake.sent) == 1  # 首轮已发一条；下一轮未再发（旧实现会发第二条）
        assert r.status is StepStatus.FAIL
        assert r.step_result.error_msg == "poll 超时未满足条件"  # 文案与循环尾超时一致
        assert r.step_result.poll_iterations == 1
        assert r.abort_case is True  # 未配置 on_failure → 默认 ABORT


# ---------------------------------------------------------------------------
# 4. teardown 忽略 when/poll 告警（P3，不再静默）
# ---------------------------------------------------------------------------
class TestTeardownIgnoresWhenPollWarning:
    def test_teardown_warns_and_executes_unconditionally(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(
            command="AT",
            when="1 == 2",  # 恒 false：teardown 仍须无条件执行
            poll=PollConfig(until="1 == 1", timeout=1.0, interval=10),
        )
        with caplog.at_level(logging.WARNING, logger=_STEP_RUNNER_LOGGER):
            r = _run(step, CaseContext(), fake, is_teardown=True)
        assert r.status is StepStatus.PASS  # when/poll 均被忽略
        assert len(fake.sent) == 1  # 单次发送（poll 未生效）
        warnings = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == _STEP_RUNNER_LOGGER and rec.levelno == logging.WARNING
        ]
        assert any("teardown" in w and "when/poll" in w for w in warnings)

    def test_teardown_without_when_poll_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(command="AT")
        with caplog.at_level(logging.WARNING, logger=_STEP_RUNNER_LOGGER):
            r = _run(step, CaseContext(), fake, is_teardown=True)
        assert r.status is StepStatus.PASS
        assert not [rec for rec in caplog.records if rec.levelno == logging.WARNING]


# ---------------------------------------------------------------------------
# 5. interval 钳制 poll 剩余预算（2b②）
# ---------------------------------------------------------------------------
class TestIntervalClampedToPollBudget:
    def test_poll_interval_delay_clamped_to_remaining_budget(self) -> None:
        """poll 场景 step.interval=5000ms、deadline 剩余 0.05s → 睡 0.05 而非 5.0."""
        clock = MutableClock()
        sleeps: list[float] = []

        def rec_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock.now += seconds

        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\nOK\r\n", persistent=True)
        step = Step(
            command="AT+CREG?",
            extract={"stat": r"\+CEREG: \d,(\d)"},
            interval=5000,  # 前置延迟 5s，远超 poll 预算
            poll=PollConfig(until="stat is not null", timeout=0.05, interval=10),
        )
        r = _run(step, CaseContext(), fake, clock=clock, sleep=rec_sleep)
        # deadline=0.05：前置延迟被钳到剩余预算 0.05（而非 5.0）
        assert sleeps and all(s <= 0.05 + 1e-9 for s in sleeps)
        assert 5.0 not in sleeps
        assert r.status is StepStatus.FAIL  # until 永不满足 → 超时

    def test_retry_path_interval_not_clamped(self) -> None:
        """retry/单次路径无预算概念：interval 睡满 5.0（注入时钟推进，不真等）."""
        clock = MutableClock()
        sleeps: list[float] = []

        def rec_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock.now += seconds

        fake = FakePortManager(sleep=_no_sleep)
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(command="AT", interval=5000)
        r = _run(step, CaseContext(), fake, clock=clock, sleep=rec_sleep)
        assert r.status is StepStatus.PASS
        assert sleeps == [pytest.approx(5.0)]


# ---------------------------------------------------------------------------
# 6. PortBusyError 步骤级分类（2b 终审⑧）
# ---------------------------------------------------------------------------
class TestPortBusyErrorStepLevel:
    def test_command_busy_is_step_failure_not_escape(self) -> None:
        """引擎步骤撞端口命令锁 → 步骤 FAIL 走 on_failure 决策（非异常逃逸）."""
        fake = BusyPortManager()
        fake.busy_command = True
        step = Step(command="AT", on_failure=FailureStrategy.CONTINUE)
        r = _run(step, CaseContext(), fake)  # 未抛 PortBusyError 即为分类成功
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False  # 按 on_failure: continue 决策
        assert "端口正忙" in (r.step_result.error_msg or "")
        assert r.step_result.error_kind == "SEND"

    def test_command_busy_default_aborts(self) -> None:
        """未配置 on_failure 的撞锁 → 默认 ABORT（abort_case=True）."""
        fake = BusyPortManager()
        fake.busy_command = True
        step = Step(command="AT")
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is True

    def test_data_busy_is_step_failure(self) -> None:
        """data 步骤撞锁同口径：send_data 抛 PortBusyError → 步骤级失败."""
        fake = BusyPortManager()
        fake.busy_data = True
        step = Step(data=DataInput(inline="hello"), on_failure=FailureStrategy.CONTINUE)
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False
        assert "端口正忙" in (r.step_result.error_msg or "")
        assert fake.data_sent == []  # 撞锁发生在写入前，字节未发出
