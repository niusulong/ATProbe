"""报告渲染集成测试（M4 §3/§4）."""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.domain.report.aggregator import aggregate
from atprobe.domain.report.models import (
    AssertionResult,
    CaseResult,
    CaseStatus,
    ExecutionResult,
    InputType,
    PressureStats,
    StepPressureStats,
    StepResult,
    StepStatus,
)
from atprobe.reporting.console import ConsoleReporter
from atprobe.reporting.html import HtmlReporter
from atprobe.reporting.interfaces import ReportOutput


def _make_result() -> ExecutionResult:
    step_ok = StepResult(
        step_index=1,
        phase="steps",
        input_type=InputType.COMMAND,
        command="AT",
        port="COM3",
        status=StepStatus.PASS,
        request="AT",
        response="OK\r\n",
        assertions=(
            AssertionResult(
                name="成功",
                op_kind="response.contains",
                expected="OK",
                actual="OK\r\n",
                passed=True,
            ),
        ),
        duration_ms=120.0,
    )
    step_fail = StepResult(
        step_index=2,
        phase="steps",
        input_type=InputType.COMMAND,
        command="AT+BAD",
        port="COM3",
        status=StepStatus.FAIL,
        request="AT+BAD",
        response="ERROR\r\n",
        assertions=(
            AssertionResult(
                name="成功",
                op_kind="response.contains",
                expected="OK",
                actual="ERROR\r\n",
                passed=False,
                reason="响应不含 OK",
            ),
        ),
        duration_ms=95.0,
        error_msg="响应不含 OK",
    )
    cases = [
        CaseResult(
            case_name="通过用例",
            case_file="a.yaml",
            tags=("network",),
            ports=("COM3",),
            status=CaseStatus.PASS,
            step_results=(step_ok,),
            duration_ms=200.0,
        ),
        CaseResult(
            case_name="失败用例",
            case_file="b.yaml",
            tags=("network",),
            ports=("COM3",),
            status=CaseStatus.FAIL,
            step_results=(step_ok, step_fail),
            duration_ms=300.0,
            error_msg="响应不含 OK",
        ),
    ]
    summary = aggregate(
        cases, start_time="2026-06-20 10:00:00", end_time="2026-06-20 10:00:01", duration_ms=500.0
    )
    return ExecutionResult(summary=summary, case_results=tuple(cases))


class TestHtmlReporter:
    def test_renders_valid_html(self, tmp_path: Path) -> None:
        result = _make_result()
        html_path = tmp_path / "report.html"
        HtmlReporter().render(result, ReportOutput(html_path=html_path, to_console=False))

        assert html_path.exists()
        html = html_path.read_text(encoding="utf-8")
        # 基本结构（§4.1）
        assert "<!DOCTYPE html>" in html
        assert "ATProbe" in html
        assert "用例总数" in html
        assert "通过用例" in html
        assert "失败用例" in html
        # UTF-8 编码（§4.7）
        assert 'charset="UTF-8"' in html
        # 内联 CSS（§4.7 单文件）
        assert "<style>" in html
        # 无外部 JS（§4.7 纯静态）
        assert "<script" not in html
        # 颜色语义类（§4.7）
        assert "PASS" in html
        assert "FAIL" in html

    def test_step_error_msg_rendered_on_fail(self, tmp_path: Path) -> None:
        # 模板渲染失败等场景：步骤 FAIL 但无 response，error_msg 必须显示在报告里，
        # 否则用户只看到 "FAIL / 0ms / 无断言" 而不知原因（回归 issue: 变量未定义诊断丢失）。
        step = StepResult(
            step_index=1,
            phase="setup",
            input_type=InputType.COMMAND,
            command="AT+HTTPCREATE=0,{{http.https_ipv6_url}}",
            port="COM28",
            status=StepStatus.FAIL,
            request="",
            response="",
            error_msg="模板渲染失败：'http.https_ipv6_url'",
            duration_ms=0.0,
        )
        case = CaseResult(
            case_name="变量未定义用例",
            case_file="c.yaml",
            tags=(),
            ports=("COM28",),
            status=CaseStatus.SKIPPED,
            setup_results=(step,),
            duration_ms=0.0,
            error_msg="setup 失败",
        )
        summary = aggregate([case])
        result = ExecutionResult(summary=summary, case_results=(case,))
        html_path = tmp_path / "err.html"
        HtmlReporter().render(result, ReportOutput(html_path=html_path, to_console=False))
        html = html_path.read_text(encoding="utf-8")
        # step 级诊断信息必须可见
        assert "模板渲染失败" in html
        assert "https_ipv6_url" in html

    def test_pressure_case_rendered(self, tmp_path: Path) -> None:
        step_stats = (
            StepPressureStats(
                step_index=1,
                command="AT",
                success_count=95,
                fail_count=0,
                min_ms=80,
                max_ms=210,
                avg_ms=95,
                p95_ms=130,
                p99_ms=180,
            ),
        )
        ps = PressureStats(
            total_rounds=100,
            warmup_rounds=5,
            counted_rounds=95,
            success_rounds=95,
            failed_rounds=0,
            success_rate=100.0,
            pass_threshold=95.0,
            passed=True,
            step_stats=step_stats,
        )
        case = CaseResult(
            case_name="压测用例",
            case_file="p.yaml",
            tags=("stress",),
            ports=("COM3",),
            status=CaseStatus.PASS,
            is_pressure=True,
            pressure_stats=ps,
            duration_ms=15000.0,
        )
        summary = aggregate([case])
        result = ExecutionResult(summary=summary, case_results=(case,))
        html_path = tmp_path / "p.html"
        HtmlReporter().render(result, ReportOutput(html_path=html_path, to_console=False))
        html = html_path.read_text(encoding="utf-8")
        assert "压测统计" in html
        assert "100" in html  # 总轮次
        assert "P95" in html or "p95" in html.lower()


