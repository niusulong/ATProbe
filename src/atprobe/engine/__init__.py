"""M3 测试执行引擎（REQ-M3）.

串行调度器（§2.2）：单线程串行执行用例与步骤，无并发竞争。
极简控制（§7.2）：对外仅 start/stop 两个接口。
"""
from atprobe.engine.config import EngineConfig, EngineState, StopMode
from atprobe.engine.interfaces import IEngine
from atprobe.engine.scheduler import Engine

__all__ = [
    "Engine",
    "EngineConfig",
    "EngineState",
    "IEngine",
    "StopMode",
]
