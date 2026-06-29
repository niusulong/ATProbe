"""infra/version.py：current_version() 版本读取测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atprobe.infra import version as version_mod


def test_current_version_reads_repo_version_in_dev(tmp_path: Path) -> None:
    """开发态：读 app_root()/VERSION（仓库根）。"""
    fake_root = tmp_path
    (fake_root / "VERSION").write_text("0.2.1\n", encoding="utf-8")
    with patch.object(version_mod, "app_root", return_value=fake_root), patch.object(
        version_mod, "is_frozen", return_value=False
    ):
        assert version_mod.current_version() == "0.2.1"


def test_current_version_reads_internal_in_frozen(tmp_path: Path) -> None:
    """打包态：读 app_root()/_internal/VERSION。"""
    fake_root = tmp_path
    internal = fake_root / "_internal"
    internal.mkdir()
    (internal / "VERSION").write_text("0.3.0", encoding="utf-8")
    with patch.object(version_mod, "app_root", return_value=fake_root), patch.object(
        version_mod, "is_frozen", return_value=True
    ):
        assert version_mod.current_version() == "0.3.0"


def test_current_version_strips_whitespace(tmp_path: Path) -> None:
    """VERSION 文件带换行/空格时 strip 干净。"""
    fake_root = tmp_path
    (fake_root / "VERSION").write_text("  1.2.3  \n", encoding="utf-8")
    with patch.object(version_mod, "app_root", return_value=fake_root), patch.object(
        version_mod, "is_frozen", return_value=False
    ):
        assert version_mod.current_version() == "1.2.3"


def test_current_version_fallback_on_missing(tmp_path: Path) -> None:
    """VERSION 文件缺失时回退 '0.0.0'，不抛异常。"""
    with patch.object(version_mod, "app_root", return_value=tmp_path), patch.object(
        version_mod, "is_frozen", return_value=False
    ):
        assert version_mod.current_version() == "0.0.0"


def test_current_version_reads_real_repo() -> None:
    """集成：读真实仓库根 VERSION，应等于 pyproject.toml 的 version。"""
    import tomllib

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert version_mod.current_version() == expected
