"""CLI 端到端测试（M5）."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from atprobe.cli.main import app

runner = CliRunner()


class TestVersion:
    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "atprobe" in result.stdout


class TestListCases:
    def test_list_cases(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            ["list", "cases", "--config", str(examples_dir / "atprobe.yaml")],
        )
        assert result.exit_code == 0
        assert "TCP/UDP参数与状态查询-响应格式" in result.stdout
        assert "网络时间同步-查询测试设置" in result.stdout

    def test_list_with_tag_filter(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            ["list", "cases", "--config", str(examples_dir / "atprobe.yaml"), "--tag", "ntp"],
        )
        assert result.exit_code == 0
        assert "网络时间同步" in result.stdout
        # tcp 用例被过滤
        assert "TCP/UDP" not in result.stdout


class TestRunDryRun:
    def test_dry_run_lists_cases(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            ["run", str(examples_dir / "testcases" / "tcp" / "tcp-param_boundary.yaml"),
             "--port", "COM99", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "TCP/UDP参数设置-参数边界" in result.stdout
        assert "COM99" in result.stdout

    def test_no_port_errors(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        # 不提供 --port 且配置文件 ports 也读不到（用不存在配置）
        result = runner.invoke(
            app,
            ["run", str(examples_dir / "testcases" / "tcp" / "tcp-param_boundary.yaml"),
             "--config", "nonexistent.yaml", "--dry-run"],
        )
        assert result.exit_code == 2

    def test_tag_filter_no_cases(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            ["run", str(examples_dir / "testcases"),
             "--port", "COM99", "--tag", "nonexistent-tag", "--dry-run"],
        )
        assert result.exit_code == 1
