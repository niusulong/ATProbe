"""命令库侧栏面板 + 管理对话框（项目→功能→命令三层树）.

面板作为普通 QWidget 嵌入手动调试页左侧（QSplitter），双击命令叶子经
send_requested(str) 信号通知宿主页发送。增删改经 LibraryManagerDialog 集中完成。

新增交互：顶部工具栏只保留「＋项目」（项目是顶级，无父节点可挂）；
每个项目节点行内嵌「＋」（在其下新增功能组），每个功能组节点行内嵌「＋」
（在其下新增命令）。在哪层就在哪层加，无需预先选中。删除/重命名仍在右侧表单。

解耦：面板不认识手动调试页，只 emit send_requested；宿主页连接该信号发送。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
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

# 树节点角色：data 存 "project:名" / "group:项目:功能" / "command:项目:功能:命令"
_NODE_ROLE = Qt.ItemDataRole.UserRole


class CommandLibraryPanel(QWidget):
    """命令库侧栏面板（嵌入手动调试页左侧）。

    唯一对外出口：send_requested(str) —— 双击命令叶子时 emit，宿主页连接后发送。
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
    def _on_click(self, item: QTreeWidgetItem, _column: int) -> None:
        """单击：命令叶子 → emit send_requested；项目/功能节点 → 展开/折叠（默认）."""
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

    顶部工具栏始终可见新增入口（项目/功能组/命令）——根据当前选中节点智能
    判断新增目标所属；加载/另存为文件操作也在顶部。右侧表单仅展示当前选中
    节点的编辑区（重命名/删除）。
    """

    def __init__(
        self, library: CommandLibrary, path: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("命令库管理")
        self.resize(760, 500)
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

    # ------------------------------------------------------------------
    # 树渲染（带 node role，供右侧表单定位层级）
    # ------------------------------------------------------------------
    def _refresh_tree(self) -> None:
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
    # 当前选中节点定位（供右侧表单 _on_tree_select 解析层级）
    # ------------------------------------------------------------------
    def _current_selection(self) -> tuple[str, ...] | None:
        """返回当前选中节点的元组标识（None 表示未选中）."""
        items = self.tree.selectedItems()
        if not items:
            return None
        node = items[0].data(0, _NODE_ROLE)
        return node if isinstance(node, tuple) else None

    # ------------------------------------------------------------------
    # 表单切换
    # ------------------------------------------------------------------
    def _clear_form(self) -> None:
        while self._form_layout.count():
            it = self._form_layout.takeAt(0)
            if it is None:
                continue
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _on_tree_select(self) -> None:
        node = self._current_selection()
        self._clear_form()
        if node is None:
            self._build_hint_form("选中左侧节点编辑，或用顶部按钮新增。")
        elif node[0] == "project":
            self._build_project_form(node[1])
        elif node[0] == "group":
            self._build_group_form(node[1], node[2])
        elif node[0] == "command":
            self._build_command_form(node[1], node[2], node[3])

    def _build_hint_form(self, text: str) -> None:
        hint = QLabel(text)
        hint.setObjectName("caption")
        self._form_layout.addWidget(hint)
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

    # ------------------------------------------------------------------
    # 增删改操作（内存 model + 重名校验）
    # ------------------------------------------------------------------
    def _add_project_interactive(self) -> None:
        name, ok = QInputDialog.getText(self, "新增项目", "项目名:")
        if not (ok and name.strip()):
            return
        try:
            self._library.add_project(name)
        except ValueError as exc:
            QMessageBox.warning(self, "无法新增", str(exc))
            return
        self._refresh_tree()

    def _add_group_interactive(self, proj_name: str) -> None:
        """直接在某项目下新增功能组（由项目节点的内嵌＋按钮调用）.

        与旧的 under_selection 版本区别：目标项目由参数显式传入（按钮所在的节点），
        不再依赖选中态，也无需"先选中项目"的提示。
        """
        name, ok = QInputDialog.getText(self, "新增功能组", f"{proj_name} 下的功能组名:")
        if not (ok and name.strip()):
            return
        try:
            self._library.add_group(proj_name, name)
        except ValueError as exc:
            QMessageBox.warning(self, "无法新增", str(exc))
            return
        self._refresh_tree()

    def _add_command_interactive(self, proj_name: str, grp_name: str) -> None:
        """直接在某功能组下新增命令（由功能组节点的内嵌＋按钮调用）.

        与旧的 under_selection 版本区别：目标功能组由参数显式传入（按钮所在的节点），
        不再依赖选中态，也无需"先选中功能组"的提示。
        """
        cmd, ok = QInputDialog.getText(self, "新增命令", f"{proj_name}/{grp_name} 的 AT 指令:")
        if not (ok and cmd.strip()):
            return
        try:
            self._library.add_command(proj_name, grp_name, cmd)
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

    def _edit_command(self, proj: str, grp: str, old: str, edit: QLineEdit) -> None:
        new = edit.text().strip()
        if not new or new == old:
            return  # 空或未改动 → 无操作（避免 add+remove 重排序）
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


def _clone_library(library: CommandLibrary) -> CommandLibrary:
    """深拷贝命令库（对话框编辑用工作副本，取消时不影响外部）."""
    new = CommandLibrary.empty()
    for p in library.projects:
        new.add_project(p.name)
        for g in p.groups:
            grp = new.add_group(p.name, g.name)
            grp.commands = list(g.commands)
    return new
