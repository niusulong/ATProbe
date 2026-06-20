"""M6 主窗口（§2.1 三栏布局 + MDI 选项卡外壳）.

侧边导航 + 多文档选项卡工作区 + 状态栏。选项卡类型经注册表插接（§2.3）。
主窗口作为引擎与各选项卡视图的中介（视图只渲染、转发操作，逻辑在 M1-M5，§10.5）。
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from atprobe.engine import Engine, EngineConfig
from atprobe.engine.config import StopMode
from atprobe.gui.icons import make_icon
from atprobe.gui.tabs.registry import TabBinding, TabTypeRegistry, default_registry
from atprobe.gui.theme import get_tokens
from atprobe.infra.config.appconfig import AppConfig, load_app_config_file
from atprobe.infra.config.envconfig import load_env_config_file
from atprobe.infra.serial.config import FlowControl, FrameFormat, PortConfig
from atprobe.infra.serial.exceptions import PortOpenError
from atprobe.infra.serial.interfaces import CancelToken
from atprobe.infra.serial.portmanager import PortManager
from atprobe.reporting.html import HtmlReporter
from atprobe.reporting.interfaces import ReportOutput


class MainWindow(QMainWindow):
    """主窗口（§2.1）.

    对各选项卡视图暴露的共享接口（视图经 main_window 访问引擎/端口，§10.5）：
        连接管理：available_ports() / connected_ports() / is_port_connected()
                  open_port() / close_port()
        手动调试：send_manual()（只写不等响应） / subscribe_rx() / unsubscribe_rx()
        实时监控：subscribe_monitor() / unsubscribe_monitor()
        用例执行：run_cases() / stop_engine()
        其它：cases_dir() / env_config_path()
    """

    # 跨线程事件投递信号（引擎线程 → 主线程）
    progress = Signal(object)

    def __init__(self, app_config: AppConfig | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ATProbe — 串口 AT 命令自动化测试工具")
        self.resize(1200, 800)

        self._app_config = app_config or load_app_config_file(Path("atprobe.yaml"))
        self._tokens = get_tokens(dark=False)
        self._registry: TabTypeRegistry = default_registry()
        self._port_manager = PortManager()
        self._engine: Engine | None = None
        self._cancel: CancelToken | None = None
        self._monitor_handle: object | None = None
        self._monitor_sink: Any = None

        self._init_sidebar()
        self._init_tabs()
        self._init_statusbar()
        self.progress.connect(self._on_progress)

    # ------------------------------------------------------------------
    # 外壳初始化
    # ------------------------------------------------------------------
    def _init_sidebar(self) -> None:
        """构造侧边导航：深色品牌头 + 图标导航列表，覆盖原生丑陋的 Dock 标题栏."""
        dock = QDockWidget(self)
        dock.setObjectName("sidebarDock")
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setTitleBarWidget(QWidget())  # 移除原生丑陋的停靠标题栏

        # 自定义容器：深色栏，含品牌头 + 导航列表
        container = QFrame()
        container.setObjectName("sidebar")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # 品牌头（应用标识）
        header = QLabel("ATProbe")
        header.setObjectName("sidebarHeader")
        cl.addWidget(header)

        # 导航列表（自绘 SVG 图标 + 文案，替代粗糙的 Unicode 符号）
        list_widget = QListWidget()
        list_widget.setObjectName("sidebarList")
        list_widget.setIconSize(QSize(18, 18))
        list_widget.itemClicked.connect(self._on_sidebar_click)
        list_widget.itemDoubleClicked.connect(self._on_sidebar_double_click)
        # 图标用浅色（接近白）：在深色未选中栏上清晰可读，选中(主色底)上更醒目
        icon_color = self._tokens["sidebar.item.text.selected"]
        for type_name, display in self._registry.sidebar_items().items():
            item = QListWidgetItem(display)
            item.setIcon(make_icon(type_name, color=icon_color))
            item.setData(Qt.ItemDataRole.UserRole, type_name)
            list_widget.addItem(item)
        cl.addWidget(list_widget, 1)

        dock.setWidget(container)
        dock.setFixedWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self._sidebar = list_widget

    def _on_sidebar_click(self, item: QListWidgetItem) -> None:
        """单击侧栏项即打开对应选项卡（更直观）。"""
        type_name = item.data(Qt.ItemDataRole.UserRole)
        self.new_tab(str(type_name))

    def _init_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self.tabs)
        # 默认打开一个用例执行选项卡
        self.new_tab("case_execute")

    def _init_statusbar(self) -> None:
        sb = QStatusBar()
        # 状态点 + 文字：用富文本圆点，颜色随引擎状态变化（语义色，主题自适应）
        self._status_engine = QLabel(
            f'● <span style="color:{self._tokens["neutral"]}">引擎 IDLE</span>'
        )
        self._status_engine.setTextFormat(Qt.TextFormat.RichText)
        self._status_ports = QLabel("端口: 0")
        self._status_ports.setProperty("caption", True)
        self._status_clock = QLabel()
        self._status_clock.setProperty("caption", True)
        sb.addWidget(self._status_engine)
        sb.addPermanentWidget(self._status_ports)
        sb.addPermanentWidget(self._status_clock)
        self.setStatusBar(sb)
        # 时钟
        timer = QTimer(self)
        timer.timeout.connect(self._tick_clock)
        timer.start(1000)
        self._tick_clock()

    def _tick_clock(self) -> None:
        self._status_clock.setText(datetime.now().strftime("%H:%M:%S"))

    def _set_engine_status(self, state: str, color: str) -> None:
        """更新状态栏的引擎状态（带语义色圆点）。"""
        self._status_engine.setText(f'● <span style="color:{color}">引擎 {state}</span>')

    # ------------------------------------------------------------------
    # 选项卡管理（§2.3）
    # ------------------------------------------------------------------
    # 所有内置选项卡均为单例：重复打开 → 跳转到已存在的页。
    # report_view 也唯一：多个报告在其内部以「子标签」形式承载（每个报告一个子页）。
    _SINGLETON_TYPES = frozenset({
        "manual_debug", "case_execute", "monitor", "execution_progress",
        "report_view", "env_config",
    })

    def new_tab(self, type_name: str, params: dict[str, object] | None = None) -> None:
        view = self._registry.get(type_name)
        if view is None:
            return
        # 单例类：若已存在则直接激活，避免重复创建相同功能的标签页
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, QWidget) and widget.property("tab_type") == type_name:
                # report_view 已存在且带 report_path 参数 → 向其追加一个报告子标签
                if type_name == "report_view" and params and params.get("report_path"):
                    open_report = getattr(widget, "open_report", None)
                    if callable(open_report):
                        open_report(str(params["report_path"]))
                self.tabs.setCurrentIndex(i)
                return
        binding = TabBinding(type_name=type_name, params=params or {})
        widget = view.create_widget(binding, self)
        widget.setProperty("tab_type", type_name)  # 记录类型，供单例去重
        title = view.display_name
        idx = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(idx)

    def _close_tab(self, idx: int) -> None:
        # 执行中的选项卡关闭前确认（§2.3）
        self.tabs.removeTab(idx)

    def _on_sidebar_double_click(self, item: QListWidgetItem) -> None:
        type_name = item.data(Qt.ItemDataRole.UserRole)
        self.new_tab(str(type_name))

    # ------------------------------------------------------------------
    # 视图层共享接口（§10.5：视图只渲染转发，逻辑在此）
    # ------------------------------------------------------------------
    def connected_ports(self) -> list[str]:
        return [p for p in self._port_manager._configs if self._port_manager.is_connected(p)]

    def available_ports(self) -> list[str]:
        """枚举系统全部可用串口名（含未连接的，如 COM1）。供下拉框填充."""
        try:
            return [p.name for p in self._port_manager.enumerate_ports()]
        except Exception:  # noqa: BLE001
            return []

    def cases_dir(self) -> Path:
        return Path(self._app_config.cases_dir)

    def env_config_path(self) -> str | None:
        p = Path(self._app_config.env_config)
        return str(p) if p.exists() else None

    def send_manual(self, port: str, command: str) -> bool:
        """手动调试：写字符串命令到端口，不等待响应（纯流式，§4.2/§6.2）.

        响应须经 ``subscribe_rx`` 订阅后在视图侧自行接收渲染。
        返回 True 表示写入成功；未连接返回 False。
        """
        if not self._port_manager.is_connected(port):
            return False
        try:
            self._port_manager.write_command(port, command)
            return True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "发送错误", f"发送失败：{exc}")
            return False

    def subscribe_rx(self, port: str, observer: Any) -> object | None:
        """订阅端口原始 RX 字节流（手动调试/实时监控的纯流式接收）."""
        if not self._port_manager.is_connected(port):
            return None
        return self._port_manager.subscribe_rx(port, observer)

    def unsubscribe_rx(self, handle: object) -> None:
        self._port_manager.unsubscribe_rx(handle)

    def is_port_connected(self, port: str) -> bool:
        """查询端口是否已连接（视图转发，避免直接访问 _port_manager）."""
        return self._port_manager.is_connected(port)

    def open_port(
        self, port: str, baud: int = 115200, frame: str = "8N1", flow: str = "none"
    ) -> bool:
        """手动调试：打开端口（§4.1）。成功返回 True，失败弹窗并返回 False.

        Args:
            port: 端口名（COM3 等）。
            baud: 波特率。
            frame: 紧凑帧格式（如 8N1），经 FrameFormat.parse 校验。
            flow: 流控（none/rts_cts/xon_xoff）。
        """
        if self._port_manager.is_connected(port):
            return True
        try:
            cfg = PortConfig(
                name=port,
                baudrate=baud,
                frame=FrameFormat.parse(frame),
                flow_control=FlowControl(flow),
            )
            self._port_manager.open(cfg)
            return True
        except ValueError as exc:
            QMessageBox.critical(self, "参数错误", f"端口参数无效：{exc}")
            return False
        except PortOpenError as exc:
            QMessageBox.critical(self, "端口错误", str(exc))
            return False
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "端口错误", f"打开端口 {port} 失败：{exc}")
            return False

    def close_port(self, port: str) -> bool:
        """手动调试：关闭端口（幂等，§4.1）。"""
        try:
            self._port_manager.close(port)
            return True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "端口错误", f"关闭端口 {port} 失败：{exc}")
            return False

    def closeEvent(self, event: object) -> None:  # noqa: D401
        """窗口关闭：释放全部串口资源（修既有未清理的泄漏）."""
        try:
            self._port_manager.close_all()
        finally:
            super().closeEvent(event)  # type: ignore[arg-type]

    def run_cases(
        self, case_files: list[str], port: str, threshold: int,
        *, dry_run: bool = False, no_report: bool = False,
    ) -> None:
        """用例执行：驱动 M3 引擎（在引擎线程，§10.2）.

        dry_run=True 时只解析用例、检查端口，不实际执行（M5 §3.6 等价）。
        no_report=True 时不生成 HTML 报告。
        """
        from atprobe.domain.case.parser import CaseParseError, parse_case_file

        cases: list[object] = []
        for f in case_files:
            try:
                cases.append(parse_case_file(f))
            except CaseParseError as exc:
                QMessageBox.critical(self, "用例解析错误", str(exc))
                return

        # dry-run：只解析 + 端口可用性检查，不执行
        if dry_run:
            try:
                self._port_manager.open(PortConfig(name=port))
                open_ok = True
            except Exception:  # noqa: BLE001
                open_ok = False
            status = "可用" if open_ok or self._port_manager.is_connected(port) else "不可用"
            QMessageBox.information(
                self, "预演 (Dry Run)",
                f"将执行用例：{len(cases)} 个\n端口 {port}：{status}\n（未实际执行）",
            )
            return

        # 确保端口已连接
        if not self._port_manager.is_connected(port):
            try:
                self._port_manager.open(PortConfig(name=port))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "端口错误", f"打开端口 {port} 失败：{exc}")
                return

        env = None
        env_path = Path(self._app_config.env_config)
        if env_path.exists():
            try:
                env = load_env_config_file(env_path)
            except Exception:  # noqa: BLE001
                env = None

        # session_id 加随机后缀，避免连续快速运行按秒冲突覆盖报告
        import secrets

        session = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
        cfg = EngineConfig(
            ports=(PortConfig(name=port),),
            cases=tuple(cases),  # type: ignore[arg-type]
            step_timeout_default=self._app_config.step_timeout,
            pressure_pass_threshold=float(threshold),
            env_config=env,
            session_id=session,
            log_dir=self._app_config.log_dir,
        )

        self._set_engine_status("RUNNING", self._tokens["accent"])
        self._engine = Engine(sender_factory=lambda: self._port_manager)

        def _run() -> None:
            assert self._engine is not None
            result = self._engine.start(cfg, handler=lambda ev: self.progress.emit(ev))
            if no_report:
                self.progress.emit(("done_noreport", "", result.summary.passed, result.summary.failed))
                return
            # 生成报告
            rdir = Path(self._app_config.report_dir) / session / "report.html"
            HtmlReporter().render(result, ReportOutput(html_path=rdir, to_console=False))
            self.progress.emit(("done", str(rdir), result.summary.passed, result.summary.failed))

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def stop_engine(self) -> None:
        if self._engine is not None:
            self._engine.stop(mode=StopMode.ALL)

    def stop_engine_dialog(self) -> None:
        """停止引擎：弹「中断当前用例 / 停止全部」对话框（M3 §7.2，REQ-M6 §5.5）."""
        if self._engine is None:
            return
        choice = QMessageBox.question(
            self, "停止执行",
            "选择停止范围：\n  「是」= 停止全部\n  「否」= 仅中断当前用例，继续后续\n  「取消」= 不停止",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return
        mode = StopMode.ALL if choice == QMessageBox.StandardButton.Yes else StopMode.CURRENT
        self._engine.stop(mode=mode)

    def subscribe_monitor(self, port: str, sink: Any) -> None:
        """订阅端口原始字节流（M6 §6.2 实时监控，TX+RX 双向）.

        sink 签名: ``sink(port, direction, data: bytes)``，direction 为 "TX"/"RX"。
        内部同时订阅 TX（写侧）与 RX（读侧），经 PortManager.subscribe_tx/subscribe_rx
        接到串口写/读线程，每次写入或读到 chunk 即回调。
        """
        self._monitor_sink = sink
        # 撤销上一次的订阅（切换监控端口）
        if self._monitor_handle is not None:
            self.unsubscribe_monitor()
        bound_port = port

        def _tx_observer(chunk: bytes) -> None:
            if self._monitor_sink is not None:
                self._monitor_sink(bound_port, "TX", chunk)

        def _rx_observer(chunk: bytes) -> None:
            if self._monitor_sink is not None:
                self._monitor_sink(bound_port, "RX", chunk)

        # 同时订阅 TX 与 RX，句柄存为 (tx_handle, rx_handle)
        tx_h = self._port_manager.subscribe_tx(port, _tx_observer)
        rx_h = self._port_manager.subscribe_rx(port, _rx_observer)
        self._monitor_handle = (tx_h, rx_h)

    def unsubscribe_monitor(self) -> None:
        if self._monitor_handle is not None:
            handle: tuple[object, object] = self._monitor_handle  # type: ignore[assignment]
            tx_h, rx_h = handle
            self._port_manager.unsubscribe_tx(tx_h)
            self._port_manager.unsubscribe_rx(rx_h)
            self._monitor_handle = None
        self._monitor_sink = None

    # ------------------------------------------------------------------
    # 进度事件处理（主线程，经信号投递）
    # ------------------------------------------------------------------
    def _on_progress(self, ev: object) -> None:
        # 终止事件：done（生成报告）/ done_noreport（不生成报告）
        if isinstance(ev, tuple) and ev and ev[0] in ("done", "done_noreport"):
            tag, report_path, passed, failed = ev  # type: ignore[misc]
            self._set_engine_status("FINISHED", self._tokens["success"])
            # 转发完成事件给执行进度选项卡（若有）
            self._forward_progress(ev)
            if tag == "done_noreport":
                QMessageBox.information(self, "执行完成", f"通过 {passed} / 失败 {failed}\n（未生成报告）")
            else:
                QMessageBox.information(
                    self, "执行完成",
                    f"通过 {passed} / 失败 {failed}\n报告: {report_path}",
                )
                # 自动打开报告选项卡
                self.new_tab("report_view", {"report_path": report_path})
            return
        # 中间进度事件：首次事件时自动弹出执行进度选项卡，并转发
        self._forward_progress(ev)

    def _forward_progress(self, ev: object) -> None:
        """把进度事件转发给执行进度选项卡（自动弹出/复用，单例）."""
        # 首次中间事件 → 确保选项卡存在
        if not isinstance(ev, tuple):
            self.new_tab("execution_progress")
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, QWidget) and w.property("tab_type") == "execution_progress":
                handler = getattr(w, "on_event", None)
                if callable(handler):
                    handler(ev)
                return

