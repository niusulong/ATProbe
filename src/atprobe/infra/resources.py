"""资源定位：内置只读资源 vs 用户可写工作区。

两类文件，两种策略：

1. **内置示例**（env.yaml / quick_commands.yaml / 出厂用例）
   只读，随包发布。开发态读仓库根 ``examples/``；打包态读
   ``<app_root>/_internal/examples/``（PyInstaller datas 注入）。

2. **用户工作区**（logs / 用户改的用例 / 用户保存的配置）
   可写、可持久化。统一锚定到 ``runtime.app_root()``：
   打包态 = exe 同级（便携式），开发态 = 仓库根。
"""

from __future__ import annotations

import sys
from pathlib import Path

from atprobe.infra.runtime import app_root, is_frozen


def builtin_resource(*parts: str) -> Path:
    """返回打包内置只读资源路径（examples/ 下）。

    开发态：``<repo>/examples/<parts>``
    打包态：``<app_root>/_internal/examples/<parts>``（PyInstaller datas 注入）

    Args:
        *parts: 相对 examples/ 的路径段，如 ``("testcases", "ntp", "x.yaml")``。

    Raises:
        FileNotFoundError: 两处都不存在。
    """
    rel = Path(*parts)

    # 打包态：PyInstaller 把 examples 打进 _internal/examples
    if is_frozen():
        candidate = app_root() / "_internal" / "examples" / rel
        if candidate.exists():
            return candidate
        # onefile 解压目录（本设计用 onedir，此处为兼容兜底）
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            meipass_candidate = Path(meipass) / "examples" / rel
            if meipass_candidate.exists():
                return meipass_candidate
        raise FileNotFoundError(f"内置资源不存在（打包态）：{rel}")

    # 开发态：仓库根 examples
    candidate = app_root() / "examples" / rel
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"内置资源不存在（开发态）：{rel}")


def user_workspace() -> Path:
    """返回用户可写工作区根。

    打包态 = exe 同级目录（便携式）；开发态 = 仓库根。
    调用方在其下拼 ``logs`` / 用户用例目录等。
    """
    return app_root()


def resolve_workspace_path(raw: str) -> Path:
    """把工作区相对路径锚定到 ``user_workspace()``；绝对路径原样返回。

    解决打包态 CLI/GUI 从非 exe 目录启动时，工作区路径（report_dir/log_dir/
    cases_dir/env_config 等）相对 ``os.getcwd()`` 解析导致写入错误位置的问题。

    - 绝对路径（如用户在 atprobe.yaml 写 ``D:/foo/reports``）→ 原样返回
    - 相对路径（如 ``./reports`` 或 ``reports``）→ ``user_workspace() / raw``

    开发态 ``user_workspace()`` = 仓库根 = 当前 cwd，故行为与旧的 cwd 相对解析一致；
    打包态 = exe 同级（便携式工作区），与 GUI 双击启动的 cwd 一致，
    但 CLI 从别处调用时也能正确写入 exe 同级工作区。
    """
    p = Path(raw)
    return p if p.is_absolute() else user_workspace() / p
