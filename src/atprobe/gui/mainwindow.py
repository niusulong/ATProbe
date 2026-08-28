"""M6 主窗口（§2.1 三栏布局 + MDI 选项卡外壳）.

侧边导航 + 多文档选项卡工作区 + 状态栏。选项卡类型经注册表插接（§2.3）。
主窗口作为引擎与各选项卡视图的中介（视图只渲染、转发操作，逻辑在 M1-M5，§10.5）。
"""

from __future__ import annotations

import logging
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

from atprobe.domain.report.models import ExecutionResult
from atprobe.engine import Engine, EngineConfig
from atprobe.engine.config import EngineState, StopMode
from atprobe.gui.controllers import UpdateController
from atprobe.gui.icons import make_icon
from atprobe.gui.tabs.registry import TabBinding, TabTypeRegistry, default_registry
from atprobe.gui.theme import get_tokens, read_theme_pref, write_theme_pref
from atprobe.infra.config.appconfig import AppConfig, load_app_config_file
from atprobe.infra.config.envconfig import load_env_config_file
from atprobe.infra.resources import resolve_workspace_path
from atprobe.infra.runtime import is_frozen
from atprobe.infra.serial.config import (
    DataStreamSpec,
    FlowControl,
    FrameFormat,
    PortConfig,
    Terminator,
)
from atprobe.infra.serial.exceptions import PortBusyError, PortOpenError
from atprobe.infra.serial.interfaces import CancelToken
from atprobe.infra.serial.portmanager import PortManager
from atprobe.infra.serial.rawlog import RawLogger
from atprobe.reporting.html import HtmlReporter
from atprobe.reporting.interfaces import ReportOutput

_log = logging.getLogger("atprobe.engine_gui")

# LED 状态 → token key 映射（M11：主题切换时按当前状态重设颜色）
_LED_COLOR = {
    "IDLE": "neutral",
    "RUNNING": "accent",
    "FINISHED": "success",
    "ERROR": "danger",
}


def _startup_error_event(result: ExecutionResult) -> tuple[str, str] | None:
    """启动级错误的消费侧事件判定（设计 §4.4②，纯函数供 _run 与测试共用）.

    engine.start 正常返回但 ``result.error`` 非空（sender 解析失败/端口全部打开
    失败，case_results 为空）时，应投递 engine_error 事件而非走 done 分支——
    旧实现消费侧呈现为绿色 FINISHED + "通过 0 / 失败 0" 弹窗，失败原因不可见。
    返回 ``("engine_error", "执行失败：{error}")``；无启动错误返回 None。
    """
    if result.error:
        return ("engine_error", f"执行失败：{result.error}")
    return None


