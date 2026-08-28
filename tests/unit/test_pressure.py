"""压测统计口径回归（P1-6 最小修）.

覆盖：
    - 步骤 on_failure: skip 在压测中被规范化为 continue → 失败轮计入 failed_rounds
      （旧实现 SKIPPED → round_ok=True → 成功率虚高、可骗过 pass_threshold）
    - 取消中断轮不计入 counted/success/failed（旧口径统计虚高）
    - P95 用最近秩（ceil）取序（旧截断法 n=20 时 P95=最大值，系统性偏大）
"""

from __future__ import annotations

import time

from atprobe.domain.case.models import (
    AssertElement,
    Case,
    FailureStrategy,
    LoopConfig,
    Step,
)
from atprobe.engine.pressure import _build_step_stat, run_pressure
from atprobe.engine.step_runner import CaseContext
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import (
    CancelToken,
    ICommandSender,
    Response,
    ResponseStatus,
)


class ScriptedSender(ICommandSender):
    """按脚本返回响应或抛异常的发送器."""

    def __init__(self, script: list[Response | BaseException]) -> None:
        self._script = list(script)

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
        # expect：step_runner 无条件透传（批 2b Task 6），替身只接受不消费
        _ = expect
        item = self._script.pop(0) if self._script else _ok()
        if isinstance(item, BaseException):
            raise item
        return item


def _ok() -> Response:
    return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)


def _case(on_failure: FailureStrategy | None) -> Case:
    """单步必败用例（断言 contains FAILMARK，响应只有 OK）."""
    return Case(
        name="压测口径",
        steps=(
            Step(
                command="AT",
                assert_=[AssertElement(contains="FAILMARK")],
                on_failure=on_failure,
            ),
        ),
        loop=LoopConfig(count=2, warmup=0, interval=0),
    )


def _run(case: Case, sender: ICommandSender) -> object:
    return run_pressure(
        case,
        ctx=CaseContext(),
        sender=sender,
        default_port="FAKE",
        step_timeout_default=1.0,
        pass_threshold=100.0,
        clock=time.monotonic,
        sleep=lambda s: None,
    )


class TestOnFailureNormalizedToContinue:
    def test_skip_config_failure_counts_as_failed_round(self) -> None:
        result = _run(_case(FailureStrategy.SKIP), ScriptedSender([_ok(), _ok()]))
        s = result.stats
        assert s.counted_rounds == 2
        assert s.success_rounds == 0
        assert s.failed_rounds == 2
        assert s.success_rate == 0.0
        assert s.passed is False


class TestInterruptedRoundNotCounted:
    def test_interrupted_round_excluded_from_stats(self) -> None:
        # 第 1 轮通过（无断言的直通用例），第 2 轮发送即取消 → 中断轮不计入统计
        ok_case = Case(
            name="中断轮",
            steps=(Step(command="AT"),),
            loop=LoopConfig(count=2, warmup=0, interval=0),
        )
        sender = ScriptedSender([_ok(), OperationCancelled("stop")])
        result = _run(ok_case, sender)
        s = result.stats
        assert s.counted_rounds == 1
        assert s.success_rounds == 1
        assert s.failed_rounds == 0
        assert result.aborted is True
        assert result.abort_reason == "cancelled"


class TestPercentileCeilingRank:
    def test_p95_uses_ceiling_rank_n20(self) -> None:
        times = [float(i) for i in range(1, 21)]  # 1..20ms
        stat = _build_step_stat(1, Step(command="AT"), times, suc=20, fail=0)
        # ceil(20*0.95)=19 → s[18]=19.0；旧截断法 int(19.0)=19 → s[19]=20.0（取到最大值）
        assert stat.p95_ms == 19.0
