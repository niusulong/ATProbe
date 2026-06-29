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


# ---------------------------------------------------------------------------
# resources.py
# ---------------------------------------------------------------------------
import pytest  # noqa: E402

from atprobe.infra import resources  # noqa: E402


def test_builtin_resource_env_yaml_exists():
    """内置 env.yaml 存在（开发态从仓库 examples 读到）。"""
    p = resources.builtin_resource("env.yaml")
    assert p.exists()
    assert p.name == "env.yaml"


def test_builtin_resource_quick_commands_exists():
    """内置 quick_commands.yaml 存在。"""
    p = resources.builtin_resource("quick_commands.yaml")
    assert p.exists()


def test_builtin_resource_missing_raises():
    """不存在的资源 → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        resources.builtin_resource("does_not_exist.yaml")


def test_user_workspace_dev_mode_returns_repo_root():
    """用户工作区 = app_root（开发态仓库根）。"""
    ws = resources.user_workspace()
    assert (ws / "pyproject.toml").exists()


def test_user_workspace_frozen_returns_exe_dir(tmp_path):
    """打包态用户工作区 = exe 同级目录。"""
    (tmp_path / "ATProbe.exe").write_text("")
    with patch.object(resources.sys, "frozen", True, create=True), \
         patch.object(resources.sys, "executable", str(tmp_path / "ATProbe.exe")):
        assert resources.user_workspace() == tmp_path
