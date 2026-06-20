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
        step_index=1, phase="steps", input_type=InputType.COMMAND,
        command="AT", port="COM3", status=StepStatus.PASS,
        request="AT", response="OK\r\n",
        assertions=(AssertionResult(name="成功", op_kind="response.contains", expected="OK", actual="OK\r\n", passed=True),),
        duration_ms=120.0,
    )
    step_fail = StepResult(
        step_index=2, phase="steps", input_type=InputType.COMMAND,
        command="AT+BAD", port="COM3", status=StepStatus.FAIL,
        request="AT+BAD", response="ERROR\r\n",
        assertions=(AssertionResult(name="成功", op_kind="response.contains", expected="OK", actual="ERROR\r\n", passed=False, reason="响应不含 OK"),),
        duration_ms=95.0, error_msg="响应不含 OK",
    )
    cases = [
        CaseResult(
            case_name="通过用例", case_file="a.yaml", tags=("network",),
            ports=("COM3",), status=CaseStatus.PASS,
            step_results=(step_ok,), duration_ms=200.0,
        ),
        CaseResult(
            case_name="失败用例", case_file="b.yaml", tags=("network",),
            ports=("COM3",), status=CaseStatus.FAIL,
            step_results=(step_ok, step_fail), duration_ms=300.0,
            error_msg="响应不含 OK",
        ),
    ]
    summary = aggregate(cases, start_time="2026-06-20 10:00:00", end_time="2026-06-20 10:00:01", duration_ms=500.0)
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

    def test_pressure_case_rendered(self, tmp_path: Path) -> None:
        step_stats = (StepPressureStats(step_index=1, command="AT", success_count=95, fail_count=0, min_ms=80, max_ms=210, avg_ms=95, p95_ms=130, p99_ms=180),)
        ps = PressureStats(total_rounds=100, warmup_rounds=5, counted_rounds=95, success_rounds=95, failed_rounds=0, success_rate=100.0, pass_threshold=95.0, passed=True, step_stats=step_stats)
        case = CaseResult(
            case_name="压测用例", case_file="p.yaml", tags=("stress",),
            ports=("COM3",), status=CaseStatus.PASS, is_pressure=True,
            pressure_stats=ps, duration_ms=15000.0,
        )
        summary = aggregate([case])
        result = ExecutionResult(summary=summary, case_results=(case,))
        html_path = tmp_path / "p.html"
        HtmlReporter().render(result, ReportOutput(html_path=html_path, to_console=False))
        html = html_path.read_text(encoding="utf-8")
        assert "压测统计" in html
        assert "100" in html  # 总轮次
        assert "P95" in html or "p95" in html.lower()


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
