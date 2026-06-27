# 手动调试界面优化：命令库（设计文档）

- **日期**：2026-06-27
- **分支**：fix/monitor-persistent-subscribe
- **主题**：优化手动调试界面——移除历史命令记录，把扁平快捷指令升级为项目→功能→命令三层命令库
- **方案**：方案 B（domain 分层 + GUI 组件分离）

## 1. 目标与范围

### 目标
1. **移除历史命令记录功能**：删除手动调试页的历史命令下拉（`history_combo`）及相关持久化。
2. **升级快捷指令为命令库**：把扁平列表升级为**项目→功能→命令**三层树，配置存于工作目录 YAML 文件。
3. **主窗口右侧停靠面板**：跨页面常驻的命令库面板，双击命令叶子直接发送到手动调试页当前连接端口。
4. **独立命令库管理对话框**：集中增删改项目/功能/命令。

### 不在范围内（YAGNI）
- 不自动迁移旧 QSettings 扁平快捷指令数据（无法可靠映射三层结构）。
- 不为命令建模额外属性（结束符、备注、HEX 标志等）——命令是纯字符串。
- 不引入命令的拖拽排序/跨层移动（删除+新增即可达到等价效果）。

### 关键决策（来自澄清问答）
| 决策项 | 选择 |
|--------|------|
| 树层级结构 | 项目→功能→命令（三层） |
| 配置存储位置/格式 | YAML 文件（项目工作目录） |
| 加载方式 | 内置示例路径 `examples/quick_commands.yaml` + 可在管理对话框切换 |
| 侧边栏形态 | 主窗口右侧独立停靠面板（QDockWidget） |
| 双击行为 | 双击命令叶子直接发送 |
| 命令属性 | 纯命令字符串 |
| 子窗口形态 | 独立"命令库管理"对话框（集中增删改） |
| 发送目标端口 | 绑定手动调试页当前端口 |

## 2. 架构与模块划分

### 新增模块
```
src/atprobe/domain/quickcmd/
├── __init__.py
├── models.py      # 数据模型：CommandProject/Group/Library（纯 dataclass，可独立单测）
└── store.py       # YAML 读写：load_library/dump_library + 校验/异常

src/atprobe/gui/widgets/
├── __init__.py
└── command_library.py   # CommandLibraryDock（停靠面板）+ LibraryManagerDialog（管理对话框）
```

### 文件改动清单
- **新增**：5 个源文件（domain 2 + widgets 1 + 两个 `__init__.py`）+ 1 个示例 YAML
- **修改**：`gui/mainwindow.py`（装配 Dock + 信号路由）、`gui/tabs/manual_debug.py`（删减 + 暴露方法）
- **测试**：`tests/unit/test_quickcmd_models.py`、`tests/unit/test_quickcmd_store.py`、`tests/integration/test_gui.py`（新增 + 改写）

### 模块职责（单一职责、可独立测试）
| 模块 | 职责 | 依赖 |
|------|------|------|
| `domain/quickcmd/models.py` | 纯数据模型 dataclass + 树形增删改方法 + 重名校验 | 无（纯 Python） |
| `domain/quickcmd/store.py` | YAML ↔ Library 序列化、文件 IO、解析异常 | models、`yaml` |
| `gui/widgets/command_library.py` | 停靠面板（树渲染 + 双击发送）+ 管理对话框（表单增删改） | models、store、Qt |
| `gui/mainwindow.py`（改） | 装配右侧 DockWidget，面板双击 → 路由到手动调试页发送 | command_library、manual_debug |
| `gui/tabs/manual_debug.py`（改） | 删历史命令卡片、删旧快捷指令卡片；暴露 `current_port()`/`send_command()` | 不依赖新模块（解耦） |

### 关键解耦点
- **命令库面板不直接知道手动调试页**：面板双击只 `emit` 一个 `send_requested(str)` 信号，由 `MainWindow` 连接到手动调试页的发送方法。面板可独立单测，避免循环依赖。
- **手动调试页不依赖命令库**：它只暴露 `current_port()` 和 `send_command(cmd)` 两个方法，主窗口做胶水。

