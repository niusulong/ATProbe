"""实时监控选项卡（M6 §6.2）—— 多端口 TX/RX 数据流监控.

独立观察端口的原始收发字节流（与手动调试响应区同源）。支持：
    - 多端口勾选：同时监控多个端口，**每个端口一个独立子标签页**（数据互不混淆）
    - 自动打开：未连接的勾选端口自动打开
    - HEX/TEXT 切换（作用于当前子页）
    - 清空/导出当前子页
    - 环形缓冲（行数上限，防长监控撑爆内存）
"""

from __future__ import annotations

import codecs
from collections import deque

from PySide6.QtCore import QTimer, Signal
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
        # P1 修复：incremental decoder——跨 chunk 的多字节字符（中文/emoji）在分块
        # 边界由 decoder 缓冲重组，而非被 errors="replace 永久替换丢失
        # （manual_debug 的 B7 修复同步到 monitor）。
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        # 块上限：Qt 在 C++ 层自动丢弃最旧块，保证 QTextDocument 有界
        # （与 deque 的 _MAX_LINES 一致，实现文件 docstring 声明的"环形缓冲"意图）。
        # 注意 setMaximumBlockCount 是 QTextDocument 的方法（非 QTextEdit），对 QTextEdit
        # 需经 document() 设置；这是富文本控件唯一原生的滚动上限机制。
        self.view.document().setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self.view)

    def feed(self, direction: str, ts: str, data: bytes, hex_mode: bool) -> None:
        """喂入一个原始字节 chunk，按行切分后入 buffer.

        - HEX 模式：整个 chunk 转十六进制一行显示（不跨 chunk 累积，与 manual_debug 一致）。
        - 文本模式：incremental decoder 解码后累积到 _line_buffer；\\r\\n 归一为单个
          换行，**孤立 \\r**（N58 等设备的进度刷行）也视为换行（P1 修复：旧实现只按
          \\n 切分，纯 \\r 行永不 flush——tail 无界增长且内容不可见）；末尾悬置的
          孤立 \\r 保留待下一 chunk（可能是 \\r\\n 的前半）。
        """
        if hex_mode:
            hex_line = " ".join(f"{b:02X}" for b in data)
            if hex_line:
                self.buffer.append((direction, ts, hex_line))
            return
        text = self._decoder.decode(data)
        self._line_buffer += text
        # 行尾悬置的 \r 暂扣（下一 chunk 若以 \n 开头则拼回 \r\n，不产生空行伪影）
        hold = ""
        if self._line_buffer.endswith("\r"):
            hold = "\r"
            self._line_buffer = self._line_buffer[:-1]
        normalized = self._line_buffer.replace("\r\n", "\n").replace("\r", "\n")
        parts = normalized.split("\n")
        # 前面所有是完整行（以 \n 结尾），最后一段可能未到换行 → 留缓冲
        if len(parts) > 1:
            complete = "\n".join(parts[:-1]) + "\n"
            for line in split_lines_preserving_blanks(complete):
                self.buffer.append((direction, ts, line))
        self._line_buffer = parts[-1] + hold

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
            f"</div>"
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
        self._line_buffer = ""
        self._decoder.reset()  # 半截多字节字符一并丢弃，避免污染后续解码
        self.view.clear()

    def to_plain_text(self) -> str:
        """导出纯文本（从元组重建，格式与历史一致：[ts] dir> text）."""
        self.flush()
        return self.view.toPlainText()


class MonitorWidget(QWidget):
    """多端口数据流监控视图（§6.2，每端口独立子标签页）."""

    # P0 修复：Qt 信号桥。串口读线程的观察者回调只 emit 本信号（emit 是线程
    # 安全的，跨线程经 queued connection 投递回 GUI 线程），_on_data 槽在 GUI
    # 线程执行——旧实现回调直接调 _on_data，在读线程上下文创建 QTabWidget 子页、
    # 读控件状态、append deque（与 QTimer flush 迭代并发），属 Qt 禁止的跨线程
    # QWidget 操作（UB/崩溃）+ deque 迭代中修改竞态。
    data_received = Signal(str, str, bytes)

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._tokens = get_tokens()
        self._port_checks: list[QCheckBox] = []
        self._sub_views: dict[str, _PortSubView] = {}  # port -> 子页
        self._init_ui()
        # 信号桥接线：任何线程 emit → GUI 线程执行 _on_data
        self.data_received.connect(self._on_data)
        # 定时刷新显示（节流，避免每字节刷新卡顿）；单 timer 遍历所有子页 flush。
        # 生命周期对齐"监控中"：随订阅起停，不监控时停止空转（P0 资源正确释放）。
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush_all)
        # 不在构造时 start —— 见 _toggle

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
        getter = getattr(self._main, "available_ports", None) or getattr(
            self._main, "connected_ports", None
        )
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
        if w is None or w is self._empty_hint:
            return  # 无效索引或占位页不允许关
        port = getattr(w, "port", None)
        self._port_tabs.removeTab(idx)
        if port and port in self._sub_views:
            del self._sub_views[port]
        # removeTab 仅摘标签不销毁 widget；显式释放，避免长会话反复加/减端口累积悬挂控件
        # （与 _refresh_port_checks 重建勾选行时的销毁模式一致）
        w.deleteLater()
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
                # P0 修复：sink 用信号 emit（线程安全），观察者回调→GUI 线程槽
                self._main.subscribe_monitor(self._selected_ports(), self.data_received.emit)
            # 订阅成功后启动刷新定时器（与订阅生命周期绑定）
            self._timer.start(200)
        else:
            self.subscribe_btn.setText("开始监控")
            if hasattr(self._main, "unsubscribe_monitor"):
                self._main.unsubscribe_monitor()
            # 停止监控：冲刷残余 buffer（保留已捕获数据供回看/导出），再停定时器避免空转
            self._flush_all()
            self._timer.stop()

    def cleanup(self) -> None:
        """统一资源清理钩子（B6：tab 关闭/窗口关闭时调用）.

        monitor 无 closeEvent，旧实现 tab 关闭后定时器空转、监控订阅泄漏。
        此方法停定时器 + 退订，由 MainWindow._close_tab / closeEvent 显式调用。
        """
        try:
            self._timer.stop()
        except Exception:  # noqa: BLE001
            pass
        if hasattr(self._main, "unsubscribe_monitor"):
            try:
                self._main.unsubscribe_monitor()
            except Exception:  # noqa: BLE001
                pass

    def refresh_theme(self) -> None:
        """主题切换时刷新内联富文本配色（M11）.

        P1 修复：同步更新已存在子页的 tokens 引用——旧实现只换 MonitorWidget
        自己的 dict 引用，已创建的子页仍指旧主题色（仅新建子页生效）。
        """
        self._tokens = get_tokens()
        for sv in self._sub_views.values():
            sv._tokens = self._tokens

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
