"""用例执行选项卡（M6 §5）—— 用例筛选与执行.

用例以**目录层级树**展示（``QTreeWidget``）：目录节点带三态复选框（``ItemIsAutoTristate``
自动级联），叶子节点 = 单个用例文件。支持全选/全不选、展开/折叠全部、标签筛选与搜索。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.tabs.registry import ITabView, TabBinding

# 叶子节点（用例）在第 0 列存储用例文件绝对路径，用于选中收集
_FILE_ROLE = Qt.ItemDataRole.UserRole


class CaseExecuteTab(ITabView):
    type_name = "case_execute"
    display_name = "用例执行"
    _icon = "play"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return CaseExecuteWidget(binding, main_window)


class CaseExecuteWidget(QWidget):
    """用例筛选与执行视图（§5）—— 目录层级树 + 多选 + 全选."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._cases: list[tuple[str, tuple[str, ...], str]] = []  # (name, tags, file)
        self._root_dir: Path | None = None  # 当前加载的根目录（用于计算相对路径）
        self._init_ui()
        self._load_default_dir()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 顶部第一行：加载目录 + 全选/展开 + 标签筛选 + 搜索
        top = QHBoxLayout()
        top.setSpacing(8)
        load_btn = QPushButton("加载目录")
        load_btn.clicked.connect(self._load_dir)
        top.addWidget(load_btn)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        top.addWidget(self.select_all_btn)
        deselect_all_btn = QPushButton("全不选")
        deselect_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        deselect_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        top.addWidget(deselect_all_btn)
        expand_btn = QPushButton("展开")
        expand_btn.clicked.connect(self.tree_expand_all)
        top.addWidget(expand_btn)
        collapse_btn = QPushButton("折叠")
        collapse_btn.clicked.connect(self.tree_collapse_all)
        top.addWidget(collapse_btn)

        top.addWidget(QLabel("标签:"))
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.tag_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.tag_combo.setMaximumWidth(120)
        self.tag_combo.currentTextChanged.connect(self._on_tag_change)
        top.addWidget(self.tag_combo)
        top.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按用例名/文件过滤")
        self.search_edit.textChanged.connect(self._filter)
        top.addWidget(self.search_edit, 1)
        layout.addLayout(top)

        # 用例目录层级树
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["用例名", "标签", "文件"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        # 只允许通过复选框选择，避免选中高亮与勾选混淆
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setSortingEnabled(False)
        layout.addWidget(self.tree, 1)

        # 执行参数
        param = QHBoxLayout()
        param.setSpacing(8)
        param.addWidget(QLabel("参与端口:"))
        self.ports_combo = QComboBox()
        self._refresh_ports()
        param.addWidget(self.ports_combo)
        param.addWidget(QLabel("压测阈值%:"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 100)
        self.threshold_spin.setValue(95)
        param.addWidget(self.threshold_spin)
        # 生成报告开关
        self.report_check = QCheckBox("生成报告")
        self.report_check.setChecked(True)
        param.addWidget(self.report_check)
        param.addStretch()
        layout.addLayout(param)

        # 执行按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        run_btn = QPushButton("执行选中")
        run_btn.setObjectName("primary")  # 主按钮样式（主色底白字）
        run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        run_btn.clicked.connect(self._run)
        btn_row.addWidget(run_btn)
        stop_btn = QPushButton("停止")
        stop_btn.setObjectName("danger")
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(stop_btn)
        dry_btn = QPushButton("预演")
        dry_btn.setToolTip("只解析用例 + 检查端口，不实际执行")
        dry_btn.clicked.connect(self._dry_run)
        btn_row.addWidget(dry_btn)
        clear_btn = QPushButton("清空结果")
        clear_btn.clicked.connect(self._clear_results)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _refresh_ports(self) -> None:
        self.ports_combo.clear()
        getter = getattr(self._main, "available_ports", None) or getattr(self._main, "connected_ports", None)
        if callable(getter):
            for p in getter():
                self.ports_combo.addItem(p)

    def _load_default_dir(self) -> None:
        if hasattr(self._main, "cases_dir"):
            self._load_path(self._main.cases_dir())

    def _load_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择用例目录")
        if d:
            self._load_path(Path(d))

    def _load_path(self, path: Path) -> None:
        from atprobe.domain.case.parser import CaseParseError, parse_case_file

        self._cases = []
        self._root_dir = path.resolve() if path.is_dir() else path.parent.resolve()
        if path.is_dir():
            files = sorted(path.rglob("*.yaml"))
        elif path.is_file():
            files = [path]
        else:
            return
        for f in files:
            if f.name.startswith("suite-"):
                continue
            try:
                c = parse_case_file(f)
            except CaseParseError:
                continue
            self._cases.append((c.name, c.tags, str(f)))
        self._refresh_tag_combo()
        self._populate("")

    def _refresh_tag_combo(self) -> None:
        """聚合所有用例标签，填入标签筛选下拉（保留当前选择/首项「全部」）."""
        all_tags: set[str] = set()
        for _name, tags, _file in self._cases:
            all_tags.update(tags)
        cur = self.tag_combo.currentText()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("（全部）")
        for t in sorted(all_tags):
            self.tag_combo.addItem(t)
        # 恢复之前的选择
        idx = self.tag_combo.findText(cur)
        self.tag_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.tag_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # 树构建
    # ------------------------------------------------------------------
    def _populate(self, filter_text: str) -> None:
        """按标签/搜索过滤后重建目录树（默认全选 + 展开根目录）."""
        tag_filter = self.tag_combo.currentText().strip()
        all_tags = tag_filter in ("", "（全部）")
        kept: list[tuple[str, tuple[str, ...], str]] = []
        for name, tags, file in self._cases:
            if filter_text and filter_text not in name and filter_text not in file:
                continue
            if not all_tags and tag_filter not in tags:
                continue
            kept.append((name, tags, file))

        self.tree.clear()
        root = self._root_dir
        # root_item：以根目录名作为顶层节点（如 testcases）；根目录下直接放用例时也要有顶层节点
        root_name = root.name if (root and root.name) else "用例"
        root_item = self._make_dir_item(root_name)

        for name, tags, file in kept:
            # 计算文件相对 root 的目录路径（相对路径列表，如 ["tcp"] 或 [] 表示直接在根下）
            rel = self._rel_dir_parts(Path(file), root)
            parent = root_item
            for part in rel:
                parent = self._ensure_dir_child(parent, part)
            self._make_case_item(parent, name, tags, file)

        self.tree.addTopLevelItem(root_item)
        # 默认展开顶层根目录，让用户看到二级目录
        self.tree.expandItem(root_item)
        # 默认全选（AutoTristate 自动级联到子孙）
        root_item.setCheckState(0, Qt.CheckState.Checked)

    @staticmethod
    def _rel_dir_parts(file_path: Path, root: Path | None) -> list[str]:
        """文件相对 root 的目录层级（不含文件名）。无法计算相对路径时返回 []."""
        if root is None:
            return []
        try:
            rel = file_path.resolve().relative_to(root)
        except (ValueError, OSError):
            return []
        parts = list(rel.parts)
        return parts[:-1] if len(parts) > 1 else []

    def _make_dir_item(self, name: str) -> QTreeWidgetItem:
        """创建目录节点（三态复选框，第 0 列 = 目录名）."""
        item = QTreeWidgetItem([name, "", ""])
        item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsAutoTristate
            | Qt.ItemFlag.ItemIsEnabled
        )
        item.setCheckState(0, Qt.CheckState.Checked)
        return item

    def _ensure_dir_child(self, parent: QTreeWidgetItem, name: str) -> QTreeWidgetItem:
        """获取/创建某父节点下的目录子节点（已存在则复用，避免重复创建）."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.childCount() > 0 and child.data(0, _FILE_ROLE) is None and child.text(0) == name:
                return child
        item = self._make_dir_item(name)
        parent.addChild(item)
        return item

    def _make_case_item(self, parent: QTreeWidgetItem, name: str, tags: tuple[str, ...], file: str) -> None:
        """创建用例叶子节点（第 0 列=用例名，1=标签，2=文件；存储文件路径于 UserRole）."""
        item = QTreeWidgetItem([name, ", ".join(tags), file])
        item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsAutoTristate
            | Qt.ItemFlag.ItemIsEnabled
        )
        item.setCheckState(0, Qt.CheckState.Checked)
        item.setData(0, _FILE_ROLE, file)
        item.setToolTip(2, file)
        parent.addChild(item)

    # ------------------------------------------------------------------
    # 选择 / 展开
    # ------------------------------------------------------------------
    def _set_all_checked(self, checked: bool) -> None:
        """全选/全不选：操作顶层节点，AutoTristate 自动传播到所有子孙."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item is not None:
                item.setCheckState(0, state)

    def tree_expand_all(self) -> None:
        self.tree.expandAll()

    def tree_collapse_all(self) -> None:
        self.tree.collapseAll()

    def _filter(self) -> None:
        self._populate(self.search_edit.text().strip())

    def _on_tag_change(self, _text: str) -> None:
        self._populate(self.search_edit.text().strip())

    def _selected_files(self) -> list[str]:
        """收集勾选用例的文件路径（仅叶子节点且 Checked）."""
        selected: list[str] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item.childCount() == 0:
                # 叶子 = 用例
                if item.checkState(0) == Qt.CheckState.Checked:
                    file = item.data(0, _FILE_ROLE)
                    if isinstance(file, str):
                        selected.append(file)
                return
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    walk(child)

        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item is not None:
                walk(item)
        return selected

    def _run(self) -> None:
        selected = self._selected_files()
        if not selected:
            return
        port = self.ports_combo.currentText()
        if not port:
            return
        if hasattr(self._main, "run_cases"):
            self._main.run_cases(
                selected, port, self.threshold_spin.value(),
                no_report=not self.report_check.isChecked(),
            )

    def _dry_run(self) -> None:
        selected = self._selected_files()
        if not selected:
            return
        port = self.ports_combo.currentText()
        if not port:
            return
        if hasattr(self._main, "run_cases"):
            self._main.run_cases(selected, port, self.threshold_spin.value(), dry_run=True)

    def _stop(self) -> None:
        # 优先用带对话框的停止（中断当前 / 停止全部）；兜底直接停止全部
        stop_dialog = getattr(self._main, "stop_engine_dialog", None)
        if callable(stop_dialog):
            stop_dialog()
        elif hasattr(self._main, "stop_engine"):
            self._main.stop_engine()

    def _clear_results(self) -> None:
        """清空执行进度选项卡的结果（若已打开）."""
        from typing import Any

        main: Any = self._main
        tabs = getattr(main, "tabs", None)
        if tabs is None:
            return
        for i in range(tabs.count()):
            w = tabs.widget(i)
            if hasattr(w, "property") and w.property("tab_type") == "execution_progress":
                clear = getattr(w, "clear", None)
                if callable(clear):
                    clear()
                break