## 3. 数据模型（domain/quickcmd/models.py）

纯 dataclass，无 Qt 依赖。

```python
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

@dataclass
class CommandLibrary:
    """命令库（整棵树根）—— 含若干项目。"""
    projects: list[CommandProject] = field(default_factory=list)

    @classmethod
    def empty(cls) -> CommandLibrary:
        return cls()

    # —— 树形增删改（带重名校验，抛 ValueError）——
    def add_project(self, name: str) -> CommandProject: ...
    def remove_project(self, name: str) -> None: ...
    def rename_project(self, old: str, new: str) -> None: ...
    def add_group(self, project: str, name: str) -> CommandGroup: ...
    def remove_group(self, project: str, name: str) -> None: ...
    def add_command(self, project: str, group: str, command: str) -> None: ...
    def remove_command(self, project: str, group: str, command: str) -> None: ...
    def find_project(self, name: str) -> CommandProject | None: ...
    def find_group(self, project: str, group: str) -> CommandGroup | None: ...
```

### 设计要点
1. **三级结构与 YAML 一一对应**：`CommandLibrary.projects[].groups[].commands[]` 直接映射嵌套 YAML，序列化零转换。
2. **重名校验集中在此层**：`add_project`/`add_group`/`add_command` 检测同层重名即抛 `ValueError`，UI 层捕获后弹提示。命令字符串本身允许重复（不同功能组下可能有相同 AT 指令），重名只针对项目名/功能组名。
3. **命令是纯字符串，无嵌套对象**：叶子层直接存 `str`，不包 dataclass，避免过度建模。
4. **`empty()` 工厂方法**：供 store.py 在文件缺失时构造空库，UI 层无库存空树也能正常渲染。
5. **无 Qt 依赖**：纯 Python dataclass，可在 `tests/unit/` 独立单测，无需 Qt offscreen 环境。

### 校验规则（明确化）
| 操作 | 规则 |
|------|------|
| 新增项目 | 项目名非空且全局唯一，否则 `ValueError` |
| 新增功能组 | 同项目下功能组名唯一 |
| 新增命令 | 命令字符串非空；同功能组下允许重复（不去重） |
| 重命名 | 目标名与同层其他节点重名则 `ValueError`；目标名等于自身原名则幂等成功（实现时排除自身后再判重）；空名 `ValueError` |
| 删除 | 不存在则静默（幂等），不抛错 |

## 4. YAML 存储层（domain/quickcmd/store.py）

### 公开接口
```python
from pathlib import Path
from atprobe.domain.quickcmd.models import CommandLibrary

class QuickCmdStoreError(Exception):
    """命令库文件读写/解析错误的基类（对齐 EnvConfigError 风格）。"""

def load_library(path: Path) -> CommandLibrary:
    """从 YAML 文件加载命令库。文件缺失 → 返回空库（不抛错，幂等）。
    格式非法 → 抛 QuickCmdStoreError（含原因）。"""

def dump_library(library: CommandLibrary, path: Path) -> None:
    """把命令库写回 YAML 文件（原子写：先写临时文件再 os.replace，避免中途崩溃损坏）。"""

def default_library() -> CommandLibrary:
    """返回出厂默认命令库（迁移现有 _DEFAULT_QUICK_COMMANDS 五条指令，
    归入「通用/基础」组），供首次加载无文件时回落。"""

def builtin_library_path() -> Path:
    """返回内置示例文件的绝对路径 examples/quick_commands.yaml（项目根下）。"""
```

