"""运行时版本读取（单一真相源的消费者）。

真相源：pyproject.toml 的 version（开发/构建时）。
运行时如何拿到：
    - 打包态：build.py 在构建后写 ``<app_root>/_internal/VERSION``，本模块读它。
    - 开发态：仓库根 ``VERSION`` 文件（build.py 维护与 pyproject.toml 一致）。
    - 都没有：回退 ``'0.0.0'``（不阻塞启动）——但该值是"未知"标记而非真实
      版本，升级检查等比较场景须先用 ``is_version_known`` 排除（否则任何
      远端版本都比 0.0.0 新，恒提示升级）。
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


def is_version_known(version: str | None = None) -> bool:
    """版本是否可确定（VERSION 文件缺失/为空 → False）。

    ``current_version()`` 的回退值 ``'0.0.0'`` 与真实 0.0.0 无法从字符串区分——
    项目从未以 0.0.0 发版（真相源 pyproject 起步即真实版本），按回退值即未知
    处理。比较场景（升级检查的 semver 比较）应先经本函数排除未知，再参与比较。
    """
    v = current_version() if version is None else version
    return v != _FALLBACK
