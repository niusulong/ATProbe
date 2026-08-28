"""M4 控制台报告渲染（REQ-M4 §3）.

两个阶段（§3.1）：
    - 实时进度：由 CLI 订阅引擎进度事件驱动（见 cli/rendering.py），本模块提供
      ``format_step_line`` 等格式化函数。
    - 结果汇总（§3.3）：引擎结束后输出整体统计 + 失败/跳过列表。

颜色（§3.4）：PASS 绿 / FAIL 红 / SKIPPED 黄 / INTERRUPTED 灰，可关闭。
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TextIO

from atprobe.domain.report.models import CaseStatus, ExecutionResult, StepStatus
from atprobe.reporting.interfaces import IReporter, ReportOutput

# ANSI 颜色码（§3.4）
_COLORS = {
    "PASS": "\033[32m",  # 绿
    "FAIL": "\033[31m",  # 红
    "SKIPPED": "\033[33m",  # 黄
    "INTERRUPTED": "\033[90m",  # 灰
    "BOLD": "\033[1m",
    "RESET": "\033[0m",
    "DIM": "\033[2m",
}


def _color(text: str, name: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{_COLORS.get(name, '')}{text}{_COLORS['RESET']}"


def _status_color(status: str, *, color: bool) -> str:
    return _color(status, status, enabled=color)


class ConsoleReporter(IReporter):
    """结果汇总控制台输出（§3.3）."""

    format_name = "console"

    def render(self, result: ExecutionResult, output: ReportOutput) -> None:
        stream: TextIO = sys.stdout
        self._render_summary(result, stream, color=output.color)

    def _render_summary(self, result: ExecutionResult, stream: TextIO, *, color: bool) -> None:
        s = result.summary
        sep = "=" * 52
        stream.write(f"\n{sep} 执行结果汇总 {sep}\n")
        if s.start_time or s.end_time:
            dur = s.duration_ms / 1000.0
            stream.write(f"执行时间: {s.start_time} ~ {s.end_time} (耗时 {dur:.1f}s)\n")
        else:
            stream.write(f"总耗时: {s.duration_ms / 1000.0:.1f}s\n")
        stream.write(
            f"用例总数: {s.total_cases} | 通过 {s.passed} | 失败 {s.failed} "
            f"| 跳过 {s.skipped} | 中断 {s.interrupted}\n"
        )
        overall = _overall(result, color)
        stream.write(f"通过率: {s.pass_rate:.1f}%  {overall}\n\n")

        failed = [c for c in result.case_results if c.status is CaseStatus.FAIL]
        if failed:
            stream.write("失败用例:\n")
            for c in failed:
                stream.write(f"  [{_status_color('FAIL', color=color)}] {c.case_name}\n")
                # 找第一个失败步骤
                for sr in c.step_results:
                    if sr.status is StepStatus.FAIL:
                        stream.write(f"      步骤{sr.step_index}: {sr.command} {sr.error_msg}\n")
                        break
                if c.log_ref:
                    stream.write(f"      日志: {c.log_ref}\n")

        skipped = [c for c in result.case_results if c.status is CaseStatus.SKIPPED]
        if skipped:
            stream.write("\n跳过用例:\n")
            for c in skipped:
                stream.write(
                    f"  [{_status_color('SKIPPED', color=color)}] {c.case_name} ({c.error_msg})\n"
                )

        interrupted = [c for c in result.case_results if c.status is CaseStatus.INTERRUPTED]
        if interrupted:
            stream.write("\n中断用例:\n")
            for c in interrupted:
                stream.write(
                    f"  [{_status_color('INTERRUPTED', color=color)}] {c.case_name} ({c.error_msg})\n"
                )

        # 套件级前后置诊断（REQ-M2 §12.2）：展示非 PASS 的 suite_setup/teardown 步骤，
        # 便于定位"用例被跳过是因 suite_setup 失败"等场景（issue #5）
        suite_failed_steps = [
            sr
            for sr in (*result.suite_setup_results, *result.suite_teardown_results)
            if sr.status is not StepStatus.PASS
        ]
        if suite_failed_steps:
            stream.write("\n套件级前后置异常:\n")
            for sr in suite_failed_steps:
                stream.write(
                    f"  [{_status_color(sr.status.value, color=color)}] {sr.phase} 步骤{sr.step_index}: "
                    f"{sr.command} {sr.error_msg}\n"
                )

        stream.write(f"\n{'=' * 118}\n")


def _overall(result: ExecutionResult, color: bool) -> str:
    """整体判定文案（§4.4② 消费侧修复，与 HtmlReporter.render_html 同口径）.

    优先级：启动级错误 > 全部通过（需 total>0，0/0 不得误判）> 全部跳过（含 0/0）
    > 全部失败（需 failed>0）> 部分通过。
    """
    s = result.summary
    if result.error:
        # 启动级错误（sender 解析失败/端口全部打开失败）：执行没开始，
        # 0/0 旧实现会误判"全部通过"——不是跳过，是错误。
        return _color(f"执行错误：{result.error}", "FAIL", enabled=color)
    if s.total_cases > 0 and s.passed == s.total_cases and s.failed == 0 and s.interrupted == 0:
        return _color("全部通过", "PASS", enabled=color)
    if s.passed == 0 and s.failed == 0:
        # 无通过、无失败（全部跳过/中断，含 0/0 空执行）
        return _color("全部跳过", "SKIPPED", enabled=color)
    if s.failed > 0 and s.passed == 0:
        return _color("全部失败", "FAIL", enabled=color)
    return _color("部分通过", "SKIPPED", enabled=color)


# ---------------------------------------------------------------------------
# 实时进度格式化（供 CLI 事件渲染用）
# ---------------------------------------------------------------------------
def now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def format_step_line(
    *,
    phase: str,
    port: str,
    command: str,
    status: str,
    duration_ms: float,
    truncate: int = 40,
    color: bool = True,
    error_msg: str = "",
) -> str:
    """格式化单步结果行（M4 §3.2）::

    [HH:MM:SS]   → [COM3] AT+CSQ ...... PASS (120ms)
    """
    ts = now_ts()
    # P3 修复：按显示宽度截断/补点——CJK 字符占 2 列，按码点数（len）计算会使
    # 中文命令的省略号列错位。用 east_asian_width 估宽（宽字符 W/F 记 2）。
    import unicodedata

    def _disp_width(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)

    if _disp_width(command) <= truncate:
        cmd = command
    else:
        # 按显示宽度截断（避免切出半个宽字符）
        cmd = ""
        w = 0
        for ch in command:
            cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
            if w + cw > truncate - 1:
                break
            cmd += ch
            w += cw
        cmd += "…"
    dots = "." * max(2, 40 - _disp_width(cmd))
    status_str = _status_color(status, color=color)
    extra = f" {error_msg}" if error_msg and status == "FAIL" else ""
    return f"[{ts}]   → [{port}] {cmd} {dots} {status_str} ({duration_ms:.0f}ms){extra}"


def format_case_start(case_name: str, index: int, total: int, *, color: bool = True) -> str:
    return f"[{now_ts()}] [{index}/{total}] {_color(case_name, 'BOLD', enabled=color)}"


def format_case_result(
    case_name: str, status: str, duration_ms: float, *, color: bool = True
) -> str:
    return f"用例结果: {_status_color(status, color=color)} ({duration_ms / 1000.0:.1f}s)"
