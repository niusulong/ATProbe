"""M4 报告渲染接口（REQ-M4，TSD §5.2.4 OCP 注册表）."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from atprobe.domain.report.models import ExecutionResult


@dataclass(frozen=True)
class ReportOutput:
    """报告输出目标."""

    # HTML 报告输出文件路径（None 表示仅渲染到内存/控制台）
    html_path: Path | None = None
    # 控制台输出开关
    to_console: bool = True
    # ANSI 颜色开关（控制台）
    color: bool = True
    # 命令截断长度（控制台）
    command_truncate: int = 40


@runtime_checkable
class IReporter(Protocol):
    """报告渲染器接口（OCP：新增格式只需实现此接口并注册）."""

    format_name: str  # "console" / "html" / "junit"

    def render(self, result: ExecutionResult, output: ReportOutput) -> None: ...


class ReporterRegistry:
    """报告格式注册表（TSD §5.3）."""

    def __init__(self) -> None:
        self._reporters: dict[str, IReporter] = {}

    def register(self, reporter: IReporter) -> None:
        self._reporters[reporter.format_name] = reporter

    def get(self, format_name: str) -> IReporter | None:
        return self._reporters.get(format_name)

    def formats(self) -> list[str]:
        return list(self._reporters.keys())


def default_registry() -> ReporterRegistry:
    """构造默认注册表（注册 console + html）."""
    from atprobe.reporting.console import ConsoleReporter
    from atprobe.reporting.html import HtmlReporter

    reg = ReporterRegistry()
    reg.register(ConsoleReporter())
    reg.register(HtmlReporter())
    return reg
