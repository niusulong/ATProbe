# 手动调试命令库 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把手动调试界面的扁平快捷指令升级为项目→功能→命令三层命令库（YAML 配置 + 主窗口右侧停靠面板 + 管理对话框），并移除历史命令记录功能。

**Architecture:** 方案 B——domain 分层（`models.py` 纯数据模型 + `store.py` YAML 读写）+ GUI 组件分离（`command_library.py` 停靠面板 + 管理对话框）。命令库面板用 `send_requested(str)` 信号解耦，主窗口路由到手动调试页 `send_command()`。

**Tech Stack:** Python 3.12、PySide6（QDockWidget/QTreeWidget/QDialog）、ruamel.yaml（项目已有依赖，`YAML(typ="safe")` 加载 / `YAML()` 写回，对齐 `envconfig.py` 模式）、pytest（单测无 Qt，集成测试 offscreen）。

**参考文件（实现时对照现有模式）：**
- `src/atprobe/infra/config/envconfig.py` —— ruamel.yaml 读写 + `EnvConfigError` 风格
- `src/atprobe/gui/tabs/case_execute.py` —— `QTreeWidget` 三层树渲染模式
- `src/atprobe/gui/tabs/manual_debug.py` —— 待改造的手动调试页（`_append_line`、`_current_port`、`send_manual` 路由）
- `src/atprobe/gui/mainwindow.py` —— DockWidget 装配（`_init_sidebar`）+ tab 查找（`_find_tab`）
- `src/atprobe/gui/icons.py` —— `make_icon(name, color)` 接口
- `tests/integration/test_gui.py` —— `_FakeMain` 替身、`TestManualDebugQuickCommands` 风格

---

## 文件结构

### 新建文件
| 文件 | 职责 |
|------|------|
| `src/atprobe/domain/quickcmd/__init__.py` | 包标识，导出公开 API |
| `src/atprobe/domain/quickcmd/models.py` | 纯 dataclass 数据模型 + 树形增删改 + 重名校验（无 Qt 依赖） |
| `src/atprobe/domain/quickcmd/store.py` | ruamel.yaml 读写：`load_library`/`dump_library`/`default_library`/`builtin_library_path` + `QuickCmdStoreError` |
| `src/atprobe/gui/widgets/__init__.py` | 包标识 |
| `src/atprobe/gui/widgets/command_library.py` | `CommandLibraryDock`（停靠面板）+ `LibraryManagerDialog`（管理对话框） |
| `examples/quick_commands.yaml` | 内置示例命令库（迁移现有 5 条默认指令） |
| `tests/unit/test_quickcmd_models.py` | models 单测 |
| `tests/unit/test_quickcmd_store.py` | store 单测 |

### 修改文件
| 文件 | 改动 |
|------|------|
| `src/atprobe/gui/tabs/manual_debug.py` | 删历史命令 + 删旧快捷指令；暴露 `current_port()`/`send_command()` |
| `src/atprobe/gui/mainwindow.py` | 装配右侧命令库 Dock + 信号路由 `_on_command_send` |
| `tests/integration/test_gui.py` | 删旧 manual_debug 历史/快捷测试；新增命令库面板/对话框/路由测试 |

---

## Task 1: 数据模型 CommandLibrary

**Files:**
- Create: `src/atprobe/domain/quickcmd/__init__.py`
- Create: `src/atprobe/domain/quickcmd/models.py`
- Create: `tests/unit/test_quickcmd_models.py`

- [ ] **Step 1.1: 写失败测试 `tests/unit/test_quickcmd_models.py`**

```python
"""命令库数据模型单测（无 Qt 依赖）."""

from __future__ import annotations

import pytest

from atprobe.domain.quickcmd.models import (
    CommandGroup,
    CommandLibrary,
    CommandProject,
)


class TestAddFind:
    def test_add_project_group_command(self) -> None:
        lib = CommandLibrary.empty()
        proj = lib.add_project("N58 项目")
        grp = lib.add_group("N58 项目", "网络")
        lib.add_command("N58 项目", "网络", "AT+CSQ")
        assert proj.name == "N58 项目"
        assert grp.name == "网络"
        assert lib.find_project("N58 项目") is proj
        assert lib.find_group("N58 项目", "网络") is grp
        assert "AT+CSQ" in lib.find_group("N58 项目", "网络").commands

    def test_find_missing_returns_none(self) -> None:
        lib = CommandLibrary.empty()
        assert lib.find_project("不存在") is None
        assert lib.find_group("N58 项目", "网络") is None


class TestDuplicateValidation:
    def test_duplicate_project_raises(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        with pytest.raises(ValueError):
            lib.add_project("P1")

    def test_duplicate_group_in_same_project_raises(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        with pytest.raises(ValueError):
            lib.add_group("P1", "G1")

    def test_same_group_name_in_different_project_ok(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_project("P2")
        lib.add_group("P1", "通用")
        lib.add_group("P2", "通用")  # 不同项目下同名功能组，允许

    def test_duplicate_command_allowed(self) -> None:
        """同功能组下命令允许重复（不去重）."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.add_command("P1", "G1", "AT")  # 允许重复
        assert lib.find_group("P1", "G1").commands == ["AT", "AT"]

    def test_empty_name_raises(self) -> None:
        lib = CommandLibrary.empty()
        with pytest.raises(ValueError):
            lib.add_project("")
        lib.add_project("P1")
        with pytest.raises(ValueError):
            lib.add_group("P1", "")
        with pytest.raises(ValueError):
            lib.add_command("P1", "G1", "")


class TestRename:
    def test_rename_project_to_new_name(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.rename_project("P1", "P2")
        assert lib.find_project("P1") is None
        assert lib.find_project("P2") is not None

    def test_rename_project_duplicate_raises(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_project("P2")
        with pytest.raises(ValueError):
            lib.rename_project("P1", "P2")

    def test_rename_project_to_self_idempotent(self) -> None:
        """重命名为自身原名应幂等成功."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.rename_project("P1", "P1")  # 不报错
        assert lib.find_project("P1") is not None


class TestRemove:
    def test_remove_project_cascades(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.remove_project("P1")
        assert lib.find_project("P1") is None

    def test_remove_group(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.remove_group("P1", "G1")
        assert lib.find_group("P1", "G1") is None

    def test_remove_command(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.add_command("P1", "G1", "ATZ")
        lib.remove_command("P1", "G1", "AT")
        assert lib.find_group("P1", "G1").commands == ["ATZ"]

    def test_remove_missing_is_idempotent(self) -> None:
        """删除不存在的项不抛错（幂等）."""
        lib = CommandLibrary.empty()
        lib.remove_project("不存在")  # 不抛错
        lib.remove_group("P", "G")
        lib.remove_command("P", "G", "AT")
```

- [ ] **Step 1.2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_quickcmd_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.domain.quickcmd'`

- [ ] **Step 1.3: 实现 `src/atprobe/domain/quickcmd/__init__.py`**

```python
"""快捷命令库领域层（项目→功能→命令三层模型 + YAML 持久化）."""

from atprobe.domain.quickcmd.models import (
    CommandGroup,
    CommandLibrary,
    CommandProject,
)
from atprobe.domain.quickcmd.store import (
    QuickCmdStoreError,
    builtin_library_path,
    default_library,
    dump_library,
    load_library,
)

__all__ = [
    "CommandGroup",
    "CommandLibrary",
    "CommandProject",
    "QuickCmdStoreError",
    "builtin_library_path",
    "default_library",
    "dump_library",
    "load_library",
]
```

