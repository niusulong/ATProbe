"""M3 压测执行（REQ-M3 §3.3 流程B、§13 / M2 §13）.

压测语义（M2 §13.2）：
    - 一轮成功标准：单命令=断言通过；序列=全步通过。
    - 失败默认记一次失败继续（abort_on_failure=true 则中止）。
    - interval = 上一轮结束→下一轮开始的间隔。
    - warmup 轮执行但不计入统计。

统计（§13.3 / M3 §8.6/§8.7）：min/max/avg/P95/P99；超时不计入分布（M3 §5.4）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from atprobe.domain.case.models import Case, FailureStrategy, Step
from atprobe.domain.report.models import (
    PressureStats,
    StepPressureStats,
    StepStatus,
)
from atprobe.engine.step_runner import CaseContext, StepExecResult, execute_step
from atprobe.infra.serial.interfaces import (
    CancelToken,
    ICommandSender,
)


@dataclass
class PressureRunResult:
    """压测整体运行结果."""

    stats: PressureStats
    aborted: bool = False


def run_pressure(
    case: Case,
    *,
    ctx: CaseContext,
    sender: ICommandSender,
    default_port: str,
    step_timeout_default: float,
    pass_threshold: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    cancel: CancelToken | None = None,
    on_progress: Callable[[int, int, int, int, float], None] | None = None,
) -> PressureRunResult:
    """执行压测循环（§3.3 流程B）.

    on_progress(current_round, total_rounds, success, fail, avg_ms) 用于实时进度上报。
    """
    assert case.loop is not None
    loop = case.loop
    total = loop.count
    warmup = loop.warmup
    abort_on_fail = loop.abort_on_failure

    # 每步统计容器
    step_rt: dict[int, list[float]] = {}
    step_suc: dict[int, int] = {}
    step_fail: dict[int, int] = {}
    for i, _step in enumerate(case.steps, start=1):
        step_rt[i] = []
        step_suc[i] = 0
        step_fail[i] = 0

    success_rounds = 0
    failed_rounds = 0
    aborted = False
    counted = 0

    # warmup + 正式轮统一循环，靠轮号区分是否计入
    for rnd in range(1, total + 1):
        # 内置变量 loop_index（REQ-M2 §5.4，压测场景从 1 开始）
        ctx.variables["loop_index"] = rnd
        if cancel is not None and cancel.cancelled:
            aborted = True
            break

        round_ok = True
        for idx, step in enumerate(case.steps, start=1):
            # 压测中 on_failure 固定 continue（§4.5）
            effective_step = step
            if step.on_failure is None:
                effective_step = step.model_copy(update={"on_failure": FailureStrategy.CONTINUE})
            result: StepExecResult = execute_step(
                effective_step,
                index=idx, phase="steps", ctx=ctx, sender=sender,
                default_port=default_port, step_timeout_default=step_timeout_default,
                clock=clock, sleep=sleep, cancel=cancel,
            )
            sr = result.step_result
            if sr.status is StepStatus.PASS:
                if rnd > warmup:
                    step_suc[idx] += 1
                    step_rt[idx].append(sr.duration_ms)
            else:
                if rnd > warmup:
                    step_fail[idx] += 1
                round_ok = False
                if abort_on_fail:
                    aborted = True
                    break

        if rnd > warmup:
            counted += 1
            if round_ok:
                success_rounds += 1
            else:
                failed_rounds += 1

        # 进度上报（含 warmup 轮）
        if on_progress is not None and (rnd % max(1, total // 20) == 0 or rnd == total):
            avg = _avg_all(step_rt)
            on_progress(rnd, total, success_rounds, failed_rounds, avg)

        if aborted:
            break

        if rnd < total:
            sleep(loop.interval / 1000.0)

    # 构建每步统计
    step_stats = tuple(
        _build_step_stat(idx, case.steps[idx - 1], step_rt[idx], step_suc[idx], step_fail[idx])
        for idx in sorted(step_rt.keys())
    )

    success_rate = (success_rounds / counted * 100.0) if counted > 0 else 0.0
    passed = success_rate >= pass_threshold and not aborted

    stats = PressureStats(
        total_rounds=total, warmup_rounds=warmup, counted_rounds=counted,
        success_rounds=success_rounds, failed_rounds=failed_rounds,
        success_rate=success_rate, aborted=aborted,
        pass_threshold=pass_threshold, passed=passed, step_stats=step_stats,
    )
    return PressureRunResult(stats=stats, aborted=aborted)


def _step_command(step: Step) -> str:
    if step.command is not None:
        return step.command
    if step.data is not None and step.data.file is not None:
        return step.data.file
    if step.data is not None and step.data.inline is not None:
        return step.data.inline
    return ""


def _build_step_stat(
    idx: int, step: Step, times: list[float], suc: int, fail: int
) -> StepPressureStats:
    cmd = _step_command(step)
    if times:
        s = sorted(times)
        n = len(s)
        avg = sum(s) / n
        p95 = s[min(n - 1, int(n * 0.95))]
        p99 = s[min(n - 1, int(n * 0.99))]
        return StepPressureStats(
            step_index=idx, command=cmd,
            success_count=suc, fail_count=fail,
            min_ms=s[0], max_ms=s[-1], avg_ms=avg,
            p95_ms=p95, p99_ms=p99,
        )
    return StepPressureStats(
        step_index=idx, command=cmd,
        success_count=suc, fail_count=fail,
    )


def _avg_all(step_rt: dict[int, list[float]]) -> float:
    all_t = [t for ts in step_rt.values() for t in ts]
    return sum(all_t) / len(all_t) if all_t else 0.0
