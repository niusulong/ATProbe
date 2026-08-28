"""用例执行选项卡（M6 §5）—— 用例筛选与执行.

用例以**目录层级树**展示（``QTreeWidget``）：目录节点带三态复选框（``ItemIsAutoTristate``
自动级联），叶子节点 = 单个用例文件。支持全选/全不选、展开/折叠全部、标签筛选与搜索。

性能（Pf-2/Pf-3）：
    - 搜索输入 300ms 防抖（输入停顿才过滤），标签/搜索过滤改为**增量隐藏**
      （遍历树 ``setHidden``，不重建——保留勾选/展开态，避免每字符全量重建）；
    - 目录批量 YAML 解析经 QTimer 驱动的协作式分片推进（每次事件循环迭代解析
      约 20ms，UI 不冻结）；解析结果经主窗口的 ``case_parse_cache`` 缓存
      （若有），run_cases 执行时复用，不重复 parse。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
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
# 叶子节点第 0 列存储标签元组（增量过滤按标签精确匹配用，避免 join/split 往返失真）
_TAGS_ROLE = Qt.ItemDataRole.UserRole + 1
# 分片解析的时间预算（ms）：每事件循环迭代最多解析这么久，让 UI 保持响应
_LOAD_SLICE_MS = 20


class CaseExecuteTab(ITabView):
    type_name = "case_execute"
    display_name = "用例执行"
    _icon = "play"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return CaseExecuteWidget(binding, main_window)


def _list_case_files(path: Path) -> tuple[Path, list[Path]]:
    """列出目录/单文件下的用例文件（有序；suite-*.yaml 套件文件跳过）."""
    if path.is_dir():
        root = path.resolve()
        files = [f for f in sorted(path.rglob("*.yaml")) if not f.name.startswith("suite-")]
    else:
        root = path.parent.resolve()
        files = [] if path.name.startswith("suite-") else [path]
    return root, files


def _parse_one_case(
    f: Path, cache: object | None = None
) -> tuple[tuple[str, tuple[str, ...], str] | None, str | None]:
    """解析单个用例文件。返回 (条目 | None, 失败消息 | None).

    cache 为主窗口的 CaseParseCache（可选）——命中 (路径, mtime) 一致的缓存
    直接复用（run_cases 执行同一批文件时不再重复 parse，Pf-3）。
    """
    from atprobe.domain.case.parser import CaseParseError, parse_case_file

    get_or_parse: Any = getattr(cache, "get_or_parse", None) if cache is not None else None
    try:
        c: Any = get_or_parse(f) if callable(get_or_parse) else parse_case_file(f)
    except CaseParseError as exc:
        return None, f"{f.name}：{exc}"
    return (c.name, c.tags, str(f)), None


class CaseExecuteWidget(QWidget):
    """用例筛选与执行视图（§5）—— 目录层级树 + 多选 + 全选."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._cases: list[tuple[str, tuple[str, ...], str]] = []  # (name, tags, file)
        self._root_dir: Path | None = None  # 当前加载的根目录（用于计算相对路径）
        # 分片加载状态（Pf-3）：批次号递增，应用时以当前批次为准（快速连续
        # 切换目录时旧分片的结果不覆盖新批次）
        self._load_seq = 0
        self._applied_seq = 0
        self._load_timer: QTimer | None = None  # 懒创建（QTimer(0) 驱动分片解析）
        self._load_root: Path | None = None
        self._load_files: list[Path] = []
        self._load_index = 0
        self._load_cases: list[tuple[str, tuple[str, ...], str]] = []
        self._load_failed: list[str] = []
        self._load_cache: object | None = None
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
        # Pf-2 防抖：每敲一字符全量过滤会卡输入——输入停顿 300ms 才触发 _filter
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._filter)
        self.search_edit.textChanged.connect(lambda _text: self._debounce.start())
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
        getter = getattr(self._main, "available_ports", None) or getattr(
            self._main, "connected_ports", None
        )
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
        """加载目录/文件：批量 YAML 解析分片在主线程推进（Pf-3）.

        大目录逐文件 YAML 解析可达秒级。不走后台线程——Python 线程内触发的 GC
        可能在非主线程回收 Qt 对象（原生崩溃路径），且跨线程信号投递在无事件
        循环的环境不可控；改为 QTimer(0) 驱动的**协作式分片**：每次事件循环
        迭代解析约 ``_LOAD_SLICE_MS``，UI 保持响应，解析始终在主线程（GC 安全）。
        连续加载按 ``_load_seq`` 只应用最新批次。
        """
        if not path.is_dir() and not path.is_file():
            # 与历史行为一致：路径不存在 → 清空数据、保留旧树展示（不重建）
            self._cases = []
            self._root_dir = path.parent.resolve()
            return
        root, files = _list_case_files(path)
        # 主窗口的共享解析缓存（若有）：加载即填充，run_cases 执行时复用（Pf-3）
        self._load_seq += 1
        self._load_root = root
        self._load_files = files
        self._load_index = 0
        self._load_cases = []
        self._load_failed = []
        self._load_cache = getattr(self._main, "case_parse_cache", None)
        if self._load_timer is None:
            self._load_timer = QTimer(self)
            self._load_timer.setInterval(0)
            self._load_timer.timeout.connect(self._load_step)
        self._load_timer.start()

    def _load_step(self) -> None:
        """分片解析一步（主线程 QTimer 回调）：预算内尽量多解析，完毕应用。"""
        if self._load_timer is None:
            return
        budget_end = time.monotonic() + _LOAD_SLICE_MS / 1000
        files = self._load_files
        while True:
            if self._load_index >= len(files):
                self._load_timer.stop()
                self._apply_loaded(
                    (self._load_seq, self._load_root, self._load_cases, self._load_failed)
                )
                return
            f = files[self._load_index]
            self._load_index += 1
            entry, err = _parse_one_case(f, self._load_cache)
            if entry is not None:
                self._load_cases.append(entry)
            elif err is not None:
                self._load_failed.append(err)
            if time.monotonic() >= budget_end:
                return  # 让出事件循环（下一 tick 继续解析）

    def _apply_loaded(self, payload: tuple[int, Path | None, list[Any], list[str]]) -> None:
        """解析完成（主线程）：更新数据 + 重建树（丢弃过期批次）。"""
        seq, root, cases, failed = payload
        if not isinstance(seq, int) or seq < self._load_seq:
            return  # 过期批次（期间又发起了新加载）
        self._applied_seq = seq
        self._cases = list(cases)
        self._root_dir = root
        # P3 修复：解析失败的用例不再静默跳过——收集后一次性提示（用户否则
        # 无法得知哪些文件损坏/不合规）
        if failed:
            from PySide6.QtWidgets import QMessageBox

            preview = "\n".join(failed[:8])
            more = f"\n…（共 {len(failed)} 个）" if len(failed) > 8 else ""
            QMessageBox.warning(
                self, "部分用例解析失败", f"以下 {len(failed)} 个文件未加载：\n{preview}{more}"
            )
        self._refresh_tag_combo()
        self._populate()

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
    def _populate(self) -> None:
        """重建完整目录树（默认全选 + 展开根目录）.

        Pf-2：只在建树时跑（_load_path 完成 / 初次加载）；搜索/标签筛选经
        ``_apply_filter`` 增量隐藏，不再重建（重量级操作与输入解耦）。
        """
        self.tree.clear()
        root = self._root_dir
        # root_item：以根目录名作为顶层节点（如 testcases）；根目录下直接放用例时也要有顶层节点
        root_name = root.name if (root and root.name) else "用例"
        root_item = self._make_dir_item(root_name)

        for name, tags, file in self._cases:
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
        # 建树后应用当前筛选态（如加载时搜索框已有内容）
        self._apply_filter()

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
            if (
                child.childCount() > 0
                and child.data(0, _FILE_ROLE) is None
                and child.text(0) == name
            ):
                return child
        item = self._make_dir_item(name)
        parent.addChild(item)
        return item

    def _make_case_item(
        self, parent: QTreeWidgetItem, name: str, tags: tuple[str, ...], file: str
    ) -> None:
        """创建用例叶子节点（第 0 列=用例名，1=标签，2=文件；路径/标签存 UserRole）."""
        item = QTreeWidgetItem([name, ", ".join(tags), file])
        item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsAutoTristate
            | Qt.ItemFlag.ItemIsEnabled
        )
        item.setCheckState(0, Qt.CheckState.Checked)
        item.setData(0, _FILE_ROLE, file)
        # 标签元组原样存（增量过滤按成员精确匹配，不走 join/split 往返）
        item.setData(0, _TAGS_ROLE, tuple(tags))
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
        """防抖到期的搜索过滤（Pf-2：textChanged → 300ms 停顿 → 本方法）."""
        self._apply_filter()

    def _on_tag_change(self, _text: str) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Pf-2 增量过滤：按搜索文本 + 标签**隐藏**不匹配项（不重建树）.

        匹配语义与旧全量重建一致：搜索文本子串命中用例名或文件路径；
        标签按成员精确匹配（「（全部）」/空 = 不过滤）。目录节点在所有子节点
        隐藏时才隐藏；树的勾选/展开状态全程保留（重建会重置为全选+展开根）。
        """
        filter_text = self.search_edit.text().strip()
        tag_filter = self.tag_combo.currentText().strip()
        all_tags = tag_filter in ("", "（全部）")

        def apply_visibility(item: QTreeWidgetItem) -> bool:
            """自底向上设置每个节点的可见性，返回该节点是否可见."""
            if item.childCount() == 0:
                # 叶子 = 用例：搜索/标签都过才可见
                name = item.text(0)
                file = str(item.data(0, _FILE_ROLE) or "")
                tags = item.data(0, _TAGS_ROLE) or ()
                if (filter_text and filter_text not in name and filter_text not in file) or (
                    not all_tags and tag_filter not in tags
                ):
                    visible = False
                else:
                    visible = True
            else:
                # 目录：任一子节点可见则可见
                visible = False
                for i in range(item.childCount()):
                    child = item.child(i)
                    if child is not None and apply_visibility(child):
                        visible = True
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is not None:
                apply_visibility(top)

    def _selected_files(self) -> list[str]:
        """收集勾选用例的文件路径（仅**可见**叶子节点且 Checked）.

        Pf-2 注记：过滤隐藏的用例不参与执行——与旧「过滤即从树中移除」的重建
        语义等价（隐藏项在树中保留但等同不存在）。
        """

        selected: list[str] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item.childCount() == 0:
                # 叶子 = 用例（隐藏 = 被过滤，等同不存在）
                if not item.isHidden() and item.checkState(0) == Qt.CheckState.Checked:
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
                selected,
                port,
                self.threshold_spin.value(),
                no_report=not self.report_check.isChecked(),
            )

    def cleanup(self) -> None:
        """统一资源清理钩子（B6）：tab 关闭时停分片加载定时器."""
        if self._load_timer is not None:
            self._load_timer.stop()

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
