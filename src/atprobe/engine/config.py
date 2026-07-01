"""M3 引擎配置与状态枚举（REQ-M3 §7.1/§7.2）.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StopMode(str, Enum):
    """stop 模式（M3 §7.2，M5 §5.3 引入）."""

    CURRENT = "current"  # 中断当前用例，继续后续
    ALL = "all"  # 中断当前用例，停止全部 → FINISHED


class EngineState(str, Enum):
    """引擎状态（M3 §7.1）."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class EngineConfig:
    """引擎启动配置（由 CLI/GUI 组装后传入 start）.

    Attributes:
        ports: 参与端口配置列表（按顺序，第一个为默认端口，M3 §6.2）。
        cases: 要执行的用例列表（已展开参数化、应用标签过滤）。
        step_timeout_default: 步骤级默认超时（秒，来自配置文件，M3 §5.1）。
        pressure_pass_threshold: 压测 PASS 阈值（%，来自配置，M3 §9 / M5 §3.5）。
        env_config: 环境配置（M7，None 表示无环境配置层）。
        session_id: 会话标识（时间戳，用于日志/报告目录，M5 §7.2）。
        log_dir: 原始日志根目录。
    """

    ports: tuple[PortConfig, ...]  # type: ignore[name-defined]  # noqa: F821
    cases: tuple[Case, ...]  # type: ignore[name-defined]  # noqa: F821
    step_timeout_default: float = 5.0
    pressure_pass_threshold: float = 95.0
    env_config: object | None = None  # EnvConfig（避免循环 import 用 object）
    session_id: str = ""
    log_dir: str = "./logs"
    report_env_snapshot: bool = True
    # 套件级前后置（REQ-M2 §12.2）：cases 循环前/后各执行一次。默认空（非套件执行）。
    # Step 来自 domain.case.models，沿用 ports/cases 的前向引用约定（见文件顶部
    # from __future__ import annotations，运行期注解为字符串，无循环 import 风险）。
    suite_setup: tuple[Step, ...] = ()  # type: ignore[name-defined]  # noqa: F821
    suite_teardown: tuple[Step, ...] = ()  # type: ignore[name-defined]  # noqa: F821


# 默认端口选取（M3 §6.2：用例/步骤未指定 port 时用第一个端口）
def default_port(config: EngineConfig) -> str | None:
    return config.ports[0].name if config.ports else None
