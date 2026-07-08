"""资源定位：内置示例资源 vs 用户可写工作区。

两类文件，两种策略：

1. **内置示例**（env.yaml / quick_commands.yaml / 出厂用例）
   随包发布。开发态读仓库根 ``examples/``；打包态优先读用户可写的外露副本
   ``<app_root>/examples/``（build.py 复制到 exe 同级，用户可编辑），
   其次读只读副本 ``<app_root>/_internal/examples/``（PyInstaller datas 注入，兜底）。

   注意：打包后存在两份 examples（外露可写 + _internal 只读）。
   ``builtin_resource`` 必须优先用外露副本，否则用户对 env.yaml/用例的编辑不生效。

2. **用户工作区**（logs / 用户改的用例 / 用户保存的配置）
   可写、可持久化。统一锚定到 ``runtime.app_root()``：
   打包态 = exe 同级（便携式），开发态 = 仓库根。
"""

from __future__ import annotations

import sys
from pathlib import Path

from atprobe.infra.runtime import app_root, is_frozen


def builtin_resource(*parts: str) -> Path:
    """返回打包内置示例资源路径（examples/ 下）。

    定位优先级（打包态）：

    1. **``<app_root>/examples/<parts>``（用户可写的外露副本）** —— build.py 的
       ``expose_user_assets`` 会把 examples/ 复制到 exe 同级，这是用户实际编辑的副本。
       必须优先用这处，否则用户改的 env.yaml/用例不生效（issue: 用户编辑
       ``<app_root>/examples/env.yaml`` 但工具读 ``_internal/examples/env.yaml`` 只读副本）。
    2. ``<app_root>/_internal/examples/<parts>``（PyInstaller datas 注入的只读副本，
       作为外露副本缺失时的兜底，如精简分发未带 examples/ 目录）。
    3. ``_MEIPASS/examples/<parts>``（onefile 解压目录；本设计用 onedir，仅兼容兜底）。

    开发态：``<repo>/examples/<parts>``。

    Args:
        *parts: 相对 examples/ 的路径段，如 ``("testcases", "ntp", "x.yaml")``。

    Raises:
        FileNotFoundError: 三处都不存在。
    """
    rel = Path(*parts)

    # 打包态
    if is_frozen():
        # 1. 用户可写的外露副本（build.py 复制到 exe 同级）—— 必须优先
        exposed = app_root() / "examples" / rel
        if exposed.exists():
            return exposed
        # 2. _internal 只读副本（PyInstaller datas 注入）—— 兜底
        internal = app_root() / "_internal" / "examples" / rel
        if internal.exists():
            return internal
        # 3. onefile 解压目录（本设计用 onedir，此处为兼容兜底）
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
