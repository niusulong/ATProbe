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
from pathlib import Path

from atprobe.domain.case.assessor import AssertionOutcome, assess_all
from atprobe.domain.case.datasource import DataPathError, read_data_file
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
from atprobe.infra.serial.config import DataStreamSpec
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import (
    ERROR_KIND_TIMEOUT,
    CancelToken,
    ICommandSender,
    Response,
    ResponseStatus,
)


@dataclass
class CaseContext:
    """单个用例执行期间的可变上下文（变量池等）.

    引擎线程私有，串行执行，无需同步。
    """

    variables: dict[str, object] = field(default_factory=dict)
    env: EnvConfig | None = None
    disconnect_streak: int = 0
    # S-8 数据路径信任边界（设计 §5）：data.file 渲染后路径须落在
    # 「case_dir ∪ data_allowed_roots」内。case_dir 由 scheduler 从
    # case.source_file 派生；额外根来自 EngineConfig.data_allowed_roots
    # （批 4 并入 mcp.allowed_roots）。None/空 = 无对应锚根。
    case_dir: Path | None = None
    data_allowed_roots: tuple[Path, ...] = ()


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
    matched: dict[str, bool]  # 每个 extract 是否匹配（用于过滤不写入池、不并入断言作用域）
    assertion_outcomes: list[AssertionOutcome]
    step_passed: bool  # 本次是否成功（发送 ok 且断言全通过）
    step_error: str  # 失败原因（成功时为空）
    duration_ms: float
    error_kind: str = "NONE"  # 结构化错误分类，从 Response 透传（M3）


@dataclass
class _DataPayload:
    """data 步骤解析产物（批 2b Task 6，修 P0-1）.

    spec     已装配的数据流规格（字节 + 分块参数，交 sender.send_data）。
    display  人类可读摘要（"[data N字节] 前 60 字节解码预览"），作 StepResult.request
             与报告 command 字段——data 步骤的「实际发送内容」无法用字符串完整
             表达（可为二进制），摘要兼顾可读与二进制安全。
    """

    spec: DataStreamSpec
    display: str


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
    wait_urc = step.wait_urc  # None=不启用（OK 即终结）；非空=异步指令等 URC 终结
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
            cond = evaluate(step.when, ctx.variables, env=ctx.env)
        except (ExpressionError, UndefinedReferenceError) as exc:
            # P1 修复：when 表达式错误与普通失败一样走 on_failure 决策
            # （旧实现硬编码 abort_case=True，绕过 on_failure: continue/skip）
            return _author_error_result(
                index, phase, port, step, f"when 表达式错误：{exc}", case_on_failure, is_teardown
            )
        if not cond:
            return _build_skipped(index, phase, port, step, "when 条件不满足")

    # ------------------------------------------------------------------
    # 2. 输入解析：command 渲染 / data 载荷装配（P0-1：data 步骤在此真正
    #    读出字节，S-8 锚定校验同步生效——渲染后路径须落在锚集内）
    # ------------------------------------------------------------------
    payload: _DataPayload | None = None
    try:
        if step.data is not None:
            payload = _resolve_data(step, ctx)
            request = payload.display  # 报告 request/中断分支统一用数据摘要
        else:
            request = _render_input(step, ctx)
    except (UndefinedReferenceError, TemplateRenderError) as exc:
        # P1 修复：同上，模板渲染失败走 on_failure 决策而非硬编码中止
        return _author_error_result(
            index, phase, port, step, f"模板渲染失败：{exc}", case_on_failure, is_teardown
        )
    except DataPathError as exc:
        # 数据源解析失败（S-8 越界/不可读、空数据、坏十六进制）：与模板失败
        # 同口径的用例作者错误，走 on_failure 决策（错误信息自带路径与锚集）
        return _author_error_result(
            index, phase, port, step, f"数据输入解析失败：{exc}", case_on_failure, is_teardown
        )

    # command/data 统一：request 即展示内容（data 为摘要，command 为渲染文本）
    command_display = _truncate(request)

    # ------------------------------------------------------------------
    # 3-6. 发送+判定（poll / retry / 单次）
    # ------------------------------------------------------------------
    try:
        if step.poll is not None and not is_teardown:
            attempt, poll_iters = _run_poll(
                step, request, payload, port, timeout, wait_urc, ctx, sender, clock, sleep, cancel
            )
            retry_count = 0
        else:
            attempt, retry_count = _run_retry(
                step, request, payload, port, timeout, wait_urc, ctx, sender, clock, sleep, cancel
            )
            poll_iters = 0
    except OperationCancelled:
        sr = StepResult(
            step_index=index,
            phase=phase,
            input_type=input_type,
            command=command_display,
            port=port,
            status=StepStatus.INTERRUPTED,
            request=request,
            response="",
        )
        return StepExecResult(status=StepStatus.INTERRUPTED, step_result=sr, interrupted=True)

    # 提交 extract 到变量池（仅匹配成功的变量；失败的等同未定义，REQ-M2 §5.1）
    for k, v in attempt.extracted.items():
        if attempt.matched.get(k, True):
            ctx.variables[k] = v

    # status 与 abort_case 一并算出（含 skip 区分，REQ-M2 §3.4）
    strategy: FailureStrategy | None = None
    if not attempt.step_passed:
        strategy = step.on_failure or case_on_failure or FailureStrategy.ABORT

    if not attempt.step_passed and strategy is FailureStrategy.SKIP:
        status = StepStatus.SKIPPED  # skip：步骤记 SKIPPED（不算失败）
    else:
        status = StepStatus.PASS if attempt.step_passed else StepStatus.FAIL

    assertion_results = tuple(
        AssertionResult(
            name=a.name,
            op_kind=a.op_kind,
            expected=a.expected,
            actual=a.actual,
            passed=a.passed,
            reason=a.reason,
        )
        for a in attempt.assertion_outcomes
    )
    sr = StepResult(
        step_index=index,
        phase=phase,
        input_type=input_type,
        command=command_display,
        port=port,
        status=status,
        request=request,
        response=attempt.response.text,
        assertions=assertion_results,
        extracted_vars=dict(attempt.extracted),
        duration_ms=attempt.duration_ms,
        retry_count=retry_count,
        poll_iterations=poll_iters,
        error_msg=attempt.step_error,
        error_kind=attempt.error_kind,
    )

    # ------------------------------------------------------------------
    # 7. on_failure
    # ------------------------------------------------------------------
    # on_failure（skip 已在 status 体现，此处仅决 abort_case）
    abort_case = not is_teardown and status is StepStatus.FAIL and strategy is FailureStrategy.ABORT

    return StepExecResult(
        status=status, step_result=sr, extracted=attempt.extracted, abort_case=abort_case
    )


