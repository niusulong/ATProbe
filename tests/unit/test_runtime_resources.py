"""runtime.py 与 resources.py 单测。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atprobe.infra import runtime


def test_is_frozen_default_false():
    """开发态 sys.frozen 不存在 → False。"""
    assert runtime.is_frozen() is False


def test_is_frozen_true_when_sys_frozen_set():
    """打包态 sys.frozen 存在 → True。"""
    with patch.object(runtime.sys, "frozen", True, create=True):
        assert runtime.is_frozen() is True


def test_app_root_dev_mode_returns_repo_root():
    """开发态：app_root() 返回仓库根（含 pyproject.toml）。"""
    root = runtime.app_root()
    assert (root / "pyproject.toml").exists()
    assert (root / "src" / "atprobe").exists()


def test_app_root_frozen_returns_executable_dir(tmp_path):
    """打包态：app_root() 返回 sys.executable 所在目录。"""
    fake_exe = tmp_path / "ATProbe.exe"
    fake_exe.write_text("")
    with patch.object(runtime.sys, "frozen", True, create=True), \
         patch.object(runtime.sys, "executable", str(fake_exe)):
        assert runtime.app_root() == tmp_path
