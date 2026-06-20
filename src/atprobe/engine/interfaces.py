"""M3 引擎接口与进度事件（REQ-M3 §7.2 接口、§7.4 进度事件）.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from atprobe.engine.config import EngineConfig, EngineState, StopMode


# ---------------------------------------------------------------------------
# §7.4 进度事件（供 M5 控制台 / M6 进度面板订阅）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CaseStartEvent:
    case_name: str
    case_index: int  # 从 1 开始
    total_cases: int
    case_type: str  # "regular" / "pressure"


@dataclass(frozen=True)
class StepResultEvent:
    step_index: int
    phase: str  # setup / steps / teardown
    status: str  # PASS / FAIL / SKIPPED
    duration_ms: float
    port: str
    command: str  # 截断前
    extracted_vars: dict[str, str] = field(default_factory=dict)
    error_msg: str = ""
    retry_count: int = 0
    poll_iterations: int = 0


@dataclass(frozen=True)
class PressureProgressEvent:
    case_name: str
    current_round: int
    total_rounds: int
    success: int
    fail: int
    avg_ms: float


@dataclass(frozen=True)
class CaseResultEvent:
    case_name: str
    status: str  # PASS / FAIL / SKIPPED / INTERRUPTED
    duration_ms: float
    error_msg: str = ""


@dataclass(frozen=True)
class EngineFinishedEvent:
    summary: object  # Summary（避免循环 import）


ProgressEvent = (
    CaseStartEvent | StepResultEvent | PressureProgressEvent | CaseResultEvent | EngineFinishedEvent
)


# 事件处理器签名
ProgressHandler = object  # Callable[[ProgressEvent], None]，用 object 避免循环


@runtime_checkable
class IEngine(Protocol):
    """引擎对外接口（M3 §7.2：仅 start/stop）."""

    def start(self, config: EngineConfig, handler: object | None = None) -> object:  # ExecutionResult
        """启动执行（阻塞直到完成或中断）。handler 为进度事件回调."""
        ...

    def stop(self, mode: StopMode = StopMode.CURRENT) -> None: ...

    def state(self) -> EngineState: ...