class TestOverallVerdictHtml:
    """整体判定口径（设计 §4.4②）：0/0 明示"无用例"、启动级错误判"执行错误"."""

    def test_zero_zero_says_no_cases(self) -> None:
        # total=0（如端口全部打开失败但 error 未设/空选集）：旧实现 0==0 误判
        # "全部通过"，修后落"全部跳过"，再修后明示"无用例"并引导检查
        result = ExecutionResult(summary=aggregate([]))
        html = HtmlReporter().render_html(result)
        assert "无用例（检查过滤条件/路径）" in html
        assert "全部通过" not in html
        assert "全部跳过" not in html
        assert "执行错误" not in html

    def test_all_interrupted_says_interrupted(self) -> None:
        # 全部中断（用户 Ctrl+C 主动取消）：不是"全部跳过"——明示"执行已中断"
        case = CaseResult(case_name="中断用例", case_file="a.yaml", status=CaseStatus.INTERRUPTED)
        result = ExecutionResult(summary=aggregate([case]), case_results=(case,))
        html = HtmlReporter().render_html(result)
        assert "执行已中断" in html
        assert "全部跳过" not in html
        assert "全部通过" not in html

    def test_startup_error_overrides_verdict(self) -> None:
        # 启动级错误：执行没开始——"执行错误"（fail 红色），且错误原因须可见
        result = ExecutionResult(summary=aggregate([]), error="端口全部打开失败：COM3 被占用")
        html = HtmlReporter().render_html(result)
        assert "执行错误" in html
        assert "全部通过" not in html
        assert "全部跳过" not in html
        # 错误详情必须呈现在报告里（模板 hero-error 块）
        assert "COM3 被占用" in html

    def test_all_pass_verdict_kept(self) -> None:
        # 正常全部通过：既有口径零回归
        case = CaseResult(case_name="通过用例", case_file="a.yaml", status=CaseStatus.PASS)
        result = ExecutionResult(summary=aggregate([case]), case_results=(case,))
        html = HtmlReporter().render_html(result)
        assert "全部通过" in html
        assert "全部跳过" not in html
        assert "执行错误" not in html

    def test_all_fail_keeps_failed_guard(self) -> None:
        # 有失败且无通过 → "全部失败"（failed>0 守卫防全部跳过误判）
        step = StepResult(
            step_index=1,
            phase="steps",
            input_type=InputType.COMMAND,
            command="AT+BAD",
            port="COM3",
            status=StepStatus.FAIL,
            request="AT+BAD",
            response="ERROR",
        )
        case = CaseResult(
            case_name="失败用例", case_file="b.yaml", status=CaseStatus.FAIL, step_results=(step,)
        )
        result = ExecutionResult(summary=aggregate([case]), case_results=(case,))
        html = HtmlReporter().render_html(result)
        assert "全部失败" in html
        assert "全部通过" not in html

    def test_exit_badge_matches_cli_on_mixed_interrupted(self) -> None:
        """PASS+INTERRUPTED 混合零失败零跳过：verdict"部分通过"但 exit 徽标 0。

        T5 审查 M-1：Ctrl+C 中途的典型态——CLI 按用户主动取消 exit 0，旧徽标
        从 overall 类别反推（partial→1）与 CLI 矛盾。徽标现走 run_exit_code
        单一决策点（渲染方传 exit_code）。
        """
        cases = (
            CaseResult(case_name="已完成", case_file="a.yaml", status=CaseStatus.PASS),
            CaseResult(case_name="在跑被中断", case_file="b.yaml", status=CaseStatus.INTERRUPTED),
        )
        result = ExecutionResult(summary=aggregate(list(cases)), case_results=cases)
        html = HtmlReporter().render_html(result)
        assert "部分通过" in html
        assert "exit 0" in html

    def test_exit_badge_one_on_fail_or_suite_setup_fail(self) -> None:
        # 含失败 → exit 1；suite_setup 失败（summary 全零）→ 同样 exit 1（M-2）
        fail_case = CaseResult(case_name="失败", case_file="a.yaml", status=CaseStatus.FAIL)
        result = ExecutionResult(summary=aggregate([fail_case]), case_results=(fail_case,))
        assert "exit 1" in HtmlReporter().render_html(result)

        setup_fail = StepResult(
            step_index=1,
            phase="suite_setup",
            input_type=InputType.COMMAND,
            command="AT",
            port="COM3",
            status=StepStatus.FAIL,
            request="AT",
            response="ERROR",
        )
        result2 = ExecutionResult(summary=aggregate([]), suite_setup_results=(setup_fail,))
        assert "exit 1" in HtmlReporter().render_html(result2)