- [ ] **Step 1.4: 实现 `src/atprobe/domain/quickcmd/models.py`**

```python
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

    def remove_command(self, project: str, group: str, command: str) -> None:
        g = self.find_group(project, group)
        if g is not None:
            g.commands = [c for c in g.commands if c != command]
```

- [ ] **Step 1.5: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_quickcmd_models.py -v`
Expected: PASS（所有测试通过）

- [ ] **Step 1.6: 提交**

```bash
git add src/atprobe/domain/quickcmd/__init__.py src/atprobe/domain/quickcmd/models.py tests/unit/test_quickcmd_models.py
git commit -m "feat(quickcmd): 命令库数据模型（项目/功能/命令三层 + 增删改校验）"
```

---

## Task 2: YAML 存储层 + 内置示例文件

**Files:**
- Create: `src/atprobe/domain/quickcmd/store.py`
- Create: `examples/quick_commands.yaml`
- Create: `tests/unit/test_quickcmd_store.py`

- [ ] **Step 2.1: 写失败测试 `tests/unit/test_quickcmd_store.py`**

```python
"""命令库 YAML 存储层单测（无 Qt 依赖）."""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.domain.quickcmd.models import CommandLibrary
from atprobe.domain.quickcmd.store import (
    QuickCmdStoreError,
    builtin_library_path,
    default_library,
    dump_library,
    load_library,
)


class TestLoad:
    def test_load_nested_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "lib.yaml"
        f.write_text(
            "projects:\n"
            "  - name: N58 项目\n"
            "    groups:\n"
            "      - name: 网络\n"
            "        commands:\n"
            "          - AT+CSQ\n"
            "          - AT+CEREG?\n",
            encoding="utf-8",
        )
        lib = load_library(f)
        grp = lib.find_group("N58 项目", "网络")
        assert grp is not None
        assert grp.commands == ["AT+CSQ", "AT+CEREG?"]

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """文件缺失 → 返回空库（不抛错，幂等）."""
        lib = load_library(tmp_path / "nope.yaml")
        assert lib.projects == []

    def test_load_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        lib = load_library(f)
        assert lib.projects == []

    def test_load_no_projects_key_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "x.yaml"
        f.write_text("foo: bar\n", encoding="utf-8")
        lib = load_library(f)
        assert lib.projects == []

    def test_load_invalid_structure_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("projects: \"不是列表\"\n", encoding="utf-8")
        with pytest.raises(QuickCmdStoreError):
            load_library(f)

    def test_load_missing_project_name_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("projects:\n  - groups: []\n", encoding="utf-8")
        with pytest.raises(QuickCmdStoreError):
            load_library(f)