# ---------------------------------------------------------------------------
# retry：围绕「单次执行（发送→extract→断言）」判定（§4.3 / §9）
# ---------------------------------------------------------------------------
def _run_retry(
    step: Step,
    request: str,
    payload: _DataPayload | None,
    port: str,
    timeout: float,
    wait_urc: str | None,
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
            # P2 修复（耗时口径）：重试间隔计入步骤总耗时（旧实现低估实际耗时）
            t_wait = clock()
            sleep(retry.interval / 1000.0)
            total_duration += (clock() - t_wait) * 1000.0
        attempt = _single_attempt(
            step, request, payload, port, timeout, wait_urc, ctx, sender, clock, sleep, cancel
        )
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
    payload: _DataPayload | None,
    port: str,
    timeout: float,
    wait_urc: str | None,
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
    # 记录 until 表达式的首次编译错误（仅一次）；运行期变量未定义不算错误，继续轮询。
    # M7 修复：旧实现 except Exception: pass 把表达式编译错误也静默吞掉，用户看到的是
    # "poll 超时未满足条件"而非"until 表达式错误"，排查困难。
    expr_error: str = ""

    while True:
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled("poll 被取消")
        iterations += 1
        # 注：首轮立即查询（sleep 在循环末尾）。这是有意设计——poll 典型场景是
        # 「发指令后等设备产生结果」，首轮立即查询可在结果已就绪时省掉一个 interval
        # 的等待；上一条命令的残留响应已由 send_command 入口的 _drain_response_q 清排。
        # P2 修复（超时预算）：单次 attempt 等待上限取「步骤超时」与「poll 剩余
        # 预算」较小值——旧实现末次 attempt 可阻塞整个步骤超时，poll 实际耗时
        # 大幅超出 poll.timeout。
        remaining_budget = max(deadline - clock(), 0.05)
        attempt = _single_attempt(
            step,
            request,
            payload,
            port,
            min(timeout, remaining_budget),
            wait_urc,
            ctx,
            sender,
            clock,
            sleep,
            cancel,
        )
        total_duration += attempt.duration_ms
        attempt.duration_ms = total_duration

        # poll 判定：until 条件是否满足（基于本次 extract 的临时作用域）
        # P0 修复：until 满足**且**本次断言通过才算成功——旧实现无条件覆盖
        # step_passed=True，把断言失败静默翻转为 PASS（报告出现「PASS 步骤带失败
        # 断言」的自相矛盾）。poll 的成功语义 = 条件满足 + 断言通过，二者缺一不可。
        if attempt.response.ok:
            tmp_scope = dict(ctx.variables)
            # P1 修复：只合并「实际匹配到」的 extract 变量（与常规步骤提交口径一致，
            # step_runner 提交池时按 matched 过滤）。旧实现把未匹配变量置 "" 合并，
            # 导致 `x is not null` 在 extract 失败的轮次假成功、`x is null` 永远轮询
            # 到超时——与 when/后续步骤的「未匹配=未定义→null」语义矛盾。
            tmp_scope.update(
                {k: v for k, v in attempt.extracted.items() if attempt.matched.get(k, True)}
            )
            try:
                if evaluate(poll.until, tmp_scope, env=ctx.env):
                    if attempt.step_passed:
                        return attempt, iterations
                    # until 已满足但断言失败：保留断言失败原因，不再继续轮询
                    # （条件已达成，重试同样的断言不会变好），也不覆盖为「超时」。
                    attempt.step_error = attempt.step_error or "poll 条件已满足但断言失败"
                    return attempt, iterations
            except UndefinedReferenceError:
                # 变量尚未定义（extract 还没拿到值）→ 继续轮询，属正常 poll 节奏
                pass
            except ExpressionError as exc:
                # 表达式编译/语法错误 → 首次记录，继续轮询（可能在首轮变量未就绪时报错）
                if not expr_error:
                    expr_error = str(exc)

        if clock() >= deadline:
            # poll 超时 → 步骤失败（§4.4）。优先报告表达式错误（若有），否则报超时
            attempt.step_passed = False
            attempt.step_error = (
                f"poll until 表达式错误：{expr_error}" if expr_error else "poll 超时未满足条件"
            )
            return attempt, iterations
        # P2 修复（耗时口径）：间隔等待计入步骤总耗时——旧实现只累计发送/等待
        # 时长，报告与压测 avg 系统性低估（retry.count=3、interval=1s 时差 ~3s）。
        # 复审补充：sleep 按剩余预算截断——贴 deadline 到达的响应通过检查后仍
        # sleep 满 interval 会残余溢出约 interval+0.05s（复审实测 11.04s/预算 10s）。
        t_wait = clock()
        sleep(min(interval, max(deadline - clock(), 0.0)))
        total_duration += (clock() - t_wait) * 1000.0
        attempt.duration_ms = total_duration


# ---------------------------------------------------------------------------
# 单次执行：发送 → extract → 断言
# ---------------------------------------------------------------------------
def _single_attempt(
    step: Step,
    request: str,
    payload: _DataPayload | None,
    port: str,
    timeout: float,
    wait_urc: str | None,
    ctx: CaseContext,
    sender: ICommandSender,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    cancel: CancelToken | None,
) -> _SingleAttempt:
    t0 = clock()
    # interval 接线（批 2b Task 6，此前为模型死字段）：每次 attempt 发送前的
    # 固定延迟（ms→s），command/data 统一。ch06「收到 > 提示符后延迟 50-100ms
    # 再发数据」即 data 步骤 interval 的典型场景；计入步骤耗时（t0 已起表）。
    if step.interval:
        sleep(step.interval / 1000.0)
    matched: dict[str, bool] = {}
    # 发送分叉（P0-1 核心）：data 步骤走 send_data 通道（分块/持锁由 spec 携带），
    # command 步骤照旧 send_command。expect 从 step.expect 传入——「附加完成
    # 条件」（如 TCPSEND 提示符 \r\n>）自此对引擎步骤生效（2a 协议已备好形参）。
    if payload is not None:
        resp = sender.send_data(
            port,
            payload.spec,
            timeout=timeout,
            wait_urc=wait_urc,
            expect=step.expect,
            cancel=cancel,
        )
    else:
        resp = sender.send_command(
            port, request, timeout=timeout, wait_urc=wait_urc, expect=step.expect, cancel=cancel
        )
    dt = (clock() - t0) * 1000.0

    extracted: dict[str, str] = {}
    outcomes: list[AssertionOutcome] = []

    if not resp.ok:
        return _SingleAttempt(
            response=resp,
            extracted=extracted,
            matched=matched,
            assertion_outcomes=outcomes,
            step_passed=False,
            step_error=resp.error or "响应异常",
            duration_ms=dt,
            error_kind=resp.error_kind,
        )

    # TIMEOUT 三态语义（真机测试修正的业务码机制）：
    #   1) 文本非空且以 \r\n 结尾 → **业务码响应**：设备已送完整行但不以 OK/ERROR
    #      终结（如 +UPDATETIME: No PPP Link），框架按设计经超时交付（见
    #      interfaces.ResponseStatus.TIMEOUT「完整但超时」与 SKILL「业务码超时
    #      陷阱」）——必须参与 extract/assert（43 个存量 N58 用例依赖此模式，
    #      严格 ^...$ 锚定断言自身防伪）。
    #   2) 文本为空/纯空白 → 完全无响应，直接失败。
    #   3) 文本非空但不以 \r\n 结尾 → 行中被截断（半截数据），不参与断言，
    #      失败并保留文本供诊断（防 contains 在残缺文本上假命中）。
    if resp.status is ResponseStatus.TIMEOUT:
        text = resp.text
        if text.strip() and text.endswith("\r\n"):
            pass  # 业务码：落入下方正常 extract/断言路径
        else:
            reason = (
                "响应超时（无任何数据）"
                if not text.strip()
                else "响应超时（数据不完整，不参与断言）"
            )
            return _SingleAttempt(
                response=resp,
                extracted=extracted,
                matched=matched,
                assertion_outcomes=outcomes,
                step_passed=False,
                step_error=reason,
                duration_ms=dt,
                error_kind=ERROR_KIND_TIMEOUT,
            )

    if step.extract:
        values, matched = extract_all(step.extract, resp.text)
        extracted = values

    # 断言求值用「本次 extract + 已有变量池」临时作用域（不污染 ctx，由外层提交）
    tmp_scope = dict(ctx.variables)
    # P1-5 修复：只合并「实际匹配到」的 extract 变量——与 _run_poll 的 until 判定
    # 口径一致（「未匹配=未定义→null」）。旧实现把未匹配变量置 "" 并入断言作用域，
    # `{var: x, op: ne, value: "ERROR"}` 在提取失败时 "" != "ERROR" 假成功。
    tmp_scope.update({k: v for k, v in extracted.items() if matched.get(k, True)})
    if step.assertions:
        outcomes = assess_all(step.assertions, resp.text, tmp_scope)

    if step.assertions and any(not a.passed for a in outcomes):
        failed = next(a for a in outcomes if not a.passed)
        return _SingleAttempt(
            response=resp,
            extracted=extracted,
            matched=matched,
            assertion_outcomes=outcomes,
            step_passed=False,
            step_error=failed.reason or "断言失败",
            duration_ms=dt,
        )
    return _SingleAttempt(
        response=resp,
        extracted=extracted,
        matched=matched,
        assertion_outcomes=outcomes,
        step_passed=True,
        step_error="",
        duration_ms=dt,
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _render_input(step: Step, ctx: CaseContext) -> str:
    """command 步骤的模板渲染（data 步骤走 _resolve_data，不经过此处）.

    case_dir/data_allowed_roots 透传给 render：命令里可用 {{file_size("./x.bin")}}
    （S-8 锚定同 data 路径），如 AT+FSWF 的长度参数。
    """
    assert step.command is not None
    return render(
        step.command,
        ctx.variables,
        env=ctx.env,
        case_dir=ctx.case_dir,
        data_allowed_roots=ctx.data_allowed_roots,
    )


def _resolve_data(step: Step, ctx: CaseContext) -> _DataPayload:
    """data 步骤输入解析（P0-1）：模板渲染 → 字节装配 → DataStreamSpec.

    - file：渲染路径 → datasource.read_data_file（S-8 锚定校验 + 读字节）；
    - inline：渲染 → UTF-8 编码；
    - inline_hex：渲染 → bytes.fromhex（渲染注入坏十六进制 → DataPathError）；
    - 零字节拒绝：设备会等满声明长度，发空数据只会拖到超时（模型校验拦不住
      渲染产物，如变量渲染出空串/纯空白十六进制）。

    UndefinedReferenceError/TemplateRenderError/DataPathError 均由 execute_step
    的 except 捕获走 _author_error_result（on_failure 决策）。
    """
    assert step.data is not None
    d = step.data
    if d.file is not None:
        raw_path = render(
            d.file,
            ctx.variables,
            env=ctx.env,
            case_dir=ctx.case_dir,
            data_allowed_roots=ctx.data_allowed_roots,
        )
        data = read_data_file(raw_path, ctx.case_dir, ctx.data_allowed_roots)
    elif d.inline is not None:
        data = (
            render(
                d.inline,
                ctx.variables,
                env=ctx.env,
                case_dir=ctx.case_dir,
                data_allowed_roots=ctx.data_allowed_roots,
            )
        ).encode("utf-8")
    else:
        assert d.inline_hex is not None
        rendered = render(
            d.inline_hex,
            ctx.variables,
            env=ctx.env,
            case_dir=ctx.case_dir,
            data_allowed_roots=ctx.data_allowed_roots,
        )
        try:
            data = bytes.fromhex(rendered)
        except ValueError as exc:
            raise DataPathError(f"inline_hex 解析失败：{exc}") from exc
    if not data:
        raise DataPathError("data 步骤解析得到 0 字节数据（空文件/空内联/空十六进制）")
    spec = DataStreamSpec(
        data=data,
        chunk_threshold=d.chunk_threshold,
        chunk_size=d.chunk_size,
        chunk_interval_ms=d.chunk_interval,
        append_terminator=d.append_terminator,
    )
    # 二进制安全摘要：前 60 字节按 UTF-8 容错解码（与 _truncate 截断风格协调）
    display = f"[data {len(data)}字节] " + data[:60].decode("utf-8", errors="replace")
    return _DataPayload(spec=spec, display=display)


def _cmd_display(step: Step) -> str:
    if step.command is not None:
        return step.command
    if step.data is not None:
        return step.data.file or "[data]"
    return ""


def _truncate(s: str, n: int = 60) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _author_error_result(
    index: int,
    phase: str,
    port: str,
    step: Step,
    msg: str,
    case_on_failure: FailureStrategy | None,
    is_teardown: bool,
) -> StepExecResult:
    """用例作者错误（模板渲染失败/when 表达式错误）的统一出口.

    P1 修复：这类错误此前硬编码 abort_case=True，绕过 on_failure 决策——
    用户显式配置 on_failure: continue/skip 对作者错误不生效。现与普通失败
    一致：按 step.on_failure → case.on_failure → 默认 ABORT 决策。
    """
    strategy = step.on_failure or case_on_failure or FailureStrategy.ABORT
    status = StepStatus.SKIPPED if strategy is FailureStrategy.SKIP else StepStatus.FAIL
    sr = StepResult(
        step_index=index,
        phase=phase,
        input_type=InputType.DATA if step.data is not None else InputType.COMMAND,
        command=_truncate(_cmd_display(step)),
        port=port,
        status=status,
        request="",
        response="",
        error_msg=msg,
    )
    abort_case = not is_teardown and status is StepStatus.FAIL and strategy is FailureStrategy.ABORT
    return StepExecResult(status=status, step_result=sr, abort_case=abort_case)


def _build_skipped(
    index: int, phase: str, port: str, step: Step, msg: str, *, is_fail: bool = False
) -> StepExecResult:
    it = InputType.DATA if step.data is not None else InputType.COMMAND
    status = StepStatus.FAIL if is_fail else StepStatus.SKIPPED
    sr = StepResult(
        step_index=index,
        phase=phase,
        input_type=it,
        command=_truncate(_cmd_display(step)),
        port=port,
        status=status,
        request="",
        response="",
        error_msg=msg,
    )
    return StepExecResult(status=status, step_result=sr, abort_case=is_fail)
