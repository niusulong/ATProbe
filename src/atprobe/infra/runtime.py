"""打包态运行时检测。

统一「我该去哪找文件」的判据，消除散落各处的 ``Path(__file__).parents[N]`` 硬编码。
- 开发态：仓库根（``src/atprobe/infra/runtime.py`` 上溯 3 级）
- 打包态：exe 所在目录（便携式工作区根）

判据：``sys.frozen`` 是否存在（PyInstaller 注入）。
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境。"""
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """应用根目录。

    - 打包态：exe 所在目录（便携式工作区根，用户可写）
    - 开发态：仓库根（含 pyproject.toml / src / examples）
    """
    if is_frozen():
        return Path(sys.executable).parent
    # src/atprobe/infra/runtime.py → 上溯 3 级到仓库根
    # （parents[0]=infra, parents[1]=atprobe, parents[2]=src, parents[3]=repo root）
    return Path(__file__).resolve().parents[3]