class TestDumpRoundTrip:
    def test_dump_then_load_roundtrip(self, tmp_path: Path) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.add_command("P1", "G1", "ATZ")
        lib.add_project("P2")
        lib.add_group("P2", "G2")
        lib.add_command("P2", "G2", "ATI")

        f = tmp_path / "out.yaml"
        dump_library(lib, f)
        assert f.exists()  # 原子写后文件存在

        lib2 = load_library(f)
        assert lib2.find_group("P1", "G1").commands == ["AT", "ATZ"]
        assert lib2.find_group("P2", "G2").commands == ["ATI"]

    def test_dump_empty_library(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        dump_library(CommandLibrary.empty(), f)
        lib = load_library(f)
        assert lib.projects == []


class TestDefaults:
    def test_default_library_has_migrated_commands(self) -> None:
        """默认库含迁移的 5 条指令（AT/AT+CSQ/AT+CEREG?/AT+CPIN?/AT+CGDCONT?）."""
        lib = default_library()
        all_cmds = [
            c for p in lib.projects for g in p.groups for c in g.commands
        ]
        for expected in ("AT", "AT+CSQ", "AT+CEREG?", "AT+CPIN?", "AT+CGDCONT?"):
            assert expected in all_cmds, f"默认库缺少迁移指令 {expected}"

    def test_builtin_library_path_points_to_examples(self) -> None:
        p = builtin_library_path()
        assert p.name == "quick_commands.yaml"
        assert "examples" in p.parts
```

- [ ] **Step 2.2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_quickcmd_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.domain.quickcmd.store'`

- [ ] **Step 2.3: 创建内置示例文件 `examples/quick_commands.yaml`**

```yaml
# ATProbe 命令库示例（项目→功能→命令三层）
# 用途：手动调试页命令库默认加载源；可手动编辑、git 跟踪、团队共享。
# 结构：projects[].groups[].commands[] —— 与树层级一一对应。
projects:
  - name: N58 项目
    groups:
      - name: 网络
        commands:
          - AT+CSQ
          - AT+CEREG?
      - name: SIM 卡
        commands:
          - AT+CPIN?
          - AT+CGDCONT?
  - name: 通用
    groups:
      - name: 基础
        commands:
          - AT
          - ATI
```

- [ ] **Step 2.4: 实现 `src/atprobe/domain/quickcmd/store.py`**

```python
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

from atprobe.domain.quickcmd.models import (
    CommandGroup,
    CommandLibrary,
    CommandProject,
)

# 项目根目录（src/atprobe/domain/quickcmd/store.py → 上溯 4 级到项目根）
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BUILTIN_PATH = _PROJECT_ROOT / "examples" / "quick_commands.yaml"


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
        proj = lib.add_project(name)
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
    proj = lib.add_project("通用")
    grp = lib.add_group("通用", "基础")
    for cmd in ("AT", "AT+CSQ", "AT+CEREG?", "AT+CPIN?", "AT+CGDCONT?"):
        grp.commands.append(cmd)
    return lib


def builtin_library_path() -> Path:
    """返回内置示例文件的绝对路径 examples/quick_commands.yaml。"""
    return _BUILTIN_PATH
```

- [ ] **Step 2.5: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_quickcmd_store.py -v`
Expected: PASS（所有测试通过）

- [ ] **Step 2.6: 提交**

```bash
git add src/atprobe/domain/quickcmd/store.py examples/quick_commands.yaml tests/unit/test_quickcmd_store.py
git commit -m "feat(quickcmd): YAML 存储层 + 内置示例（原子写 + 缺失幂等）"
```

---

## Task 3: 手动调试页改造（删历史/快捷 + 暴露方法）

**Files:**
- Modify: `src/atprobe/gui/tabs/manual_debug.py`

本任务是**删减为主**，先改造页面再在 Task 4-6 重建命令库。改造后页面保留端口/发送/响应三卡片，发送来源由右侧命令库面板提供。先改代码，测试改写放在 Task 7 一并处理（删旧测试 + 加新测试），避免中途测试处于不一致状态。

- [ ] **Step 3.1: 删除历史命令相关代码**

打开 `src/atprobe/gui/tabs/manual_debug.py`，删除以下内容：

1. 删除常量 `_HISTORY_KEY` 和 `_MAX_HISTORY`（约第 48-49 行）
2. 删除 import 中的 `QComboBox`（如仅历史下拉使用则删；但波特率/帧格式也用 QComboBox，**保留**）。检查：`QComboBox` 被端口/波特率/帧格式/结束符下拉使用，**保留 import**。
3. 在 `__init__` 中删除 `self._load_history()` 调用（约第 85 行）
4. 在 `_init_ui` 发送卡片中，删除整个 `hist_row` 块（约第 153-160 行，从 `hist_row = QHBoxLayout()` 到 `send_layout.addLayout(hist_row)`）
5. 删除方法 `_on_history_pick`、`_add_history`、`_load_history`（约第 396-467 行区间）
6. 在 `_send` 方法末尾删除 `self._add_history(commands[-1])` 调用（约第 394 行）

- [ ] **Step 3.2: 删除旧快捷指令相关代码**

删除以下内容：

1. 删除常量 `_DEFAULT_QUICK_COMMANDS`、`_MAX_QUICK_COMMANDS`、`_SETTINGS_KEY`（约第 45-47 行）
2. 在 `__init__` 中删除 `self._quick_commands = self._load_quick_commands()`（约第 78 行）
3. 在 `_init_ui` 末尾删除 `layout.addWidget(self._build_quick_group())`（约第 216 行）
4. 删除整个方法 `_build_quick_group`、`_populate_quick_buttons`、`_add_quick_from_edit`、`_add_quick`、`_remove_quick`、`_reset_quick`、`_show_quick_menu`、`_load_quick_commands`、`_save_quick_commands`（约第 218-523 行区间）
5. 删除 import 中不再使用的：`QLineEdit`（检查是否仅快捷指令使用——发送区无 QLineEdit，**确认可删**）、`QMenu`（仅快捷指令右键菜单使用，**可删**）

> 注意：`QShortcut` 仍被发送区 Ctrl+Return 使用，**保留**。

- [ ] **Step 3.3: 新增 `current_port()` 公开方法**

在 `manual_debug.py` 的 `ManualDebugWidget` 类中（`_current_port` 私有方法附近），新增公开方法：

```python
    def current_port(self) -> str:
        """返回当前选中端口的真实名（供命令库面板路由发送目标）."""
        return self._current_port()
```

- [ ] **Step 3.4: 新增 `send_command()` 公开方法**

在 `manual_debug.py` 的 `ManualDebugWidget` 类中，新增方法（独立实现，不读 send_edit，复用连接校验与 TX 上屏逻辑）：

```python
    def send_command(self, command: str) -> None:
        """发送单条命令（命令库面板双击调用）：TX 上屏 + 调 send_manual。

        与处理多行的 _send 分离：不修改发送框内容，不引入副作用。
        用发送区当前全局结束符 self._terminator。
        """
        port = self._current_port()
        if not port:
            QMessageBox.warning(self, "提示", "请先选择端口")
            return
        is_conn = getattr(self._main, "is_port_connected", None)
        if callable(is_conn) and not is_conn(port):
            QMessageBox.warning(self, "提示", f"端口 {port} 未连接，请先「打开端口」")
            return
        send_manual = getattr(self._main, "send_manual", None)
        if not callable(send_manual):
            self._append_line("RX", "[错误] 引擎未就绪", self._tokens["danger"])
            return
        # TX 立即上屏（串口助手语义：发送即记录）
        self._append_line("TX", command, self._tokens["data.tx"])
        if not send_manual(port, command):
            self._append_line("RX", "[错误] 发送失败（端口未连接）", self._tokens["danger"])
```

> 注意：`send_manual` 内部会自动追加结束符（见 `portmanager.write_command`），`send_command` 不需手动拼接 `\r\n`。

- [ ] **Step 3.5: 更新模块 docstring**

将 `manual_debug.py` 顶部模块 docstring（第 1-13 行）替换为：

```python
"""手动调试选项卡（M6 §4）—— 类似串口助手的手动发送。

直接调用 M1（不经 M3 引擎、不产生用例结果）。支持：
    - 选择端口 + 波特率/帧格式 + 打开/关闭连接（状态徽标 + 按钮切换）
    - 发送 AT 指令（可调结束符；无超时参数——超时是「用例执行」判定响应完整性的概念）
    - 命令库：经主窗口右侧「命令库」停靠面板管理（项目→功能→命令三层树），
      双击命令直接发送到本页当前端口；增删改经「命令库管理」对话框。

数据模型（纯流式，串口助手语义）：
    - 发送：调 MainWindow.send_manual → PortManager.write_command，只写字节不等响应，TX 立即上屏。
    - 接收：端口打开时经 subscribe_rx 订阅原始 RX 字节流，读线程每收到 chunk 经
      Qt 信号 rx_received 切回主线程按行渲染（_on_rx_bytes）。模块回什么实时显示什么，
      不回则不显示——不引入「等待响应/超时」概念。
"""
```

- [ ] **Step 3.6: 手动冒烟检查（暂不跑全量测试，旧测试会失败，Task 7 统一改）**

Run: `python -c "from atprobe.gui.tabs.manual_debug import ManualDebugWidget; print('import OK')"`
Expected: 输出 `import OK`（确认无语法错误、无残留引用）

Run: `python -c "from PySide6.QtWidgets import QApplication; import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); app=QApplication([]); from atprobe.gui.tabs.registry import TabBinding; from atprobe.gui.tabs.manual_debug import ManualDebugWidget; w=ManualDebugWidget(TabBinding(type_name='manual_debug',params={}), object()); print('construct OK'); print('has current_port:', hasattr(w,'current_port')); print('has send_command:', hasattr(w,'send_command')); print('has history_combo:', hasattr(w,'history_combo'))"`
Expected: 输出 `construct OK` / `has current_port: True` / `has send_command: True` / `has history_combo: False`

- [ ] **Step 3.7: 提交**

```bash
git add src/atprobe/gui/tabs/manual_debug.py
git commit -m "refactor(manual_debug): 移除历史命令/旧快捷指令，暴露 current_port/send_command"
```

---

## Task 4: 命令库停靠面板 CommandLibraryDock

**Files:**
- Create: `src/atprobe/gui/widgets/__init__.py`
- Create: `src/atprobe/gui/widgets/command_library.py`（面板 + 对话框骨架）

本任务实现完整的 `CommandLibraryDock` 面板 + `LibraryManagerDialog` 的最小可用骨架（仅构造 + 树渲染 + `current_path()`，不含增删改表单——Task 5 填充）。这样面板能立即完整工作，对话框在 Task 5 扩展而不破坏接口。集成测试在 Task 7 统一加入。

- [ ] **Step 4.1: 创建 `src/atprobe/gui/widgets/__init__.py`**

```python
"""GUI 可复用组件（停靠面板、对话框等，区别于 tabs 目录的选项卡视图）."""
```

- [ ] **Step 4.2: 创建 `src/atprobe/gui/widgets/command_library.py`（完整面板 + 对话框骨架）**

完整文件内容如下（注意 `refresh_tree` 已是正确版本，group 下正确添加 command）：

```python
"""命令库停靠面板 + 管理对话框（项目→功能→命令三层树）.

面板挂载于主窗口右侧，跨页面常驻；双击命令叶子经 send_requested(str) 信号
通知主窗口路由到手动调试页发送。增删改经 LibraryManagerDialog 集中完成。

解耦：面板不认识手动调试页，只 emit send_requested；主窗口做胶水路由。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from atprobe.domain.quickcmd import (
    CommandLibrary,
    QuickCmdStoreError,
    builtin_library_path,
    load_library,
)
from atprobe.gui.icons import make_icon
from atprobe.gui.theme import get_tokens

# 树节点角色：data 存 "project:名" / "group:项目:功能" / "command:项目:功能:命令"
_NODE_ROLE = Qt.ItemDataRole.UserRole


class CommandLibraryDock(QWidget):
    """命令库停靠面板内容（用 QDockWidget 包裹后挂主窗口右侧）。

    唯一对外出口：send_requested(str) —— 双击命令叶子时 emit。
    """

    send_requested = Signal(str)

    def __init__(self, main_window: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._main = main_window
        self._tokens = get_tokens(dark=False)
        self._path: Path = builtin_library_path()
        self._library: CommandLibrary = CommandLibrary.empty()
        self._init_ui()
        self.reload_library()

    # ------------------------------------------------------------------
    # UI 构造
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QPushButton

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 顶部工具栏：[管理] [刷新] [文件名]
        bar = QHBoxLayout()
        bar.setSpacing(6)
        manage_btn = QPushButton("管理")
        manage_btn.setObjectName("primary")
        manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_btn.clicked.connect(self._open_manager)
        bar.addWidget(manage_btn)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload_library)
        bar.addWidget(refresh_btn)
        bar.addStretch()
        self._file_label = QLabel()
        self._file_label.setObjectName("caption")
        bar.addWidget(self._file_label)
        layout.addLayout(bar)

        # 命令树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("命令库")
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree, 1)

    # ------------------------------------------------------------------
    # 加载与渲染
    # ------------------------------------------------------------------
    def reload_library(self) -> None:
        """从当前 path 重新加载命令库并重建树。"""
        try:
            self._library = load_library(self._path)
        except QuickCmdStoreError as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "加载失败", str(exc))
            return
        self._file_label.setText(self._path.name)
        self.refresh_tree()

    def refresh_tree(self) -> None:
        """按 self._library 重建 QTreeWidget。"""
        self.tree.clear()
        if not self._library.projects:
            hint = QTreeWidgetItem(["（空，点击「管理」添加命令）"])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(hint)
            return
        for proj in self._library.projects:
            pitem = QTreeWidgetItem([proj.name])
            pitem.setData(0, _NODE_ROLE, f"project:{proj.name}")
            pitem.setIcon(0, make_icon("report_view", color=self._tokens["accent"]))
            for grp in proj.groups:
                gitem = QTreeWidgetItem([grp.name])
                gitem.setData(0, _NODE_ROLE, f"group:{proj.name}:{grp.name}")
                gitem.setIcon(0, make_icon("env_config", color=self._tokens["accent"]))
                for cmd in grp.commands:
                    citem = QTreeWidgetItem([cmd])
                    citem.setData(0, _NODE_ROLE, f"command:{proj.name}:{grp.name}:{cmd}")
                    citem.setToolTip(0, cmd)
                    gitem.addChild(citem)
                pitem.addChild(gitem)
            self.tree.addTopLevelItem(pitem)
        self.tree.expandAll()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        """双击：命令叶子 → emit send_requested；项目/功能节点 → 展开/折叠（默认）."""
        raw = item.data(0, _NODE_ROLE)
        if not isinstance(raw, str) or not raw.startswith("command:"):
            return  # 非命令叶子，交给 Qt 默认展开/折叠行为
        # command:项目:功能:命令 → 命令可能含冒号，取第 4 段起拼接
        parts = raw.split(":", 3)
        if len(parts) < 4:
            return
        command = parts[3]
        self.send_requested.emit(command)

    # ------------------------------------------------------------------
    # 管理对话框
    # ------------------------------------------------------------------
    def _open_manager(self) -> None:
        """打开命令库管理对话框，关闭后刷新树."""
        dlg = LibraryManagerDialog(self._library, self._path, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._path = dlg.current_path()
            self.reload_library()


class LibraryManagerDialog(QDialog):
    """命令库管理对话框（模态）：左侧树 + 右侧表单，集中增删改。

    Task 4 提供最小可用骨架（构造 + 树渲染 + current_path），
    Task 5 填充表单与增删改逻辑。
    """

    def __init__(
        self, library: CommandLibrary, path: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("命令库管理")
        self.resize(720, 480)
        self._tokens = get_tokens(dark=False)
        self._library = _clone_library(library)
        self._path = path
        self._init_ui()
        self._refresh_tree()

    def _init_ui(self) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QPushButton

        outer = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("项目 / 功能 / 命令")
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        outer.addWidget(self.tree, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("确定（保存）")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)

    def _refresh_tree(self) -> None:
        """Task 5 扩展为带 node role 的完整渲染；此处先简单渲染让骨架可用."""
        self.tree.clear()
        for proj in self._library.projects:
            pitem = QTreeWidgetItem([proj.name])
            for grp in proj.groups:
                gitem = QTreeWidgetItem([grp.name])
                for cmd in grp.commands:
                    gitem.addChild(QTreeWidgetItem([cmd]))
                pitem.addChild(gitem)
            self.tree.addTopLevelItem(pitem)
        self.tree.expandAll()

    def _on_accept(self) -> None:
        """确定：dump_library 原子写回当前 path。Task 5 完善错误处理."""
        from atprobe.domain.quickcmd import dump_library as _dump

        _dump(self._library, self._path)
        self.accept()

    def current_path(self) -> Path:
        """返回对话框当前的文件路径（供面板同步）。"""
        return self._path


def _clone_library(library: CommandLibrary) -> CommandLibrary:
    """深拷贝命令库（对话框编辑用工作副本，取消时不影响外部）."""
    new = CommandLibrary.empty()
    for p in library.projects:
        proj = new.add_project(p.name)
        for g in p.groups:
            grp = new.add_group(p.name, g.name)
            grp.commands = list(g.commands)
    return new
```

- [ ] **Step 4.3: 冒烟检查（构造面板与对话框骨架）**

Run: `python -c "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); from PySide6.QtWidgets import QApplication; app=QApplication([]); from atprobe.gui.widgets.command_library import CommandLibraryDock, LibraryManagerDialog; from atprobe.domain.quickcmd import builtin_library_path, load_library; w=CommandLibraryDock(object()); print('dock OK, items:', w.tree.topLevelItemCount()); lib=load_library(builtin_library_path()); d=LibraryManagerDialog(lib, builtin_library_path()); print('dialog OK, items:', d.tree.topLevelItemCount())"`
Expected: 输出 `dock OK, items: 2` 和 `dialog OK, items: 2`

- [ ] **Step 4.4: 提交**

```bash
git add src/atprobe/gui/widgets/__init__.py src/atprobe/gui/widgets/command_library.py
git commit -m "feat(gui): 命令库停靠面板 + 管理对话框骨架（三层树 + 双击发送信号）"
```

---

## Task 5: 命令库管理对话框扩展（表单 + 增删改）

**Files:**
- Modify: `src/atprobe/gui/widgets/command_library.py`

Task 4 已建好 `LibraryManagerDialog` 骨架（构造 + 简单树 + `current_path`）。本任务扩展它：加入左右分栏布局、按节点类型动态切换的右侧表单、增删改操作、加载/另存为文件。改写 `_init_ui`、`_refresh_tree`、`_on_accept`，并新增表单构建与操作方法。

- [ ] **Step 5.1: 扩展文件顶部 import（补全对话框所需控件）**

在 `src/atprobe/gui/widgets/command_library.py` 顶部，把 `from PySide6.QtWidgets import (...)` 替换为完整 import（含 `QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QPushButton`）：

```python
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
```

> 注意：`CommandLibraryDock._init_ui` 中的局部 `from PySide6.QtWidgets import QHBoxLayout, QPushButton` 可保留（局部 import 无害）或删除（顶部已 import）。建议删除局部 import 以保持简洁。

- [ ] **Step 5.2: 重写 `LibraryManagerDialog._init_ui`（左右分栏 + 文件栏）**

用以下版本**完整替换** Task 4.2 骨架中的 `_init_ui` 方法：

```python
    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 顶部：[加载文件…] [另存为…] [文件名]
        top = QHBoxLayout()
        load_btn = QPushButton("加载文件…")
        load_btn.clicked.connect(self._on_load_file)
        top.addWidget(load_btn)
        save_as_btn = QPushButton("另存为…")
        save_as_btn.clicked.connect(self._on_save_as)
        top.addWidget(save_as_btn)
        top.addStretch()
        self._file_label = QLabel(self._path.name if self._path else "（未保存）")
        self._file_label.setObjectName("caption")
        top.addWidget(self._file_label)
        outer.addLayout(top)

        # 左右分栏：左树 + 右表单
        body = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("项目 / 功能 / 命令")
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self._on_tree_select)
        body.addWidget(self.tree, 3)

        # 右侧表单容器（动态切换内容）
        self._form_host = QWidget()
        self._form_layout = QVBoxLayout(self._form_host)
        self._form_layout.setContentsMargins(8, 0, 8, 0)
        body.addWidget(self._form_host, 2)
        outer.addLayout(body, 1)

        # 底部：[确定(保存)] [取消]
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("确定（保存）")
        ok_btn.setObjectName("primary")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)
```

- [ ] **Step 5.3: 重写 `_refresh_tree`（带 node role，供右侧表单定位）**

用以下版本**完整替换** Task 4.2 骨架中的 `_refresh_tree` 方法：

```python
    def _refresh_tree(self) -> None:
        """重建树，每个节点 data 存元组标识（供右侧表单定位层级）."""
        self.tree.clear()
        for proj in self._library.projects:
            pitem = QTreeWidgetItem([proj.name])
            pitem.setData(0, _NODE_ROLE, ("project", proj.name))
            for grp in proj.groups:
                gitem = QTreeWidgetItem([grp.name])
                gitem.setData(0, _NODE_ROLE, ("group", proj.name, grp.name))
                for cmd in grp.commands:
                    citem = QTreeWidgetItem([cmd])
                    citem.setData(0, _NODE_ROLE, ("command", proj.name, grp.name, cmd))
                    gitem.addChild(citem)
                pitem.addChild(gitem)
            self.tree.addTopLevelItem(pitem)
        self.tree.expandAll()
```

- [ ] **Step 5.4: 新增表单切换逻辑（`_clear_form` / `_on_tree_select` + 四个表单构建方法）**

在 `LibraryManagerDialog` 类中（`_refresh_tree` 之后）新增以下方法：

```python
    def _clear_form(self) -> None:
        while self._form_layout.count():
            it = self._form_layout.takeAt(0)
            if it is not None and it.widget() is not None:
                it.widget().deleteLater()

    def _on_tree_select(self) -> None:
        items = self.tree.selectedItems()
        node = items[0].data(0, _NODE_ROLE) if items else None
        self._clear_form()
        if node is None:
            self._build_root_form()
        elif node[0] == "project":
            self._build_project_form(node[1])
        elif node[0] == "group":
            self._build_group_form(node[1], node[2])
        elif node[0] == "command":
            self._build_command_form(node[1], node[2], node[3])

    def _build_root_form(self) -> None:
        hint = QLabel("选中左侧节点编辑，或在此新增项目。")
        self._form_layout.addWidget(hint)
        add_btn = QPushButton("＋ 新增项目")
        add_btn.clicked.connect(self._add_project_interactive)
        self._form_layout.addWidget(add_btn)
        self._form_layout.addStretch()

    def _build_project_form(self, proj_name: str) -> None:
        title = QLabel(f"项目：{proj_name}")
        title.setObjectName("caption")
        self._form_layout.addWidget(title)

        row = QHBoxLayout()
        edit = QLineEdit(proj_name)
        row.addWidget(edit, 1)
        rename_btn = QPushButton("重命名")
        rename_btn.clicked.connect(lambda: self._rename_project(proj_name, edit))
        row.addWidget(rename_btn)
        self._form_layout.addLayout(row)

        del_btn = QPushButton("删除项目")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(lambda: self._delete_project(proj_name))
        wrap = QHBoxLayout()
        wrap.addWidget(del_btn)
        self._form_layout.addLayout(wrap)

        add_grp_btn = QPushButton("＋ 新增功能组")
        add_grp_btn.clicked.connect(lambda: self._add_group_interactive(proj_name))
        self._form_layout.addWidget(add_grp_btn)
        self._form_layout.addStretch()

    def _build_group_form(self, proj_name: str, grp_name: str) -> None:
        title = QLabel(f"功能组：{proj_name} / {grp_name}")
        title.setObjectName("caption")
        self._form_layout.addWidget(title)

        row = QHBoxLayout()
        edit = QLineEdit(grp_name)
        row.addWidget(edit, 1)
        rename_btn = QPushButton("重命名")
        rename_btn.clicked.connect(lambda: self._rename_group(proj_name, grp_name, edit))
        row.addWidget(rename_btn)
        self._form_layout.addLayout(row)

        del_btn = QPushButton("删除功能组")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(lambda: self._delete_group(proj_name, grp_name))
        wrap = QHBoxLayout()
        wrap.addWidget(del_btn)
        self._form_layout.addLayout(wrap)

        add_cmd_btn = QPushButton("＋ 新增命令")
        add_cmd_btn.clicked.connect(lambda: self._add_command_interactive(proj_name, grp_name))
        self._form_layout.addWidget(add_cmd_btn)
        self._form_layout.addStretch()

    def _build_command_form(self, proj_name: str, grp_name: str, cmd: str) -> None:
        title = QLabel(f"命令：{proj_name} / {grp_name}")
        title.setObjectName("caption")
        self._form_layout.addWidget(title)

        row = QHBoxLayout()
        edit = QLineEdit(cmd)
        row.addWidget(edit, 1)
        save_btn = QPushButton("修改")
        save_btn.clicked.connect(lambda: self._edit_command(proj_name, grp_name, cmd, edit))
        row.addWidget(save_btn)
        self._form_layout.addLayout(row)

        del_btn = QPushButton("删除命令")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(lambda: self._delete_command(proj_name, grp_name, cmd))
        wrap = QHBoxLayout()
        wrap.addWidget(del_btn)
        self._form_layout.addLayout(wrap)
        self._form_layout.addStretch()
```

- [ ] **Step 5.5: 新增增删改操作方法**

在 `LibraryManagerDialog` 类中（表单构建方法之后）新增以下方法：

```python
    def _add_project_interactive(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新增项目", "项目名:")
        if not (ok and name.strip()):
            return
        try:
            self._library.add_project(name)
        except ValueError as exc:
            QMessageBox.warning(self, "无法新增", str(exc))
            return
        self._refresh_tree()

    def _rename_project(self, old: str, edit: QLineEdit) -> None:
        new = edit.text().strip()
        if not new:
            return
        try:
            self._library.rename_project(old, new)
        except ValueError as exc:
            QMessageBox.warning(self, "无法重命名", str(exc))
            return
        self._refresh_tree()

    def _delete_project(self, name: str) -> None:
        self._library.remove_project(name)
        self._refresh_tree()

    def _add_group_interactive(self, proj_name: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新增功能组", f"{proj_name} 下的功能组名:")
        if not (ok and name.strip()):
            return
        try:
            self._library.add_group(proj_name, name)
        except ValueError as exc:
            QMessageBox.warning(self, "无法新增", str(exc))
            return
        self._refresh_tree()

    def _rename_group(self, proj: str, old: str, edit: QLineEdit) -> None:
        """重命名功能组：add 新组迁移命令 + remove 旧组（model 无 rename_group）."""
        new = edit.text().strip()
        if not new or new == old:
            return
        old_grp = self._library.find_group(proj, old)
        cmds = list(old_grp.commands) if old_grp is not None else []
        try:
            self._library.add_group(proj, new)
        except ValueError as exc:
            QMessageBox.warning(self, "无法重命名", str(exc))
            return
        for c in cmds:
            self._library.add_command(proj, new, c)
        self._library.remove_group(proj, old)
        self._refresh_tree()

    def _delete_group(self, proj: str, name: str) -> None:
        self._library.remove_group(proj, name)
        self._refresh_tree()

    def _add_command_interactive(self, proj: str, grp: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        cmd, ok = QInputDialog.getText(self, "新增命令", f"{proj}/{grp} 的 AT 指令:")
        if not (ok and cmd.strip()):
            return
        try:
            self._library.add_command(proj, grp, cmd)
        except ValueError as exc:
            QMessageBox.warning(self, "无法新增", str(exc))
            return
        self._refresh_tree()

    def _edit_command(self, proj: str, grp: str, old: str, edit: QLineEdit) -> None:
        new = edit.text().strip()
        if not new:
            return
        try:
            self._library.add_command(proj, grp, new)
        except ValueError as exc:
            QMessageBox.warning(self, "无法修改", str(exc))
            return
        self._library.remove_command(proj, grp, old)
        self._refresh_tree()

    def _delete_command(self, proj: str, grp: str, cmd: str) -> None:
        self._library.remove_command(proj, grp, cmd)
        self._refresh_tree()
```

- [ ] **Step 5.6: 新增文件操作方法 + 完善 `_on_accept` 错误处理**

在 `LibraryManagerDialog` 类中新增文件操作方法，并**完整替换**骨架中的 `_on_accept`：

```python
    def _on_load_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "加载命令库", "", "YAML (*.yaml *.yml)")
        if not f:
            return
        try:
            self._library = load_library(Path(f))
        except QuickCmdStoreError as exc:
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        self._path = Path(f)
        self._file_label.setText(self._path.name)
        self._refresh_tree()

    def _on_save_as(self) -> None:
        f, _ = QFileDialog.getSaveFileName(self, "另存为", "quick_commands.yaml", "YAML (*.yaml)")
        if not f:
            return
        try:
            dump_library(self._library, Path(f))
        except QuickCmdStoreError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self._path = Path(f)
        self._file_label.setText(self._path.name)

    def _on_accept(self) -> None:
        """确定：dump_library 原子写回当前 path。失败则不关闭（可重试）."""
        try:
            dump_library(self._library, self._path)
        except QuickCmdStoreError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.accept()
```

> 由于 Step 5.1 已把 `dump_library`/`load_library` 通过顶部 import 引入（`from atprobe.domain.quickcmd import ...`），上面方法体内直接用即可。确认顶部 import 已包含 `dump_library, load_library`——若无则补到现有 import。

- [ ] **Step 5.7: 冒烟检查（对话框完整构造 + 切换表单）**

Run: `python -c "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); from PySide6.QtWidgets import QApplication; app=QApplication([]); from pathlib import Path; from atprobe.domain.quickcmd import builtin_library_path, load_library; from atprobe.gui.widgets.command_library import LibraryManagerDialog; lib=load_library(builtin_library_path()); dlg=LibraryManagerDialog(lib, builtin_library_path()); print('construct OK, items:', dlg.tree.topLevelItemCount()); proj_item=dlg.tree.topLevelItem(0); proj_item.setSelected(True); print('after select project, form children:', dlg._form_host.layout().count())"`
Expected: 输出 `construct OK, items: 2` 和 `after select project, form children:` 一个正数（表单已切换）

- [ ] **Step 5.8: 提交**

```bash
git add src/atprobe/gui/widgets/command_library.py
git commit -m "feat(gui): 命令库管理对话框扩展（左右分栏 + 动态表单 + 增删改 + 文件操作）"
```

---

## Task 6: 主窗口装配 Dock + 信号路由

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py`

- [ ] **Step 6.1: 添加 import**

在 `src/atprobe/gui/mainwindow.py` 顶部 import 区（`from atprobe.gui.tabs.registry ...` 附近）添加：

```python
from atprobe.gui.widgets.command_library import CommandLibraryDock
```

- [ ] **Step 6.2: 在 `__init__` 末尾装配 Dock**

在 `MainWindow.__init__` 中，`self._init_menubar()` 之后、`self.progress.connect(self._on_progress)` 之前，插入：

```python
        self._init_command_dock()
```

- [ ] **Step 6.3: 新增 `_init_command_dock` 方法**

在 `mainwindow.py` 的 `_init_sidebar` 方法之后（选项卡管理之前），新增方法：

```python
    def _init_command_dock(self) -> None:
        """装配命令库停靠面板（主窗口右侧，跨页面常驻）.

        面板双击命令 → send_requested(str) → _on_command_send 路由到手动调试页。
        """
        from PySide6.QtWidgets import QDockWidget

        dock = QDockWidget("命令库", self)
        dock.setObjectName("commandLibraryDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._command_dock = CommandLibraryDock(self)
        dock.setWidget(self._command_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._command_dock.send_requested.connect(self._on_command_send)
```

- [ ] **Step 6.4: 新增 `_on_command_send` 路由方法**

在 `mainwindow.py` 中（视图层共享接口区，如 `send_manual` 附近），新增方法：

```python
    def _on_command_send(self, command: str) -> None:
        """命令库面板双击 → 路由到手动调试页发送。

        找不到手动调试页或端口未连接 → warning 提示。
        """
        widget = self._find_tab("manual_debug")
        if widget is None:
            QMessageBox.warning(self, "提示", "请先打开「手动调试」页")
            return
        # 类型已知：manual_debug 页暴露 current_port() / send_command()
        port = widget.current_port()  # type: ignore[attr-defined]
        is_conn = getattr(self, "is_port_connected", None)
        if callable(is_conn) and not is_conn(port):
            QMessageBox.warning(
                self, "提示", f"端口 {port} 未连接，请先在手动调试页打开端口"
            )
            return
        widget.send_command(command)  # type: ignore[attr-defined]
```

- [ ] **Step 6.5: 更新 docstring 的共享接口说明**

在 `mainwindow.py` 的 `MainWindow` 类 docstring 中（约第 47-53 行），找到 `手动调试：send_manual()...` 那一行，在其下方追加：

```python
                  （手动调试页对外暴露 current_port()/send_command() 供命令库面板路由）
```

- [ ] **Step 6.6: 冒烟检查（主窗口构造 + Dock 存在）**

Run: `python -c "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); from PySide6.QtWidgets import QApplication; app=QApplication([]); from atprobe.gui.mainwindow import MainWindow; w=MainWindow(); print('construct OK'); print('has command dock:', hasattr(w,'_command_dock')); print('dock tree items:', w._command_dock.tree.topLevelItemCount())"`
Expected: 输出 `construct OK` / `has command dock: True` / `dock tree items: 2`

- [ ] **Step 6.7: 提交**

```bash
git add src/atprobe/gui/mainwindow.py
git commit -m "feat(gui): 主窗口装配命令库停靠面板 + 双击发送信号路由"
```

---

## Task 7: 集成测试改写与新增

**Files:**
- Modify: `tests/integration/test_gui.py`

本任务删除被淘汰的旧测试，新增命令库相关测试，并修正保留测试中对已删属性的引用。

- [ ] **Step 7.1: 删除旧测试类 `TestManualDebugQuickCommands`**

在 `tests/integration/test_gui.py` 中，删除整个 `class TestManualDebugQuickCommands:`（含其 `test_add_remove_persist` 和 `test_loads_persisted_on_construct` 两个方法，约第 473-511 行）。这两个测试验证的是被删的 QSettings 快捷指令功能。

- [ ] **Step 7.2: 删除 `TestManualDebugExtras` 类**

删除整个 `class TestManualDebugExtras:` 及其全部方法（`test_multiline_send_and_history`、`test_hex_display`，约第 514-566 行）。其中的历史断言、QSettings quick_commands setup 已失效。

> 注：多行发送和 HEX 显示功能本身保留，会在 Step 7.4 用新测试覆盖。

- [ ] **Step 7.3: 修正 `TestManualDebugPortControl` 与 `test_rx_streams_via_subscription` 中的失效引用**

在 `tests/integration/test_gui.py` 中：

1. 在 `TestManualDebugPortControl` 类的每个测试方法开头，删除以下行（若存在）：
   ```python
   QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)
   ```
   共 3 处（`test_open_close_toggle`、`test_send_requires_connection`、`test_rx_streams_via_subscription`）。这些 QSettings key 已不再使用。

2. 检查 `TestManualDebugPortControl` 的 import：`from PySide6.QtCore import QSettings` 若仍被其他保留测试使用则保留；若全文件不再使用 QSettings，可删除该 import（**保守起见保留 import，不删**）。

> 这些测试验证端口开关/发送/RX 订阅，功能仍在，只需去掉失效的 QSettings 初始化。

- [ ] **Step 7.4: 新增 `TestManualDebugStripped` 测试类（替换被删测试的功能覆盖）**

在 `tests/integration/test_gui.py` **末尾**追加：

```python


class TestManualDebugStripped:
    """命令库改造后：历史/旧快捷指令已删，current_port/send_command 可用，
    多行发送与 HEX 显示功能保留。"""

    def test_no_history_no_quick_attrs(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """确认历史下拉与旧快捷指令属性已移除。"""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        assert not hasattr(widget, "history_combo")
        assert not hasattr(widget, "quick_btn_row")
        assert not hasattr(widget, "_add_quick")

    def test_current_port_and_send_command(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """current_port() 返回选中端口；send_command() 发送并 TX 上屏。"""
        import PySide6.QtWidgets as _qw
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        assert widget.current_port() == "COM1"
        widget._toggle_connect()  # noqa: SLF001  打开 COM1
        widget.send_command("AT+CSQ")
        assert main.last_command == ("COM1", "AT+CSQ")
        assert "TX> AT+CSQ" in widget.response_view.toPlainText()

    def test_send_command_requires_connection(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """send_command 端口未连接时不发送。"""
        import PySide6.QtWidgets as _qw
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget.send_command("AT+CSQ")  # 未连接
        assert main.last_command is None

    def test_multiline_send_preserved(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """多行发送功能保留（经 send_edit + _send，非 send_command）。"""
        import PySide6.QtWidgets as _qw
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001
        widget.send_edit.setPlainText("AT\nATI\nAT+CSQ")
        widget._send()  # noqa: SLF001
        assert main.last_command == ("COM1", "AT+CSQ")
        text = widget.response_view.toPlainText()
        assert "TX> AT" in text and "TX> ATI" in text and "TX> AT+CSQ" in text

    def test_hex_display_preserved(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """HEX 显示功能保留。"""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001
        widget.hex_check.setChecked(True)
        main.emit_rx("COM1", b"OK\r\n")
        assert "4F 4B" in widget.response_view.toPlainText()
```

- [ ] **Step 7.5: 新增 `TestCommandLibraryDock` 测试类**

在 `tests/integration/test_gui.py` 末尾追加：

```python


class TestCommandLibraryDock:
    """命令库停靠面板：加载渲染 + 双击发送信号。"""

    def test_loads_and_renders_tree(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """面板从内置示例加载 → 渲染出项目/功能/命令三层。"""
        from atprobe.gui.widgets.command_library import CommandLibraryDock

        dock = CommandLibraryDock(object())  # type: ignore[arg-type]
        # 内置示例含 2 个顶层项目（N58 项目 + 通用）
        assert dock.tree.topLevelItemCount() == 2
        # 第一个项目下应有功能组（叶子为命令）
        first = dock.tree.topLevelItem(0)
        assert first is not None and first.childCount() > 0

    def test_double_click_command_emits_signal(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """双击命令叶子 → emit send_requested(命令字符串)。"""
        from PySide6.QtCore import Qt
        from atprobe.gui.widgets.command_library import CommandLibraryDock

        dock = CommandLibraryDock(object())  # type: ignore[arg-type]
        received: list[str] = []
        dock.send_requested.connect(lambda cmd: received.append(cmd))

        # 找第一个命令叶子并双击
        first_proj = dock.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        first_cmd = first_grp.child(0)
        dock._on_double_click(first_cmd, 0)  # noqa: SLF001
        assert len(received) == 1
        assert received[0] == first_cmd.text(0)

    def test_double_click_project_does_not_emit(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """双击项目/功能节点 → 不 emit 信号。"""
        from atprobe.gui.widgets.command_library import CommandLibraryDock

        dock = CommandLibraryDock(object())  # type: ignore[arg-type]
        received: list[str] = []
        dock.send_requested.connect(lambda cmd: received.append(cmd))

        proj_item = dock.tree.topLevelItem(0)
        dock._on_double_click(proj_item, 0)  # noqa: SLF001
        assert received == []
```

- [ ] **Step 7.6: 新增 `TestMainWindowCommandRouting` 测试类**

在 `tests/integration/test_gui.py` 末尾追加：

```python


class TestMainWindowCommandRouting:
    """主窗口：命令库面板 send_requested → 路由到手动调试页 send_command。"""

    def test_routes_to_manual_debug(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """面板 emit → 手动调试页打开且端口连接 → send_manual 被调用。"""
        import PySide6.QtWidgets as _qw
        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.config import PortConfig
        from atprobe.infra.serial.fakeserial import FakePortManager

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        win = MainWindow()
        win._port_manager = FakePortManager(sleep=lambda s: None)  # noqa: SLF001
        win._port_manager.open(PortConfig(name="COM9"))  # noqa: SLF001

        # 打开手动调试页并选中 COM9
        win.new_tab("manual_debug")
        md_widget = win._find_tab("manual_debug")  # noqa: SLF001
        assert md_widget is not None
        # 选 COM9（FakePortManager 枚举的端口）
        idx = md_widget.port_combo.findData("COM9")
        if idx >= 0:
            md_widget.port_combo.setCurrentIndex(idx)
        md_widget._toggle_connect()  # noqa: SLF001  打开端口

        sent: list[tuple[str, str]] = []
        original = win.send_manual

        def _capture(port: str, command: str) -> bool:
            sent.append((port, command))
            return original(port, command)

        win.send_manual = _capture  # type: ignore[assignment]

        # 触发路由
        win._on_command_send("AT+CSQ")  # noqa: SLF001
        assert sent == [("COM9", "AT+CSQ")]

    def test_no_manual_debug_warns(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """无手动调试页时 emit → warning，不发送。"""
        import PySide6.QtWidgets as _qw
        from atprobe.gui.mainwindow import MainWindow

        warned: list[str] = []

        def _warn(_parent, title, text):  # noqa: ANN001
            warned.append(text)

        monkeypatch.setattr(_qw.QMessageBox, "warning", _warn)
        win = MainWindow()
        win._on_command_send("AT")  # noqa: SLF001
        assert warned and "手动调试" in warned[0]
```

- [ ] **Step 7.7: 运行全部 GUI 集成测试**

Run: `python -m pytest tests/integration/test_gui.py -v`
Expected: PASS（所有测试通过，包括新增的命令库测试和修正后的 manual_debug 测试）

- [ ] **Step 7.8: 提交**

```bash
git add tests/integration/test_gui.py
git commit -m "test(gui): 命令库面板/对话框/路由集成测试 + 修正 manual_debug 旧测试"
```

---

## Task 8: 全量回归 + 文档对齐

**Files:**
- Verify: 全量测试
- Modify: `src/atprobe/gui/tabs/manual_debug.py`（docstring 已在 Task 3 更新）
- Modify: `src/atprobe/gui/mainwindow.py`（docstring 已在 Task 6 更新）

- [ ] **Step 8.1: 运行全量测试**

Run: `python -m pytest tests/ -v`
Expected: PASS（全部通过，无 failure）

如有 failure，逐个排查：
- 若是 `manual_debug` 相关：确认 Task 3 删除是否干净（无残留 `history_combo`/`_quick_commands` 引用）
- 若是命令库相关：确认 Task 1-6 实现完整（特别是 Task 5 扩展后顶部 import 是否含 `dump_library, load_library`、对话框表单方法是否齐全）

- [ ] **Step 8.2: 运行 lint（项目用 ruff + mypy）**

Run: `ruff check src/atprobe/domain/quickcmd/ src/atprobe/gui/widgets/ src/atprobe/gui/tabs/manual_debug.py src/atprobe/gui/mainwindow.py tests/unit/test_quickcmd_models.py tests/unit/test_quickcmd_store.py tests/integration/test_gui.py`
Expected: 无错误（若有未用 import，删除）

Run: `mypy src/atprobe/domain/quickcmd/ src/atprobe/gui/widgets/command_library.py`
Expected: 无类型错误（`# type: ignore[attr-defined]` 已标注 Qt 跨类型调用处）

- [ ] **Step 8.3: 启动 GUI 手动验收（真实交互，非 offscreen）**

Run: `python -c "import os; from PySide6.QtWidgets import QApplication; from atprobe.gui.mainwindow import MainWindow; app=QApplication([]); w=MainWindow(); w.show(); app.exec()"`

手动验收清单（逐项确认）：
- [ ] 主窗口右侧出现「命令库」停靠面板，含「管理」「刷新」按钮 + 树
- [ ] 树展开显示「N58 项目」（网络/SIM 卡）+「通用」（基础）三层
- [ ] 点击「管理」打开对话框，左侧树 + 右侧表单
- [ ] 对话框选中项目 → 右侧显示重命名/删除/+功能组
- [ ] 对话框选中功能组 → 右侧显示重命名/删除/+命令
- [ ] 对话框新增一条命令 → 确定 → 树刷新出现新命令
- [ ] 对话框重名新增 → 弹 warning、不生效
- [ ] 回主界面，双击命令叶子 → 发送到手动调试页（需先打开手动调试页并连接端口）
- [ ] 未打开手动调试页时双击 → 弹"请先打开手动调试页"
- [ ] 手动调试页**无**历史下拉、**无**旧快捷指令卡片
- [ ] 手动调试页端口/发送/响应三卡片正常

- [ ] **Step 8.4: 提交（如有 lint/文档微调）**

```bash
git add -A
git commit -m "chore: 全量回归通过 + lint/文档对齐" --allow-empty
```

（若 Step 8.1-8.2 无改动，此步可跳过；`--allow-empty` 仅在需要标记回归节点时用）

---

## Self-Review（计划自检）

### 1. Spec 覆盖检查
| Spec 要求 | 覆盖任务 |
|-----------|---------|
| 移除历史命令记录 | Task 3.1, 3.2 |
| 三层树数据模型（项目→功能→命令） | Task 1 |
| YAML 配置文件存储 | Task 2 |
| 内置示例路径 + 可切换 | Task 2.3（示例文件）+ Task 5（管理对话框加载/另存为）|
| 主窗口右侧停靠面板 | Task 4（面板）+ Task 6（装配）|
| 双击直接发送 | Task 4.2（信号）+ Task 6.4（路由）|
| 纯命令字符串（无额外属性） | Task 1（模型叶子是 str）|
| 独立命令库管理对话框 | Task 5 |
| 绑定手动调试页端口 | Task 6.4（`_on_command_send` 查手动调试页）|
| 测试三层覆盖 | Task 1.1, 2.1（单测）+ Task 7（集成测试）|
| 不自动迁移旧 QSettings 数据 | Task 3（不读旧 key）+ Task 2.3（示例提供等价默认）|
| 原子写 | Task 2.4（`dump_library` os.replace）|
| 文档对齐 | Task 3.5, 6.5 |

✅ 全覆盖。

### 2. 占位符扫描
- Task 4/5 不含占位代码：Task 4 给出完整可用的面板 + 对话框骨架（`refresh_tree` 直接是正确版本），Task 5 通过方法替换逐步扩展，每步都是完整代码 ✓
- 无 "TBD"/"TODO"/"实现略"/"add appropriate" 等 ✓

### 3. 类型/方法签名一致性
- `current_port() -> str`：Task 3.3 定义，Task 6.4 调用 ✓
- `send_command(command: str) -> None`：Task 3.4 定义，Task 6.4 调用，Task 7.4 测试 ✓
- `send_requested = Signal(str)`：Task 4.2 定义，Task 6.3 连接，Task 7.5 测试 ✓
- `CommandLibraryDock(main_window, parent=None)`：Task 4.2 构造签名，Task 6.3 调用 `CommandLibraryDock(self)` ✓
- `LibraryManagerDialog(library, path, parent)`：Task 4.2 骨架定义构造签名，Task 5 扩展内部方法（构造签名不变），Task 4.2 `_open_manager` 调用 `LibraryManagerDialog(self._library, self._path, self)` ✓
- `current_path() -> Path`：Task 4.2 骨架定义，Task 4.2 `_open_manager` 调用 `dlg.current_path()`，Task 5 不改此方法 ✓
- `_find_tab("manual_debug")`：Task 6.4 调用，mainwindow.py 已有此方法 ✓
- `_NODE_ROLE` / node data：Task 4.2 面板用字符串（`"command:项目:功能:命令"`，只需 split 区分命令叶子），Task 5.3 对话框用元组（`("command", proj, grp, cmd)`，结构化访问）—— **两套独立解析、互不干扰**（面板树和对话框树是两个独立的 QTreeWidget）✓
- Task 5 顶部 import 需补 `dump_library, load_library`：Task 5.6 的 `_on_load_file`/`_on_save_as`/`_on_accept` 直接用这两个名字（非局部 import），Step 5.6 末尾已明确提示补 import ✓

✅ 一致。
