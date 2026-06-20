"""M2 测试用例定义 — 领域层（见 REQ-M2）.

子模块：
    models    — Case/Step/Assert/Extract 等 Pydantic 数据模型（§2/§3/§4）
    parser    — YAML → Case 解析（§2）
    templater — {{var}} / {{group.param}} 模板替换器，纯函数（§5）
    evaluator — when/poll.until 条件表达式求值器，纯函数（§6）
    assessor  — 断言求值（§4）
    extractor — extract 提取（§5.1）
"""
from atprobe.domain.case.models import (
    Assert,
    AssertElement,
    AssertionOp,
    Case,
    DataInput,
    FailureStrategy,
    LoopConfig,
    PollConfig,
    RetryConfig,
    Step,
    StepInput,
)
from atprobe.domain.case.parser import CaseParseError, parse_case, parse_case_file

__all__ = [
    "Assert",
    "AssertElement",
    "AssertionOp",
    "Case",
    "CaseParseError",
    "DataInput",
    "FailureStrategy",
    "LoopConfig",
    "PollConfig",
    "RetryConfig",
    "Step",
    "StepInput",
    "parse_case",
    "parse_case_file",
]
