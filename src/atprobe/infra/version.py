"""运行时版本读取（单一真相源的消费者）。

真相源：pyproject.toml 的 version（开发/构建时）。
运行时如何拿到：
    - 打包态：build.py 在构建后写 ``<app_root>/_internal/VERSION``，本模块读它。
    - 开发态：仓库根 ``VERSION`` 文件（build.py 维护与 pyproject.toml 一致）。
    - 都没有：回退 ``'0.0.0'``（不阻塞启动，升级检查会认为该升级）。
"""

from __future__ import annotations

from atprobe.infra.runtime import app_root, is_frozen

_FALLBACK = "0.0.0"


def current_version() -> str:
    """当前运行版本号（如 '0.2.1'），未知返回 '0.0.0'。"""
    if is_frozen():
        candidate = app_root() / "_internal" / "VERSION"
    else:
        candidate = app_root() / "VERSION"
    try:
        text = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK
    return text or _FALLBACK