### YAML 结构
```yaml
# examples/quick_commands.yaml
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

### 设计要点
1. **容错加载（幂等缺失）**：`load_library` 文件不存在时返回 `empty()` 而非抛错——与 `envconfig` 回退内置示例策略一致。
2. **原子写**：`dump_library` 先写 `path.with_suffix('.yaml.tmp')` 再 `os.replace` 覆盖原文件。Windows 上 `os.replace` 是原子操作，避免管理对话框保存中途异常导致原配置损坏。
3. **解析校验**：YAML 解析后做结构校验——缺 `projects` 键视作空库；某项缺 `name`/`groups`/`commands` 抛 `QuickCmdStoreError` 并指出位置。`commands` 元素强制转 `str`（兼容用户手写成整数等）。
4. **默认库与内置示例分离**：`default_library()` 是内存对象（程序兜底），`builtin_library_path()` 指向随项目分发的 `examples/quick_commands.yaml`（实际加载源）。

### 加载优先级
```
1. MainWindow 启动 → 调 builtin_library_path() 得 examples/quick_commands.yaml
2. load_library(path)：文件存在则解析；缺失则用 default_library() 内存兜底
3. 管理对话框"加载文件/另存为" → 重新 load_library(用户选的路径)
4. 所有增删改 → 写回当前 path（dump_library 原子写）
```

## 5. GUI 组件（gui/widgets/command_library.py）

### 5.1 命令库停靠面板 `CommandLibraryDock`

主窗口右侧 `QDockWidget`，跨页面常驻，用 `QTreeWidget` 渲染三层树（复用 `case_execute` 的树模式）。

```python
class CommandLibraryDock(QDockWidget):
    """命令库停靠面板（主窗口右侧，跨页面常驻）。
    双击命令叶子 → emit send_requested(command: str)，由 MainWindow 路由到手动调试页。
    """
    send_requested = Signal(str)   # 唯一对外出口（解耦：面板不认识手动调试页）

    def __init__(self, main_window): ...
    def reload_library(self): ...          # 从当前 path 重新加载并重建树
    def refresh_tree(self): ...            # 按 self._library 重建 QTreeWidget
    # 顶部工具栏：[管理] [刷新] [当前文件名]
    # 树：双击叶子 → _on_double_click → emit send_requested(cmd)
    # 树：双击项目/功能节点 → 展开/折叠（默认行为，不发送）
```

**树渲染规则：**
- 顶层节点 = 项目（📁 图标），二级 = 功能组（📂），叶子 = 命令（📄，显示命令字符串）
- 不用复选框（命令库是"选择发送"语义，不是"多选执行"语义）
- 叶子节点 tooltip 显示完整命令；选中模式 `SingleSelection`
- 空库时树显示提示文本"（空，点击「管理」添加命令）"

**双击行为：**
| 节点类型 | 双击 |
|---------|------|
| 命令叶子 | `emit send_requested(command)`（唯一发送出口）|
| 项目/功能节点 | 展开/折叠（Qt 默认，不发送）|

### 5.2 命令库管理对话框 `LibraryManagerDialog`

模态 `QDialog`，集中增删改，关闭后通知面板刷新。

```python
class LibraryManagerDialog(QDialog):
    """命令库管理对话框（模态）：左侧树 + 右侧表单，集中增删改项目/功能/命令。
    确定 → dump_library 写回当前 path；取消 → 丢弃改动。
    """
    def __init__(self, parent, library: CommandLibrary, path: Path): ...
    # 顶部：[加载文件...] [另存为...] [文件名显示]
    # 左侧：QTreeWidget（同面板树结构，可选中任意层级节点作为"当前编辑目标"）
    # 右侧表单：根据选中节点类型动态切换
    #   - 选中项目：[项目名] [重命名] [删除项目] [+ 功能组]
    #   - 选中功能组：[功能名] [重命名] [删除功能] [+ 命令]
    #   - 选中命令：[命令内容] [修改] [删除命令]
    #   - 未选中/根：[+ 项目]
    # 底部：[确定(保存)] [取消]
