"""CLI update 子命令测试（mock checker/installer，零真实网络/替换）。"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from atprobe.cli.main import app

runner = CliRunner()


def test_update_check_reports_new_version() -> None:
    """--check：有新版时报告版本与下载地址。"""
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.3.0",
        tag="v0.3.0",
        zip_url="https://example.com/ATProbe-0.3.0-win64.zip",
        zip_size=80000000,
        release_notes="notes",
        html_url="https://github.com/niusulong/ATProbe/releases/tag/v0.3.0",
    )
    with patch("atprobe.cli.commands.update.fetch_latest", return_value=fake), patch(
        "atprobe.cli.commands.update.is_newer", return_value=True
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "0.3.0" in result.stdout
    assert "ATProbe-0.3.0-win64.zip" in result.stdout


def test_update_check_already_latest() -> None:
    """--check：已是最新时报告。"""
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.2.1", tag="v0.2.1", zip_url="u", zip_size=1,
        release_notes="", html_url="h",
    )
    with patch("atprobe.cli.commands.update.fetch_latest", return_value=fake), patch(
        "atprobe.cli.commands.update.is_newer", return_value=False
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "最新" in result.stdout


def test_update_check_network_error_exit_code() -> None:
    """--check：网络失败时非零退出码 + 错误提示。"""
    from atprobe.infra.update import UpdateCheckError

    with patch(
        "atprobe.cli.commands.update.fetch_latest",
        side_effect=UpdateCheckError("网络连接失败"),
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code != 0
    assert "网络" in result.stdout or "网络" in (result.output or "")
