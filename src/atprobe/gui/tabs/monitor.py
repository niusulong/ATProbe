"""实时监控选项卡（M6 §6）—— 端口数据流监控."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    """端口数据流监控视图（§6.2）."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._buffer: deque[str] = deque(maxlen=_MAX_LINES)
        self._init_ui()
        # 定时刷新显示（节流，避免每字节刷新卡顿）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        self._timer.start(200)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("监控端口:"))
        self.port_combo = QComboBox()
        self._refresh_ports()
        top.addWidget(self.port_combo)
        self.subscribe_btn = QPushButton("开始监控")
        self.subscribe_btn.setCheckable(True)
        self.subscribe_btn.toggled.connect(self._toggle)
        top.addWidget(self.subscribe_btn)
        self.hex_check = QCheckBox("HEX显示")
        top.addWidget(self.hex_check)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear)
        top.addWidget(clear_btn)
        top.addStretch()
        layout.addLayout(top)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        # 字体/底色由 theme.py 的 QTextEdit QSS 统一控制（MONO_FONT + bg.inset）
        layout.addWidget(self.view, 1)

    def _refresh_ports(self) -> None:
        self.port_combo.clear()
        getter = getattr(self._main, "available_ports", None) or getattr(self._main, "connected_ports", None)
        if callable(getter):
            for p in getter():
                self.port_combo.addItem(p)

    def _toggle(self, checked: bool) -> None:
        if checked:
            port = self.port_combo.currentText()
            if not port:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "提示", "请先选择监控端口")
                self.subscribe_btn.setChecked(False)
                return
            # 端口未连接时自动打开（监控通常需要先建立连接）
            is_conn = getattr(self._main, "is_port_connected", None)
            if callable(is_conn) and not is_conn(port):
                open_port = getattr(self._main, "open_port", None)
                if callable(open_port) and not open_port(port):
                    self.subscribe_btn.setChecked(False)
                    return
            self.subscribe_btn.setText("停止监控")
            if hasattr(self._main, "subscribe_monitor"):
                self._main.subscribe_monitor(port, self._on_data)
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
