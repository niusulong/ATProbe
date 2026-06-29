"""命令库 YAML 存储层（ruamel.yaml，对齐 envconfig 模式）.

加载优先级（由调用方编排）：
    1. 内置示例文件 examples/quick_commands.yaml（builtin_library_path）
    2. load_library：文件存在则解析，缺失返回空库（幂等）
    3. default_library：内存兜底（迁移旧版默认指令）

原子写：dump_library 先写 .tmp 再 os.replace，避免保存中途异常损坏原文件。
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from atprobe.domain.quickcmd.models import CommandLibrary


class QuickCmdStoreError(Exception):
    """命令库文件读写/解析错误（对齐 EnvConfigError 风格）。"""


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------
_yaml_load = YAML(typ="safe")


def load_library(path: Path) -> CommandLibrary:
    """从 YAML 文件加载命令库。

    文件缺失或为空 → 返回空库（不抛错，幂等）。
    格式非法 → 抛 QuickCmdStoreError。
    """
    if not path.exists():
        return CommandLibrary.empty()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuickCmdStoreError(f"无法读取命令库文件：{exc}") from exc
    if not text.strip():
        return CommandLibrary.empty()
    try:
        raw = _yaml_load.load(StringIO(text))
    except YAMLError as exc:
        raise QuickCmdStoreError(f"YAML 语法错误：{exc}") from exc
    if raw is None:
        return CommandLibrary.empty()
    if not isinstance(raw, dict):
        raise QuickCmdStoreError(
            f"命令库根节点必须是映射，实际为 {type(raw).__name__}"
        )
    projects_raw = raw.get("projects")
    if projects_raw is None:
        return CommandLibrary.empty()
    if not isinstance(projects_raw, list):
        raise QuickCmdStoreError(
            f"'projects' 必须是列表，实际为 {type(projects_raw).__name__}"
        )
    lib = CommandLibrary.empty()
    for i, proj_raw in enumerate(projects_raw):
        if not isinstance(proj_raw, dict):
            raise QuickCmdStoreError(
                f"第 {i + 1} 个项目必须是映射，实际为 {type(proj_raw).__name__}"
            )
        name = proj_raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise QuickCmdStoreError(f"第 {i + 1} 个项目缺少 'name' 或为空")
        lib.add_project(name)
        groups_raw = proj_raw.get("groups", []) or []
        if not isinstance(groups_raw, list):
            raise QuickCmdStoreError(
                f"项目 {name!r} 的 'groups' 必须是列表"
            )
        for j, grp_raw in enumerate(groups_raw):
            if not isinstance(grp_raw, dict):
                raise QuickCmdStoreError(
                    f"项目 {name!r} 第 {j + 1} 个功能组必须是映射"
                )
            gname = grp_raw.get("name")
            if not isinstance(gname, str) or not gname.strip():
                raise QuickCmdStoreError(
                    f"项目 {name!r} 第 {j + 1} 个功能组缺少 'name' 或为空"
                )
            grp = lib.add_group(name, gname)
            cmds_raw = grp_raw.get("commands", []) or []
            if not isinstance(cmds_raw, list):
                raise QuickCmdStoreError(
                    f"功能组 {name!r}/{gname!r} 的 'commands' 必须是列表"
                )
            for c in cmds_raw:
                # 强制转 str，兼容用户手写整数等
                grp.commands.append(str(c))
    return lib


# ---------------------------------------------------------------------------
# 保存（原子写）
# ---------------------------------------------------------------------------
def dump_library(library: CommandLibrary, path: Path) -> None:
    """把命令库写回 YAML 文件（原子写：先写 .tmp 再 os.replace）。"""
    data = {
        "projects": [
            {
                "name": p.name,
                "groups": [
                    {"name": g.name, "commands": list(g.commands)}
                    for g in p.groups
                ],
            }
            for p in library.projects
        ]
    }
    out = StringIO()
    yaml_write = YAML()
    yaml_write.default_flow_style = False
    yaml_write.indent(mapping=2, sequence=4, offset=2)
    yaml_write.dump(data, out)
    text = out.getvalue()

    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # Windows 上原子覆盖


# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------
def default_library() -> CommandLibrary:
    """返回出厂默认命令库（迁移旧版 _DEFAULT_QUICK_COMMANDS 五条指令）。

    归入「通用/基础」组，供首次加载无文件时回落。
    """
    lib = CommandLibrary.empty()
    lib.add_project("通用")
    grp = lib.add_group("通用", "基础")
    for cmd in ("AT", "AT+CSQ", "AT+CEREG?", "AT+CPIN?", "AT+CGDCONT?"):
        grp.commands.append(cmd)
    return lib


def builtin_library_path() -> Path:
    """返回内置示例文件的绝对路径 examples/quick_commands.yaml。

    经 ``atprobe.infra.resources.builtin_resource`` 定位，开发态读仓库根、
    打包态读 _internal/examples，避免 ``parents[N]`` 硬编码在打包后失效。
    """
    from atprobe.infra.resources import builtin_resource

    return builtin_resource("quick_commands.yaml")
