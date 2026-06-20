"""M4 HTML 报告渲染（REQ-M4 §4）.

纯静态 HTML（§4.7）：单文件、内联 CSS、无 JS、无外部依赖。展开/收起用原生
``<details>`` 标签。颜色语义统一（PASS 绿/FAIL 红/SKIPPED 黄/INTERRUPTED 灰）。

用 Jinja2 渲染（TSD §3.1：Jinja2 仅用于报告侧，模板不可信无注入风险）。
"""

from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape

from atprobe.domain.report.models import ExecutionResult
from atprobe.reporting.interfaces import IReporter, ReportOutput


class HtmlReporter(IReporter):
    """HTML 报告渲染器（§4）."""

    format_name = "html"

    def __init__(self) -> None:
        self._env = Environment(
            loader=PackageLoader("atprobe.reporting", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, result: ExecutionResult, output: ReportOutput) -> None:
        if output.html_path is None:
            return
        html = self.render_html(result)
        output.html_path.parent.mkdir(parents=True, exist_ok=True)
        output.html_path.write_text(html, encoding="utf-8")

    def render_html(self, result: ExecutionResult) -> str:
        """渲染为 HTML 字符串."""
        template = self._env.get_template("report.html.j2")
        # 整体结果标识（§4.2）
        s = result.summary
        if s.passed == s.total_cases and s.failed == 0 and s.interrupted == 0:
            overall = ("全部通过", "pass")
        elif s.passed == 0:
            overall = ("全部失败", "fail")
        else:
            overall = ("部分通过", "partial")
        return template.render(result=result, summary=s, overall=overall)
