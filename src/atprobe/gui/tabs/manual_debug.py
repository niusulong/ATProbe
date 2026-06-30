"""手动调试选项卡（M6 §4）—— 类似串口助手的手动发送。

直接调用 M1（不经 M3 引擎、不产生用例结果）。支持：
    - 选择端口 + 波特率/帧格式 + 打开/关闭连接（状态徽标 + 按钮切换）
    - 发送 AT 指令（可调结束符；无超时参数——超时是「用例执行」判定响应完整性的概念）
    - 命令库：本页内嵌命令树侧栏（项目→功能→命令三层树，QSplitter 左侧），
      单击命令直接发送到本页当前端口；增删改经「命令库管理」对话框。
    - 文件发送：把整个文件作为原始字节（不加结束符）写入端口。
      小文件（≤4KB）同步瞬发；大文件后台分块（块 1024/间隔 5ms）、
      进度可取消、TX 原始数据流式逐块上屏（同 RX 渲染）。

布局：左侧 = 命令库侧栏（CommandLibraryPanel），右侧 = 端口/文件发送/发送/响应四卡片。

数据模型（纯流式，串口助手语义）：
    - 发送：调 MainWindow.send_manual → PortManager.write_command，只写字节不等响应，TX 立即上屏。
    - 接收：端口打开时经 subscribe_rx 订阅原始 RX 字节流，读线程每收到 chunk 经
      Qt 信号 rx_received 切回主线程按行渲染（_on_rx_bytes）。模块回什么实时显示什么，
      不回则不显示——不引入「等待响应/超时」概念。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.icons import make_icon
from atprobe.gui.tabs.registry import ITabView, TabBinding
from atprobe.gui.theme import get_tokens
from atprobe.gui.widgets.command_library import CommandLibraryPanel
from atprobe.gui.widgets.text_render import split_lines_preserving_blanks
from atprobe.infra.serial.config import Terminator

if TYPE_CHECKING:
    from PySide6.QtCore import QThread

    from atprobe.gui.widgets.file_send import FileSendWorker
    from atprobe.infra.serial.interfaces import CancelToken

# 常见波特率（可编辑输入自定义值）
_BAUDRATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
# 自定义波特率上限（覆盖常见 USB-串口芯片支持的最高值，如 FTDI/CH340）
_MAX_BAUDRATE = 4_000_000
# 下拉末尾固定项：选中后弹输入框让用户填自定义波特率
_CUSTOM_BAUD_LABEL = "自定义…"
# 常见帧格式（3 字符紧凑写法）
_FRAMES = ["8N1", "8N2", "8E1", "8O1", "7E1", "7O1"]

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
    """手动调试视图（§4.3 布局）—— 卡片化分组，呼应 HTML 报告的视觉语言.

    对外暴露 current_port()/send_command() 供主窗口右侧「命令库」停靠面板
    双击命令时路由发送。
    """

    # 读线程收到原始 RX 字节 → 经此信号切回主线程渲染（线程安全）
    rx_received = Signal(bytes)

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._tokens = get_tokens(dark=False)
        self._terminator = Terminator.CRLF
        # 当前订阅句柄（端口打开后建立，关闭时撤销）
        self._rx_handle: object | None = None
        # 行缓冲：未遇到换行的 RX 片段累积，到换行再整行渲染
        self._rx_buffer = bytearray()
        # 上一个有效波特率（选「自定义…」取消输入时回退到此值）
        self._last_valid_baud: int = 115200
        self._init_ui()
        # RX 字节在串口读线程到达 → 信号切主线程 → 渲染
        self.rx_received.connect(self._on_rx_bytes)

    # ------------------------------------------------------------------
    # UI 构造
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # 左右分栏：左 = 命令库侧栏，右 = 端口/发送/响应
        splitter = QSplitter(Qt.Orientation.Horizontal)
        # 左侧：命令库侧栏（双击命令 → 发送到本页当前端口）
        self._cmd_panel = CommandLibraryPanel()
        self._cmd_panel.send_requested.connect(self.send_command)
        splitter.addWidget(self._cmd_panel)

        # 右侧：原有端口/发送/响应三卡片容器
        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ===== 卡片 1: 端口（选择 + 配置 + 打开/关闭）=====
        port_group = QGroupBox("端口")
        port_layout = QHBoxLayout(port_group)
        port_layout.setContentsMargins(12, 8, 12, 12)
        port_layout.setSpacing(8)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(140)
        port_layout.addWidget(self.port_combo)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_ports)
        port_layout.addWidget(refresh_btn)

        port_layout.addWidget(self._caption_label("波特率"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(_BAUDRATES)
        self.baud_combo.addItem(_CUSTOM_BAUD_LABEL)  # 末尾固定项：触发自定义输入
        # 用 setCurrentIndex（而非 setCurrentText）设默认值：editable combo 的
        # setCurrentText 只改 lineEdit 文本、不更新 currentIndex，会导致后续
        # currentIndexChanged 信号判断失准。先设 index 再连信号，避免构造期误触发。
        self.baud_combo.setCurrentIndex(_BAUDRATES.index("115200"))
        self.baud_combo.currentIndexChanged.connect(self._on_baud_index_changed)
        # 显式宽度：容纳最长项 921600（6 位，14px 下约 72px）+ padding 20 + 下拉箭头 22，
        # 留余量防字体回退/DPR 缩放导致砍首位（AdjustToContents 在 editable 模式计算不可靠）
        self.baud_combo.setMinimumWidth(120)
        port_layout.addWidget(self.baud_combo)

        port_layout.addWidget(self._caption_label("帧格式"))
        self.frame_combo = QComboBox()
        self.frame_combo.addItems(_FRAMES)
        self.frame_combo.setCurrentText("8N1")
        port_layout.addWidget(self.frame_combo)

        # 打开/关闭端口按钮（toggle 语义，文案与图标随连接状态切换）
        self.connect_btn = QPushButton("打开端口")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.setIcon(self._action_icon("connect"))
        self.connect_btn.clicked.connect(self._toggle_connect)
        port_layout.addWidget(self.connect_btn)
        port_layout.addStretch()  # 多余空间留到末尾，避免端口框/按钮被拉宽

        layout.addWidget(port_group)
        self._refresh_ports()

        # ===== 卡片 2: 文件发送（原始字节，不加结束符）=====
        file_group = QGroupBox("文件发送")
        file_layout = QVBoxLayout(file_group)
        file_layout.setContentsMargins(12, 8, 12, 12)
        file_layout.setSpacing(8)

        file_row = QHBoxLayout()
        self.file_btn = QPushButton("选择文件…")
        self.file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_btn.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_btn)

        self.file_label = QLabel("未选择文件")
        self.file_label.setObjectName("caption")
        file_row.addWidget(self.file_label, 1)

        self.file_send_btn = QPushButton("发送")
        self.file_send_btn.setObjectName("primary")
        self.file_send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_send_btn.setIcon(self._action_icon("send"))
        self.file_send_btn.setEnabled(False)
        self.file_send_btn.clicked.connect(self._send_file)
        file_row.addWidget(self.file_send_btn)

        self.file_cancel_btn = QPushButton("取消")
        self.file_cancel_btn.setObjectName("danger")
        self.file_cancel_btn.setVisible(False)
        self.file_cancel_btn.clicked.connect(self._cancel_file_send)
        file_row.addWidget(self.file_cancel_btn)
        file_layout.addLayout(file_row)

        # 进度行：仅发送中显示
        self.file_progress = QProgressBar()
        self.file_progress.setVisible(False)
        file_layout.addWidget(self.file_progress)
        layout.addWidget(file_group)

        # 文件发送状态
        self._file_path: str | None = None
        self._file_worker: FileSendWorker | None = None  # 发送中持有
        self._file_thread: QThread | None = None
        self._file_cancel_token: CancelToken | None = None
        self._file_result: tuple[bool, str] | None = None  # worker 完成结果缓存

        # ===== 卡片 3: 发送区 =====
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

        send_row = QHBoxLayout()
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setIcon(self._action_icon("send"))
        self.send_btn.clicked.connect(self._send)
        send_row.addWidget(self.send_btn)
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

        # 右侧容器装入分栏，设置初始宽度比例（命令库侧栏较窄）
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)  # 命令库侧栏
        splitter.setStretchFactor(1, 3)  # 调试区
        splitter.setSizes([260, 740])
        outer.addWidget(splitter)

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

    def current_port(self) -> str:
        """返回当前选中端口的真实名（供命令库面板路由发送目标）."""
        return self._current_port()

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
            baud = self._current_baud()
            if baud is None:
                return  # 波特率校验失败（已弹提示），放弃打开
            open_port = getattr(self._main, "open_port", None)
            if not callable(open_port):
                self._append_line("RX", "[错误] 引擎未就绪", self._tokens["danger"])
                return
            ok = open_port(port, baud, self.frame_combo.currentText())
            # 打开失败（被占用/权限/参数错，open_port 已弹错误框）→ 不记忆、不订阅。
            # 显式判 False：兼容返回 None 的旧实现（视为成功，不误杀）。
            if ok is False:
                self._refresh_ports()
                return
            # 成功：记忆自定义波特率候选 + 建立 RX 订阅（纯流式接收）
            self._remember_baud(baud)
            self._attach_rx(port)
        self._refresh_ports()

    def _on_baud_index_changed(self, index: int) -> None:
        """下拉项变更：选中「自定义…」→ 弹输入框；选中预设值 → 仅记录最近有效值.

        「自定义…」是固定触发项，确认输入合法后把值填回 currentText 并记忆为候选；
        取消或非法则回退到 _last_valid_baud，避免残留「自定义…」字样导致打开失败。
        _last_valid_baud 的权威更新统一收口在 _current_baud（toggle 时），
        此处仅在选预设值时做轻量同步（下拉是主交互路径）。
        所有 setCurrentText 都包在 blockSignals 内，避免重入本槽二次触发信号。
        """
        text = self.baud_combo.itemText(index) if index >= 0 else ""
        if text != _CUSTOM_BAUD_LABEL:
            if text.isdigit():
                self._last_valid_baud = int(text)
            return
        value, ok = QInputDialog.getInt(
            self,
            "自定义波特率",
            f"输入波特率（1 ~ {_MAX_BAUDRATE}）:",
            self._last_valid_baud,
            1,
            _MAX_BAUDRATE,
        )
        if ok:
            self._last_valid_baud = value
            target = str(value)
            # 记忆候选（内部已 blockSignals 重建）；落地的 setCurrentText 也包进
            # blockSignals，否则会再次触发 currentIndexChanged 造成重入。
            self.baud_combo.blockSignals(True)
            self._remember_baud(value)
            self.baud_combo.setCurrentText(target)
            self.baud_combo.blockSignals(False)
        else:
            # 取消 → 回退到最近有效值，不残留「自定义…」（同样防重入）
            self.baud_combo.blockSignals(True)
            self.baud_combo.setCurrentText(str(self._last_valid_baud))
            self.baud_combo.blockSignals(False)

    def _current_baud(self) -> int | None:
        """解析当前波特率输入（支持自定义），返回 int 或校验失败返回 None.

        校验：必须为纯整数、且在 1 ~ 4_000_000（覆盖常见 USB-串口芯片上限）。
        非法时不静默回落，而是弹提示返回 None，让调用方放弃打开端口。
        """
        raw = self.baud_combo.currentText().strip()
        try:
            baud = int(raw)
        except ValueError:
            QMessageBox.warning(self, "波特率无效", f"波特率必须为整数，当前输入：{raw!r}")
            return None
        if baud < 1 or baud > _MAX_BAUDRATE:
            QMessageBox.warning(
                self, "波特率无效", f"波特率需在 1 ~ {_MAX_BAUDRATE} 之间，当前：{baud}"
            )
            return None
        # 有效值收口：无论来源（下拉/键盘/自定义输入框），都同步为最近有效值，
        # 供「自定义…」取消输入时回退（避免丢弃用户键入的有效值）。
        self._last_valid_baud = baud
        return baud

    def _remember_baud(self, baud: int) -> None:
        """把使用过的自定义波特率加入下拉候选（去重、按数值升序）.

        仅在本会话生效（不持久化）；让用户下次能直接从下拉选到，不必重输。
        重建后末尾保留「自定义…」固定项。
        """
        items = [self.baud_combo.itemText(i) for i in range(self.baud_combo.count())]
        text = str(baud)
        if text in items:
            return  # 已在候选中
        values = sorted({int(x) for x in items if x.isdigit()} | {baud})
        cur = self.baud_combo.currentText()
        self.baud_combo.blockSignals(True)
        self.baud_combo.clear()
        self.baud_combo.addItems([str(v) for v in values])
        self.baud_combo.addItem(_CUSTOM_BAUD_LABEL)
        self.baud_combo.setCurrentText(cur)
        self.baud_combo.blockSignals(False)

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
        self._terminator = Terminator.CRLF if "n" in text else Terminator.CR

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
            self._render_tx_command(command)
            ok = send_manual(port, command, terminator=self._terminator)
            if not ok:
                self._append_line("RX", "[错误] 发送失败（端口未连接）", self._tokens["danger"])

    def send_command(self, command: str) -> None:
        """发送单条命令（命令库面板双击调用）：TX 上屏 + 调 send_manual。

        与处理多行的 _send 分离：不修改发送框内容，不引入副作用。
        用发送区当前全局结束符 self._terminator。
        """
        port = self._current_port()
        if not port:
            QMessageBox.warning(self, "提示", "请先选择端口")
            return
        is_conn = getattr(self._main, "is_port_connected", None)
        if callable(is_conn) and not is_conn(port):
            QMessageBox.warning(self, "提示", f"端口 {port} 未连接，请先「打开端口」")
            return
        send_manual = getattr(self._main, "send_manual", None)
        if not callable(send_manual):
            self._append_line("RX", "[错误] 引擎未就绪", self._tokens["danger"])
            return
        # TX 立即上屏（串口助手语义：发送即记录）
        self._render_tx_command(command)
        if not send_manual(port, command, terminator=self._terminator):
            self._append_line("RX", "[错误] 发送失败（端口未连接）", self._tokens["danger"])

    # ------------------------------------------------------------------
    # 文件发送（原始字节，不加结束符）
    # ------------------------------------------------------------------
    def _choose_file(self) -> None:
        """选择文件：弹出对话框，记录路径并更新标签。"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "选择要发送的文件")
        if not path:
            return
        self._file_path = path
        self._update_file_label()
        self._sync_file_send_state()

    def _update_file_label(self) -> None:
        """根据当前 _file_path 更新文件名 + 字节数标签。"""
        from pathlib import Path

        if not self._file_path:
            self.file_label.setText("未选择文件")
            return
        try:
            size = Path(self._file_path).stat().st_size
        except OSError:
            size = 0
        name = Path(self._file_path).name
        self.file_label.setText(f"{name} ({size:,} 字节)")

    def _sync_file_send_state(self) -> None:
        """根据文件选择/连接状态/发送中，刷新发送按钮可用性。"""
        port = self._current_port()
        sending = self._file_worker is not None
        is_conn = getattr(self._main, "is_port_connected", None)
        connected = bool(callable(is_conn) and is_conn(port))
        self.file_send_btn.setEnabled(
            bool(self._file_path) and connected and not sending
        )

    def _send_file(self) -> None:
        """发送文件：读取 → 按大小路由小文件同步 / 大文件后台。"""
        from pathlib import Path

        if not self._file_path:
            QMessageBox.warning(self, "提示", "请先选择文件")
            return
        port = self._current_port()
        if not port:
            QMessageBox.warning(self, "提示", "请先选择端口")
            return
        is_conn = getattr(self._main, "is_port_connected", None)
        if callable(is_conn) and not is_conn(port):
            QMessageBox.warning(self, "提示", f"端口 {port} 未连接，请先「打开端口」")
            return
        try:
            data = Path(self._file_path).read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "读取错误", f"无法读取文件：{exc}")
            return
        if not data:
            return

        from atprobe.infra.serial.config import DataStreamSpec

        if len(data) <= DataStreamSpec.chunk_threshold:
            self._send_file_small(port, data)
        else:
            self._send_file_large(port, data)

    def _send_file_small(self, port: str, data: bytes) -> None:
        """小文件同步发送（主线程单次 write_bytes）。"""
        send_file = getattr(self._main, "send_file", None)
        if not callable(send_file):
            self._append_line("RX", "[错误] 引擎未就绪", self._tokens["danger"])
            return
        # TX 原始数据流式上屏（复用 RX 渲染逻辑，方向 TX）
        self._render_tx_bytes(data)
        if not send_file(port, data):
            self._append_line("RX", "[错误] 文件发送失败（端口未连接）", self._tokens["danger"])

    def _send_file_large(self, port: str, data: bytes) -> None:
        """大文件后台分块发送（worker 线程，进度可取消）。"""
        from PySide6.QtCore import QThread

        from atprobe.gui.widgets.file_send import FileSendWorker
        from atprobe.infra.serial.interfaces import CancelToken

        get_conn = getattr(self._main, "get_connection", None)
        conn = get_conn(port) if callable(get_conn) else None
        if conn is None:
            self._append_line("RX", "[错误] 端口连接不可用", self._tokens["danger"])
            return

        self._file_cancel_token = CancelToken()
        self._file_worker = FileSendWorker(conn, data, cancel_token=self._file_cancel_token)
        # 重置结果缓存：worker.finished 时先记录，再让线程退出
        self._file_result = None
        self._file_worker.chunk_sent.connect(self._on_file_chunk_sent)
        self._file_worker.progress.connect(self._on_file_progress)
        self._file_worker.finished.connect(self._capture_file_result)

        self._file_thread = QThread()
        self._file_worker.moveToThread(self._file_thread)
        self._file_thread.started.connect(self._file_worker.run)
        # worker 完成后让线程事件循环退出（否则线程会一直挂着等事件）
        self._file_worker.finished.connect(self._file_thread.quit)
        # 线程真正退出后再做 UI 清理（此时 .wait() 必然返回，无死锁）
        self._file_thread.finished.connect(self._on_file_thread_done)
        self._file_thread.start()

        self._enter_file_sending()

    def _capture_file_result(self, ok: bool, msg: str) -> None:
        """worker 完成回调（主线程，Queued）：先记录结果，线程随后退出。"""
        self._file_result = (ok, msg)

    def _on_file_thread_done(self) -> None:
        """QThread 真正退出后（主线程）：用缓存结果做 UI 上屏与清理。"""
        from pathlib import Path

        ok, msg = self._file_result if self._file_result is not None else (False, "未知结果")
        if ok:
            self._append_line("TX", f"📄 {msg}", self._tokens["data.tx"])
        else:
            name = Path(self._file_path).name if self._file_path else "文件"
            if "已取消" in msg:
                self._append_line("TX", f"📄 {name} {msg}", self._tokens["data.tx"])
            else:
                self._append_line("RX", f"[错误] {name} {msg}", self._tokens["danger"])
        # 线程已退出，清理引用（无需再 quit/wait）
        self._file_worker = None
        self._file_thread = None
        self._file_cancel_token = None
        self._file_result = None
        self._exit_file_sending()

    def _enter_file_sending(self) -> None:
        """进入文件发送中状态：显示进度/取消，禁用相关控件（互斥）。"""
        self.file_progress.setVisible(True)
        self.file_progress.setValue(0)
        self.file_cancel_btn.setVisible(True)
        self.file_send_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        # 互斥：禁用文本发送框与文本发送
        self.send_edit.setEnabled(False)

    def _exit_file_sending(self) -> None:
        """退出文件发送中状态：恢复控件可用性（worker/线程由调用方清理）。"""
        self.file_progress.setVisible(False)
        self.file_cancel_btn.setVisible(False)
        self.file_btn.setEnabled(True)
        self.send_edit.setEnabled(True)
        self._sync_file_send_state()

    def _on_file_chunk_sent(self, chunk: bytes) -> None:
        """worker 每块发出 → 流式上屏 TX（复用渲染）。"""
        self._render_tx_bytes(chunk)

    def _on_file_progress(self, pct: int) -> None:
        self.file_progress.setValue(pct)

    def _cancel_file_send(self) -> None:
        """取消文件发送：触发 CancelToken。"""
        if self._file_cancel_token is not None:
            self._file_cancel_token.cancel()

    def _cleanup_file_send(self) -> None:
        """析构前清理：取消进行中的文件发送并等待线程退出。"""
        if self._file_cancel_token is not None:
            self._file_cancel_token.cancel()
        if self._file_thread is not None and self._file_thread.isRunning():
            self._file_thread.quit()
            self._file_thread.wait(2000)

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
        文本模式下按实际换行符显示：一个 \\n 换一行，连续 \\n 之间的空行保留，
        忠实反映模块返回的换行结构（行尾 \\r 去除，避免回车错乱）。
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
        # 按换行切：完整的行立即渲染（保留空行），最后一段（无换行）留作下次
        parts = data.split("\n")
        if len(parts) > 1:
            complete = "\n".join(parts[:-1]) + "\n"
            for line in split_lines_preserving_blanks(complete):
                self._append_line("RX", line, self._tokens["data.rx"])
        self._rx_buffer = bytearray(parts[-1].encode("utf-8"))

    def _render_tx_command(self, command: str) -> None:
        """渲染命令型 TX（手动发送/命令库双击）上屏。

        HEX 模式下显示「命令正文 + 结束符」的完整字节，让用户直观确认结束符配置生效
        —— N58 不回显 <LF>（手册 §3.2 结束符约定为 <CR>），RX 侧无法区分 \\r/\\r\\n，
        故在 TX 侧显示完整字节作为判据。非 HEX 模式仅显示命令文本。
        """
        if self.hex_check.isChecked():
            payload = command.encode("utf-8") + self._terminator.value.encode("ascii")
            hex_line = " ".join(f"{b:02X}" for b in payload)
            self._append_line("TX", hex_line, self._tokens["data.tx"])
        else:
            self._append_line("TX", command, self._tokens["data.tx"])

    def _render_tx_bytes(self, chunk: bytes) -> None:
        """渲染 TX 原始字节（文件/数据流发送）—— 复用 RX 的切分+转义逻辑.

        HEX 开关打开时按十六进制展示；否则按 UTF-8 文本拆行，行末换行符转义。
        方向标 TX、用 data.tx 色。TX 块边界即显示边界（不跨块缓冲，简化）。
        """
        if self.hex_check.isChecked():
            hex_line = " ".join(f"{b:02X}" for b in chunk)
            if hex_line:
                self._append_line("TX", hex_line, self._tokens["data.tx"])
            return
        text = chunk.decode("utf-8", errors="replace")
        for line in split_lines_preserving_blanks(text):
            self._append_line("TX", line, self._tokens["data.tx"])

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

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """页面关闭：撤销 RX 订阅 + 取消进行中的文件发送，避免悬挂线程。"""
        self._detach_rx()
        self._cleanup_file_send()
        super().closeEvent(event)
