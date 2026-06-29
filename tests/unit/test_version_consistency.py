"""版本 drift 防护：VERSION 文件 / pyproject.toml / __version__ 必须一致。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import atprobe

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_version_file_matches_pyproject() -> None:
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    expected = tomllib.loads(pyproject)["project"]["version"]
    version_file = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version_file == expected, (
        f"VERSION 文件={version_file!r} 与 pyproject.toml version={expected!r} 不一致"
    )


def test_dunder_version_matches_pyproject() -> None:
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    expected = tomllib.loads(pyproject)["project"]["version"]
    assert atprobe.__version__ == expected, (
        f"__version__={atprobe.__version__!r} 与 pyproject.toml version={expected!r} 不一致"
    )
