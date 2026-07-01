"""M4 报告数据模型（REQ-M4 §2 / M3 §8）.

字段对应 M3 §8.1~§8.8 的执行结果分层结构：
    ExecutionResult
    ├── Summary（概览，§8.2）
    ├── CaseResult[]（用例结果，§8.3）
    │   └── StepResult[]（步骤结果，§8.4）
    │       └── AssertionResult[]（断言明细，§8.5）
    │   └── PressureStats（压测统计，§8.6）
    │       └── StepPressureStats[]（步骤压测统计，§8.7）
    └── LogIndex（原始日志索引）

全部 frozen 数据类，跨线程传递安全（TSD §5.1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# 状态枚举（M3 §7.3）
# ---------------------------------------------------------------------------
class CaseStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    INTERRUPTED = "INTERRUPTED"


class StepStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    INTERRUPTED = "INTERRUPTED"


class InputType(str, Enum):
    COMMAND = "command"
    DATA = "data"


# ---------------------------------------------------------------------------
# §8.5 断言明细
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AssertionResult:
    name: str
    op_kind: str  # "response.contains" / "var.eq"（来自 assessor.AssertionOutcome.op_kind）
    expected: str
    actual: str
    passed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# §8.4 步骤结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StepResult:
    step_index: int
    phase: str  # "setup" / "steps" / "teardown"
    input_type: InputType
    command: str  # 发送的命令或数据摘要（截断后）
    port: str
    status: StepStatus
    request: str  # 实际发送内容（模板替换后）
    response: str  # 完整响应文本
    assertions: tuple[AssertionResult, ...] = ()
    extracted_vars: dict[str, str] = field(default_factory=dict)
    duration_ms: float = 0.0
    retry_count: int = 0
    poll_iterations: int = 0
    error_msg: str = ""


# ---------------------------------------------------------------------------
# §8.6 / §8.7 压测统计
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StepPressureStats:
    step_index: int
    command: str
    success_count: int = 0
    fail_count: int = 0
    # 响应时间分布统计量（毫秒，仅成功的，§5.4：超时不计入分布）。
    # 不保留全量 response_times 数组 —— 它是计算百分位的中间实现细节，
    # 且随轮数线性增长会放大内存占用（零消费者）。模型只持有统计结论，
    # 保持领域层纯净（TSD §2.1 SRP / §2.2 领域层无实现泄漏）。
    min_ms: float = 0.0
    max_ms: float = 0.0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0


@dataclass(frozen=True)
class PressureStats:
    total_rounds: int = 0
    warmup_rounds: int = 0
    counted_rounds: int = 0
    success_rounds: int = 0
    failed_rounds: int = 0
    success_rate: float = 0.0
    aborted: bool = False
    pass_threshold: float = 0.0  # 使用的阈值（配置 pressure.pass_rate_threshold）
    passed: bool = False  # 是否达到阈值
    step_stats: tuple[StepPressureStats, ...] = ()


# ---------------------------------------------------------------------------
# §8.3 用例结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CaseResult:
    case_name: str
    case_file: str
    tags: tuple[str, ...] = ()
    ports: tuple[str, ...] = ()
    status: CaseStatus = CaseStatus.PASS
    is_pressure: bool = False
    setup_results: tuple[StepResult, ...] = ()
    step_results: tuple[StepResult, ...] = ()
    teardown_results: tuple[StepResult, ...] = ()
    pressure_stats: PressureStats | None = None
    duration_ms: float = 0.0
    log_ref: str = ""
    error_msg: str = ""


# ---------------------------------------------------------------------------
# §8.2 概览
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Summary:
    start_time: str = ""  # ISO-ish 或 YYYY-MM-DD HH:MM:SS
    end_time: str = ""
    duration_ms: float = 0.0
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    interrupted: int = 0
    pass_rate: float = 0.0  # 通过率 = passed / (total - skipped - interrupted)
    # 按标签分组（可选，报告展示用）
    by_tag: dict[str, dict[str, int]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 原始日志索引（M4 §4.6）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LogIndex:
    session_dir: str = ""
    # 端口 → [(日志相对路径, 用例名)]
    by_port: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# §8.1 顶层执行结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExecutionResult:
    summary: Summary
    case_results: tuple[CaseResult, ...] = ()
    log_index: LogIndex = field(default_factory=LogIndex)
    # 本次执行使用的环境配置快照（可选，M7 §9 报告头展示，便于复现）
    env_snapshot: dict[str, dict[str, object]] = field(default_factory=dict)
    # 套件级前后置步骤结果（REQ-M2 §12.2）。非套件执行为空。
    # 失败的 suite_setup 会导致 cases 被跳过，此处保留结果供报告诊断。
    suite_setup_results: tuple[StepResult, ...] = ()
    suite_teardown_results: tuple[StepResult, ...] = ()