class TestOverallVerdictConsole:
    """console 汇总与 html 同口径（§4.4②）."""

    def _render(self, result: ExecutionResult, capsys: pytest.CaptureFixture[str]) -> str:
        ConsoleReporter().render(result, ReportOutput(to_console=True, color=False))
        return capsys.readouterr().out

    def test_zero_zero_says_no_cases(self, capsys: pytest.CaptureFixture[str]) -> None:
        # total=0：明示"无用例（检查过滤条件/路径）"，不落"全部跳过"
        out = self._render(ExecutionResult(summary=aggregate([])), capsys)
        assert "无用例（检查过滤条件/路径）" in out
        assert "全部通过" not in out
        assert "全部跳过" not in out
        assert "全部失败" not in out

    def test_all_interrupted_says_interrupted(self, capsys: pytest.CaptureFixture[str]) -> None:
        # 全部中断（用户主动取消）：不是"全部跳过"——"执行已中断"
        case = CaseResult(case_name="中断用例", case_file="a.yaml", status=CaseStatus.INTERRUPTED)
        out = self._render(ExecutionResult(summary=aggregate([case]), case_results=(case,)), capsys)
        assert "执行已中断" in out
        assert "全部跳过" not in out
        assert "全部通过" not in out

    def test_startup_error_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = ExecutionResult(summary=aggregate([]), error="端口全部打开失败：COM3 不存在")
        out = self._render(result, capsys)
        assert "执行错误" in out
        assert "COM3 不存在" in out
        assert "全部通过" not in out

    def test_all_fail_keeps_failed_guard(self, capsys: pytest.CaptureFixture[str]) -> None:
        # passed=0 且 failed>0 → "全部失败"（守卫回归：不得被 0/0→跳过分支吃掉）
        step = StepResult(
            step_index=1,
            phase="steps",
            input_type=InputType.COMMAND,
            command="AT+BAD",
            port="COM3",
            status=StepStatus.FAIL,
            request="AT+BAD",
            response="ERROR",
        )
        case = CaseResult(
            case_name="失败用例", case_file="b.yaml", status=CaseStatus.FAIL, step_results=(step,)
        )
        out = self._render(ExecutionResult(summary=aggregate([case]), case_results=(case,)), capsys)
        assert "全部失败" in out
        assert "全部通过" not in out


