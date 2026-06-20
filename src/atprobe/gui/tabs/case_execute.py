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

        # 顶部：目录加载 + 搜索
        top = QHBoxLayout()
        top.setSpacing(8)
        load_btn = QPushButton("加载目录")
        load_btn.clicked.connect(self._load_dir)
        top.addWidget(load_btn)
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
        self._populate("")

    def _populate(self, filter_text: str) -> None:
        self.table.setRowCount(0)
        for name, tags, file in self._cases:
            if filter_text and filter_text not in name and filter_text not in file:
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

    def _run(self) -> None:
        selected = []
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if isinstance(chk, QCheckBox) and chk.isChecked():
                selected.append(self._cases[row][2])  # file path
        if not selected:
            return
        port = self.ports_combo.currentText()
        if not port:
            return
        if hasattr(self._main, "run_cases"):
            self._main.run_cases(selected, port, self.threshold_spin.value())

    def _stop(self) -> None:
        if hasattr(self._main, "stop_engine"):
            self._main.stop_engine()
