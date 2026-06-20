"""M4 测试报告渲染（REQ-M4 §3 控制台、§4 HTML）."""
from atprobe.reporting.console import ConsoleReporter
from atprobe.reporting.html import HtmlReporter
from atprobe.reporting.interfaces import IReporter, ReporterRegistry

__all__ = ["ConsoleReporter", "HtmlReporter", "IReporter", "ReporterRegistry"]
