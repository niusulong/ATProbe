"""实时监控选项卡（M6 §6.2）—— 多端口 TX/RX 数据流监控.

独立观察端口的原始收发字节流（与手动调试响应区同源）。支持：
    - 多端口勾选：同时监控多个端口，**每个端口一个独立子标签页**（数据互不混淆）
    - 自动打开：未连接的勾选端口自动打开
    - HEX/TEXT 切换（作用于当前子页）
    - 清空/导出当前子页
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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.tabs.registry import ITabView, TabBinding
from atprobe.gui.theme import MONO_FONT, get_tokens
from atprobe.gui.widgets.text_render import split_lines_preserving_blanks

_MAX_LINES = 10000  # 环形缓冲上限（§10.3）


class MonitorTab(ITabView):
    type_name = "monitor"
    display_name = "实时监控"
    _icon = "monitor"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return MonitorWidget(binding, main_window)


class _PortSubView(QWidget):
    """单个端口的监控子页（独立 QTextEdit + 环形 buffer）.

    buffer 存 ``(direction, ts, text)`` 元组（direction ∈ {TX, RX}），flush 时批量
    渲染为带方向色的 HTML（对齐 manual_debug 终端美学：方向标记加粗方向色、
    时间戳弱化、内容方向色）。导出仍可从元组重建纯文本。
    """

    def __init__(self, port: str, tokens: dict[str, str]) -> None:
        super().__init__()
        self.port = port
        self._tokens = tokens
        self.buffer: deque[tuple[str, str, str]] = deque(maxlen=_MAX_LINES)
        # 跨 chunk 的不完整行缓冲（仅文本模式用；HEX 模式每 chunk 独立渲染不累积）
        self._line_buffer = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        layout.addWidget(self.view)

    def feed(self, direction: str, ts: str, data: bytes, hex_mode: bool) -> None:
        """喂入一个原始字节 chunk，按行切分后入 buffer.

        - HEX 模式：整个 chunk 转十六进制一行显示（不跨 chunk 累积，与 manual_debug 一致）。
        - 文本模式：累积到 _line_buffer，按 \\n 切分；完整行入 buffer（保留空行，
          忠实反映换行符数量），末尾未换行的片段留在缓冲等下次 chunk。
        """
        if hex_mode:
            hex_line = " ".join(f"{b:02X}" for b in data)
            if hex_line:
                self.buffer.append((direction, ts, hex_line))
            return
        text = data.decode("utf-8", errors="replace")
        self._line_buffer += text
        parts = self._line_buffer.split("\n")
        # 前面所有是完整行（以 \n 结尾），最后一段可能未到换行 → 留缓冲
        if len(parts) > 1:
            complete = "\n".join(parts[:-1]) + "\n"
            for line in split_lines_preserving_blanks(complete):
                self.buffer.append((direction, ts, line))
        self._line_buffer = parts[-1]

    def append(self, direction: str, ts: str, text: str) -> None:
        self.buffer.append((direction, ts, text))

    def _color_of(self, direction: str) -> str:
        """方向 → 语义色（TX 蓝 / RX 深色文本，复用主题 data.* 令牌）."""
        return self._tokens["data.tx"] if direction == "TX" else self._tokens["data.rx"]

    def _format_line_html(self, direction: str, ts: str, text: str) -> str:
        """单行 → 着色 HTML（时间戳弱化 + 方向标记加粗方向色 + 内容方向色）."""
        import html as _html

        safe = _html.escape(text, quote=False)
        color = self._color_of(direction)
        muted = self._tokens["text.secondary"]
        return (
            f'<div style="font-family:{MONO_FONT};font-size:12px;margin:1px 0;">'
            f'<span style="color:{muted};font-size:11px;">{ts}</span> '
            f'<b style="color:{color};">{_html.escape(direction)}&gt;</b> '
            f'<span style="color:{color};">{safe}</span>'
            f'</div>'
        )

    def flush(self) -> None:
        """把 buffer 批量渲染为 HTML 写入 view 并滚到底."""
        if not self.buffer:
            return
        html = "".join(self._format_line_html(d, ts, t) for d, ts, t in self.buffer)
        self.buffer.clear()
        self.view.append(html)
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.view.setTextCursor(cursor)

    def clear(self) -> None:
        self.buffer.clear()
        self.view.clear()

    def to_plain_text(self) -> str:
        """导出纯文本（从元组重建，格式与历史一致：[ts] dir> text）."""
        self.flush()
        return self.view.toPlainText()


class MonitorWidget(QWidget):
    """多端口数据流监控视图（§6.2，每端口独立子标签页）."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._tokens = get_tokens()
        self._port_checks: list[QCheckBox] = []
        self._sub_views: dict[str, _PortSubView] = {}  # port -> 子页
        self._init_ui()
        # 定时刷新显示（节流，避免每字节刷新卡顿）；单 timer 遍历所有子页 flush
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush_all)
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

        # 操作行：开始/停止 + HEX + 清空 + 导出（均作用于当前子页）
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

        # 端口子标签页（每端口一个独立子页）
        self._port_tabs = QTabWidget()
        self._port_tabs.setTabsClosable(True)
        self._port_tabs.tabCloseRequested.connect(self._on_close_sub_tab)
        self._empty_hint = QLabel("（开始监控后，每个端口将显示为独立子页）")
        self._empty_hint.setStyleSheet("color: gray; padding: 20px;")
        self._port_tabs.addTab(self._empty_hint, "—")
        layout.addWidget(self._port_tabs, 1)

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
    # 子页管理
    # ------------------------------------------------------------------
    def _ensure_sub_view(self, port: str) -> _PortSubView:
        """获取/创建某端口的子页（首次数据到达或开始监控时创建）."""
        sv = self._sub_views.get(port)
        if sv is not None:
            return sv
        sv = _PortSubView(port, self._tokens)
        self._sub_views[port] = sv
        # 移除占位空提示页（首次创建子页时）
        if self._port_tabs.indexOf(self._empty_hint) >= 0:
            self._port_tabs.removeTab(self._port_tabs.indexOf(self._empty_hint))
        self._port_tabs.addTab(sv, port)
        return sv

    def _on_close_sub_tab(self, idx: int) -> None:
        """用户关闭某端口子页：移除子页（历史数据清除）。不影响监控订阅状态。"""
        w = self._port_tabs.widget(idx)
        if w is self._empty_hint:
            return  # 占位页不允许关
        port = getattr(w, "port", None)
        self._port_tabs.removeTab(idx)
        if port and port in self._sub_views:
            del self._sub_views[port]
        # 若无子页了，恢复占位提示
        if not self._sub_views and self._port_tabs.indexOf(self._empty_hint) < 0:
            self._port_tabs.addTab(self._empty_hint, "—")

    def _current_sub_view(self) -> _PortSubView | None:
        w = self._port_tabs.currentWidget()
        if isinstance(w, _PortSubView):
            return w
        return None

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
                # 预创建子页（即使暂无数据也先显示空页）
                self._ensure_sub_view(p)
            self.subscribe_btn.setText("停止监控")
            if hasattr(self._main, "subscribe_monitor"):
                self._main.subscribe_monitor(self._selected_ports(), self._on_data)
        else:
            self.subscribe_btn.setText("开始监控")
            if hasattr(self._main, "unsubscribe_monitor"):
                self._main.unsubscribe_monitor()

    def _on_data(self, port: str, direction: str, data: bytes) -> None:
        from datetime import datetime

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sv = self._ensure_sub_view(port)
        sv.feed(direction, ts, data, self.hex_check.isChecked())

    def _flush_all(self) -> None:
        """遍历所有子页 flush 各自 buffer（单 timer）。"""
        for sv in self._sub_views.values():
            sv.flush()

    def _clear(self) -> None:
        """清空当前子页（不影响其他端口）。"""
        sv = self._current_sub_view()
        if sv is not None:
            sv.clear()

    def _export(self) -> None:
        """导出当前子页内容到文件（M1 §7.3 日志格式）。"""
        sv = self._current_sub_view()
        if sv is None:
            return
        text = sv.to_plain_text()  # 内部已 flush，确保导出最新内容
        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {sv.port} 监控日志", f"atprobe-monitor-{sv.port}.log", "Text (*.log *.txt)"
        )
        if path:
            from pathlib import Path

            Path(path).write_text(text, encoding="utf-8")