class CaseParseCache:
    """路径级用例解析缓存（Pf-3）：目录加载与 run_cases 共用，消除重复 parse.

    用例树的 ``_load_path``（分片解析）与 ``run_cases`` 原本各自 parse 同一批
    YAML——执行前必经加载，同批文件至少解析两次。以 ``(路径, mtime)`` 为键：
    文件在加载后、执行前被编辑 → mtime 变化 → 重解析，不会执行过期内容。
    加锁保护：当前两处都在主线程调用，锁为后续任何一方移后台时的前向保障。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, object]] = {}

    def get_or_parse(self, path: Path) -> object:
        """命中同一 mtime 的缓存直接复用；未命中则解析并缓存.

        解析失败向上抛 ``CaseParseError``（语义与直调 parse_case_file 一致，
        调用方原有的错误处理/弹窗逻辑不变）。
        """
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        key = str(path)
        with self._lock:
            hit = self._entries.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        from atprobe.domain.case.parser import parse_case_file

        case = parse_case_file(path)  # 锁外解析：YAML 慢，不阻塞并发读
        with self._lock:
            self._entries[key] = (mtime, case)
        return case


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
    # 后台打开端口结果（工作线程 → 主线程，Pf-3）：(port, ok, 错误消息)
    port_open_result = Signal(str, bool, str)

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
        # 主题状态：优先读持久化偏好（QSettings），无记录时回退全局状态。
        # P2 修复（单一真相源）：旧实现只读全局 _THEME_DARK（app.py 启动时桥接），
        # 单独构造 MainWindow（测试/嵌入复用）会忽略已持久化的主题偏好。
        # P3 收敛：读取经 theme.read_theme_pref 单点（与 app.py 启动共用，
        # type=bool 归一在单点内完成）。
        from atprobe.gui.theme import current_theme_is_dark

        _pref = read_theme_pref()
        self._dark = current_theme_is_dark() if _pref is None else _pref
        self._tokens = get_tokens(dark=self._dark)
        self._registry: TabTypeRegistry = default_registry()
        # M8 修复：常驻 RawLogger 注入共享 PortManager 与 Engine——GUI 引擎执行
        # 此前不落原始日志（sender_factory 注入裸 PM，connection._raw_logger 为
        # None，_bind_case_logs 只建目录不写文件）。写入随引擎每用例绑定。
        self._raw_logger = RawLogger()
        self._raw_logger.start()
        self._port_manager = PortManager(raw_logger=self._raw_logger)
        self._engine: Engine | None = None
        self._cancel: CancelToken | None = None
        self._monitor_handle: object | None = None
        self._monitor_sink: Any = None
        # 端口枚举缓存（available_ports 的 2 秒 TTL，见该方法）
        self._ports_cache: list[str] | None = None
        self._ports_cache_at: float = 0.0
        # 引擎工作线程引用（closeEvent join 用，P3）
        self._engine_thread: threading.Thread | None = None
        # 用例解析缓存（Pf-3）：case_execute 目录加载填充、run_cases 复用
        self._case_cache = CaseParseCache()
        # 后台打开在途端口集合（Pf-3）：防同端口重复发起
        self._open_in_flight: set[str] = set()
        # 环境配置页引用：开启时由内存 EnvConfig 供 run_cases 实时生效（所见即所跑）；
        # 关闭后置 None，run_cases 回退到磁盘读取。
        self._env_widget: Any = None

        self._init_sidebar()
        self._init_tabs()
        self._init_statusbar()
        # D-1 拆分：更新流程（检查/下载/安装确认）收敛 UpdateController——
        # 本类只保留实例化与菜单入口，弹窗呈现随迁控制器（以本窗口为弹窗父级）
        self._update_controller = UpdateController(parent=self)
        self._init_menubar()
        self.progress.connect(self._on_progress)
        self.port_open_result.connect(self._on_port_open_result)
        # F-17：closeEvent 重入防护——等待循环期间用户再点 X 会二次进入
        self._closing = False
        # LED 信号灯呼吸动效（仅 RUNNING 状态闪烁，体现「引擎在跑」的活力）
        self._led_state = "IDLE"
        self._led_color = self._tokens["neutral"]
        self._led_blink_phase = True
        self._led_timer = QTimer(self)
        self._led_timer.setInterval(600)
        self._led_timer.timeout.connect(self._blink_led)

    # ------------------------------------------------------------------
    # 外壳初始化
    # ------------------------------------------------------------------
    def _init_sidebar(self) -> None:
        """构造侧边导航：深色品牌头 + 图标导航列表，覆盖原生丑陋的 Dock 标题栏."""
        dock = QDockWidget(self)
        dock.setObjectName("sidebarDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
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
            f'<span style="color:{self._tokens["neutral"]};font-size:13px;">●</span> '
            f'<span style="color:{self._tokens["text.secondary"]}">引擎 IDLE</span>'
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
        """更新引擎状态并驱动 LED 信号灯.

        RUNNING 时 LED 呼吸闪烁（亮/暗相位交替，体现「引擎在跑」的活力）；
        其它状态常亮（IDLE 中性 / FINISHED 绿 / ERROR 红）。
        """
        self._led_state = state
        self._led_color = color
        if state == "RUNNING":
            self._led_blink_phase = True
            self._led_timer.start()
        else:
            self._led_timer.stop()
            self._led_blink_phase = True  # 常亮相位
        self._render_engine_status()

    def _render_engine_status(self) -> None:
        """按当前 LED 相位渲染状态栏（圆点色 + 中性灰文字）."""
        color = self._led_color
        # RUNNING 暗相位：状态色加低透明（Qt6 支持 #RRGGBBAA），形成呼吸
        if self._led_state == "RUNNING" and not self._led_blink_phase:
            color = self._led_color + "33"
        self._status_engine.setText(
            f'<span style="color:{color};font-size:13px;">●</span> '
            f'<span style="color:{self._tokens["text.secondary"]}">引擎 {self._led_state}</span>'
        )

    def _blink_led(self) -> None:
        """LED 呼吸：切换亮/暗相位并重渲染."""
        self._led_blink_phase = not self._led_blink_phase
        self._render_engine_status()

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
        check_action.triggered.connect(lambda: self._update_controller.check(manual=True))
        help_menu.addAction(check_action)
        log_action = QAction("打开日志目录", self)
        log_action.triggered.connect(self._open_log_dir)
        help_menu.addAction(log_action)
        help_menu.addSeparator()
        about_action = QAction("关于 ATProbe", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _toggle_theme(self, dark: bool) -> None:
        """切换浅/深主题：重应用 QSS + 记忆偏好（§2.2）.

        注意（有意设计）：主题切换不重渲染监控/执行进度等视图的**历史行**——
        这些视图按渲染快照语义工作（append-only 文档），旧行保留渲染时的配色；
        refresh_theme 只换令牌供后续新行使用。逐行重染成本高且可能扰动滚动位置，
        新会话（清空/重开）自然用新主题。
        """
        from PySide6.QtWidgets import QApplication

        from atprobe.gui.theme import apply_theme

        self._dark = dark
        apply_theme(QApplication.instance(), dark=dark)  # type: ignore[arg-type]
        self._theme_action.setText("切换深色主题" if not dark else "切换浅色主题")
        # 刷新主窗口令牌 + 状态点颜色（M11：用当前 LED 状态而非重推 RUNNING/IDLE）
        self._tokens = get_tokens(dark=dark)
        led_key = _LED_COLOR.get(self._led_state, "neutral")
        led_color = self._tokens.get(led_key, self._tokens["neutral"])
        self._set_engine_status(self._led_state, led_color)
        # M11 修复：遍历所有 tab 调 refresh_theme（若有），刷新内联富文本配色。
        # 旧实现各 tab 硬编码 get_tokens(dark=False)，切深色后 TX/RX 色块/状态字色不变。
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if widget is None:
                continue
            refresher = getattr(widget, "refresh_theme", None)
            if callable(refresher):
                try:
                    refresher()
                except Exception:  # noqa: BLE001
                    _log.debug("refresh_theme 抛异常", exc_info=True)
        # P1/P2 修复（写入持久化）：显式 sync（旧实现靠临时 QSettings 对象析构
        # 触发落盘，进程异常退出时 5 秒自动 sync 定时器可能未跑到 → 偏好丢失）。
        # P3 收敛：写入经 theme.write_theme_pref 单点。
        write_theme_pref(dark)

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

    def _open_log_dir(self) -> None:
        """打开日志目录（资源管理器定位 atprobe.log，便于非技术用户排查）."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from atprobe.infra.logging_config import _log_dir

        try:
            log_dir = _log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法打开", f"日志目录不可访问：{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir.resolve())))

    # ------------------------------------------------------------------
    # 选项卡管理（§2.3）
    # ------------------------------------------------------------------
    # 所有内置选项卡均为单例：重复打开 → 跳转到已存在的页。
    _SINGLETON_TYPES = frozenset(
        {
            "manual_debug",
            "case_execute",
            "monitor",
            "execution_progress",
            "env_config",
        }
    )

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
        # 环境配置页：登记引用，供 run_cases 读取内存 EnvConfig 实时生效
        if type_name == "env_config":
            self._env_widget = widget
        title = view.display_name
        idx = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(idx)

    def _close_tab(self, idx: int) -> None:
        # B6 修复：关闭 tab 时调 widget 的 cleanup（若有），释放 RX 订阅/定时器/worker。
        # Qt 的 removeTab 不触发 closeEvent 也不 deleteLater，旧实现仅清理 env_config
        # 引用，导致 manual_debug 的 RX 订阅、monitor 的定时器/订阅在 tab 关闭后泄漏。
        widget = self.tabs.widget(idx)
        if widget is not None:
            # 环境配置页关闭：有未保存改动时先提示（P2 修复：旧实现直接置
            # _env_widget=None，编辑静默丢弃，与"所见即所跑"语义相悖）
            if widget.property("tab_type") == "env_config":
                is_dirty = getattr(widget, "is_dirty", None)
                if callable(is_dirty) and is_dirty():
                    from PySide6.QtWidgets import QMessageBox

                    ret = QMessageBox.question(
                        self,
                        "未保存的环境配置",
                        "环境配置有未保存的改动，关闭前保存吗？",
                        QMessageBox.StandardButton.Save
                        | QMessageBox.StandardButton.Discard
                        | QMessageBox.StandardButton.Cancel,
                    )
                    if ret is QMessageBox.StandardButton.Save:
                        saver = getattr(widget, "_save", None)
                        if callable(saver):
                            saver()
                    elif ret is QMessageBox.StandardButton.Cancel:
                        return  # 取消关闭
                self._env_widget = None
            # 统一调用 cleanup（经 getattr 安全访问，未实现则跳过）
            cleaner = getattr(widget, "cleanup", None)
            if callable(cleaner):
                try:
                    cleaner()
                except Exception:  # noqa: BLE001 - 清理失败不阻断关闭
                    _log.debug("tab cleanup 抛异常", exc_info=True)
        self.tabs.removeTab(idx)
        if widget is not None:
            widget.deleteLater()

    def _on_sidebar_double_click(self, item: QListWidgetItem) -> None:
        type_name = item.data(Qt.ItemDataRole.UserRole)
        self.new_tab(str(type_name))

    # ------------------------------------------------------------------
    # 视图层共享接口（§10.5：视图只渲染转发，逻辑在此）
    # ------------------------------------------------------------------
    def connected_ports(self) -> list[str]:
        # configs() 持锁快照（批 2a Task 7）：裸迭代 _configs 与 open/close 并发时
        # 会 RuntimeError（F-3 同型崩溃点），且越封装访问私有字段（§3.3）。
        return [p for p in self._port_manager.configs() if self._port_manager.is_connected(p)]

    def available_ports(self) -> list[str]:
        """枚举系统全部可用串口名（含未连接的，如 COM1）。供下拉框填充.

        P2 修复：2 秒 TTL 缓存——多个 tab 构造/刷新都调用本方法，USB 串口多时
        枚举可达秒级，反复调用会连续阻塞 GUI 线程。
        """
        import time as _time

        now = _time.monotonic()
        if self._ports_cache is not None and now - self._ports_cache_at < 2.0:
            return list(self._ports_cache)
        try:
            names = [p.name for p in self._port_manager.enumerate_ports()]
        except Exception:  # noqa: BLE001
            names = []
        self._ports_cache = names
        self._ports_cache_at = now
        return list(names)

    def cases_dir(self) -> Path:
        return resolve_workspace_path(self._app_config.cases_dir)

    @property
    def case_parse_cache(self) -> CaseParseCache:
        """共享用例解析缓存（Pf-3）：case_execute 目录加载填充、run_cases 复用."""
        return self._case_cache

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

    def engine_state(self) -> str:
        """当前引擎状态（str Enum，"IDLE"/"RUNNING"/"FINISHED"/"ERROR"）.

        供 tab 侧（手动调试等）在发送前检查引擎是否运行，避免与引擎争抢串口。
        """
        if self._engine is None:
            return "IDLE"
        return str(self._engine.state().value)

    def _file_send_active(self) -> bool:
        """manual_debug 选项卡的文件发送是否进行中（2b⑧ 启动前探测）.

        经 ``_find_tab("manual_debug")`` 定位 widget 后读其 ``_file_worker`` /
        ``_file_thread``（getattr 防御：tab 未开、替身缺属性或属性非预期形态
        一律视为不在发送，不阻断启动）。worker 与 thread 在 manual_debug 中
        同置同清，双检仅为对竞态窗口（set 间隙）保守。
        """
        tab = self._find_tab("manual_debug")
        if tab is None:
            return False
        if getattr(tab, "_file_worker", None) is not None:
            return True
        thread = getattr(tab, "_file_thread", None)
        is_running = getattr(thread, "isRunning", None)
        return callable(is_running) and bool(is_running())

    def send_manual(self, port: str, command: str, *, terminator: Terminator | None = None) -> bool:
        """手动调试：写字符串命令到端口，不等待响应（纯流式，§4.2/§6.2）.

        响应须经 ``subscribe_rx`` 订阅后在视图侧自行接收渲染。

        返回值语义（2a）：True=已写入；False=未发送——引擎运行/端口忙/发送异常
        分支已弹框告知原因（调用方不得据此再渲染误导文案）；未连接分支静默返回
        False（调用方各自检查连接并提示，不重复弹框）。

        Args:
            terminator: 逐命令覆盖的结束符；None 时用连接级 PortConfig.terminator。
                手动调试页结束符下拉的选择经此透传（修：UI 选择原本被忽略）。
        """
        # P1 修复：引擎执行期间禁止手动写入同一端口——引擎正在 send_command 等待
        # 响应时，手动命令的回显/回包会并入引擎响应缓冲，污染断言（跨流串扰）。
        if self._engine is not None and self._engine.state() is EngineState.RUNNING:
            QMessageBox.warning(
                self, "发送被拒绝", "测试引擎正在运行，请先停止后再手动发送（避免污染引擎响应）"
            )
            return False
        if not self._port_manager.is_connected(port):
            return False
        try:
            self._port_manager.write_command(port, command, terminator=terminator)
            return True
        except PortBusyError:
            # P1-3 命令锁撞锁（连接层快速失败）：并发发送周期（引擎命令/批 2b 数据
            # 发送周期）持锁时 write_command 抛出——友好提示而非通用错误框。
            QMessageBox.information(self, "端口忙", "另一发送周期进行中(如引擎命令),请稍候再发送")
            return False
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "发送错误", f"发送失败：{exc}")
            return False

    def send_file(self, port: str, data: bytes) -> bool:
        """手动调试：持锁分块写原始字节到端口（不加结束符），供文件/二进制数据发送.

        返回值语义（2a，同 send_manual）：True=已写入；False=未发送——引擎运行/
        端口忙/发送异常分支已弹框告知原因；未连接分支静默返回 False。
        小文件（≤4KB）走本同步路径（默认 spec 单块写）；大文件由 worker 直接
        持连接调 write_data——两者均持端口命令锁，与引擎命令/数据周期互斥。
        """
        # P1 修复：同 send_manual，引擎运行期间拒绝（避免污染引擎响应缓冲）
        if self._engine is not None and self._engine.state() is EngineState.RUNNING:
            QMessageBox.warning(
                self, "发送被拒绝", "测试引擎正在运行，请先停止后再发送文件（避免污染引擎响应）"
            )
            return False
        if not self._port_manager.is_connected(port):
            return False
        try:
            spec = DataStreamSpec(data=data)
            self._port_manager.write_data(port, spec)
            return True
        except PortBusyError:
            # P1-3/P1-8 撞锁快速失败（并发发送周期持端口命令锁时 write_data 抛出）
            # ——与 send_manual 的 2a 分支同文案风格
            QMessageBox.information(self, "端口忙", "另一发送周期进行中(如引擎命令),请稍候再发送")
            return False
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

    def _open_port_impl(
        self, port: str, baud: int, frame: str, flow: str
    ) -> tuple[bool, str | None]:
        """执行端口打开（不弹窗——可在工作线程调用）。返回 (ok, 错误消息)."""
        if self._port_manager.is_connected(port):
            return True, None
        try:
            cfg = PortConfig(
                name=port,
                baudrate=baud,
                frame=FrameFormat.parse(frame),
                flow_control=FlowControl(flow),
                urc_filter=self._app_config.urc_filter,
            )
            self._port_manager.open(cfg)
            return True, None
        except ValueError as exc:
            return False, f"端口参数无效：{exc}"
        except PortOpenError as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001
            return False, f"打开端口 {port} 失败：{exc}"

    def open_port(
        self,
        port: str,
        baud: int = 115200,
        frame: str = "8N1",
        flow: str = "none",
        *,
        quiet: bool = False,
    ) -> bool:
        """同步打开端口（兼容入口：monitor 等仍在主线程调用）。失败弹窗并返回 False.

        慢速 COM 驱动的 open 可达秒级——GUI 按钮触发的打开应改走
        ``open_port_async``（Pf-3，后台线程 + 信号回主线程），本方法保留给
        已有同步调用方与测试替身。

        Args:
            port: 端口名（COM3 等）。
            baud: 波特率。
            frame: 紧凑帧格式（如 8N1），经 FrameFormat.parse 校验。
            flow: 流控（none/rts_cts/xon_xoff）。
            quiet: True 时失败不弹窗（P3：monitor 多端口批量打开由调用方聚合
                失败端口单弹窗列出，替代逐端口连环弹窗）。
        """
        ok, err = self._open_port_impl(port, baud, frame, flow)
        if not ok and not quiet:
            QMessageBox.critical(self, "端口错误", err or f"打开端口 {port} 失败")
        return ok

    def open_port_async(
        self, port: str, baud: int = 115200, frame: str = "8N1", flow: str = "none"
    ) -> None:
        """后台打开端口（Pf-3，worker 线程 + 信号回主线程模式，同更新控制器）.

        慢速 COM 驱动的 open 可达秒级，同步在主线程会冻结 UI。工作线程执行
        ``_open_port_impl``（不弹窗），结果经 ``port_open_result`` 信号回主线程
        （Queued：失败弹窗在主线程；发起方视图监听同一信号恢复按钮/建订阅）。
        同端口在途时忽略重复请求。
        """
        if port in self._open_in_flight:
            _log.warning("端口 %s 打开中，忽略重复请求", port)
            return
        self._open_in_flight.add(port)

        def _worker() -> None:
            ok, err = self._open_port_impl(port, baud, frame, flow)
            self._open_in_flight.discard(port)
            self.port_open_result.emit(port, ok, err or "")

        threading.Thread(target=_worker, daemon=True, name=f"atprobe-open-{port}").start()

    def _on_port_open_result(self, port: str, ok: bool, error: str) -> None:
        """主线程：后台打开结果——失败弹窗（成功静默；UI 恢复由发起方自行监听）."""
        if not ok:
            _log.warning("后台打开端口 %s 失败: %s", port, error)
            QMessageBox.critical(self, "端口错误", error or f"打开端口 {port} 失败")

    def close_port(self, port: str) -> bool:
        """手动调试：关闭端口（幂等，§4.1）。"""
        try:
            self._port_manager.close(port)
            return True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "端口错误", f"关闭端口 {port} 失败：{exc}")
            return False

    def closeEvent(self, event: object) -> None:  # noqa: D401
        """窗口关闭：释放全部资源（B6 修复：遍历 tab cleanup + 停引擎 + 关串口）."""
        if self._closing:
            # F-17：processEvents 重入防护——等待循环期间用户再点 X 会二次进入
            # closeEvent（重复 stop_engine/双重 close_all/二次清理信号已断的 tab）
            ignore = getattr(event, "ignore", None)
            if callable(ignore):
                ignore()
            return
        self._closing = True
        try:
            # 先停引擎（若在跑），避免引擎线程操作已关闭的串口
            self.stop_engine()
            # P3 修复：等待引擎线程退出（旧实现只置停止标志，窗口销毁后引擎可能
            # 仍在 send_command 等待中继续跑到超时——信号已断但后台残留活动）。
            # 复审补充：循环等待期间处理事件（引擎卡重连睡眠最长 ~30s 时保持
            # UI 可响应，避免"无响应→强杀"恶化路径）
            if self._engine_thread is not None and self._engine_thread.is_alive():
                from PySide6.QtWidgets import QApplication

                stop_evt = threading.Event()
                waited = 0.0
                while self._engine_thread.is_alive() and waited < 5.0:
                    QApplication.processEvents()
                    stop_evt.wait(0.1)  # threading 用 Event 控节拍（Thread 无 wait）
                    waited += 0.1
            # 遍历所有 tab 调 cleanup，释放 RX 订阅/定时器/worker
            for i in range(self.tabs.count()):
                widget = self.tabs.widget(i)
                if widget is None:
                    continue
                cleaner = getattr(widget, "cleanup", None)
                if callable(cleaner):
                    try:
                        cleaner()
                    except Exception:  # noqa: BLE001
                        _log.debug("closeEvent tab cleanup 抛异常", exc_info=True)
            # 最后关闭所有串口
            self._port_manager.close_all()
            # 停原始日志写线程（drain 队列确保尾部记录落盘；M8 修复引入）
            self._raw_logger.stop()
        finally:
            super().closeEvent(event)  # type: ignore[arg-type]

    def run_cases(
        self,
        case_files: list[str],
        port: str,
        threshold: int,
        *,
        dry_run: bool = False,
        no_report: bool = False,
    ) -> None:
        """用例执行：驱动 M3 引擎（在引擎线程，§10.2）.

        dry_run=True 时只解析用例、检查端口，不实际执行（M5 §3.6 等价）。
        no_report=True 时不生成 HTML 报告。
        """
        # B8 修复：防重入——引擎在跑时拒绝再次执行，避免两个引擎线程并发操作同一串口。
        from atprobe.engine.config import EngineState

        if self._engine is not None and self._engine.state() is EngineState.RUNNING:
            QMessageBox.warning(self, "正在执行", "已有用例正在执行中，请先停止后再开始。")
            return

        # 2b⑧ 启动前探测（终审 Important）：manual_debug 文件发送进行中（分块写
        # 持端口命令锁）时启动引擎，首条 send_command 即 PortBusyError——步骤串
        # 连环失败后才以引擎错误终结。此处快速拒绝并给出可操作提示。
        if self._file_send_active():
            QMessageBox.warning(self, "无法启动", "文件发送进行中，请先完成或取消后再启动测试")
            return

        from atprobe.domain.case.parser import CaseParseError

        # Pf-3：经共享解析缓存取用例——用例树 _load_path 加载时已 parse 过同一批
        # 文件（命中 mtime 一致即复用），消除「加载一次 + 执行一次」的重复解析；
        # 错误语义不变（CaseParseError 照旧上抛此处弹窗）
        cases: list[object] = []
        for f in case_files:
            try:
                cases.append(self._case_cache.get_or_parse(Path(f)))
            except CaseParseError as exc:
                QMessageBox.critical(self, "用例解析错误", str(exc))
                return

        # dry-run：只解析 + 端口可用性检查，不执行
        if dry_run:
            was_open = self._port_manager.is_connected(port)
            try:
                self._port_manager.open(
                    PortConfig(name=port, urc_filter=self._app_config.urc_filter)
                )
                open_ok = True
            except Exception:  # noqa: BLE001
                open_ok = False
            # P2 修复：dry-run 打开的端口用后即关（预演不改变连接状态）；
            # 外部已连接的端口不动
            if open_ok and not was_open:
                self._port_manager.close(port)
            status = "可用" if open_ok or was_open else "不可用"
            QMessageBox.information(
                self,
                "预演 (Dry Run)",
                f"将执行用例：{len(cases)} 个\n端口 {port}：{status}\n（未实际执行）",
            )
            return

        # 确保端口已连接
        if not self._port_manager.is_connected(port):
            try:
                self._port_manager.open(
                    PortConfig(name=port, urc_filter=self._app_config.urc_filter)
                )
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "端口错误", f"打开端口 {port} 失败：{exc}")
                return

        env = None
        env_widget = self._env_widget
        if env_widget is not None:
            # 环境配置页已开：内存 EnvConfig 是唯一活跃来源（所见即所跑）。
            # dirty 则先隐式存盘，保证内存=磁盘一致（单一数据源，避免关 tab 后回退磁盘突变）。
            env_widget.save_if_dirty()
            env = env_widget.current_env()
        else:
            # 环境配置页未开：从磁盘读 env.yaml。
            # 用 env_config_path()（含内置 env.yaml 回退），而非裸 app_config 路径：
            # 打包态用户路径可能不存在，裸路径会让 env=None → 所有 {{group.param}} 静默失败。
            env_path_str = self.env_config_path()
            if env_path_str is not None:
                env_path = Path(env_path_str)
                try:
                    env = load_env_config_file(env_path)
                except Exception as exc:  # noqa: BLE001
                    # 不再静默吞：env 解析失败会让所有点号引用变未定义，必须提示用户。
                    QMessageBox.warning(
                        self,
                        "环境配置加载失败",
                        f"加载环境配置失败，用例中的 {{{{group.param}}}} 引用可能无法替换：\n"
                        f"{env_path}\n\n{exc}\n\n请检查该 YAML 语法（应为两级 group.param 映射）。",
                    )
                    env = None

        # session_id 加随机后缀，避免连续快速运行按秒冲突覆盖报告
        import secrets

        session = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
        cfg = EngineConfig(
            ports=(PortConfig(name=port, urc_filter=self._app_config.urc_filter),),
            cases=tuple(cases),  # type: ignore[arg-type]
            step_timeout_default=self._app_config.step_timeout,
            pressure_pass_threshold=float(threshold),
            env_config=env,
            session_id=session,
            log_dir=str(resolve_workspace_path(self._app_config.log_dir)),
            # S-8 额外数据根：GUI 用例可来自任意文件，cases_dir 作统一数据目录兜底
            data_allowed_roots=(str(self.cases_dir().resolve()),),
        )

        _log.info("开始执行: %d 个用例, 端口 %s, 阈值 %d%%", len(cases), port, threshold)

        self._set_engine_status("RUNNING", self._tokens["accent"])
        self._engine = Engine(
            sender_factory=lambda: self._port_manager, raw_logger=self._raw_logger
        )

        def _run() -> None:
            assert self._engine is not None
            try:
                result = self._engine.start(cfg, handler=lambda ev: self.progress.emit(ev))
            except Exception as exc:
                # 引擎线程异常兜底：写完整 traceback 日志 + 推 UI 即时提示。
                # 此前异常静默死亡 → UI 表现为"卡住"；现在用户能看到"出错了"并查日志。
                # P0-2 修复：删除本线程内的 _set_engine_status 调用——QTimer/QLabel 仅
                # 主线程可操作；主线程槽 _on_progress 处理 ("engine_error", ...) 时已设置。
                _log.exception("引擎执行异常")
                self.progress.emit(("engine_error", f"执行异常：{exc}"))
                return
            finally:
                # B8 补充：执行结束（含异常）后清理引擎引用。
                # 旧实现不置 None，导致 stop_engine_dialog 对已结束引擎误弹停止框、
                # _toggle_theme 误把 FINISHED/IDLE 重设为 RUNNING 色。
                self._engine = None
            ev = _startup_error_event(result)
            if ev is not None:
                # §4.4②：启动级错误消费侧呈现——旧实现走 done 分支，绿色 FINISHED
                # +"通过 0 / 失败 0" 弹窗。与 done/done_noreport 三分支互斥。
                self.progress.emit(ev)
                return
            if no_report:
                _log.info("执行结束: %d通过/%d失败", result.summary.passed, result.summary.failed)
                self.progress.emit(
                    ("done_noreport", "", result.summary.passed, result.summary.failed)
                )
                return
            # 生成报告
            try:
                rdir = resolve_workspace_path(self._app_config.report_dir) / session / "report.html"
                HtmlReporter().render(result, ReportOutput(html_path=rdir, to_console=False))
                _log.info(
                    "执行结束: %d通过/%d失败, 报告: %s",
                    result.summary.passed,
                    result.summary.failed,
                    rdir,
                )
                self.progress.emit(
                    ("done", str(rdir), result.summary.passed, result.summary.failed)
                )
            except Exception as exc:
                _log.exception("报告生成异常")
                # P0-2 修复：同上——状态设置交由主线程槽，此处仅投递事件
                self.progress.emit(("engine_error", f"报告生成异常：{exc}"))

        t = threading.Thread(target=_run, daemon=True)
        self._engine_thread = t  # P3 修复：保留引用供 closeEvent join
        t.start()

    def stop_engine(self) -> None:
        if self._engine is not None:
            self._engine.stop(mode=StopMode.ALL)

    def stop_engine_dialog(self) -> None:
        """停止引擎：弹「中断当前用例 / 停止全部」对话框（M3 §7.2，REQ-M6 §5.5）."""
        if self._engine is None:
            return
        choice = QMessageBox.question(
            self,
            "停止执行",
            "选择停止范围：\n  「是」= 停止全部\n  「否」= 仅中断当前用例，继续后续\n  「取消」= 不停止",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
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
        # 复审修复：先退订（unsubscribe 会把 sink 置 None）再设新 sink——
        # 旧实现顺序颠倒，切换监控端口集时新订阅静默失效（当前 UI 流程
        # toggle 互斥不可达，属潜伏缺陷）
        if self._monitor_handle is not None:
            self.unsubscribe_monitor()
        self._monitor_sink = sink
        # P2 修复：句柄按 (tx, rx) 配对存储（旧实现平铺 tuple 用奇偶下标区分，
        # 与 subscribe 顺序强耦合，端口只订一侧时会静默错退订）
        pairs: list[tuple[object, object]] = []

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

            tx_h = self._port_manager.subscribe_tx(port, _tx_observer)
            rx_h = self._port_manager.subscribe_rx(port, _rx_observer)
            pairs.append((tx_h, rx_h))
        self._monitor_handle = tuple(pairs)

    def unsubscribe_monitor(self) -> None:
        if self._monitor_handle is not None:
            pairs: tuple[tuple[object, object], ...] = self._monitor_handle  # type: ignore[assignment]
            for tx_h, rx_h in pairs:
                self._port_manager.unsubscribe_tx(tx_h)
                self._port_manager.unsubscribe_rx(rx_h)
            self._monitor_handle = None
        self._monitor_sink = None

    # ------------------------------------------------------------------
    # 进度事件处理（主线程，经信号投递）
    # ------------------------------------------------------------------
    def _on_progress(self, ev: object) -> None:
        # 引擎异常（线程内 try/except 捕获后推来）：状态栏变红 + 弹窗提示看日志
        if isinstance(ev, tuple) and ev and ev[0] == "engine_error":
            msg = ev[1] if len(ev) > 1 else "未知错误"  # type: ignore[union-attr]
            self._set_engine_status("ERROR", self._tokens["danger"])
            from atprobe.infra.logging_config import _log_dir

            try:
                log_file: Path | None = _log_dir() / "atprobe.log"
            except Exception:  # noqa: BLE001
                log_file = None
            log_hint = f"\n\n详见日志：{log_file}" if log_file else "\n\n详见日志"
            QMessageBox.critical(self, "执行异常", f"{msg}{log_hint}")
            return
        # 终止事件：done（生成报告）/ done_noreport（不生成报告）
        if isinstance(ev, tuple) and ev and ev[0] in ("done", "done_noreport"):
            tag, report_path, passed, failed = ev  # type: ignore[misc]
            self._set_engine_status("FINISHED", self._tokens["success"])
            # 转发完成事件给执行进度选项卡（若有）
            self._forward_progress(ev)
            if tag == "done_noreport":
                QMessageBox.information(
                    self, "执行完成", f"通过 {passed} / 失败 {failed}\n（未生成报告）"
                )
            else:
                QMessageBox.information(
                    self,
                    "执行完成",
                    f"通过 {passed} / 失败 {failed}\n报告: {report_path}",
                )
                # 用系统默认浏览器打开报告（HTML 纯静态，浏览器渲染效果最佳；
                # 不再用内嵌 WebEngine 以避免引入 ~200MB 的 Chromium 体积）
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(report_path).resolve())))
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
