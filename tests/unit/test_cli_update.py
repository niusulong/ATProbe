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
        patch("atprobe.infra.update.checker.fetch_latest", return_value=fake),
        patch("atprobe.infra.update.checker.is_newer", return_value=True),
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
        patch("atprobe.infra.update.checker.fetch_latest", return_value=fake),
        patch("atprobe.infra.update.checker.is_newer", return_value=False),
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "最新" in result.stdout


def test_update_check_network_error_exit_code() -> None:
    """--check：网络失败时非零退出码 + 错误提示。"""
    from atprobe.infra.update import UpdateCheckError

    with patch(
        "atprobe.infra.update.checker.fetch_latest",
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
        patch("atprobe.infra.update.checker.fetch_latest", return_value=fake),
        patch("atprobe.infra.update.checker.is_newer", return_value=True),
        patch("atprobe.cli.commands.update.is_frozen", return_value=True),
        patch("atprobe.infra.update.session.UpdateSession", return_value=session),
        patch("atprobe.infra.update.installer.apply_update") as apply_mock,
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
        patch("atprobe.infra.update.checker.fetch_latest", return_value=fake),
        patch("atprobe.infra.update.checker.is_newer", return_value=True),
        patch("atprobe.cli.commands.update.is_frozen", return_value=True),
    ):
        result = runner.invoke(app, ["update"], input="\n")  # 确认提示默认否
    assert result.exit_code == 0
    assert "0.10.0-rc1（预发布）" in result.stdout
    assert "已取消" in result.stdout


# ---------- 批 5：退出码口径 + 版本未知特殊文案 ----------


def test_update_download_cancelled_exit_zero() -> None:
    """用户取消下载 → exit 0（旧实现 1，主动取消不是错误，脚本无法区分失败与取消）."""
    from atprobe.infra.update import DownloadCancelled
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.3.0",
        tag="v0.3.0",
        zip_url="https://example.com/ATProbe-0.3.0-win64.zip",
        zip_size=80000000,
        release_notes="",
        html_url="h",
    )
    session = MagicMock()
    session.download.side_effect = DownloadCancelled()
    with (
        patch("atprobe.infra.update.checker.fetch_latest", return_value=fake),
        patch("atprobe.infra.update.checker.is_newer", return_value=True),
        patch("atprobe.cli.commands.update.is_frozen", return_value=True),
        patch("atprobe.cli.commands.update.current_version", return_value="0.2.1"),
        patch("atprobe.infra.update.session.UpdateSession", return_value=session),
    ):
        result = runner.invoke(app, ["update", "--yes"])
    assert result.exit_code == 0
    assert "已取消下载" in result.stdout


def test_update_version_unknown_shows_hint_not_upgrade() -> None:
    """VERSION 缺失（current_version 回退 0.0.0）：特殊文案 + Release 页，不进升级流程.

    旧实现拿 0.0.0 参与比较：任何远端版本都"更新"，恒提示"有新版本可用"误导。
    """
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.99.0",
        tag="v0.99.0",
        zip_url="https://example.com/ATProbe-0.99.0-win64.zip",
        zip_size=80000000,
        release_notes="",
        html_url="https://github.com/niusulong/ATProbe/releases",
    )
    is_newer_mock = MagicMock(return_value=True)
    with (
        patch("atprobe.infra.update.checker.fetch_latest", return_value=fake),
        patch("atprobe.infra.update.checker.is_newer", is_newer_mock),
        # current_version/is_version_known 是 update 模块顶层轻量导入，
        # 按既有惯例在消费方命名空间打桩
        patch("atprobe.cli.commands.update.current_version", return_value="0.0.0"),
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "无法确定当前版本" in result.stdout
    assert "Release 页" in result.stdout
    assert "0.99.0" in result.stdout
    # 不当作 0.0.0 参与比较：不提示升级、不调用 is_newer
    assert "有新版本可用" not in result.stdout
    is_newer_mock.assert_not_called()
