"""手动调试选项卡（M6 §4）—— 类似串口助手的手动发送。

直接调用 M1（不经 M3 引擎、不产生用例结果）。支持：
    - 选择端口 + 波特率/帧格式 + 打开/关闭连接（状态徽标 + 按钮切换）
    - 发送 AT 指令（可调结束符；无超时参数——超时是「用例执行」判定响应完整性的概念）
    - 快捷指令：自定义增删，跨会话持久化（QSettings）

数据模型（纯流式，串口助手语义）：
    - 发送：调 MainWindow.send_manual → PortManager.write_command，只写字节不等响应，TX 立即上屏。
    - 接收：端口打开时经 subscribe_rx 订阅原始 RX 字节流，读线程每收到 chunk 经
      Qt 信号 rx_received 切回主线程按行渲染（_on_rx_bytes）。模块回什么实时显示什么，
      不回则不显示——不引入「等待响应/超时」概念。
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.icons import make_icon
from atprobe.gui.tabs.registry import ITabView, TabBinding
from atprobe.gui.theme import get_tokens

# 常见波特率（可编辑输入自定义值）
_BAUDRATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
# 常见帧格式（3 字符紧凑写法）
_FRAMES = ["8N1", "8N2", "8E1", "8O1", "7E1", "7O1"]

# 出厂默认快捷指令（用户自定义为空时回落）
_DEFAULT_QUICK_COMMANDS = ("AT", "AT+CSQ", "AT+CEREG?", "AT+CPIN?", "AT+CGDCONT?")
_MAX_QUICK_COMMANDS = 32
_SETTINGS_KEY = "manual_debug/quick_commands"
_HISTORY_KEY = "manual_debug/history"
_MAX_HISTORY = 50
# 响应区环形缓冲行数上限（§10.3，超出自动丢弃旧行）
_MAX_RESPONSE_LINES = 10000


class ManualDebugTab(ITabView):
    type_name = "manual_debug"
    display_name = "手动调试"
    _icon = "debug"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return ManualDebugWidget(binding, main_window)


class ManualDebugWidget(QWidget):
    """手动调试视图（§4.3 布局）—— 卡片化分组，呼应 HTML 报告的视觉语言."""

    # 读线程收到原始 RX 字节 → 经此信号切回主线程渲染（线程安全）
    rx_received = Signal(bytes)

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._tokens = get_tokens(dark=False)
        self._terminator = "\r\n"
        # 快捷指令列表（可能来自 QSettings 自定义，或默认值）
        self._quick_commands: list[str] = self._load_quick_commands()
        # 当前订阅句柄（端口打开后建立，关闭时撤销）
        self._rx_handle: object | None = None
        # 行缓冲：未遇到换行的 RX 片段累积，到换行再整行渲染
        self._rx_buffer = bytearray()
        self._init_ui()
        # 载入历史指令（QSettings 持久化）
        self._load_history()
        # RX 字节在串口读线程到达 → 信号切主线程 → 渲染
        self.rx_received.connect(self._on_rx_bytes)

    # ------------------------------------------------------------------
    # UI 构造
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ===== 卡片 1: 端口（选择 + 配置 + 打开/关闭）=====
        port_group = QGroupBox("端口")
        port_layout = QHBoxLayout(port_group)
        port_layout.setContentsMargins(12, 8, 12, 12)
        port_layout.setSpacing(8)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(140)
        port_layout.addWidget(self.port_combo, 1)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_ports)
        port_layout.addWidget(refresh_btn)

        port_layout.addWidget(self._caption_label("波特率"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(_BAUDRATES)
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setMaximumWidth(90)
        port_layout.addWidget(self.baud_combo)

        port_layout.addWidget(self._caption_label("帧格式"))
        self.frame_combo = QComboBox()
        self.frame_combo.addItems(_FRAMES)
        self.frame_combo.setCurrentText("8N1")
        self.frame_combo.setMaximumWidth(70)
        port_layout.addWidget(self.frame_combo)

        # 打开/关闭端口按钮（toggle 语义，文案与图标随连接状态切换）
        self.connect_btn = QPushButton("打开端口")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.setIcon(self._action_icon("connect"))
        self.connect_btn.clicked.connect(self._toggle_connect)
        port_layout.addWidget(self.connect_btn)

        layout.addWidget(port_group)
        self._refresh_ports()

        # ===== 卡片 2: 发送区 =====
        send_group = QGroupBox("发送")
        send_layout = QVBoxLayout(send_group)
        send_layout.setContentsMargins(12, 8, 12, 12)
        send_layout.setSpacing(8)

        # 多行发送框：单行回车发送，多行（Shift+Enter 换行）点「发送」按行依次发送
        self.send_edit = QPlainTextEdit()
        self.send_edit.setPlaceholderText("输入 AT 指令，回车发送；Shift+Enter 换行可多行批量发送")
        self.send_edit.setMaximumHeight(70)
        # Ctrl+Enter / Enter 发送（Enter 在单行时发送，Shift+Enter 换行由默认行为处理）
        send_sc = QShortcut(QKeySequence("Ctrl+Return"), self.send_edit)
        send_sc.activated.connect(self._send)
        send_layout.addWidget(self.send_edit)

        # 历史指令下拉（最近发送，可回选）
        hist_row = QHBoxLayout()
        hist_row.addWidget(self._caption_label("历史"))
        self.history_combo = QComboBox()
        self.history_combo.setMaximumWidth(220)
        self.history_combo.currentTextChanged.connect(self._on_history_pick)
        hist_row.addWidget(self.history_combo)
        hist_row.addStretch()
        send_layout.addLayout(hist_row)

        send_row = QHBoxLayout()
        send_btn = QPushButton("发送")
        send_btn.setObjectName("primary")
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setIcon(self._action_icon("send"))
        send_btn.clicked.connect(self._send)
        send_row.addWidget(send_btn)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.send_edit.clear)
        send_row.addWidget(clear_btn)
        send_row.addStretch()

        # 选项行（结束符 + HEX 显示）—— 串口助手语义：发送即记录、收数据即流入
        send_row.addWidget(self._caption_label("结束符"))
        self.term_combo = QComboBox()
        self.term_combo.addItems(["\\r\\n", "\\r"])
        self.term_combo.currentTextChanged.connect(self._on_term_change)
        self.term_combo.setMaximumWidth(80)
        send_row.addWidget(self.term_combo)
        self.hex_check = QCheckBox("HEX显示")
        send_row.addWidget(self.hex_check)
        send_layout.addLayout(send_row)
        layout.addWidget(send_group)

        # ===== 卡片 3: 响应区（占用主要空间）=====
        resp_group = QGroupBox("响应")
        resp_layout = QVBoxLayout(resp_group)
        resp_layout.setContentsMargins(12, 8, 12, 12)
        resp_layout.setSpacing(6)
        legend_row = QHBoxLayout()
        legend = QLabel(
            f'<span style="color:{self._tokens["data.tx"]}">■ TX</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:{self._tokens["data.rx"]}">■ RX</span>'
        )
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setObjectName("caption")
        legend_row.addWidget(legend)
        legend_row.addStretch()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_log)
        legend_row.addWidget(save_btn)
        clear_resp_btn = QPushButton("清空")
        legend_row.addWidget(clear_resp_btn)
        resp_layout.addLayout(legend_row)

        self.response_view = QTextEdit()
        self.response_view.setReadOnly(True)
        # 在 response_view 定义之后再连接，避免 mypy 无法推断 lambda 内属性类型
        clear_resp_btn.clicked.connect(self.response_view.clear)  # type: ignore[attr-defined]
        resp_layout.addWidget(self.response_view, 1)
        layout.addWidget(resp_group, 1)

        # ===== 卡片 4: 快捷指令（可自定义）=====
        layout.addWidget(self._build_quick_group())

    def _build_quick_group(self) -> QWidget:
        """快捷指令卡片：指令按钮流 + 输入框 + 添加/恢复默认."""
        quick_group = QGroupBox("快捷指令（可自定义，右键删除）")
        quick_layout = QVBoxLayout(quick_group)
        quick_layout.setContentsMargins(12, 8, 12, 12)
        quick_layout.setSpacing(8)

        # 指令按钮流容器（每次重建）
        self.quick_btn_row = QHBoxLayout()
        self.quick_btn_row.setSpacing(6)
        self.quick_btn_row.addStretch()
        self._populate_quick_buttons()
        quick_layout.addLayout(self.quick_btn_row)

        # 输入 + 添加 + 恢复默认
        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        self.quick_edit = QLineEdit()
        self.quick_edit.setPlaceholderText("输入指令，点「添加」加入快捷列表")
        edit_row.addWidget(self.quick_edit, 1)
        add_btn = QPushButton("添加")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setIcon(self._action_icon("add"))
        add_btn.clicked.connect(self._add_quick_from_edit)
        edit_row.addWidget(add_btn)
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_quick)
        edit_row.addWidget(reset_btn)
        quick_layout.addLayout(edit_row)
        return quick_group

    def _populate_quick_buttons(self) -> None:
        """清空并按 self._quick_commands 重建快捷指令按钮流."""
        # 清空旧行（保留尾部 stretch item）
        while self.quick_btn_row.count() > 1:
            item = self.quick_btn_row.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for cmd in self._quick_commands:
            btn = QPushButton(cmd)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # 左键 → 填入并发送；右键 → 删除菜单
            btn.clicked.connect(lambda _checked=False, c=cmd: self._send_quick(c))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, c=cmd: self._show_quick_menu(c)
            )
            self.quick_btn_row.insertWidget(self.quick_btn_row.count() - 1, btn)

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    def _caption_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("caption")
        return lbl

    def _action_icon(self, name: str) -> QIcon:
        """动作图标（用主色描边，在主按钮/浅按钮上均清晰）."""
        return make_icon(name, color=self._tokens["accent"])

    # ------------------------------------------------------------------
    # 端口连接管理
    # ------------------------------------------------------------------
    def _refresh_ports(self) -> None:
        """刷新端口下拉，已连接端口名加 ● 前缀徽标."""
        current = self.port_combo.currentData() or self.port_combo.currentText()
        self.port_combo.clear()
        getter = getattr(self._main, "available_ports", None) or getattr(
            self._main, "connected_ports", None
        )
        ports: list[str] = list(getter()) if callable(getter) else []
        is_connected = getattr(self._main, "is_port_connected", None)
        select_idx = 0
        for i, p in enumerate(ports):
            connected = bool(is_connected(p)) if callable(is_connected) else False
            label = f"● {p}" if connected else p
            self.port_combo.addItem(label, p)
            if p == current or (current == "" and i == 0):
                select_idx = i
        if ports:
            self.port_combo.setCurrentIndex(select_idx)
        self._sync_connect_state()

    def _current_port(self) -> str:
        """取当前选中端口的真实名（data，去掉徽标前缀）."""
        data = self.port_combo.currentData()
        return data or self.port_combo.currentText()

    def _toggle_connect(self) -> None:
        port = self._current_port()
        if not port:
            QMessageBox.warning(self, "提示", "请先选择端口")
            return
        is_conn = getattr(self._main, "is_port_connected", None)
        if callable(is_conn) and is_conn(port):
            # 当前已连接 → 先撤销本视图的 RX 订阅，再关闭
            self._detach_rx()
            if hasattr(self._main, "close_port"):
                self._main.close_port(port)
        else:
            # 当前未连接 → 打开（带波特率/帧格式）
            open_port = getattr(self._main, "open_port", None)
            if not callable(open_port):
                self._append_line("RX", "[错误] 引擎未就绪", self._tokens["danger"])
                return
            open_port(port, self._current_baud(), self.frame_combo.currentText())
            # 打开成功后建立 RX 订阅（纯流式接收）
            self._attach_rx(port)
        self._refresh_ports()

    def _current_baud(self) -> int:
        try:
            return int(self.baud_combo.currentText().strip())
        except ValueError:
            return 115200

    def _sync_connect_state(self) -> None:
        """根据当前端口连接状态切换按钮文案/图标与参数控件可用性."""
        port = self._current_port()
        is_conn = getattr(self._main, "is_port_connected", None)
        connected = bool(callable(is_conn) and is_conn(port))
        if connected:
            self.connect_btn.setText("关闭端口")
            self.connect_btn.setObjectName("danger")
            self.connect_btn.setIcon(self._action_icon("disconnect"))
            self.baud_combo.setEnabled(False)
            self.frame_combo.setEnabled(False)
        else:
            self.connect_btn.setText("打开端口")
            self.connect_btn.setObjectName("primary")
            self.connect_btn.setIcon(self._action_icon("connect"))
            self.baud_combo.setEnabled(True)
            self.frame_combo.setEnabled(True)
        # objectName 变了需强制重算 QSS
        self.connect_btn.style().unpolish(self.connect_btn)  # type: ignore[union-attr]
        self.connect_btn.style().polish(self.connect_btn)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    def _on_term_change(self, text: str) -> None:
        self._terminator = "\r\n" if "n" in text else "\r"

    def _send_quick(self, cmd: str) -> None:
        self.send_edit.setPlainText(cmd)
        self._send()

    def _send(self) -> None:
        port = self._current_port()
        if not port:
            QMessageBox.warning(self, "提示", "请先选择端口")
            return
        # 多行按行依次发送（§4.4 多行发送）
        raw = self.send_edit.toPlainText()
        commands = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not commands:
            return
        is_conn = getattr(self._main, "is_port_connected", None)
        if callable(is_conn) and not is_conn(port):
            QMessageBox.warning(self, "提示", f"端口 {port} 未连接，请先「打开端口」")
            return
        send_manual = getattr(self._main, "send_manual", None)
        if not callable(send_manual):
            self._append_line("RX", "[错误] 引擎未就绪", self._tokens["danger"])
            return
        for command in commands:
            # TX 立即上屏（串口助手语义：发送即记录）
            self._append_line("TX", command, self._tokens["data.tx"])
            ok = send_manual(port, command)
            if not ok:
                self._append_line("RX", "[错误] 发送失败（端口未连接）", self._tokens["danger"])
        # 记录历史指令（去重，最多 50 条，持久化）
        self._add_history(commands[-1])

    def _on_history_pick(self, text: str) -> None:
        """从历史下拉回选指令：填入发送框（不自动发送，让用户可改后发）."""
        if text:
            self.send_edit.setPlainText(text)

    def _add_history(self, command: str) -> None:
        """把指令加入历史下拉（去重、置顶、限 50 条），QSettings 持久化."""
        items = [self.history_combo.itemText(i) for i in range(self.history_combo.count())]
        if command in items:
            items.remove(command)
        items.insert(0, command)
        items = items[:50]
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        self.history_combo.addItems(items)
        self.history_combo.blockSignals(False)
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/history", items)

    # ------------------------------------------------------------------
    # RX 流式接收（读线程 → 信号 → 主线程渲染）
    # ------------------------------------------------------------------
    def _attach_rx(self, port: str) -> None:
        """打开端口后建立 RX 订阅（只订阅一次）."""
        self._detach_rx()
        subscribe = getattr(self._main, "subscribe_rx", None)
        if not callable(subscribe):
            return
        self._rx_buffer.clear()
        self._rx_handle = subscribe(port, self._on_rx_chunk)

    def _detach_rx(self) -> None:
        if self._rx_handle is None:
            return
        unsubscribe = getattr(self._main, "unsubscribe_rx", None)
        if callable(unsubscribe):
            unsubscribe(self._rx_handle)
        self._rx_handle = None
        self._rx_buffer.clear()

    def _on_rx_chunk(self, chunk: bytes) -> None:
        """串口读线程回调：转发到主线程（避免在非主线程操作 UI）."""
        self.rx_received.emit(chunk)

    def _on_rx_bytes(self, chunk: bytes) -> None:
        """主线程槽：按换行把 RX 字节拆成行渲染，未到换行的尾部留作缓冲.

        HEX 开关打开时，每行以十六进制展示（M1 §7.2）。
        """
        if self.hex_check.isChecked():
            hex_line = " ".join(f"{b:02X}" for b in chunk)
            if hex_line:
                self._append_line("RX", hex_line, self._tokens["data.rx"])
            self._rx_buffer.clear()
            return
        text = chunk.decode("utf-8", errors="replace")
        self._rx_buffer.extend(text.encode("utf-8"))
        data = self._rx_buffer.decode("utf-8", errors="replace")
        # 按换行切：完整的行立即渲染，最后一段（无换行）留作下次
        parts = data.split("\n")
        for line in parts[:-1]:
            stripped = line.rstrip("\r")
            if stripped:
                self._append_line("RX", stripped, self._tokens["data.rx"])
        self._rx_buffer = bytearray(parts[-1].encode("utf-8"))

    def _load_history(self) -> None:
        """从 QSettings 载入历史指令下拉."""
        raw = QSettings("ATProbe", "ATProbe").value(_HISTORY_KEY)
        items = list(raw) if isinstance(raw, (list, tuple)) else []
        items = [str(x).strip() for x in items if str(x).strip()]
        if items:
            self.history_combo.addItems(items)

    # ------------------------------------------------------------------
    # 快捷指令自定义 + 持久化
    # ------------------------------------------------------------------
    def _add_quick_from_edit(self) -> None:
        cmd = self.quick_edit.text().strip()
        if not cmd:
            return
        self._add_quick(cmd)
        self.quick_edit.clear()

    def _add_quick(self, cmd: str) -> None:
        if cmd in self._quick_commands:
            return
        if len(self._quick_commands) >= _MAX_QUICK_COMMANDS:
            QMessageBox.information(self, "提示", f"快捷指令已达上限（{_MAX_QUICK_COMMANDS} 条）")
            return
        self._quick_commands.append(cmd)
        self._save_quick_commands(self._quick_commands)
        self._populate_quick_buttons()

    def _remove_quick(self, cmd: str) -> None:
        if cmd in self._quick_commands:
            self._quick_commands.remove(cmd)
            self._save_quick_commands(self._quick_commands)
            self._populate_quick_buttons()

    def _reset_quick(self) -> None:
        self._quick_commands = list(_DEFAULT_QUICK_COMMANDS)
        self._save_quick_commands(self._quick_commands)
        self._populate_quick_buttons()

    def _show_quick_menu(self, cmd: str) -> None:
        menu = QMenu(self)
        act_del = menu.addAction("删除「" + cmd + "」")
        chosen = menu.exec(self.cursor().pos())
        if chosen is act_del:
            self._remove_quick(cmd)

    def _load_quick_commands(self) -> list[str]:
        """从 QSettings 读取自定义快捷指令；无则回落默认五条."""
        s = QSettings("ATProbe", "ATProbe")
        raw = s.value(_SETTINGS_KEY)
        if raw is None:
            return list(_DEFAULT_QUICK_COMMANDS)
        # QSettings 可能返回 list / QStringList / str
        if isinstance(raw, (list, tuple)):
            cmds = [str(x).strip() for x in raw if str(x).strip()]
        else:
            cmds = [str(raw).strip()] if str(raw).strip() else []
        return cmds if cmds else list(_DEFAULT_QUICK_COMMANDS)

    def _save_quick_commands(self, cmds: list[str]) -> None:
        s = QSettings("ATProbe", "ATProbe")
        s.setValue(_SETTINGS_KEY, cmds)
        s.sync()

    # ------------------------------------------------------------------
    # 日志保存 + 响应区渲染
    # ------------------------------------------------------------------
    def _save_log(self) -> None:
        """保存响应区内容到文件（复用 M1 §7.3 思路，最小实现）."""
        from PySide6.QtWidgets import QFileDialog

        text = self.response_view.toPlainText()
        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存响应日志", "atprobe-debug.log", "Text (*.log *.txt)"
        )
        if path:
            from pathlib import Path

            Path(path).write_text(text, encoding="utf-8")

    def _append_line(self, direction: str, text: str, color: str) -> None:
        """向响应区追加带方向色的行（TX 蓝 / RX 深色，时间戳弱化）.

        视觉语言对齐 HTML 报告的终端美学：
        - 方向标记 (TX>/RX>) 等宽加粗、方向色
        - 时间戳弱化为 secondary 灰，小一号
        - 内容用方向色，强化"谁说的"
        """
        import html as _html
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        safe = _html.escape(text, quote=False)
        muted = self._tokens["text.secondary"]
        self.response_view.append(
            f'<div style="font-family:\'JetBrains Mono\',\'Cascadia Code\',Consolas,monospace;'
            f'font-size:12px;margin:1px 0;">'
            f'<span style="color:{muted};font-size:11px;">{ts}</span> '
            f'<b style="color:{color};">{direction}&gt;</b> '
            f'<span style="color:{color};">{safe}</span>'
            f'</div>'
        )
        # 环形缓冲：超过行数上限丢弃旧行（§10.3，防止长会话撑爆内存）
        doc = self.response_view.document()
        if doc.blockCount() > _MAX_RESPONSE_LINES:
            cursor = self.response_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
            cursor.movePosition(cursor.MoveOperation.Right, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
