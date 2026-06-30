"""命令库侧栏面板 + 管理对话框（项目→功能→命令三层树）.

面板作为普通 QWidget 嵌入手动调试页左侧（QSplitter），单击命令叶子经
send_requested(str) 信号通知宿主页发送。增删改经两种入口：
  - 侧栏面板（发送界面）：右键菜单（修改/删除/新增下级）+ 双击修改，改动即时落盘。
  - 管理对话框（添加界面）：左树双击修改 + 右键增删，确定时统一落盘。

交互统一：节点内嵌「＋」按钮（项目节点→加功能组、功能组节点→加命令），
无需预选；双击任意节点改、右键删/增。删除项目/功能组（有子节点）弹确认，
删命令直接执行。

解耦：面板不认识手动调试页，只 emit send_requested；宿主页连接该信号发送。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from atprobe.domain.quickcmd import (
    CommandLibrary,
    QuickCmdStoreError,
    builtin_library_path,
    dump_library,
    load_library,
)
from atprobe.gui.icons import make_icon
from atprobe.gui.theme import get_tokens

# 树节点角色：data 存元组 ("project",name) / ("group",proj,grp) / ("command",proj,grp,cmd)
_NODE_ROLE = Qt.ItemDataRole.UserRole


# ---------------------------------------------------------------------------
# 共享层级解析辅助（面板与对话框复用）
# ---------------------------------------------------------------------------
def _parse_node(raw: object) -> tuple[str, ...] | None:
    """解析 _NODE_ROLE 数据为元组；非元组返回 None（如空树 hint 节点）."""
    return raw if isinstance(raw, tuple) else None


def _level(node: tuple[str, ...] | None) -> str:
    """节点层级：'project' | 'group' | 'command' | ''（None/空）."""
    return node[0] if node else ""


def _node_from_item(item: QTreeWidgetItem | None) -> tuple[str, ...] | None:
    """从 QTreeWidgetItem 取出节点元组（None = item 为空/无效/hint 节点）."""
    if item is None:
        return None
    return _parse_node(item.data(0, _NODE_ROLE))


# ---------------------------------------------------------------------------
# 节点层级标签（元组首项）+ 右键菜单文案常量（集中定义，避免散落字符串字面量）
# ---------------------------------------------------------------------------
_LEVEL_PROJECT = "project"
_LEVEL_GROUP = "group"
_LEVEL_COMMAND = "command"

# 右键菜单 action 文案（_build_node_menu 与测试断言共用，改文案只动这里）
_MENU_RENAME = "重命名"
_MENU_EDIT = "修改"
_MENU_ADD_GROUP = "新增功能组"
_MENU_ADD_COMMAND = "新增命令"
_MENU_DEL_PROJECT = "删除项目"
_MENU_DEL_GROUP = "删除功能组"
_MENU_DEL_COMMAND = "删除命令"
_MENU_ADD_PROJECT = "新增项目"


class _LibraryTreeEditor:
    """命令库树的共享增删改控制器（面板与对话框的公共基类）.

    聚合 13 个操作方法（右键菜单/双击触发的 add/rename/edit/delete）与菜单构造，
    消除面板与对话框之间的逐字重复。子类只需提供：

      - ``self._library``: CommandLibrary（面板=持久态；对话框=工作副本）
      - ``self.tree``: QTreeWidget
      - ``self._tokens``: 主题色 dict
      - ``_commit_and_refresh(select)``: 唯一持久化钩子。面板即时 dump_library 落盘，
        对话框仅刷新内存副本（确定时统一落盘）。select 是改动后建议选中的节点元组
        （面板忽略它全量重渲染；对话框滚动定位到该节点）。

    这样持久化策略差异收口在唯一一个方法里，新增操作只写一份。
    """

    # 子类约定字段（仅类型标注，由子类 __init__ 赋值；不在此初始化避免覆盖）
    _library: CommandLibrary
    tree: QTreeWidget
    _tokens: dict[str, str]

    # ------------------------------------------------------------------
    # 持久化钩子（子类必须实现）
    # ------------------------------------------------------------------
    def _commit_and_refresh(self, select: tuple[str, ...] | None = None) -> None:
        """改动后提交并刷新（持久化策略的唯一收口点）.

        Args:
            select: 建议重建后选中并滚动到的节点元组；None 表示不主动选中。
                面板忽略此参数（全量重渲染，无定位需求）；对话框据此定位。
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 双击 + 右键入口
    # ------------------------------------------------------------------
    def _on_double_click(self, item: QTreeWidgetItem) -> None:
        """双击任意节点 → 弹输入框就地修改（项目/功能组/命令）."""
        node = _node_from_item(item)
        lvl = _level(node)
        if lvl == _LEVEL_PROJECT:
            assert node is not None
            self._rename_project(node[1])
        elif lvl == _LEVEL_GROUP:
            assert node is not None
            self._rename_group(node[1], node[2])
        elif lvl == _LEVEL_COMMAND:
            assert node is not None
            self._edit_command(node[1], node[2], node[3])

    def _on_context_menu(self, pos: QPoint) -> None:
        """右键菜单：按节点层级提供 重命名/删除/新增下级."""
        item = self.tree.itemAt(pos)
        menu = self._build_context_menu(item)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_context_menu(self, item: QTreeWidgetItem | None) -> QMenu:
        """构造右键菜单（不 exec），供 _on_context_menu 与测试复用."""
        return _build_node_menu(
            QMenu(self._as_widget()), _node_from_item(item), self._tokens, self
        )

    def _collect_menu_texts(self, item: QTreeWidgetItem) -> list[str]:
        """测试辅助：返回给定节点的右键菜单 action 文本列表."""
        return [a.text() for a in self._build_context_menu(item).actions()]

    def _as_widget(self) -> QWidget:
        """取自身作为 QWidget 父对象（菜单/对话框的 parent）."""
        return self  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 增删改操作（内存 model 改动 + 经 _commit_and_refresh 落盘/刷新）
    # ------------------------------------------------------------------
    def _add_project_interactive(self) -> None:
        name, ok = QInputDialog.getText(self._as_widget(), "新增项目", "项目名:")
        if not (ok and name.strip()):
            return
        name = name.strip()
        try:
            self._library.add_project(name)
        except ValueError as exc:
            QMessageBox.warning(self._as_widget(), "无法新增", str(exc))
            return
        self._commit_and_refresh(select=(_LEVEL_PROJECT, name))

    def _add_group_interactive(self, proj_name: str) -> None:
        """直接在某项目下新增功能组（由项目节点的内嵌＋按钮调用）."""
        name, ok = QInputDialog.getText(
            self._as_widget(), "新增功能组", f"{proj_name} 下的功能组名:"
        )
        if not (ok and name.strip()):
            return
        name = name.strip()
        try:
            self._library.add_group(proj_name, name)
        except ValueError as exc:
            QMessageBox.warning(self._as_widget(), "无法新增", str(exc))
            return
        self._commit_and_refresh(select=(_LEVEL_GROUP, proj_name, name))

    def _add_command_interactive(self, proj_name: str, grp_name: str) -> None:
        """直接在某功能组下新增命令（由功能组节点的内嵌＋按钮调用）."""
        cmd, ok = QInputDialog.getText(
            self._as_widget(), "新增命令", f"{proj_name}/{grp_name} 的 AT 指令:"
        )
        if not (ok and cmd.strip()):
            return
        cmd = cmd.strip()
        try:
            self._library.add_command(proj_name, grp_name, cmd)
        except ValueError as exc:
            QMessageBox.warning(self._as_widget(), "无法新增", str(exc))
            return
        self._commit_and_refresh(select=(_LEVEL_COMMAND, proj_name, grp_name, cmd))

    def _rename_project(self, old: str) -> None:
        new, ok = QInputDialog.getText(
            self._as_widget(), "重命名项目", "新项目名:", text=old
        )
        if not (ok and new.strip() and new.strip() != old):
            return
        new = new.strip()
        try:
            self._library.rename_project(old, new)
        except ValueError as exc:
            QMessageBox.warning(self._as_widget(), "无法重命名", str(exc))
            return
        self._commit_and_refresh(select=(_LEVEL_PROJECT, new))

    def _rename_group(self, proj: str, old: str) -> None:
        """重命名功能组：add 新组迁移命令 + remove 旧组（model 无原生 rename_group）."""
        new, ok = QInputDialog.getText(
            self._as_widget(), "重命名功能组", "新功能组名:", text=old
        )
        if not (ok and new.strip() and new.strip() != old):
            return
        new = new.strip()
        old_grp = self._library.find_group(proj, old)
        cmds = list(old_grp.commands) if old_grp is not None else []
        try:
            self._library.add_group(proj, new)
        except ValueError as exc:
            QMessageBox.warning(self._as_widget(), "无法重命名", str(exc))
            return
        for c in cmds:
            self._library.add_command(proj, new, c)
        self._library.remove_group(proj, old)
        self._commit_and_refresh(select=(_LEVEL_GROUP, proj, new))

    def _edit_command(self, proj: str, grp: str, old: str) -> None:
        new, ok = QInputDialog.getText(self._as_widget(), "修改命令", "AT 指令:", text=old)
        if not (ok and new.strip() and new.strip() != old):
            return  # 空或未改动 → 无操作（避免 add+remove 重排序）
        new = new.strip()
        try:
            self._library.add_command(proj, grp, new)
        except ValueError as exc:
            QMessageBox.warning(self._as_widget(), "无法修改", str(exc))
            return
        self._library.remove_command(proj, grp, old)
        self._commit_and_refresh(select=(_LEVEL_COMMAND, proj, grp, new))

    def _delete_project(self, name: str) -> None:
        if not _confirm_delete(self._as_widget(), "项目", name):
            return
        self._library.remove_project(name)
        self._commit_and_refresh()

    def _delete_group(self, proj: str, name: str) -> None:
        if not _confirm_delete(self._as_widget(), "功能组", name):
            return
        self._library.remove_group(proj, name)
        self._commit_and_refresh()

    def _delete_command(self, proj: str, grp: str, cmd: str) -> None:
        self._library.remove_command(proj, grp, cmd)
        self._commit_and_refresh()


