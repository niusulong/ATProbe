"""实时监控选项卡（M6 §6.2）—— 多端口 TX/RX 数据流监控.

独立观察端口的原始收发字节流（与手动调试响应区同源）。支持：
    - 多端口勾选：同时监控多个端口，合并显示加 [COMx] 前缀
    - 自动打开：未连接的勾选端口自动打开
    - HEX/TEXT 切换
    - 导出当前监控段为文件
    - 环形缓冲（行数上限，防长监控撑爆内存）
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.tabs.registry import ITabView, TabBinding

_MAX_LINES = 10000  # 环形缓冲上限（§10.3）


class MonitorTab(ITabView):
    type_name = "monitor"
    display_name = "实时监控"
    _icon = "monitor"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return MonitorWidget(binding, main_window)


class MonitorWidget(QWidget):
    """多端口数据流监控视图（§6.2）."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._buffer: deque[str] = deque(maxlen=_MAX_LINES)
        self._port_checks: list[QCheckBox] = []
        self._init_ui()
        # 定时刷新显示（节流，避免每字节刷新卡顿）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        self._timer.start(200)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 顶部：端口勾选行 + 操作按钮
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("监控端口:"))
        self._ports_row = QHBoxLayout()
        self._ports_row.setSpacing(6)
        self._refresh_port_checks()
        ports_container = QWidget()
        ports_container.setLayout(self._ports_row)
        top.addWidget(ports_container, 1)

        refresh_btn = QPushButton("刷新端口")
        refresh_btn.clicked.connect(self._refresh_port_checks)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        # 操作行：开始/停止 + HEX + 清空 + 导出
        op_row = QHBoxLayout()
        op_row.setSpacing(8)
        self.subscribe_btn = QPushButton("开始监控")
        self.subscribe_btn.setCheckable(True)
        self.subscribe_btn.toggled.connect(self._toggle)
        op_row.addWidget(self.subscribe_btn)
        self.hex_check = QCheckBox("HEX显示")
        op_row.addWidget(self.hex_check)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear)
        op_row.addWidget(clear_btn)
        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export)
        op_row.addWidget(export_btn)
        op_row.addStretch()
        layout.addLayout(op_row)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        # 字体/底色由 theme.py 的 QTextEdit QSS 统一控制（MONO_FONT + bg.inset）
        layout.addWidget(self.view, 1)

    # ------------------------------------------------------------------
    # 端口勾选
    # ------------------------------------------------------------------
    def _refresh_port_checks(self) -> None:
        """重建端口勾选列表（保留之前勾选状态）."""
        prev_checked = {cb.text() for cb in self._port_checks if cb.isChecked()}
        # 清空旧 checkbox
        while self._ports_row.count():
            item = self._ports_row.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._port_checks = []
        getter = getattr(self._main, "available_ports", None) or getattr(self._main, "connected_ports", None)
        ports = list(getter()) if callable(getter) else []
        for p in ports:
            cb = QCheckBox(p)
            cb.setChecked(p in prev_checked)
            self._port_checks.append(cb)
            self._ports_row.addWidget(cb)

    def _selected_ports(self) -> list[str]:
        return [cb.text() for cb in self._port_checks if cb.isChecked()]

    # ------------------------------------------------------------------
    # 监控开/关
    # ------------------------------------------------------------------
    def _toggle(self, checked: bool) -> None:
        if checked:
            ports = self._selected_ports()
            if not ports:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "提示", "请先勾选至少一个监控端口")
                self.subscribe_btn.setChecked(False)
                return
            # 未连接的端口自动打开
            is_conn = getattr(self._main, "is_port_connected", None)
            open_port = getattr(self._main, "open_port", None)
            for p in ports:
                if callable(is_conn) and not is_conn(p) and callable(open_port):
                    if not open_port(p):
                        # 打开失败则跳过该端口
                        continue
            self.subscribe_btn.setText("停止监控")
            if hasattr(self._main, "subscribe_monitor"):
                self._main.subscribe_monitor(self._selected_ports(), self._on_data)
        else:
            self.subscribe_btn.setText("开始监控")
            if hasattr(self._main, "unsubscribe_monitor"):
                self._main.unsubscribe_monitor()

    def _on_data(self, port: str, direction: str, data: bytes) -> None:
        if self.hex_check.isChecked():
            text = " ".join(f"{b:02X}" for b in data)
        else:
            text = data.decode("utf-8", errors="replace")
        # 去掉末尾换行（TX/RX chunk 常带 \r\n，避免渲染出多余空行）
        text = text.rstrip("\r\n")
        line = f"[{port}] {direction}> {text}"
        self._buffer.append(line)

    def _flush(self) -> None:
        if not self._buffer:
            return
        # 批量追加
        text = "\n".join(self._buffer)
        self._buffer.clear()
        self.view.append(text)
        # 滚到底
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.view.setTextCursor(cursor)

    def _clear(self) -> None:
        self._buffer.clear()
        self.view.clear()

    def _export(self) -> None:
        """导出当前监控区内容到文件（M1 §7.3 日志格式）."""
        text = self.view.toPlainText()
        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出监控日志", "atprobe-monitor.log", "Text (*.log *.txt)"
        )
        if path:
            from pathlib import Path

            Path(path).write_text(text, encoding="utf-8")
