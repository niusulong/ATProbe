"""M4 HTML 报告渲染（REQ-M4 §4）.

纯静态 HTML（§4.7）：单文件、内联 CSS、无 JS、无外部依赖。展开/收起用原生
``<details>`` 标签。颜色语义统一（PASS 绿/FAIL 红/SKIPPED 黄/INTERRUPTED 灰）。

用 Jinja2 渲染（TSD §3.1：Jinja2 仅用于报告侧，模板不可信无注入风险）。
"""

from __future__ import annotations

from jinja2 import Environment, PackageLoader

from atprobe.domain.report.models import ExecutionResult
from atprobe.reporting.interfaces import IReporter, ReportOutput


class HtmlReporter(IReporter):
    """HTML 报告渲染器（§4）."""

    format_name = "html"

    def __init__(self) -> None:
        # P2 修复（XSS/HTML 注入）：旧实现 select_autoescape(["html","xml"]) 按文件
        # 名后缀判断，而模板名 report.html.j2 以 .j2 结尾 → autoescape 实际关闭，
        # 用例名/设备响应/错误信息（可含 <script> 等任意文本）原样进 HTML。
        # 报告经浏览器打开（file://），注入脚本可执行。强制开启转义。
        self._env = Environment(
            loader=PackageLoader("atprobe.reporting", "templates"),
            autoescape=True,
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
        # 整体结果标识（§4.2）。判定口径（§4.4② 消费侧修复，与 console._overall 同口径）：
        #   启动级错误 > 无用例（total=0，引导检查过滤条件/路径）> 全部通过
        #   > 全部中断（用户主动取消，非"跳过"）> 全部跳过 > 全部失败（需 failed>0）
        #   > 部分通过
        s = result.summary
        if result.error:
            # 启动级错误（sender 解析失败/端口全部打开失败）：执行根本没开始，
            # 既非"全部通过"（total=0 时旧实现 0==0 误判）也非"全部跳过"。
            overall = ("执行错误", "fail")
        elif s.total_cases == 0:
            # 空执行：明示无用例并引导检查（旧实现落"全部跳过"，语义混淆）
            overall = ("无用例（检查过滤条件/路径）", "neutral")
        elif s.passed == s.total_cases and s.failed == 0 and s.interrupted == 0:
            overall = ("全部通过", "pass")
        elif s.interrupted > 0 and s.passed == 0 and s.failed == 0 and s.skipped == 0:
            # 全部中断：用户 Ctrl+C 等主动取消——"执行已中断"，不是"全部跳过"
            overall = ("执行已中断", "interrupted")
        elif s.passed == 0 and s.failed == 0:
            overall = ("全部跳过", "neutral")
        elif s.failed > 0 and s.passed == 0:
            # 有失败且无通过 → 全部失败（必须有 failed>0，否则全部跳过会被误判）
            overall = ("全部失败", "fail")
        else:
            overall = ("部分通过", "partial")
        # exit 徽标：与 CLI 退出码共用单一决策点（run_exit_code）——不再从
        # overall 类别反推（T5 审查 M-1："部分通过"+零失败零跳过=用户中断时
        # 已完成的用例，CLI 实际 exit 0，按类别反推会误显 exit 1）
        from atprobe.domain.report.models import run_exit_code

        return template.render(
            result=result, summary=s, overall=overall, exit_code=run_exit_code(result)
        )