```

**对话框布局（左右分栏）：**
```
┌─命令库管理─────────────────────────────────────┐
│ [加载文件…] [另存为…]  当前: examples/quick_...yaml│
├──────────────────────┬──────────────────────────┤
│ 📁 N58 项目          │ 当前选中：N58 项目 / 网络  │
│  📂 网络      ←选中   │ ─────────────────────── │
│   AT+CSQ             │ [+ 功能组]  [+ 命令]      │
│   AT+CEREG?          │ 功能名: [网络       ]     │
│  📂 SIM 卡           │ [重命名] [删除功能]       │
│ 📁 通用              │                          │
│  📂 基础             │ （选中命令时显示命令编辑）│
├──────────────────────┴──────────────────────────┤
│                              [确定(保存)] [取消] │
└──────────────────────────────────────────────────┘
```

**操作流程：**
- 树左侧单击选中节点 → 右侧表单切换为对应编辑区
- 所有增删改先在内存 `CommandLibrary` 上操作（model 层校验重名）；重名校验失败 → `QMessageBox.warning`，操作不生效
- **确定**：`dump_library(self._library, self._path)` 原子写回，`accept()`
- **取消**：`reject()`，内存改动丢弃（下次重新 load）
- **加载文件/另存为**：`QFileDialog` 选路径，load/dump 后更新树与 `self._path`

### 5.3 与现有代码的对接

**手动调试页（manual_debug.py）改造：**
- **删除**：`history_combo`、`_add_history`、`_load_history`、`_on_history_pick`、`_HISTORY_KEY`、`_MAX_HISTORY` 等全部历史相关代码
- **删除**：`_build_quick_group`、`_populate_quick_buttons`、`_add_quick`、`_remove_quick`、`_reset_quick`、`_show_quick_menu`、`_load_quick_commands`、`_save_quick_commands`、`_SETTINGS_KEY`、`_DEFAULT_QUICK_COMMANDS`、`_MAX_QUICK_COMMANDS` 等全部旧快捷指令相关代码
- **暴露方法**：新增 `current_port() -> str`（返回当前选中端口）、`send_command(cmd: str) -> None`（独立实现单条命令发送：TX 上屏 + 调 `send_manual`；不读 `send_edit`，与处理多行的 `_send` 分离，避免引入"填入发送框"副作用）
- **保留**：端口卡片、发送卡片（发送框+结束符+HEX）、响应卡片——这些不受影响
- **说明**：`send_command` 用发送区当前的全局结束符（`self._terminator`）与连接校验逻辑，但不修改发送框内容；侧边栏双击发送的 TX 记录同样上屏到响应区

**主窗口（mainwindow.py）改造：**
- `__init__` 末尾新增 `_init_command_dock()`：创建 `CommandLibraryDock`，`addDockWidget(RightDockWidgetArea, dock)`
- 连接信号：`dock.send_requested.connect(self._on_command_send)`
- 新增 `_on_command_send(cmd)`：查手动调试页 → 取 `current_port()` → 校验连接 → `manual_widget.send_command(cmd)`；未连接/页面不存在则 `QMessageBox.warning`

### 5.4 错误处理
| 场景 | 处理 |
|------|------|
| 双击发送但无手动调试页 | `QMessageBox.warning("请先打开「手动调试」页")` |
| 双击发送但端口未连接 | `QMessageBox.warning("端口 X 未连接，请先在手动调试页打开端口")` |
| 管理对话框重名冲突 | `QMessageBox.warning("项目/功能名已存在")`，操作回滚 |
| 管理对话框保存失败 | `QMessageBox.critical` 显示 `QuickCmdStoreError`，对话框不关闭（可重试） |
| 加载文件解析失败 | `QMessageBox.critical`，面板树保持上一次状态 |

## 6. 测试策略

### 单元测试（无 Qt，最快）

`tests/unit/test_quickcmd_models.py`
- 增删改项目/功能/命令正确性
- 重名校验抛 `ValueError`（项目名全局唯一、功能组名同项目唯一）
- 命令允许重复（同功能组下）、删除幂等不抛错
- `find_project`/`find_group` 命中/未命中

`tests/unit/test_quickcmd_store.py`
- `load_library` 正常解析嵌套 YAML → `CommandLibrary`
- `load_library` 文件缺失 → 返回空库（不抛错）
- `load_library` 格式非法 → 抛 `QuickCmdStoreError`
- `dump_library` → 重新 `load` 往返一致（round-trip）
- `default_library()` 含迁移的 5 条指令、`builtin_library_path()` 指向 examples

### 集成测试（Qt offscreen，对齐 `TestManualDebugQuickCommands` 风格）

`tests/integration/test_gui.py` 新增 `TestCommandLibraryDock`
- 面板从内置示例加载 → 树渲染出项目/功能/命令三层
- 双击命令叶子 → `send_requested` 信号 emit 正确命令字符串
- 双击项目/功能节点 → 不 emit 信号（只展开折叠）
- `reload_library` 后树刷新

新增 `TestLibraryManagerDialog`
- 选中项目 → 右侧表单显示"重命名/删除/+功能组"
- 新增命令 → 写入内存 `CommandLibrary`、树更新
- 重名新增 → `ValueError` 被捕获、弹 warning、操作回滚
- 确定 → `dump_library` 写到 tmp_path、文件往返一致

新增 `TestManualDebugStripped`（替代被删的 `TestManualDebugQuickCommands`、`TestManualDebugExtras` 中的历史/快捷部分）
- 构造 `ManualDebugWidget`：确认**无** `history_combo` 属性、**无** `quick_btn_row`/`_add_quick` 方法
- 确认 `current_port()` / `send_command(cmd)` 方法存在且可用
- 保留的 RX 流式订阅、HEX 显示、多行发送测试（功能保留，测试改用 `send_command` 调用）
- 清理：测试中不再 set/清 `manual_debug/quick_commands`、`manual_debug/history` QSettings

新增 `TestMainWindowCommandRouting`（主窗口胶水）
- 面板 `send_requested` emit → 路由到手动调试页 → `send_manual` 被调用（用 `_FakeMain` 风格替身验证）
- 手动调试页未打开时 emit → warning（弹窗打桩）

## 7. 内置示例文件 `examples/quick_commands.yaml`

```yaml
# ATProbe 命令库示例（项目→功能→命令三层）
# 用途：手动调试页命令库默认加载源；可手动编辑、git 跟踪、团队共享。
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

