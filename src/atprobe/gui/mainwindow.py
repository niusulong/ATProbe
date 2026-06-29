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
from atprobe.infra.resources import resolve_workspace_path
from atprobe.infra.runtime import is_frozen
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
    # 升级检查/下载结果投递信号（工作线程 → 主线程）
    update_check_result = Signal(object)  # ReleaseInfo | None(无新版/失败) | Exception
    update_download_progress = Signal(int, int)  # (done, total)
    update_download_done = Signal(object)  # Path | Exception

    def __init__(self, app_config: AppConfig | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ATProbe — 串口 AT 命令自动化测试工具")
        self.resize(1200, 800)

        # atprobe.yaml 定位：打包态优先 exe 同级，回退 cwd（开发态 cwd=仓库根）
        if is_frozen() and resolve_workspace_path("atprobe.yaml").exists():
            _cfg_path = resolve_workspace_path("atprobe.yaml")
        else:
            _cfg_path = Path("atprobe.yaml")
        self._app_config = app_config or load_app_config_file(_cfg_path)
        # 主题状态（与 app.py 启动时加载的偏好一致）
        from atprobe.gui.theme import current_theme_is_dark

        self._dark = current_theme_is_dark()
        self._tokens = get_tokens(dark=self._dark)
        self._registry: TabTypeRegistry = default_registry()
        self._port_manager = PortManager()
        self._engine: Engine | None = None
        self._cancel: CancelToken | None = None
        self._monitor_handle: object | None = None
        self._monitor_sink: Any = None

        self._init_sidebar()
        self._init_tabs()
        self._init_statusbar()
        self._init_menubar()
        self.progress.connect(self._on_progress)
        self.update_check_result.connect(self._on_check_result)
        self.update_download_progress.connect(self._on_download_progress)
        self.update_download_done.connect(self._on_download_done)
        self._update_in_progress = False

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

    def _init_menubar(self) -> None:
        """构造菜单栏：视图（主题切换）+ 帮助（检查更新/关于）."""
        from PySide6.QtGui import QAction

        view_menu = self.menuBar().addMenu("视图(&V)")
        self._theme_action = QAction("切换深色主题", self)
        self._theme_action.setCheckable(True)
        self._theme_action.setChecked(self._dark)
        self._theme_action.toggled.connect(self._toggle_theme)
        view_menu.addAction(self._theme_action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        check_action = QAction("检查更新...", self)
        check_action.triggered.connect(lambda: self._on_check_update(manual=True))
        help_menu.addAction(check_action)
        help_menu.addSeparator()
        about_action = QAction("关于 ATProbe", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _toggle_theme(self, dark: bool) -> None:
        """切换浅/深主题：重应用 QSS + 记忆偏好（§2.2）."""
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication

        from atprobe.gui.theme import apply_theme

        self._dark = dark
        apply_theme(QApplication.instance(), dark=dark)  # type: ignore[arg-type]
        self._theme_action.setText("切换深色主题" if not dark else "切换浅色主题")
        # 刷新状态点颜色（内联令牌随主题变）
        self._tokens = get_tokens(dark=dark)
        self._set_engine_status(
            "RUNNING" if self._engine is not None else "IDLE",
            self._tokens["accent"] if self._engine is not None else self._tokens["neutral"],
        )
        QSettings("ATProbe", "ATProbe").setValue("theme/dark", dark)

    def _on_about(self) -> None:
        """关于对话框：显示版本号与项目地址."""
        import sys as _sys

        from PySide6.QtWidgets import QMessageBox

        from atprobe.infra.version import current_version

        QMessageBox.about(
            self,
            "关于 ATProbe",
            (
                f"<h3>ATProbe</h3>"
                f"<p>版本：{current_version()}</p>"
                f"<p>串口 AT 命令自动化测试工具</p>"
                f"<p>项目地址：<a href='https://github.com/niusulong/ATProbe'>"
                f"github.com/niusulong/ATProbe</a></p>"
                f"<p>Python {_sys.version.split()[0]} · MIT License</p>"
            ),
        )

    def _on_check_update(self, manual: bool = True) -> None:
        """检查更新（菜单手动触发）。完整实现见 _check_update。"""
        self._check_update(manual=manual)

    def _check_update(self, manual: bool = True) -> None:
        """后台检查更新（工作线程做 HTTP，结果经信号回主线程）。

        manual=False（启动自动）：失败/无新版静默；manual=True（手动）：弹提示。
        """
        if self._update_in_progress:
            return
        self._check_manual = manual
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self) -> None:
        from atprobe.infra.update import UpdateCheckError
        from atprobe.infra.update.checker import fetch_latest, is_newer
        from atprobe.infra.version import current_version

        try:
            info = fetch_latest()
            result = info if is_newer(info.version, current_version()) else None
            self.update_check_result.emit(result)
        except (UpdateCheckError, Exception) as exc:  # noqa: BLE001
            # 网络失败等：手动模式弹窗，自动模式静默
            self.update_check_result.emit(exc)

    def _on_check_result(self, result: object) -> None:
        """主线程：处理检查结果。"""
        from PySide6.QtWidgets import QMessageBox

        from atprobe.infra.version import current_version

        # 异常：失败
        if isinstance(result, Exception):
            if getattr(self, "_check_manual", False):
                QMessageBox.warning(self, "检查更新", f"检查失败：{result}")
            return
        # None：已是最新
        if result is None:
            if getattr(self, "_check_manual", False):
                QMessageBox.information(
                    self, "检查更新", f"当前已是最新版本 {current_version()}"
                )
            return
        # ReleaseInfo：有新版 → 弹升级对话框
        self._show_update_dialog(result)  # type: ignore[arg-type]

    def _show_update_dialog(self, info: object) -> None:
        """有新版时弹升级对话框（版本号 + changelog + 立即更新/稍后）。"""
        import html as _html

        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QTextEdit,
            QVBoxLayout,
        )

        from atprobe.infra.version import current_version

        dlg = QDialog(self)
        dlg.setWindowTitle("发现新版本")
        dlg.setMinimumWidth(480)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"<b>发现新版本 {info.version}</b>（当前 {current_version()}）"  # type: ignore[attr-defined]
        ))
        notes = QTextEdit()
        notes.setReadOnly(True)
        # HTML 转义 changelog，避免含 <,>,& 的 release body 破坏渲染
        safe_notes = _html.escape(str(getattr(info, "release_notes", "")))
        notes.setHtml(f"<pre>{safe_notes}</pre>")
        layout.addWidget(QLabel("更新内容："))
        layout.addWidget(notes, 1)
        size_mb = getattr(info, "zip_size", 0) / (1024 * 1024)
        layout.addWidget(QLabel(f"下载大小：约 {size_mb:.1f} MB"))
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("立即更新")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("稍后")
        btns.accepted.connect(lambda: self._start_download(info, dlg))
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.exec()

    def _start_download(self, info: object, dlg: object) -> None:
        """用户点立即更新：关闭对话框，启动下载（工作线程 + 进度对话框）。"""
        from PySide6.QtWidgets import QProgressDialog

        dlg.accept()  # type: ignore[attr-defined]
        self._update_in_progress = True

        self._progress_dlg = QProgressDialog(
            f"正在更新到 {info.version}...", "取消", 0, 100, self  # type: ignore[attr-defined]
        )
        self._progress_dlg.setWindowTitle("更新")
        self._progress_dlg.setMinimumDuration(0)
        self._progress_dlg.setValue(0)
        self._progress_dlg.canceled.connect(self._cancel_download)
        self._cancelled = False

        threading.Thread(target=self._download_worker, args=(info,), daemon=True).start()

    def _download_worker(self, info: object) -> None:
        import tempfile
        from pathlib import Path

        from atprobe.infra.update import DownloadCancelled, DownloadError
        from atprobe.infra.update.downloader import download

        url = getattr(info, "zip_url", "")
        name = f"ATProbe-{getattr(info, 'version', '')}-win64.zip"
        try:
            result = download(
                url,
                Path(tempfile.gettempdir()),
                filename=name,
                expected_size=getattr(info, "zip_size", None),
                progress_cb=lambda d, t: self.update_download_progress.emit(d, t),
                cancel_token=lambda: getattr(self, "_cancelled", False),
            )
            self.update_download_done.emit(result.path)
        except (DownloadCancelled, DownloadError, Exception) as exc:  # noqa: BLE001
            self.update_download_done.emit(exc)

    def _on_download_progress(self, done: int, total: int) -> None:
        if hasattr(self, "_progress_dlg") and total > 0:
            self._progress_dlg.setValue(done * 100 // total)

    def _cancel_download(self) -> None:
        self._cancelled = True

    def _on_download_done(self, result: object) -> None:
        """下载完成（Path）或失败（Exception）。"""
        from pathlib import Path

        from PySide6.QtWidgets import QApplication, QMessageBox

        from atprobe.infra.runtime import app_root
        from atprobe.infra.update import DownloadCancelled, UpdateError
        from atprobe.infra.update.installer import apply_update

        if hasattr(self, "_progress_dlg"):
            self._progress_dlg.close()
        self._update_in_progress = False

        if isinstance(result, Exception):
            if not isinstance(result, DownloadCancelled):
                QMessageBox.critical(self, "更新失败", f"下载失败：{result}")
            return
        # 下载成功 → 最终确认安装
        zip_path = Path(result)  # type: ignore[arg-type]
        choice = QMessageBox.question(
            self, "开始安装",
            "更新已就绪。点击「是」后程序将关闭并自动完成升级（约 5 秒）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            apply_update(zip_path, app_root())
        except UpdateError as exc:
            QMessageBox.critical(self, "安装失败", str(exc))
            return
        # 脚本已 detached 启动，主动退出
        QApplication.quit()

    # ------------------------------------------------------------------
    # 选项卡管理（§2.3）
    # ------------------------------------------------------------------
    # 所有内置选项卡均为单例：重复打开 → 跳转到已存在的页。
    _SINGLETON_TYPES = frozenset({
        "manual_debug", "case_execute", "monitor", "execution_progress",
        "env_config",
    })

    def new_tab(self, type_name: str, params: dict[str, object] | None = None) -> None:
        view = self._registry.get(type_name)
        if view is None:
            return
        # 单例类：若已存在则直接激活，避免重复创建相同功能的标签页
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, QWidget) and widget.property("tab_type") == type_name:
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
        return resolve_workspace_path(self._app_config.cases_dir)

    def env_config_path(self) -> str | None:
        # 优先用用户配置（app.yaml 的 env_config）；不存在则回退到项目内置示例，
        # 确保环境配置页默认打开就有内容可编辑，而非空白页。
        # 经 resolve_workspace_path 锚定工作区 + builtin_resource 兜底内置示例。
        p = resolve_workspace_path(self._app_config.env_config)
        if p.exists():
            return str(p)
        from atprobe.infra.resources import builtin_resource

        try:
            builtin = builtin_resource("env.yaml")
            return str(builtin)
        except FileNotFoundError:
            return None

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

    def send_file(self, port: str, data: bytes) -> bool:
        """手动调试：写原始字节到端口（不加结束符），供文件/二进制数据发送.

        返回 True 表示写入成功；未连接返回 False。
        小文件（≤4KB）走本同步路径；大文件由 worker 直接持连接发送。
        """
        if not self._port_manager.is_connected(port):
            return False
        try:
            self._port_manager.write_bytes(port, data)
            return True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "发送错误", f"文件发送失败：{exc}")
            return False

    def get_connection(self, port: str) -> Any:
        """手动调试：取端口底层连接（供大文件 worker 直接持有发送）。"""
        return self._port_manager.get_connection(port)

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
            log_dir=str(resolve_workspace_path(self._app_config.log_dir)),
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
            rdir = resolve_workspace_path(self._app_config.report_dir) / session / "report.html"
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

    def subscribe_monitor(self, ports: list[str], sink: Any) -> None:
        """订阅多端口原始字节流（M6 §6.2 实时监控，TX+RX 双向）.

        sink 签名: ``sink(port, direction, data: bytes)``，direction 为 "TX"/"RX"。
        对每个端口同时订阅 TX（写侧）与 RX（读侧），每次写入或读到 chunk 即回调。
        ports 为空或端口未打开时静默跳过该端口。
        """
        self._monitor_sink = sink
        # 撤销上一次的订阅（切换监控端口集）
        if self._monitor_handle is not None:
            self.unsubscribe_monitor()
        handles: list[object] = []

        for port in ports:
            if not self._port_manager.is_connected(port):
                continue
            bound_port = port

            def _tx_observer(chunk: bytes, bp: str = bound_port) -> None:
                if self._monitor_sink is not None:
                    self._monitor_sink(bp, "TX", chunk)

            def _rx_observer(chunk: bytes, bp: str = bound_port) -> None:
                if self._monitor_sink is not None:
                    self._monitor_sink(bp, "RX", chunk)

            handles.append(self._port_manager.subscribe_tx(port, _tx_observer))
            handles.append(self._port_manager.subscribe_rx(port, _rx_observer))
        self._monitor_handle = tuple(handles)

    def unsubscribe_monitor(self) -> None:
        if self._monitor_handle is not None:
            handles: tuple[object, ...] = self._monitor_handle  # type: ignore[assignment]
            for i, h in enumerate(handles):
                if i % 2 == 0:
                    self._port_manager.unsubscribe_tx(h)
                else:
                    self._port_manager.unsubscribe_rx(h)
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
                # 用系统默认浏览器打开报告（HTML 纯静态，浏览器渲染效果最佳；
                # 不再用内嵌 WebEngine 以避免引入 ~200MB 的 Chromium 体积）
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(Path(report_path).resolve()))
                )
            return
        # 中间进度事件：首次事件时自动弹出执行进度选项卡，并转发
        self._forward_progress(ev)

    def _forward_progress(self, ev: object) -> None:
        """把进度事件转发给执行进度选项卡（自动弹出/复用，单例）.

        仅在选项卡不存在时创建（首次事件自动弹出，符合用户启动执行后查看进度的预期）；
        已存在则只转发事件、不抢焦点——避免执行过程中用户切到其他页面（如实时监控）
        被反复弹回执行进度页。
        """
        w = self._find_tab("execution_progress")
        if w is not None:
            handler = getattr(w, "on_event", None)
            if callable(handler):
                handler(ev)
            return
        # 不存在 → 首次事件创建（创建即激活，这是"开始执行后弹出进度"的合理行为）
        if not isinstance(ev, tuple):
            self.new_tab("execution_progress")
            w = self._find_tab("execution_progress")
            if w is not None:
                handler = getattr(w, "on_event", None)
                if callable(handler):
                    handler(ev)

    def _find_tab(self, type_name: str) -> QWidget | None:
        """按 tab_type 属性查找已存在的选项卡 widget（单例去重用）."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, QWidget) and w.property("tab_type") == type_name:
                return w
        return None