class CommandLibraryPanel(QWidget, _LibraryTreeEditor):
    """命令库侧栏面板（嵌入手动调试页左侧）。

    唯一对外出口：send_requested(str) —— 单击命令叶子时 emit，宿主页连接后发送。
    增删改经右键菜单/双击就地完成，改动即时 dump_library 落盘（面板是持久态，不像
    对话框用工作副本）。
    """

    send_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = get_tokens(dark=False)
        self._path: Path = builtin_library_path()
        self._library: CommandLibrary = CommandLibrary.empty()
        self._init_ui()
        self.reload_library()

    # ------------------------------------------------------------------
    # UI 构造
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 顶部工具栏：[管理] [刷新] [文件名]
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.setContentsMargins(4, 4, 4, 0)
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
        self.tree.setHeaderHidden(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree, 1)

    # ------------------------------------------------------------------
    # 加载与渲染
    # ------------------------------------------------------------------
    def reload_library(self) -> None:
        """从当前 path 重新加载命令库并重建树。

        内置示例文件缺失或为空时，回落到内存默认库（store.default_library），
        保证开箱即用而非空树。
        """
        from atprobe.domain.quickcmd import default_library

        try:
            self._library = load_library(self._path)
        except QuickCmdStoreError as exc:
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        # 内置示例文件缺失/为空 → 内存默认库兜底（迁移的 5 条指令）
        if not self._library.projects and self._path == builtin_library_path():
            self._library = default_library()
        self._file_label.setText(self._path.name)
        self.refresh_tree()

    def refresh_tree(self) -> None:
        """按 self._library 重建 QTreeWidget（节点角色统一为元组格式）."""
        self.tree.clear()
        if not self._library.projects:
            hint = QTreeWidgetItem(["（空，点击「管理」或右键添加命令）"])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(hint)
            return
        for proj in self._library.projects:
            pitem = QTreeWidgetItem([proj.name])
            pitem.setData(0, _NODE_ROLE, (_LEVEL_PROJECT, proj.name))
            pitem.setIcon(0, make_icon("report_view", color=self._tokens["accent"]))
            for grp in proj.groups:
                gitem = QTreeWidgetItem([grp.name])
                gitem.setData(0, _NODE_ROLE, (_LEVEL_GROUP, proj.name, grp.name))
                gitem.setIcon(0, make_icon("env_config", color=self._tokens["accent"]))
                for cmd in grp.commands:
                    citem = QTreeWidgetItem([cmd])
                    citem.setData(0, _NODE_ROLE, (_LEVEL_COMMAND, proj.name, grp.name, cmd))
                    citem.setToolTip(0, cmd)
                    gitem.addChild(citem)
                pitem.addChild(gitem)
            self.tree.addTopLevelItem(pitem)
        self.tree.expandAll()

    def _save_library(self) -> None:
        """原子写回 self._path 后刷新树（面板是持久态，改动需即时落盘）."""
        try:
            dump_library(self._library, self._path)
        except QuickCmdStoreError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.refresh_tree()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_click(self, item: QTreeWidgetItem, _column: int) -> None:
        """单击：命令叶子 → emit send_requested；项目/功能节点 → 展开/折叠（默认）."""
        node = _node_from_item(item)
        if _level(node) != _LEVEL_COMMAND:
            return  # 非命令叶子，交给 Qt 默认展开/折叠行为
        assert node is not None
        # command 元组第四项即命令字符串（可含冒号）
        self.send_requested.emit(node[3])

    # ------------------------------------------------------------------
    # 持久化钩子实现（面板策略：即时 dump_library 落盘）
    # ------------------------------------------------------------------
    def _commit_and_refresh(self, select: tuple[str, ...] | None = None) -> None:
        """面板策略：改动即时落盘（select 在面板无定位需求，忽略）."""
        self._save_library()

    # ------------------------------------------------------------------
    # 管理对话框
    # ------------------------------------------------------------------
    def _open_manager(self) -> None:
        """打开命令库管理对话框，关闭后刷新树."""
        dlg = LibraryManagerDialog(self._library, self._path, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._path = dlg.current_path()
            self.reload_library()


class LibraryManagerDialog(QDialog, _LibraryTreeEditor):
    """命令库管理对话框（模态）：单树，双击修改 + 右键增删。

    项目/功能组节点行内嵌「＋」（在其下新增）。编辑改的是内存工作副本
    （_clone_library），取消即丢弃；「确定」时 dump_library 落盘。
    """

    def __init__(
        self, library: CommandLibrary, path: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("命令库管理")
        self.resize(640, 500)
        self._tokens = get_tokens(dark=False)
        # 深拷贝一份工作副本（取消时丢弃改动，不影响外部 library）
        self._library = _clone_library(library)
        self._path = path
        self._init_ui()
        self._refresh_tree()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 顶部工具栏：[＋项目][加载…][另存为…] [文件名]
        # 新增功能组/命令的入口下放到树节点（项目/功能组行内嵌＋），无需预选。
        top = QHBoxLayout()
        top.setSpacing(6)
        self._add_project_btn = QPushButton("＋项目")
        self._add_project_btn.clicked.connect(self._add_project_interactive)
        top.addWidget(self._add_project_btn)
        top.addSpacing(12)
        load_btn = QPushButton("加载…")
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

        # 单树（已去掉右侧表单面板，全靠双击 + 右键）
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("项目 / 功能 / 命令（双击修改 · 右键增删）")
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        outer.addWidget(self.tree, 1)

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

    # ------------------------------------------------------------------
    # 树渲染（带 node role，供双击/右键定位层级）
    # ------------------------------------------------------------------
    def _refresh_tree(self, *, select: tuple[str, ...] | None = None) -> None:
        """按 self._library 重建 QTreeWidget。

        Args:
            select: 重建后要选中并滚动到视野内的节点元组（与 _NODE_ROLE 存储格式一致），
                None 表示不主动选中。用于「添加后保持位置」——新增项被选中并居中滚动，
                避免 expandAll() 让滚动条跳回顶端、指令多时无法连续添加。
        """
        self.tree.clear()
        for proj in self._library.projects:
            pitem = QTreeWidgetItem([proj.name])
            pitem.setData(0, _NODE_ROLE, (_LEVEL_PROJECT, proj.name))
            for grp in proj.groups:
                gitem = QTreeWidgetItem([grp.name])
                gitem.setData(0, _NODE_ROLE, (_LEVEL_GROUP, proj.name, grp.name))
                for cmd in grp.commands:
                    citem = QTreeWidgetItem([cmd])
                    citem.setData(0, _NODE_ROLE, (_LEVEL_COMMAND, proj.name, grp.name, cmd))
                    gitem.addChild(citem)
                pitem.addChild(gitem)
            self.tree.addTopLevelItem(pitem)
            # 项目节点内嵌「＋」：在其下新增功能组
            self.tree.setItemWidget(pitem, 0, self._make_node_widget(proj.name))
            # 功能组节点内嵌「＋」：在其下新增命令
            for i in range(pitem.childCount()):
                gitem = pitem.child(i)
                gnode = gitem.data(0, _NODE_ROLE)
                if isinstance(gnode, tuple) and len(gnode) >= 3:
                    self.tree.setItemWidget(
                        gitem, 0, self._make_node_widget(gnode[2], proj=gnode[1])
                    )
        self.tree.expandAll()
        if select is not None:
            self._select_node(select)

    def _make_node_widget(self, label_text: str, *, proj: str | None = None) -> QWidget:
        """构造节点行 widget：[QLabel 名称] [stretch] [内嵌＋按钮].

        setItemWidget 会替换 item 第 0 列的整个显示内容（原文字会消失），
        故容器内放一个 QLabel 显示名称，再贴一个右对齐的 ＋ 按钮。

        Args:
            label_text: 节点显示名（项目名或功能组名）。
            proj: 项目名；非 None 表示这是功能组节点（＋→加命令），否则是项目节点（＋→加功能组）。
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(4)
        name_lbl = QLabel(label_text)
        row.addWidget(name_lbl)
        row.addStretch()
        btn = QToolButton()
        btn.setAutoRaise(True)  # 扁平、悬停才显边框，不喧宾夺主
        btn.setIcon(make_icon("add", color=self._tokens["accent"]))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("新增功能组" if proj is None else "新增命令")
        if proj is None:
            btn.clicked.connect(lambda _checked=False, p=label_text: self._add_group_interactive(p))
        else:
            btn.clicked.connect(
                lambda _checked=False, p=proj, g=label_text: self._add_command_interactive(p, g)
            )
        row.addWidget(btn)
        return container

    # ------------------------------------------------------------------
    # 节点定位（重建后选中并居中滚动）
    # ------------------------------------------------------------------
    def _select_node(self, node: tuple[str, ...]) -> None:
        """定位匹配 node 元组的树项：选中并居中滚动到视野内。"""
        match = self._find_item(node)
        if match is not None:
            self.tree.setCurrentItem(match)
            self.tree.scrollToItem(match, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _find_item(self, node: tuple[str, ...]) -> QTreeWidgetItem | None:
        """递归查找 node 元组匹配的树项（顶到叶全扫）."""
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is None:
                continue
            found = self._search_item(top, node)
            if found is not None:
                return found
        return None

    def _search_item(
        self, item: QTreeWidgetItem, node: tuple[str, ...]
    ) -> QTreeWidgetItem | None:
        if item.data(0, _NODE_ROLE) == node:
            return item
        for i in range(item.childCount()):
            found = self._search_item(item.child(i), node)
            if found is not None:
                return found
        return None

    # ------------------------------------------------------------------
    # 持久化钩子实现（对话框策略：刷新内存工作副本，select 定位到改动点）
    # ------------------------------------------------------------------
    def _commit_and_refresh(self, select: tuple[str, ...] | None = None) -> None:
        """对话框策略：仅刷新内存副本并定位到改动节点（确定时统一落盘）."""
        self._refresh_tree(select=select)

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------
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

    def current_path(self) -> Path:
        """返回对话框当前的文件路径（供面板同步）。"""
        return self._path


# ---------------------------------------------------------------------------
# 模块级共享辅助：菜单项构造、节点菜单构造、删除确认、深拷贝
# ---------------------------------------------------------------------------
def _menu_action(menu: QMenu, text: str, icon: QIcon) -> QAction:
    """给菜单加一个带图标的 action（沿用 mainwindow 菜单栏范式）."""
    act = QAction(icon, text, menu)
    menu.addAction(act)
    return act


def _build_node_menu(
    menu: QMenu,
    node: tuple[str, ...] | None,
    tokens: dict[str, str],
    target: _LibraryTreeEditor,
) -> QMenu:
    """按节点层级构造右键菜单（不 exec，供面板/对话框/测试复用）.

    菜单结构对所有 _LibraryTreeEditor 子类一致，差异仅在落盘时机（由子类的
    _commit_and_refresh 决定），target 直接提供 _rename/_delete/_add_* 方法。
    文案统一取 _MENU_* 常量，节点层级取 _LEVEL_* 常量，避免散落字符串字面量。
    """
    lvl = _level(node)
    accent = tokens["accent"]
    danger = tokens.get("danger", "#ef4444")
    if lvl == _LEVEL_PROJECT:
        assert node is not None
        proj = node[1]
        a_rename = _menu_action(menu, _MENU_RENAME, make_icon("edit", color=accent))
        a_rename.triggered.connect(lambda: target._rename_project(proj))
        a_add_grp = _menu_action(menu, _MENU_ADD_GROUP, make_icon("add", color=accent))
        a_add_grp.triggered.connect(lambda: target._add_group_interactive(proj))
        menu.addSeparator()
        a_del = _menu_action(menu, _MENU_DEL_PROJECT, make_icon("remove", color=danger))
        a_del.triggered.connect(lambda: target._delete_project(proj))
    elif lvl == _LEVEL_GROUP:
        assert node is not None
        proj, grp = node[1], node[2]
        a_rename = _menu_action(menu, _MENU_RENAME, make_icon("edit", color=accent))
        a_rename.triggered.connect(lambda: target._rename_group(proj, grp))
        a_add_cmd = _menu_action(menu, _MENU_ADD_COMMAND, make_icon("add", color=accent))
        a_add_cmd.triggered.connect(lambda: target._add_command_interactive(proj, grp))
        menu.addSeparator()
        a_del = _menu_action(menu, _MENU_DEL_GROUP, make_icon("remove", color=danger))
        a_del.triggered.connect(lambda: target._delete_group(proj, grp))
    elif lvl == _LEVEL_COMMAND:
        assert node is not None
        proj, grp, cmd = node[1], node[2], node[3]
        a_edit = _menu_action(menu, _MENU_EDIT, make_icon("edit", color=accent))
        a_edit.triggered.connect(lambda: target._edit_command(proj, grp, cmd))
        menu.addSeparator()
        a_del = _menu_action(menu, _MENU_DEL_COMMAND, make_icon("remove", color=danger))
        a_del.triggered.connect(lambda: target._delete_command(proj, grp, cmd))
    else:
        # 空白 / hint 节点：只能加项目
        a_add_proj = _menu_action(menu, _MENU_ADD_PROJECT, make_icon("add", color=accent))
        a_add_proj.triggered.connect(target._add_project_interactive)
    return menu


def _confirm_delete(parent: QWidget, kind: str, name: str) -> bool:
    """删除项目/功能组前二次确认（有子节点连带删除）；返回是否确认.

    命令不调用此函数（直接删）。标题/文案用简体中文，沿用 mainwindow 的
    QMessageBox.question 范式。
    """
    choice = QMessageBox.question(
        parent,
        f"删除{kind}",
        f"确定删除{kind}「{name}」吗？\n该{kind}下的所有子节点将一并删除。",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return choice == QMessageBox.StandardButton.Yes


def _clone_library(library: CommandLibrary) -> CommandLibrary:
    """深拷贝命令库（对话框编辑用工作副本，取消时不影响外部）."""
    new = CommandLibrary.empty()
    for p in library.projects:
        new.add_project(p.name)
        for g in p.groups:
            grp = new.add_group(p.name, g.name)
            grp.commands = list(g.commands)
    return new