内容 = 迁移现有 5 条默认指令（AT/AT+CSQ/AT+CEREG?/AT+CPIN?/AT+CGDCONT?）+ 补 ATI，归入两个项目两个功能组，作为开箱可用的示例。

## 8. 兼容性与迁移

### QSettings 残留数据处理
- 旧版在 QSettings 写过 `manual_debug/quick_commands` 和 `manual_debug/history`。新代码**完全不读这两个 key**，残留值无害（自然废弃，不主动清理用户注册表以免误伤其他配置）。
- 用户的自定义快捷指令**不自动迁移**（旧的是扁平列表，无项目/功能归属信息，无法可靠映射到三层结构）。由内置示例文件 `examples/quick_commands.yaml` 提供等价默认值，用户在管理对话框手动重组。

### 既有测试清理
- `TestManualDebugQuickCommands`（2 个测试）和 `TestManualDebugExtras.test_multiline_send_and_history` 中历史断言 → 删除/改写
- `TestManualDebugPortControl`、`test_rx_streams_via_subscription`、`test_hex_display` → 保留（功能仍在），但去掉其中 `QSettings("manual_debug/quick_commands", None)` 的 setup/teardown（属性已不存在）

### 文档对齐
- `manual_debug.py` 模块 docstring 更新：移除"历史指令""自定义快捷指令"描述，新增"命令库停靠面板（右侧）"描述
- `mainwindow.py` docstring 的共享接口列表新增 `current_port()`/`send_command()`（手动调试页暴露）

## 9. 实现顺序

1. `domain/quickcmd/models.py` + 单测（无依赖，先立数据根基）
2. `domain/quickcmd/store.py` + 单测 + `examples/quick_commands.yaml`
3. `gui/widgets/command_library.py`（面板 + 对话框）+ 集成测试
4. `manual_debug.py` 改造（删减 + 暴露方法）+ 测试改写
5. `mainwindow.py` 装配 Dock + 信号路由 + 测试
6. 全量回归（`pytest tests/`）+ 文档对齐
