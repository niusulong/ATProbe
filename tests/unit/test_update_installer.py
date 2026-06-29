"""update/installer.py：apply_update 测试（mock Popen/zipfile，不真实替换）。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from atprobe.infra.update import UpdateError
from atprobe.infra.update.installer import apply_update, build_updater_script


def _make_fake_zip(zip_path: Path) -> None:
    """构造含 atprobe.exe + _internal/ 的假 zip。"""
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe-0.3.0/atprobe.exe", b"PE")
        z.writestr("ATProbe-0.3.0/_internal/python311.dll", b"dll")
        z.writestr("ATProbe-0.3.0/examples/env.yaml", b"env")  # 应被忽略


def test_apply_update_dev_mode_rejected(tmp_path: Path) -> None:
    """开发态（is_frozen=False）直接拒绝。"""
    zip_path = tmp_path / "update.zip"
    _make_fake_zip(zip_path)
    with patch("atprobe.infra.update.installer.is_frozen", return_value=False):
        with pytest.raises(UpdateError, match="开发态"):
            apply_update(zip_path, tmp_path)


def test_apply_update_corrupt_zip_rejected(tmp_path: Path) -> None:
    """损坏 zip（无 atprobe.exe）拒绝启动脚本。"""
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("foo/bar.txt", b"x")  # 无 exe，无 _internal
    with patch("atprobe.infra.update.installer.is_frozen", return_value=True):
        with pytest.raises(UpdateError, match="损坏"):
            apply_update(zip_path, tmp_path)


def test_apply_update_generates_and_launches_script(tmp_path: Path) -> None:
    """打包态：解压 staging + 生成 bat + detached 启动 Popen。"""
    zip_path = tmp_path / "update.zip"
    _make_fake_zip(zip_path)
    fake_internal = tmp_path / "_internal"
    fake_internal.mkdir()
    (tmp_path / "atprobe.exe").write_bytes(b"old")

    popen_mock = MagicMock()
    with patch("atprobe.infra.update.installer.is_frozen", return_value=True), patch(
        "atprobe.infra.update.installer.subprocess.Popen", return_value=popen_mock
    ) as p_open, patch(
        "atprobe.infra.update.installer.os.getpid", return_value=12345
    ):
        apply_update(zip_path, tmp_path)

    # Popen 被调用一次，启动某个 .bat
    assert p_open.called
    cmd = p_open.call_args[0][0]
    bat_arg = [a for a in cmd if str(a).endswith(".bat") or ".bat" in str(a)]
    assert bat_arg, f"Popen 应启动 .bat 脚本，实际 cmd={cmd}"


def test_updater_script_contains_key_commands(tmp_path: Path) -> None:
    """生成的 bat 必须含关键命令：等待退出 / 备份 / xcopy / 回滚标签 / 重启。"""
    script = build_updater_script(
        exe_path=tmp_path / "atprobe.exe",
        internal_path=tmp_path / "_internal",
        staging_dir=tmp_path / "ATProbe-0.3.0",
        pid=12345,
    )
    assert "tasklist" in script  # 等待主程序退出
    assert "12345" in script  # PID 嵌入
    assert "ren" in script  # 备份重命名
    assert "xcopy" in script  # 部署
    assert ":rollback" in script  # 回滚标签
    assert "start" in script  # 重启
    assert "chcp 65001" in script  # UTF-8 编码
    assert "mshta" in script  # 失败弹框


def test_updater_script_paths_quoted(tmp_path: Path) -> None:
    """路径含空格时 bat 内必须加引号（防 PATH/参数注入）。"""
    exe = Path("D:/my tools/ATProbe/atprobe.exe")
    script = build_updater_script(
        exe_path=exe,
        internal_path=exe.parent / "_internal",
        staging_dir=exe.parent / "ATProbe-0.3.0",
        pid=1,
    )
    assert '"D:/my tools/ATProbe/atprobe.exe"' in script or (
        '"D:\\my tools\\ATProbe\\atprobe.exe"' in script
    )
