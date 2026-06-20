"""用例执行进度选项卡（M6 §6.3）—— 实时消费 M3 §7.4 进度事件。

执行时自动弹出（不经侧栏点击），用例/步骤状态实时刷新：
    - CaseStartEvent → 新增用例行（运行中）
    - StepResultEvent → 步骤状态更新（PASS 绿 / FAIL 红 / SKIPPED 黄）
    - PressureProgressEvent → 压测用例轮次进度（成功/失败/平均耗时）
    - CaseResultEvent → 用例行状态落定
    - EngineFinishedEvent → 进度条到 100%，显示总耗时

进度条基于 CaseStartEvent.case_index/total_cases（M3 §7.4）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.tabs.registry import ITabView, TabBinding
from atprobe.gui.theme import get_tokens


class ExecutionProgressTab(ITabView):
    type_name = "execution_progress"
    display_name = "执行进度"
    _icon = "play"

    def icon_name(self) -> str:
        return self._icon

    def is_sidebar_visible(self) -> bool:
        """执行进度选项卡不在侧栏显示，执行时自动弹出."""
        return False

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return ExecutionProgressWidget(binding, main_window)


class ExecutionProgressWidget(QWidget):
    """执行进度视图（§6.3）—— 实时用例/步骤状态 + 进度条 + 压测轮次."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._tokens = get_tokens(dark=False)
        # 用例索引 → 表格行号（每个用例一行步骤明细在第二列文本）
        self._case_rows: dict[int, int] = {}
        self._case_names: dict[int, str] = {}
        self._total_cases = 0
        self._init_ui()

    # ------------------------------------------------------------------
    # UI 构造
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 顶部进度条
        prog_group = QGroupBox("整体进度")
        prog_layout = QVBoxLayout(prog_group)
        prog_layout.setContentsMargins(12, 8, 12, 12)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("等待开始...")
        prog_layout.addWidget(self.progress_bar)
        layout.addWidget(prog_group)

        # 用例结果表格
        case_group = QGroupBox("用例进度")
        case_layout = QVBoxLayout(case_group)
        case_layout.setContentsMargins(12, 8, 12, 12)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "用例", "状态", "耗时"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 80)
        case_layout.addWidget(self.table)
        layout.addWidget(case_group, 1)

        # 步骤明细 / 压测进度区
        self.detail_label = QLabel("步骤明细：")
        self.detail_label.setObjectName("caption")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        # 操作行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.clear)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # 事件入口（由 MainWindow._on_progress 转发，主线程上下文）
    # ------------------------------------------------------------------
    def on_event(self, ev: object) -> None:
        """统一入口：按事件类型分发到具体渲染方法."""
        from atprobe.engine.interfaces import (
            CaseResultEvent,
            CaseStartEvent,
            EngineFinishedEvent,
            PressureProgressEvent,
            StepResultEvent,
        )

        if isinstance(ev, CaseStartEvent):
            self._on_case_start(ev)
        elif isinstance(ev, StepResultEvent):
            self._on_step(ev)
        elif isinstance(ev, PressureProgressEvent):
            self._on_pressure(ev)
        elif isinstance(ev, CaseResultEvent):
            self._on_case_result(ev)
        elif isinstance(ev, EngineFinishedEvent):
            self._on_finished(ev)

    # ------------------------------------------------------------------
    def _on_case_start(self, ev: object) -> None:
        from atprobe.engine.interfaces import CaseStartEvent

        assert isinstance(ev, CaseStartEvent)
        self._total_cases = max(self._total_cases, ev.total_cases)
        row = self.table.rowCount()
        self._case_rows[ev.case_index] = row
        self._case_names[ev.case_index] = ev.case_name
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(ev.case_index)))
        self.table.setItem(row, 1, QTableWidgetItem(ev.case_name))
        status_item = QTableWidgetItem("运行中")
        status_item.setForeground(self._qt_color(self._tokens["accent"]))
        self.table.setItem(row, 2, status_item)
        self.table.setItem(row, 3, QTableWidgetItem(""))
        self._update_progress(ev.case_index - 1, ev.total_cases)
        self.detail_label.setText(f"步骤明细：[{ev.case_name}] 开始执行...")

    def _on_step(self, ev: object) -> None:
        from atprobe.domain.report.models import StepStatus
        from atprobe.engine.interfaces import StepResultEvent

        assert isinstance(ev, StepResultEvent)
        glyph = {
            StepStatus.PASS.value: "✓",
            StepStatus.FAIL.value: "✗",
            StepStatus.SKIPPED.value: "⤳",
            StepStatus.INTERRUPTED.value: "⏹",
        }.get(ev.status, "·")
        # 步骤明细追加到 detail_label
        prefix = f"[{ev.port}] {ev.command}"
        suffix = f" {glyph} {ev.duration_ms:.0f}ms"
        if ev.error_msg:
            suffix += f"  {ev.error_msg}"
        cur = self.detail_label.text()
        # 截断，避免过长
        self.detail_label.setText((cur + f"\n  {prefix}{suffix}")[-2000:])

    def _on_pressure(self, ev: object) -> None:
        from atprobe.engine.interfaces import PressureProgressEvent

        assert isinstance(ev, PressureProgressEvent)
        self.detail_label.setText(
            f"压测 [{ev.case_name}]：第 {ev.current_round}/{ev.total_rounds} 轮  "
            f"成功 {ev.success} 失败 {ev.fail}  平均 {ev.avg_ms:.0f}ms"
        )

    def _on_case_result(self, ev: object) -> None:
        from atprobe.domain.report.models import CaseStatus
        from atprobe.engine.interfaces import CaseResultEvent

        assert isinstance(ev, CaseResultEvent)
        # 按用例名反查行（case_index 可能跨多个用例不连续，用名字匹配）
        row = self._find_row_by_name(ev.case_name)
        if row is None:
            return
        color_key = {
            CaseStatus.PASS.value: "success",
            CaseStatus.FAIL.value: "danger",
            CaseStatus.SKIPPED.value: "warning",
            CaseStatus.INTERRUPTED.value: "neutral",
        }.get(ev.status, "text.primary")
        status_item = QTableWidgetItem(ev.status)
        status_item.setForeground(self._qt_color(self._tokens[color_key]))
        self.table.setItem(row, 2, status_item)
        self.table.setItem(row, 3, QTableWidgetItem(f"{ev.duration_ms:.2f}s"))

    def _on_finished(self, ev: object) -> None:
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("执行完成 100%")
        self.detail_label.setText(self.detail_label.text() + "\n执行完成。")

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _find_row_by_name(self, name: str) -> int | None:
        for idx, n in self._case_names.items():
            if n == name:
                return self._case_rows.get(idx)
        return None

    def _update_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(done / total * 100)
        self.progress_bar.setValue(min(pct, 100))
        self.progress_bar.setFormat(f"{done}/{total} 用例  {pct}%")

    def _qt_color(self, hex_color: str) -> QColor:
        return QColor(hex_color)

    def clear(self) -> None:
        self.table.setRowCount(0)
        self._case_rows.clear()
        self._case_names.clear()
        self._total_cases = 0
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("等待开始...")
        self.detail_label.setText("步骤明细：")
