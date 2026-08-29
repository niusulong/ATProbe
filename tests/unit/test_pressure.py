"""压测统计口径回归（P1-6 最小修 + 批 3 §4.2 口径对齐）.

覆盖：
    - 步骤 on_failure: skip 在压测中被规范化为 continue → 失败轮计入 failed_rounds
      （旧实现 SKIPPED → round_ok=True → 成功率虚高、可骗过 pass_threshold）
    - 用例级 on_failure 同样显式规范化为 CONTINUE（§4.2b 防倒退：透传 case 级
      skip 会产生 SKIPPED → 失败轮计为成功轮）
    - 取消中断轮不计入 counted/success/failed，且整轮步骤统计一并丢弃
      （§4.2a 轮末提交：step_stats 与 rounds 完全同口径，旧实现该轮已 PASS
      的步骤仍计入 step_suc/step_rt，分层统计留 ≤1 受控偏差）
    - 轮间隔可取消（F-14）：interval 内取消立即出循环，不再滞留整段间隔
    - P95 用最近秩（ceil）取序（旧截断法 n=20 时 P95=最大值，系统性偏大）
"""

from __future__ import annotations

import time
from collections.abc import Callable

from _fakes import FakeCommandSender

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


class ScriptedSender(FakeCommandSender):
    """按脚本返回响应或抛异常的发送器.

    脚本消费/异常注入/耗尽返回 OK 即基类默认行为（批 5 T4 收敛），
    本类仅保留测试语义命名；签名失配修复见 _fakes.FakeCommandSender。
    """


def _ok() -> Response:
    return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)


def _case(
    on_failure: FailureStrategy | None,
    *,
    case_on_failure: FailureStrategy | None = None,
) -> Case:
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
        on_failure=case_on_failure,
        loop=LoopConfig(count=2, warmup=0, interval=0),
    )


def _run(
    case: Case,
    sender: ICommandSender,
    *,
    sleep: Callable[[float], None] | None = None,
    cancel: CancelToken | None = None,
) -> object:
    return run_pressure(
        case,
        ctx=CaseContext(),
        sender=sender,
        default_port="FAKE",
        step_timeout_default=1.0,
        pass_threshold=100.0,
        clock=time.monotonic,
        sleep=sleep if sleep is not None else (lambda s: None),
        cancel=cancel,
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


class TestInterruptedRoundDiscardsStepStats:
    """§4.2a 中断轮整轮丢弃：该轮此前已 PASS 的步骤不再计入 step_stats."""

    def test_step1_pass_step2_interrupted_discards_whole_round(self) -> None:
        # 2 步用例：步骤 1 PASS 后步骤 2 发送即取消 → 中断轮整轮丢弃
        case = Case(
            name="中断轮步骤统计",
            steps=(Step(command="AT+1"), Step(command="AT+2")),
            loop=LoopConfig(count=1, warmup=0, interval=0),
        )
        sender = ScriptedSender([_ok(), OperationCancelled("stop")])
        result = _run(case, sender)
        s = result.stats
        # rounds 口径：中断轮不计
        assert s.counted_rounds == 0
        assert s.success_rounds == 0
        assert s.failed_rounds == 0
        # step_stats 同口径：步骤 1 该轮已 PASS 也不计入（旧实现 step_suc[1]==1）
        assert s.step_stats[0].success_count == 0
        assert s.step_stats[0].fail_count == 0
        assert s.step_stats[0].skipped_count == 0
        # step_rt 空：无响应时间样本，分布统计量保持默认 0.0
        assert s.step_stats[0].avg_ms == 0.0
        assert s.step_stats[0].p95_ms == 0.0
        assert s.step_stats[1].success_count == 0
        assert s.step_stats[1].fail_count == 0
        assert result.aborted is True
        assert result.abort_reason == "cancelled"


class TestCaseLevelOnFailureNormalized:
    """§4.2b 防倒退：用例级 on_failure 显式规范化为 CONTINUE.

    若透传 case 级 SKIP：execute_step 走 case 级策略产生 SKIPPED → 不计失败、
    不判废该轮 → 失败轮计为成功轮（成功率虚高）。
    """

    def test_case_level_skip_failure_counts_as_failed_round(self) -> None:
        # 步骤级 on_failure=None + 用例级 SKIP：步骤失败仍记 FAIL（非 SKIPPED）
        result = _run(
            _case(None, case_on_failure=FailureStrategy.SKIP),
            ScriptedSender([_ok(), _ok()]),
        )
        s = result.stats
        assert s.counted_rounds == 2
        assert s.success_rounds == 0
        assert s.failed_rounds == 2
        assert s.success_rate == 0.0
        assert s.passed is False
        # 该步记 FAIL 而非 SKIPPED（若 case 级 SKIP 泄漏 → skipped_count==2）
        assert s.step_stats[0].fail_count == 2
        assert s.step_stats[0].skipped_count == 0


class _CancelAfterFirstSend(FakeCommandSender):
    """第 1 次发送返回成功，并在返回前触发取消令牌（模拟轮执行后、间隔期取消）.

    覆写 send_command（不复用基类脚本队列——行为是"无条件成功 + 副作用触发"，
    与队列消费无关）；继承基类仅为固化全形参签名（含 pre_check，批 5 T4）。
    """

    def __init__(self, cancel: CancelToken) -> None:
        super().__init__()
        self._cancel = cancel
        self._sent = False

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
        _ = port, command, timeout, wait_urc, expect, cancel, pre_check
        if not self._sent:
            self._sent = True
            self._cancel.cancel()
        return _ok()


class TestIntervalCancellable:
    """F-14 压测侧：轮间隔分片睡眠、取消即出循环（旧实现整段 sleep 不响应取消）."""

    def _interval_case(self) -> Case:
        return Case(
            name="轮间隔取消",
            steps=(Step(command="AT"),),
            loop=LoopConfig(count=2, warmup=0, interval=5000),
        )

    def test_cancelled_before_interval_exits_immediately(self) -> None:
        # 轮 1 执行成功（发送时置取消令牌，但发送本身成功）→ 轮间隔睡眠入口
        # 即见取消：0 次分片睡眠、循环直接退出
        token = CancelToken()
        recorded: list[float] = []
        result = _run(
            self._interval_case(),
            _CancelAfterFirstSend(token),
            sleep=recorded.append,
            cancel=token,
        )
        assert result.aborted is True
        assert result.abort_reason == "cancelled"
        # 第 1 轮已完成计入；取消发生在间隔期，不回退该轮统计
        assert result.stats.counted_rounds == 1
        assert result.stats.success_rounds == 1
        # 未睡任何分片（5s 间隔被取消打断，非阻塞 5s）
        assert sum(recorded) <= 0.1 * 2
        assert len(recorded) <= 2

    def test_cancel_mid_interval_stops_after_one_slice(self) -> None:
        # 取消发生在间隔睡眠的第 1 个分片内 → 睡 1 片（0.1s）后即出循环
        token = CancelToken()
        recorded: list[float] = []

        def _sleep(d: float) -> None:
            recorded.append(d)
            token.cancel()

        result = _run(
            self._interval_case(),
            ScriptedSender([_ok()]),
            sleep=_sleep,
            cancel=token,
        )
        assert result.aborted is True
        assert result.abort_reason == "cancelled"
        assert result.stats.counted_rounds == 1
        # 恰好 1 个 0.1s 分片后退出（旧实现会睡满整段 5s）
        assert len(recorded) == 1
        assert recorded[0] == 0.1
        assert sum(recorded) <= 0.1 * 2