class TestConsoleReporter:
    def test_renders_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = _make_result()
        ConsoleReporter().render(result, ReportOutput(to_console=True, color=False))
        out = capsys.readouterr().out
        assert "执行结果汇总" in out
        assert "通过用例" not in out  # 通过用例不在失败列表
        assert "失败用例" in out
        assert "AT+BAD" in out  # 失败步骤命令

    def test_empty_result(self, capsys: pytest.CaptureFixture[str]) -> None:
        summary = aggregate([])
        result = ExecutionResult(summary=summary)
        ConsoleReporter().render(result, ReportOutput(to_console=True, color=False))
        out = capsys.readouterr().out
        assert "用例总数: 0" in out

    def test_suite_setup_failure_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        # suite_setup 失败的步骤应在汇总中展示（issue #5：套件前后置诊断）
        suite_step = StepResult(
            step_index=1,
            phase="suite_setup",
            input_type=InputType.COMMAND,
            command="AT+CFUN=1",
            port="COM3",
            status=StepStatus.FAIL,
            request="AT+CFUN=1",
            response="ERROR\r\n",
            error_msg="响应不含 OK",
        )
        summary = aggregate([])
        result = ExecutionResult(summary=summary, suite_setup_results=(suite_step,))
        ConsoleReporter().render(result, ReportOutput(to_console=True, color=False))
        out = capsys.readouterr().out
        assert "套件级前后置异常" in out
        assert "suite_setup" in out
        assert "AT+CFUN=1" in out


class TestFormatStepLine:
    """实时进度行点线填充（M4 §3.2）：按显示宽度截断+补点，长命令不撑爆行宽.

    旧实现按码点数（len）拼点：CJK 命令占 2 列却按 1 列计，点数补多、
    整行溢出换行错位。特征口径：命令按 truncate 列截断（超出加 …），
    点线按显示宽度补齐——同 truncate 下 ASCII 与 CJK 命令总宽一致。
    """

    @staticmethod
    def _disp_width(s: str) -> int:
        import unicodedata

        return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)

    def test_long_ascii_command_truncated_with_ellipsis(self) -> None:
        from atprobe.reporting.console import format_step_line

        line = format_step_line(
            phase="steps",
            port="COM3",
            command="AT+VERYLONGCOMMAND=" + "A" * 80,
            status="PASS",
            duration_ms=100.0,
            color=False,
        )
        assert "…" in line  # 超宽截断加省略号
        cmd = line.split("] ", 2)[2].split(" .")[0]
        assert self._disp_width(cmd) <= 40  # 截断到 truncate 列

    def test_long_cjk_command_same_total_width_as_ascii(self) -> None:
        """CJK 宽字符按 2 列计：同 truncate 下与 ASCII 命令的点线段总宽一致.

        旧实现按 len 拼点（CJK 记 1 列）：截断后的中文命令仍按码点数补点，
        填充段比 ASCII 宽出近一倍、整行溢出换行。修后按显示宽度补点——
        两侧填充段宽度差不超过 1（CJK 截断粒度是 2 列，奇偶差一列属精度内）。
        """
        from atprobe.reporting.console import format_step_line

        line_a = format_step_line(
            phase="steps",
            port="COM3",
            command="A" * 60,
            status="PASS",
            duration_ms=100.0,
            color=False,
        )
        line_c = format_step_line(
            phase="steps",
            port="COM3",
            command="查询信号质量" * 10,
            status="PASS",
            duration_ms=100.0,
            color=False,
        )
        seg_a = line_a.split("] ", 2)[2]
        seg_c = line_c.split("] ", 2)[2]
        # 命令 + 空格 + 点线（到状态前的填充段）总显示宽度一致
        fill_a = self._disp_width(seg_a.split("PASS")[0])
        fill_c = self._disp_width(seg_c.split("PASS")[0])
        assert abs(fill_a - fill_c) <= 1
        assert line_c.count("…") == 1  # CJK 命令也走截断路径

    def test_short_command_padded_with_dots(self) -> None:
        from atprobe.reporting.console import format_step_line

        line = format_step_line(
            phase="steps",
            port="COM3",
            command="AT",
            status="PASS",
            duration_ms=100.0,
            color=False,
        )
        assert "AT " in line
        assert "..." in line  # 短命令有点线填充
        assert "…" not in line  # 未超宽不截断
