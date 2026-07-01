"""M3 单步执行器（REQ-M3 §3.1 单步骤流程、§4 失败处理、§9 retry、§11 poll）.

实现单个步骤的完整执行流程（§3.1）::

    1. 检查 when 条件（false → SKIPPED）
    2. 解析输入（command/data），模板替换 {{var}}
    3. 发送 + 接收响应（带 retry 或 poll）
    4. extract（写入用例变量池）
    5. assert
    6. 记录步骤结果
    7. FAIL 时按 on_failure 处理

关键语义（§4.2 分层）：
    - retry 围绕「单次执行（发送→extract→断言）」判定，吃掉重试期间的失败
      （§4.3：重试是完整步骤重做，含重新 extract/assert）。因此 retry 判定基于步骤
      是否成功（发送成功且断言通过），而非仅发送成功。
    - poll 最外层独占：单次「发送→条件不满足」是正常轮询节奏，不算失败；poll.timeout
      到期才 FAIL → 走 on_failure。
    - poll 与 retry 互斥（M2 模型已校验）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from atprobe.domain.case.assessor import AssertionOutcome, assess_all
from atprobe.domain.case.evaluator import ExpressionError, evaluate
from atprobe.domain.case.extractor import extract_all
from atprobe.domain.case.models import FailureStrategy, Step
from atprobe.domain.case.templater import (
    TemplateRenderError,
    UndefinedReferenceError,
    render,
)
from atprobe.domain.report.models import (
    AssertionResult,
    InputType,
    StepResult,
    StepStatus,
)
from atprobe.infra.config.envconfig import EnvConfig
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import (
    CancelToken,
    ICommandSender,
    Response,
)


class StepInterrupted(Exception):
    """步骤被 stop 中断（不等于失败）。"""


@dataclass
class CaseContext:
    """单个用例执行期间的可变上下文（变量池等）.

    引擎线程私有，串行执行，无需同步。
    """

    variables: dict[str, object] = field(default_factory=dict)
    env: EnvConfig | None = None
    disconnect_streak: int = 0


@dataclass
class StepExecResult:
    """步骤执行结果."""

    status: StepStatus
    step_result: StepResult
    extracted: dict[str, str] = field(default_factory=dict)
    abort_case: bool = False
    interrupted: bool = False


# ---------------------------------------------------------------------------
# 单次执行（发送→extract→断言）的核心，返回单次的「成功/失败」判定
# ---------------------------------------------------------------------------
@dataclass
class _SingleAttempt:
    """单次执行（发送+extract+断言）的结果."""

    response: Response
    extracted: dict[str, str]
    assertion_outcomes: list[AssertionOutcome]
    step_passed: bool  # 本次是否成功（发送 ok 且断言全通过）
    step_error: str  # 失败原因（成功时为空）
    duration_ms: float


def execute_step(
    step: Step,
    *,
    index: int,
    phase: str,
    ctx: CaseContext,
    sender: ICommandSender,
    default_port: str,
    step_timeout_default: float,
    case_on_failure: FailureStrategy | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    cancel: CancelToken | None = None,
    is_teardown: bool = False,
) -> StepExecResult:
    """执行单个步骤（§3.1）."""
    port = step.port or default_port
    timeout = step.timeout if step.timeout is not None else step_timeout_default
    input_type = InputType.DATA if step.data is not None else InputType.COMMAND

    # ------------------------------------------------------------------
    # 0. 内置变量注入（REQ-M2 §5.4）
    # ------------------------------------------------------------------
    ctx.variables["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ctx.variables["port"] = port
    # loop_index 仅压测场景由 pressure.run_pressure 注入，常规场景不注入

    # ------------------------------------------------------------------
    # 1. when 条件检查（teardown 不支持 when）
    # ------------------------------------------------------------------
    if not is_teardown and step.when is not None:
        try:
            cond = evaluate(step.when, ctx.variables)
        except (ExpressionError, UndefinedReferenceError) as exc:
            return _build_skipped(index, phase, port, step, f"when 表达式错误：{exc}", is_fail=True)
        if not cond:
            return _build_skipped(index, phase, port, step, "when 条件不满足")

    # ------------------------------------------------------------------
    # 2. 模板替换
    # ------------------------------------------------------------------
    try:
        request = _render_input(step, ctx)
    except (UndefinedReferenceError, TemplateRenderError) as exc:
        sr = StepResult(
            step_index=index, phase=phase, input_type=input_type,
            command=_truncate(_cmd_display(step)), port=port,
            status=StepStatus.FAIL, request="", response="",
            error_msg=f"模板渲染失败：{exc}",
        )
        return StepExecResult(status=StepStatus.FAIL, step_result=sr, abort_case=True)

    command_display = _truncate(request if step.command is not None else _cmd_display(step))

    # ------------------------------------------------------------------
    # 3-6. 发送+判定（poll / retry / 单次）
    # ------------------------------------------------------------------
    try:
        if step.poll is not None and not is_teardown:
            attempt, poll_iters = _run_poll(
                step, request, port, timeout, ctx, sender, clock, sleep, cancel
            )
            retry_count = 0
        else:
            attempt, retry_count = _run_retry(
                step, request, port, timeout, ctx, sender, clock, sleep, cancel
            )
            poll_iters = 0
    except OperationCancelled:
        sr = StepResult(
            step_index=index, phase=phase, input_type=input_type, command=command_display,
            port=port, status=StepStatus.INTERRUPTED, request=request, response="",
        )
        return StepExecResult(status=StepStatus.INTERRUPTED, step_result=sr, interrupted=True)

    # 提交 extract 到变量池（最后一次执行的值，§9.2 变量值保留）
    for k, v in attempt.extracted.items():
        ctx.variables[k] = v

    status = StepStatus.PASS if attempt.step_passed else StepStatus.FAIL

    assertion_results = tuple(
        AssertionResult(
            name=a.name, op_kind=a.op_kind, expected=a.expected, actual=a.actual,
            passed=a.passed, reason=a.reason,
        )
        for a in attempt.assertion_outcomes
    )
    sr = StepResult(
        step_index=index, phase=phase, input_type=input_type, command=command_display,
        port=port, status=status, request=request, response=attempt.response.text,
        assertions=assertion_results, extracted_vars=dict(attempt.extracted),
        duration_ms=attempt.duration_ms, retry_count=retry_count,
        poll_iterations=poll_iters, error_msg=attempt.step_error,
    )

    # ------------------------------------------------------------------
    # 7. on_failure
    # ------------------------------------------------------------------
    abort_case = False
    if status is StepStatus.FAIL and not is_teardown:
        strategy = step.on_failure or case_on_failure or FailureStrategy.ABORT
        abort_case = strategy is FailureStrategy.ABORT

    return StepExecResult(
        status=status, step_result=sr, extracted=attempt.extracted, abort_case=abort_case
    )


# ---------------------------------------------------------------------------
# retry：围绕「单次执行（发送→extract→断言）」判定（§4.3 / §9）
# ---------------------------------------------------------------------------
def _run_retry(
    step: Step,
    request: str,
    port: str,
    timeout: float,
    ctx: CaseContext,
    sender: ICommandSender,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    cancel: CancelToken | None,
) -> tuple[_SingleAttempt, int]:
    retry = step.retry
    max_attempts = (retry.count + 1) if retry is not None else 1

    last: _SingleAttempt | None = None
    total_duration = 0.0
    for attempt_no in range(max_attempts):
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled("步骤被取消")
        if attempt_no > 0 and retry is not None:
            sleep(retry.interval / 1000.0)
        attempt = _single_attempt(step, request, port, timeout, ctx, sender, clock, cancel)
        total_duration += attempt.duration_ms
        # 合并耗时到 attempt
        attempt.duration_ms = total_duration
        last = attempt
        if attempt.step_passed:
            return attempt, attempt_no  # retry_count = attempt_no
    assert last is not None
    return last, max_attempts - 1


# ---------------------------------------------------------------------------
# poll：最外层独占，单次不满足不算失败（§4.4 / §11）
# ---------------------------------------------------------------------------
def _run_poll(
    step: Step,
    request: str,
    port: str,
    timeout: float,
    ctx: CaseContext,
    sender: ICommandSender,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    cancel: CancelToken | None,
) -> tuple[_SingleAttempt, int]:
    assert step.poll is not None
    poll = step.poll
    deadline = clock() + poll.timeout
    interval = poll.interval / 1000.0
    iterations = 0
    total_duration = 0.0

    while True:
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled("poll 被取消")
        iterations += 1
        attempt = _single_attempt(step, request, port, timeout, ctx, sender, clock, cancel)
        total_duration += attempt.duration_ms
        attempt.duration_ms = total_duration

        # poll 判定：until 条件是否满足（基于本次 extract 的临时作用域）
        if attempt.response.ok:
            tmp_scope = dict(ctx.variables)
            tmp_scope.update(attempt.extracted)
            try:
                if evaluate(poll.until, tmp_scope):
                    attempt.step_passed = True
                    attempt.step_error = ""
                    return attempt, iterations
            except Exception:  # noqa: BLE001
                pass

        if clock() >= deadline:
            # poll 超时 → 步骤失败（§4.4）
            attempt.step_passed = False
            attempt.step_error = "poll 超时未满足条件"
            return attempt, iterations
        sleep(interval)


# ---------------------------------------------------------------------------
# 单次执行：发送 → extract → 断言
# ---------------------------------------------------------------------------
def _single_attempt(
    step: Step,
    request: str,
    port: str,
    timeout: float,
    ctx: CaseContext,
    sender: ICommandSender,
    clock: Callable[[], float],
    cancel: CancelToken | None,
) -> _SingleAttempt:
    t0 = clock()
    resp = sender.send_command(port, request, timeout=timeout, cancel=cancel)
    dt = (clock() - t0) * 1000.0

    extracted: dict[str, str] = {}
    outcomes: list[AssertionOutcome] = []

    if not resp.ok:
        return _SingleAttempt(
            response=resp, extracted=extracted, assertion_outcomes=outcomes,
            step_passed=False, step_error=resp.error or "响应异常", duration_ms=dt,
        )

    if step.extract:
        values, _matched = extract_all(step.extract, resp.text)
        extracted = values

    # 断言求值用「本次 extract + 已有变量池」临时作用域（不污染 ctx，由外层提交）
    tmp_scope = dict(ctx.variables)
    tmp_scope.update(extracted)
    if step.assertions:
        outcomes = assess_all(step.assertions, resp.text, tmp_scope)

    if step.assertions and any(not a.passed for a in outcomes):
        failed = next(a for a in outcomes if not a.passed)
        return _SingleAttempt(
            response=resp, extracted=extracted, assertion_outcomes=outcomes,
            step_passed=False, step_error=failed.reason or "断言失败", duration_ms=dt,
        )
    return _SingleAttempt(
        response=resp, extracted=extracted, assertion_outcomes=outcomes,
        step_passed=True, step_error="", duration_ms=dt,
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _render_input(step: Step, ctx: CaseContext) -> str:
    if step.command is not None:
        return render(step.command, ctx.variables, env=ctx.env)
    assert step.data is not None
    if step.data.inline is not None:
        return render(step.data.inline, ctx.variables, env=ctx.env)
    assert step.data.file is not None
    return render(step.data.file, ctx.variables, env=ctx.env)


def _cmd_display(step: Step) -> str:
    if step.command is not None:
        return step.command
    if step.data is not None:
        return step.data.file or "[data]"
    return ""


def _truncate(s: str, n: int = 60) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _build_skipped(
    index: int, phase: str, port: str, step: Step, msg: str, *, is_fail: bool = False
) -> StepExecResult:
    it = InputType.DATA if step.data is not None else InputType.COMMAND
    status = StepStatus.FAIL if is_fail else StepStatus.SKIPPED
    sr = StepResult(
        step_index=index, phase=phase, input_type=it,
        command=_truncate(_cmd_display(step)), port=port,
        status=status, request="", response="", error_msg=msg,
    )
    return StepExecResult(status=status, step_result=sr, abort_case=is_fail)
