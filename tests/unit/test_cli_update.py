"""CLI update 子命令测试（mock checker/installer/session，零真实网络/替换）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
    with (
        patch("atprobe.cli.commands.update.fetch_latest", return_value=fake),
        patch("atprobe.cli.commands.update.is_newer", return_value=True),
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "0.3.0" in result.stdout
    assert "ATProbe-0.3.0-win64.zip" in result.stdout


def test_update_check_already_latest() -> None:
    """--check：已是最新时报告。"""
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.2.1",
        tag="v0.2.1",
        zip_url="u",
        zip_size=1,
        release_notes="",
        html_url="h",
    )
    with (
        patch("atprobe.cli.commands.update.fetch_latest", return_value=fake),
        patch("atprobe.cli.commands.update.is_newer", return_value=False),
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


# ---------- D-3：下载编排收敛 UpdateSession（T5 迁移） ----------


def test_update_install_uses_update_session() -> None:
    """完整安装路径经 UpdateSession.download，apply_update 收到其返回 path。"""
    from atprobe.infra.update.checker import ReleaseInfo
    from atprobe.infra.update.downloader import DownloadResult

    fake = ReleaseInfo(
        version="0.3.0",
        tag="v0.3.0",
        zip_url="https://github.com/niusulong/ATProbe/releases/download/v0.3.0/ATProbe-0.3.0-win64.zip",
        zip_size=80000000,
        release_notes="notes",
        html_url="https://github.com/niusulong/ATProbe/releases/tag/v0.3.0",
        sha256="a" * 64,
    )
    dl_result = DownloadResult(path=Path("tmp") / "ATProbe-0.3.0-win64.zip", size=1)
    session = MagicMock()
    session.download.return_value = dl_result
    with (
        patch("atprobe.cli.commands.update.fetch_latest", return_value=fake),
        patch("atprobe.cli.commands.update.is_newer", return_value=True),
        patch("atprobe.cli.commands.update.is_frozen", return_value=True),
        patch("atprobe.cli.commands.update.UpdateSession", return_value=session),
        patch("atprobe.cli.commands.update.apply_update") as apply_mock,
    ):
        result = runner.invoke(app, ["update", "--yes"])
    assert result.exit_code == 0
    args, kwargs = session.download.call_args
    assert args[0] is fake  # ReleaseInfo 原样交给 session（文件名/校验/签名策略单点）
    assert callable(kwargs["progress_cb"])  # CLI 进度条透传
    apply_mock.assert_called_once()
    assert apply_mock.call_args.args[0] == dl_result.path


def test_update_prerelease_labeled_in_prompt() -> None:
    """P3：预发布版本在版本报告与确认提示处带（预发布）标注。"""
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.10.0-rc1",
        tag="v0.10.0-rc1",
        zip_url="https://example.com/ATProbe-0.10.0-rc1-win64.zip",
        zip_size=80000000,
        release_notes="",
        html_url="h",
        prerelease=True,
    )
    with (
        patch("atprobe.cli.commands.update.fetch_latest", return_value=fake),
        patch("atprobe.cli.commands.update.is_newer", return_value=True),
        patch("atprobe.cli.commands.update.is_frozen", return_value=True),
    ):
        result = runner.invoke(app, ["update"], input="\n")  # 确认提示默认否
    assert result.exit_code == 0
    assert "0.10.0-rc1（预发布）" in result.stdout
    assert "已取消" in result.stdout
