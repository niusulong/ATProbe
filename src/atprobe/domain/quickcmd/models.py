"""命令库数据模型（纯 dataclass，无 Qt 依赖，可独立单测）.

三级结构：CommandLibrary → CommandProject[] → CommandGroup[] → commands[](str)
与 YAML 文件 projects/groups/commands 嵌套一一对应，序列化零转换。

重名校验集中在此层：项目名全局唯一、功能组名同项目内唯一、命令允许重复。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommandGroup:
    """功能分组（树第二层）—— 一组 AT 命令字符串。"""

    name: str
    commands: list[str] = field(default_factory=list)


@dataclass
class CommandProject:
    """项目（树顶层）—— 含若干功能分组。"""

    name: str
    groups: list[CommandGroup] = field(default_factory=list)

    def find_group(self, name: str) -> CommandGroup | None:
        for g in self.groups:
            if g.name == name:
                return g
        return None


@dataclass
class CommandLibrary:
    """命令库（整棵树根）—— 含若干项目。"""

    projects: list[CommandProject] = field(default_factory=list)

    @classmethod
    def empty(cls) -> CommandLibrary:
        return cls()

    # ------------------------------------------------------------------
    # 查找
    # ------------------------------------------------------------------
    def find_project(self, name: str) -> CommandProject | None:
        for p in self.projects:
            if p.name == name:
                return p
        return None

    def find_group(self, project: str, group: str) -> CommandGroup | None:
        p = self.find_project(project)
        return p.find_group(group) if p is not None else None

    # ------------------------------------------------------------------
    # 新增（重名校验）
    # ------------------------------------------------------------------
    def add_project(self, name: str) -> CommandProject:
        name = name.strip()
        if not name:
            raise ValueError("项目名不能为空")
        if self.find_project(name) is not None:
            raise ValueError(f"项目 {name!r} 已存在")
        proj = CommandProject(name=name)
        self.projects.append(proj)
        return proj

    def add_group(self, project: str, name: str) -> CommandGroup:
        name = name.strip()
        if not name:
            raise ValueError("功能组名不能为空")
        p = self.find_project(project)
        if p is None:
            raise ValueError(f"项目 {project!r} 不存在")
        if p.find_group(name) is not None:
            raise ValueError(f"功能组 {name!r} 已存在于项目 {project!r}")
        grp = CommandGroup(name=name)
        p.groups.append(grp)
        return grp

    def add_command(self, project: str, group: str, command: str) -> None:
        command = command.strip()
        if not command:
            raise ValueError("命令不能为空")
        g = self.find_group(project, group)
        if g is None:
            raise ValueError(f"功能组 {project!r}/{group!r} 不存在")
        g.commands.append(command)

    # ------------------------------------------------------------------
    # 重命名（排除自身后判重）
    # ------------------------------------------------------------------
    def rename_project(self, old: str, new: str) -> None:
        new = new.strip()
        if not new:
            raise ValueError("项目名不能为空")
        if new == old:
            return  # 幂等
        if self.find_project(new) is not None:
            raise ValueError(f"项目 {new!r} 已存在")
        p = self.find_project(old)
        if p is None:
            raise ValueError(f"项目 {old!r} 不存在")
        p.name = new

    # ------------------------------------------------------------------
    # 删除（幂等，不存在不抛错）
    # ------------------------------------------------------------------
    def remove_project(self, name: str) -> None:
        self.projects = [p for p in self.projects if p.name != name]

    def remove_group(self, project: str, name: str) -> None:
        p = self.find_project(project)
        if p is not None:
            p.groups = [g for g in p.groups if g.name != name]

    # ------------------------------------------------------------------
    # 按索引操作命令（GUI 树节点自带位置上下文；同组命令允许重复，按文本操作
    # 会误伤全部同文命令——批 5 T6-9）
    # ------------------------------------------------------------------
    def remove_command_at(self, project: str, group: str, index: int) -> None:
        """按索引删除命令（只删点中的那一条，同文重复命令不受牵连）.

        Raises:
            ValueError: 项目/功能组不存在。
            IndexError: 索引越界（附组内命令数与有效范围，便于 UI 提示）。
        """
        g = self.find_group(project, group)
        if g is None:
            raise ValueError(f"功能组 {project!r}/{group!r} 不存在")
        if not 0 <= index < len(g.commands):
            raise IndexError(
                f"命令索引 {index} 越界：功能组 {project!r}/{group!r} 共 {len(g.commands)} 条"
                f"（有效范围 0..{max(len(g.commands) - 1, 0)}）"
            )
        del g.commands[index]

    def replace_command_at(self, project: str, group: str, index: int, command: str) -> None:
        """按索引原位修改命令（保持组内顺序；与 add+remove 的"挪到末尾"相对）.

        校验口径与 add_command 一致（strip + 非空）。Raises 同 remove_command_at。
        """
        command = command.strip()
        if not command:
            raise ValueError("命令不能为空")
        g = self.find_group(project, group)
        if g is None:
            raise ValueError(f"功能组 {project!r}/{group!r} 不存在")
        if not 0 <= index < len(g.commands):
            raise IndexError(
                f"命令索引 {index} 越界：功能组 {project!r}/{group!r} 共 {len(g.commands)} 条"
                f"（有效范围 0..{max(len(g.commands) - 1, 0)}）"
            )
        g.commands[index] = command
