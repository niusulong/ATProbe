"""用例执行选项卡（M6 §5）—— 用例筛选与执行."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.tabs.registry import ITabView, TabBinding


class CaseExecuteTab(ITabView):
    type_name = "case_execute"
    display_name = "用例执行"
    _icon = "play"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return CaseExecuteWidget(binding, main_window)


class CaseExecuteWidget(QWidget):
    """用例筛选与执行视图（§5）."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._cases: list[tuple[str, tuple[str, ...], str]] = []  # (name, tags, file)
        self._init_ui()
        self._load_default_dir()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 顶部：目录加载 + 标签筛选 + 搜索
        top = QHBoxLayout()
        top.setSpacing(8)
        load_btn = QPushButton("加载目录")
        load_btn.clicked.connect(self._load_dir)
        top.addWidget(load_btn)
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

        # 用例表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["选", "用例名", "标签", "文件"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

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

    def _populate(self, filter_text: str) -> None:
        tag_filter = self.tag_combo.currentText().strip()
        all_tags = tag_filter in ("", "（全部）")
        self.table.setRowCount(0)
        for name, tags, file in self._cases:
            if filter_text and filter_text not in name and filter_text not in file:
                continue
            if not all_tags and tag_filter not in tags:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QCheckBox()
            chk.setChecked(True)
            self.table.setCellWidget(row, 0, chk)
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(", ".join(tags)))
            self.table.setItem(row, 3, QTableWidgetItem(file))

    def _filter(self) -> None:
        self._populate(self.search_edit.text().strip())

    def _on_tag_change(self, _text: str) -> None:
        self._populate(self.search_edit.text().strip())

    def _selected_files(self) -> list[str]:
        """收集勾选用例的文件路径。注意：表格只显示筛选后的用例，需按文件匹配回 _cases."""
        shown_files = [self.table.item(row, 3).text() for row in range(self.table.rowCount())  # type: ignore[union-attr]
                       if self.table.item(row, 3) is not None]
        selected: list[str] = []
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if isinstance(chk, QCheckBox) and chk.isChecked():
                selected.append(shown_files[row])
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
