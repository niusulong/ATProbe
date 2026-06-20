"""M4 报告数据模型（REQ-M4 §2，对应 M3 §8 执行结果数据结构）.

纯数据结构，由 M3 引擎产出，供 M4 渲染器消费。无 I/O。
"""
from atprobe.domain.report.aggregator import aggregate
from atprobe.domain.report.models import (
    AssertionResult,
    CaseResult,
    CaseStatus,
    ExecutionResult,
    InputType,
    LogIndex,
    PressureStats,
    StepPressureStats,
    StepResult,
    StepStatus,
    Summary,
)

__all__ = [
    "AssertionResult",
    "CaseResult",
    "CaseStatus",
    "ExecutionResult",
    "InputType",
    "LogIndex",
    "PressureStats",
    "StepPressureStats",
    "StepResult",
    "StepStatus",
    "Summary",
    "aggregate",
]
