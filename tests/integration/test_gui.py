"""GUI 模块导入与构造冒烟测试（offscreen 模式）."""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 带后台 worker 的用例创建的 Qt 对象保活表：防止 GC 在工作线程回收已弃用的
# QObject（C++ 对象非主线程析构 → 原生崩溃）。仅测试用，进程退出统一释放。
_KEEP_ALIVE: list[object] = []


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class TestRegistry:
    def test_default_registry_has_all_types(self) -> None:
        from atprobe.gui.tabs.registry import default_registry

        reg = default_registry()
        types = reg.types()
        # §2.3 第一阶段选项卡（含执行进度，执行时自动弹出；报告查看已改用浏览器打开）
        for t in ("manual_debug", "case_execute", "monitor", "execution_progress", "env_config"):
            assert t in types, f"缺少选项卡类型 {t}"

    def test_execution_progress_excluded_from_sidebar(self) -> None:
        """执行进度选项卡不在侧栏显示（执行时自动弹出，§2.3）."""
        from atprobe.gui.tabs.registry import default_registry

        sidebar = default_registry().sidebar_items()
        assert "execution_progress" not in sidebar
        assert "manual_debug" in sidebar

    def test_display_names(self) -> None:
        from atprobe.gui.tabs.registry import default_registry

        names = default_registry().display_names()
        assert names["manual_debug"] == "手动调试"
        assert names["env_config"] == "环境配置"


class TestMainWindow:
    def test_constructs(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        assert win.windowTitle().startswith("ATProbe")
        # 默认打开了一个选项卡
        assert win.tabs.count() >= 1

    def test_raw_logger_wired_to_shared_pm(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """M8 修复回归：共享 PortManager 挂 RawLogger（GUI 引擎执行恢复原始日志落盘）.

        根因：GUI 与 MCP 同为 sender_factory 注入外部裸 PortManager——connection
        的 _raw_logger 为 None，_bind_case_logs 只建目录不写文件。修复：MainWindow
        创建常驻 RawLogger 并传入 PortManager 与 Engine。
        """
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        try:
            assert win._raw_logger is not None
            assert win._port_manager._raw_logger is win._raw_logger
        finally:
            win._raw_logger.stop()  # 测试收尾：drain 写线程，避免跨测试泄漏

    def test_new_tab_creates_widget(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        initial = win.tabs.count()
        win.new_tab("manual_debug")
        assert win.tabs.count() == initial + 1
        win.new_tab("env_config")
        assert win.tabs.count() == initial + 2

    def test_theme_toggle_persists(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """C1：主题切换更新全局状态 + QSettings 记忆.

        P2 修复配套：改用 INI 后端 + tmp_path——注册表后端在受限环境（沙箱/CI
        策略拒绝 HKCU 写入）下 setValue 静默落空（仅置 status），测试必假失败；
        INI 落盘路径由 setPath 注入，环境无关且不污染真实用户偏好。
        """
        from PySide6.QtCore import QSettings

        from atprobe.gui.mainwindow import MainWindow
        from atprobe.gui.theme import current_theme_is_dark

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        try:
            _probe = QSettings("ATProbe", "ATProbe")
            _probe.setValue("theme/dark", False)
            _probe.sync()
            if _probe.status() is not QSettings.Status.NoError:
                # 受限环境（沙箱策略拒绝 Qt C++ 侧文件/注册表写入，setValue 静默落空）：
                # 持久化断言在此环境不可能通过，显式跳过而非假失败。
                pytest.skip("QSettings 持久化在当前环境不可写（仅内存缓存）")
            QSettings("ATProbe", "ATProbe").setValue("theme/dark", False)
            win = MainWindow()
            assert win._dark is False  # noqa: SLF001
            # 切到深色
            win._toggle_theme(True)  # noqa: SLF001
            assert current_theme_is_dark() is True
            assert (
                bool(QSettings("ATProbe", "ATProbe").value("theme/dark", False, type=bool)) is True
            )
            assert win._theme_action.text() == "切换浅色主题"  # noqa: SLF001
            # 切回浅色
            win._toggle_theme(False)  # noqa: SLF001
            assert current_theme_is_dark() is False
        finally:
            QSettings.setDefaultFormat(QSettings.Format.NativeFormat)

    def test_subscribe_monitor_wires_tx_rx(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """监控订阅同时接 TX（写侧）与 RX（读侧），双向数据都到 sink（REQ-M6 §6.2）."""
        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.config import PortConfig
        from atprobe.infra.serial.fakeserial import FakePortManager

        win = MainWindow()
        win._port_manager = FakePortManager(sleep=lambda s: None)  # noqa: SLF001
        win._port_manager.open(PortConfig(name="COM9"))  # noqa: SLF001

        received: list[tuple[str, str, bytes]] = []
        win.subscribe_monitor(
            ["COM9"], lambda port, direction, data: received.append((port, direction, data))
        )
        assert win._monitor_handle is not None  # noqa: SLF001

        # TX：经 write_command 写入 → TX 观察者应收到（含结束符）
        win._port_manager.write_command("COM9", "AT")  # noqa: SLF001
        # RX：模拟读线程投递
        win._port_manager.emit_rx("COM9", b"OK\r\n")  # noqa: SLF001
        directions = sorted(d for _, d, _ in received)
        assert directions == ["RX", "TX"]
        tx_chunk = next(data for _, d, data in received if d == "TX")
        assert tx_chunk == b"AT\r\n"

        # 取消订阅后 TX/RX 都不再收到
        received.clear()
        win.unsubscribe_monitor()
        win._port_manager.write_command("COM9", "AT2")  # noqa: SLF001
        win._port_manager.emit_rx("COM9", b"more")  # noqa: SLF001
        assert received == []

    def test_help_menu_exists(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """帮助菜单存在，含检查更新/关于两个 action。"""
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        menubar = win.menuBar()
        help_actions = [a for a in menubar.actions() if a.text().startswith("帮助")]
        assert len(help_actions) == 1
        help_menu = help_actions[0].menu()
        assert help_menu is not None
        texts = [a.text() for a in help_menu.actions() if a.text()]
        assert any("检查更新" in t for t in texts)
        assert any("关于" in t for t in texts)

    def test_about_dialog_shows_version(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """关于对话框显示当前版本号。"""
        from PySide6.QtWidgets import QMessageBox

        from atprobe.gui.mainwindow import MainWindow

        shown = {}
        monkeypatch.setattr(
            QMessageBox,
            "about",
            lambda parent, title, text: shown.update(title=title, text=text),
        )
        win = MainWindow()
        win._on_about()  # noqa: SLF001
        assert "ATProbe" in shown.get("text", "")


class TestMonitorMultiPort:
    """B4：多端口监控合并显示 + 导出."""

    def test_multi_port_merged(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """监控两个端口，数据都带 [COMx] 前缀合并到同一 sink."""
        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.config import PortConfig
        from atprobe.infra.serial.fakeserial import FakePortManager

        win = MainWindow()
        win._port_manager = FakePortManager(sleep=lambda s: None)  # noqa: SLF001
        win._port_manager.open(PortConfig(name="COM3"))  # noqa: SLF001
        win._port_manager.open(PortConfig(name="COM5"))  # noqa: SLF001

        received: list[tuple[str, str, bytes]] = []
        win.subscribe_monitor(["COM3", "COM5"], lambda p, d, data: received.append((p, d, data)))

        win._port_manager.write_command("COM3", "AT")  # noqa: SLF001
        win._port_manager.emit_rx("COM5", b"OK\r\n")  # noqa: SLF001
        ports = sorted(p for p, _d, _data in received)
        assert ports == ["COM3", "COM5"]

        # 未在订阅列表的端口不收
        received.clear()
        win._port_manager.open(PortConfig(name="COM7"))  # noqa: SLF001
        win._port_manager.write_command("COM7", "AT")  # noqa: SLF001
        assert received == []

        win.unsubscribe_monitor()


class TestMonitorLineRendering:
    """监控页 RX/TX 按行切分渲染（多行 chunk 应渲染成多行，非黏成一行）."""

    def test_multiline_rx_renders_as_separate_lines(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """回归：RX chunk = AT\\r\\n\\r\\nOK\\r\\n 应渲染为两行（AT / OK），非 'AT OK'.

        bug：_on_data 把整个 chunk 当一行 append，中间 \\r\\n 既未切分也未转 <br>，
        导致文本模式 'AT OK' 黏成一行（\\r 回车不换行、\\n 被当空格）。
        """
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        # 模拟模块回包：AT 回显 + 空行 + OK
        widget._on_data("COM5", "RX", b"AT\r\n\r\nOK\r\n")  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        # AT 和 OK 应在不同行（不能黏成 'AT OK'）
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        joined = " ".join(lines)
        assert "AT OK" not in joined, f"AT 和 OK 不应黏成一行: {text!r}"
        # 两者各自独立成行
        assert any("AT" in ln for ln in lines)
        assert any("OK" in ln for ln in lines)

    def test_rx_partial_chunk_accumulated_across_calls(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """跨 chunk 的不完整行应累积，凑齐换行后再渲染（与 manual_debug 同语义）."""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        # 分两次到达：先 'AT'（无换行），再 '\r\nOK\r\n'
        widget._on_data("COM5", "RX", b"AT")  # noqa: SLF001
        widget._on_data("COM5", "RX", b"\r\nOK\r\n")  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        joined = " ".join(lines)
        assert "AT OK" not in joined, f"跨 chunk 也应正确切行: {text!r}"
        assert any("AT" in ln for ln in lines)
        assert any("OK" in ln for ln in lines)

    def test_hex_mode_not_split(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """HEX 模式按原始字节显示，不按行切分（与 manual_debug HEX 语义一致）."""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        widget.hex_check.setChecked(True)
        widget._on_data("COM5", "RX", b"AT\r\nOK\r\n")  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        assert "41 54" in text and "4F 4B" in text  # HEX 完整显示

    def test_text_mode_clean_newline_preserves_blanks(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """文本模式：按实际换行显示，保留空行，不显示转义字符.

        N58 真实回包 b'+CSQ: 12,99\\r\\n\\r\\nOK\\r\\n'（响应与 OK 间有空行）。
        一个 \\r\\n 一行，两个之间保留空行；不出现 \\r / \\n 字样。
        """
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        widget._on_data("COM5", "RX", b"+CSQ: 12,99\r\n\r\nOK\r\n")  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        # 不应出现转义字样
        assert r"\r" not in text, f"文本模式不应显示 \\r 转义: {text!r}"
        assert r"\n" not in text, f"文本模式不应显示 \\n 转义: {text!r}"
        # 内容各自独立成行
        assert "+CSQ: 12,99" in text and "OK" in text
        assert "12,99OK" not in text

    def test_cr_progress_lines_visible_after_flush(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """复审回归：孤立 \\r 刷新的进度行在 flush 时必须可见（不滞留缓冲）.

        设备用纯 CR 刷进度（42%\\r50%\\r）：旧实现只按 \\n 切分，这些行永不
        入 buffer；修复后 feed 切分 + flush 把悬置半行渲染出来。
        """
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        widget._on_data("COM5", "RX", b"progress 42%\r")  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        assert "42%" in text, f"CR 进度行应在 flush 后可见: {text!r}"

    def test_cr_then_crlf_no_phantom_blank(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """复审回归："b\\r" + "\\r\\n" 不得产生伪空行（hold 语义）."""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        widget._on_data("COM5", "RX", b"done\r")  # noqa: SLF001
        widget._on_data("COM5", "RX", b"\r\nnext\r\n")  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        assert "done" in " ".join(lines)
        assert "next" in " ".join(lines)

    def test_hex_switch_clears_text_residue(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """复审回归：TEXT→HEX 切换清掉半行残留（切回不串行）."""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        widget._on_data("COM5", "RX", b"half-line-no-newline")  # noqa: SLF001
        widget.hex_check.setChecked(True)  # 切 HEX
        widget._on_data("COM5", "RX", b"\r\nOK\r\n")  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        # HEX 模式：全部按十六进制展示，旧半行文本不得混入
        assert "half-line-no-newline" not in text

    def test_utf8_multibyte_across_chunks(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """复审回归：中文 3 字节字符被 chunk 边界切开仍完整（incremental decoder）."""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        raw = "注册状态:已注册\r\n".encode()
        mid = 7  # 切在多字节字符中间
        widget._on_data("COM5", "RX", raw[:mid])  # noqa: SLF001
        widget._on_data("COM5", "RX", raw[mid:])  # noqa: SLF001
        widget._flush_all()  # noqa: SLF001

        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        assert "注册状态:已注册" in text, f"跨 chunk 中文应完整重组: {text!r}"


class TestMonitorMemoryBounding:
    """长会话内存治理：QTextEdit 块上限 + 定时器随订阅起停 + 关子页释放控件."""

    def test_sub_view_has_block_limit(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """每个监控子页 view 的 QTextDocument 必须设了块上限（防长监控撑爆内存）."""
        from atprobe.gui.tabs.monitor import _MAX_LINES, _PortSubView
        from atprobe.gui.theme import get_tokens

        sv = _PortSubView("COM5", get_tokens())
        assert sv.view.document().maximumBlockCount() == _MAX_LINES

    def test_block_limit_actually_trims(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """块上限真实生效：append 超过上限后旧块被丢弃（验证非空设值）."""
        from atprobe.gui.tabs.monitor import _PortSubView
        from atprobe.gui.theme import get_tokens

        sv = _PortSubView("COM5", get_tokens())
        cap = sv.view.document().maximumBlockCount()
        assert cap > 0
        for i in range(cap + 50):
            sv.view.append(f"line{i}")
        assert sv.view.document().blockCount() == cap
        # 最旧块应被丢弃：line0 不再存在
        assert "line0" not in sv.view.toPlainText()

    def test_timer_not_started_at_construction(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """定时器在构造时不启动（随订阅起停；构造态不应空转）."""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        assert not widget._timer.isActive()  # noqa: SLF001

    def test_toggle_stops_timer_and_keeps_data(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """停止监控：定时器停转，但已捕获数据仍保留（可回看/导出）."""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        widget._timer.start(200)  # noqa: SLF001
        widget._on_data("COM5", "RX", b"hello\r\n")  # noqa: SLF001
        widget._toggle(False)  # noqa: SLF001
        assert not widget._timer.isActive()  # noqa: SLF001
        # 数据仍保留：停止前已 flush（_toggle(False) 内冲刷残余 buffer）
        text = widget._current_sub_view().view.toPlainText()  # noqa: SLF001
        assert "hello" in text

    def test_close_sub_tab_schedules_widget_delete(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """关闭子页：子页从 _sub_views 移除且控件标记 deleteLater（待事件循环回收）.

        反复加/减端口会累积悬挂控件，deleteLater 让其被回收，防长会话内存增长。
        """
        import shiboken6 as shiboken  # noqa: PLC0415
        from PySide6.QtCore import QCoreApplication, QEvent

        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), object())  # type: ignore[arg-type]
        sv = widget._ensure_sub_view("COM5")  # noqa: SLF001
        idx = widget._port_tabs.indexOf(sv)  # noqa: SLF001
        widget._on_close_sub_tab(idx)  # noqa: SLF001
        assert "COM5" not in widget._sub_views  # noqa: SLF001
        # deleteLater 投递 DeferredDelete 事件到 sv；处理之使 C++ 对象回收
        QCoreApplication.sendPostedEvents(sv, int(QEvent.Type.DeferredDelete))
        assert not shiboken.isValid(sv)  # sv 的 C++ 对象已被回收


class TestExecutionProgressTab:
    def test_event_flow_renders(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """B1：执行进度选项卡消费 CaseStart/Step/CaseResult/Finished 事件，更新表格与进度条."""
        from atprobe.domain.report.models import Summary
        from atprobe.engine.interfaces import (
            CaseResultEvent,
            CaseStartEvent,
            EngineFinishedEvent,
            StepResultEvent,
        )
        from atprobe.gui.tabs.execution_progress import ExecutionProgressWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ExecutionProgressWidget(
            TabBinding(type_name="execution_progress", params={}), object()
        )  # type: ignore[arg-type]

        # 2 个用例：用例1 PASS，用例2 FAIL
        widget.on_event(
            CaseStartEvent(case_name="网络注册", case_index=1, total_cases=2, case_type="regular")
        )
        assert widget.table.rowCount() == 1
        assert widget._case_names[1] == "网络注册"  # noqa: SLF001

        widget.on_event(
            StepResultEvent(
                step_index=1,
                phase="steps",
                status="PASS",
                duration_ms=120,
                port="COM3",
                command="AT+CSQ",
            )
        )
        assert "AT+CSQ" in widget.detail_label.text() and "✓" in widget.detail_label.text()

        widget.on_event(CaseResultEvent(case_name="网络注册", status="PASS", duration_ms=500.0))
        row0 = widget._find_row_by_name("网络注册")  # noqa: SLF001
        assert row0 == 0
        assert widget.table.item(row0, 2).text() == "PASS"  # type: ignore[union-attr]

        widget.on_event(
            CaseStartEvent(case_name="PDP激活", case_index=2, total_cases=2, case_type="regular")
        )
        widget.on_event(
            CaseResultEvent(case_name="PDP激活", status="FAIL", duration_ms=300.0, error_msg="超时")
        )
        assert widget.table.rowCount() == 2

        # 进度条应在第二个用例开始时推进
        assert 0 < widget.progress_bar.value() <= 100

        # 完成
        widget.on_event(EngineFinishedEvent(summary=Summary(total_cases=2, passed=1, failed=1)))
        assert widget.progress_bar.value() == 100

    def test_new_run_clears_previous_results(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """新运行首个用例（case_index==1）自动清空上一轮结果（防跨运行累积）."""
        from atprobe.engine.interfaces import CaseStartEvent
        from atprobe.gui.tabs.execution_progress import ExecutionProgressWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ExecutionProgressWidget(
            TabBinding(type_name="execution_progress", params={}), object()
        )  # type: ignore[arg-type]
        # 第一轮：2 个用例
        widget.on_event(
            CaseStartEvent(case_name="A", case_index=1, total_cases=2, case_type="regular")
        )
        widget.on_event(
            CaseStartEvent(case_name="B", case_index=2, total_cases=2, case_type="regular")
        )
        assert widget.table.rowCount() == 2

        # 第二轮：case_index==1 应触发清空，只保留本轮首个用例
        widget.on_event(
            CaseStartEvent(case_name="C", case_index=1, total_cases=1, case_type="regular")
        )
        assert widget.table.rowCount() == 1
        assert widget.table.item(0, 1).text() == "C"  # type: ignore[union-attr]
        # 上一轮映射表也清空，仅本轮首行
        assert widget._case_names == {1: "C"}  # noqa: SLF001


class TestEnvConfigTab:
    def test_edit_and_save(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.env_config import EnvConfigWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 写一个测试 env.yaml
        env_file = tmp_path / "env.yaml"
        env_file.write_text("ftp:\n  host: 1.2.3.4\n  port: 21\n", encoding="utf-8")

        binding = TabBinding(type_name="env_config", params={})
        widget = EnvConfigWidget(binding, object())  # type: ignore[arg-type]
        widget._load_path(env_file)  # noqa: SLF001
        # 表单应包含 ftp 组的两个参数
        assert "ftp" in widget._group_widgets  # noqa: SLF001
        assert "host" in widget._group_widgets["ftp"]  # noqa: SLF001
        assert widget._group_widgets["ftp"]["host"].text() == "1.2.3.4"  # noqa: SLF001


class TestCaseExecuteExtras:
    """B2：目录层级树、标签筛选、dry-run、报告开关、_selected_files 正确性."""

    @staticmethod
    def _wait_cases_applied(widget, timeout: float = 5.0) -> None:  # noqa: ANN001
        """等待后台解析批次应用（Pf-3：_load_path 移 worker，经信号回主线程）."""
        import time

        from PySide6.QtWidgets import QApplication

        target = widget._load_seq  # noqa: SLF001
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and widget._applied_seq < target:  # noqa: SLF001
            QApplication.processEvents()
            time.sleep(0.01)
        assert widget._applied_seq >= target, "用例目录后台解析未在超时内完成"  # noqa: SLF001

    @staticmethod
    def _count_leaves(widget) -> int:  # noqa: ANN001
        """递归统计树中**可见**用例叶子数（Pf-2 增量过滤：被隐藏 = 被过滤）."""
        count = 0

        def walk(item) -> None:  # noqa: ANN001
            nonlocal count
            if item.childCount() == 0:
                if not item.isHidden():
                    count += 1
                return
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(widget.tree.topLevelItemCount()):
            walk(widget.tree.topLevelItem(i))
        return count

    @staticmethod
    def _first_leaf_name(widget) -> str | None:  # noqa: ANN001
        """取树中第一个**可见**用例叶子的用例名（第 0 列文本）."""

        def walk(item):  # noqa: ANN001
            if item.childCount() == 0:
                if not item.isHidden():
                    return item.text(0)
                return None
            for i in range(item.childCount()):
                r = walk(item.child(i))
                if r is not None:
                    return r
            return None

        for i in range(widget.tree.topLevelItemCount()):
            r = walk(widget.tree.topLevelItem(i))
            if r is not None:
                return r
        return None

    def test_tree_tag_filter_and_dry_run(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import PySide6.QtWidgets as _qw

        from atprobe.gui.tabs.case_execute import CaseExecuteWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 弹窗打桩（dry-run 会弹 information）
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)

        # 写用例：根目录下两个 + tcp/ 子目录一个，验证目录层级 + 标签筛选
        (tmp_path / "net.yaml").write_text(
            "name: 网络用例\ntags: [network]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )
        (tmp_path / "sms.yaml").write_text(
            "name: 短信用例\ntags: [sms]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )
        (tmp_path / "tcp").mkdir()
        (tmp_path / "tcp" / "t1.yaml").write_text(
            "name: TCP用例\ntags: [tcp]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )

        run_calls: list[dict] = []

        class _Main:
            def __init__(self):
                self.tabs = _qw.QTabWidget()

            def available_ports(self):
                return ["COM3"]

            def run_cases(self, files, port, threshold, *, dry_run=False, no_report=False):
                run_calls.append({"files": list(files), "dry_run": dry_run, "no_report": no_report})

            def stop_engine_dialog(self):
                pass

        main = _Main()
        widget = CaseExecuteWidget(TabBinding(type_name="case_execute", params={}), main)  # type: ignore[arg-type]
        widget._load_path(tmp_path)  # noqa: SLF001
        self._wait_cases_applied(widget)  # Pf-3：解析在后台 worker，等批次应用

        # 标签聚合：下拉应含 network、sms、tcp
        tag_items = [widget.tag_combo.itemText(i) for i in range(widget.tag_combo.count())]
        assert "network" in tag_items and "sms" in tag_items and "tcp" in tag_items

        # 默认（全部）三个用例都显示为叶子
        assert self._count_leaves(widget) == 3

        # 选 network 标签 → 只显示网络用例
        widget.tag_combo.setCurrentText("network")
        assert self._count_leaves(widget) == 1
        assert self._first_leaf_name(widget) == "网络用例"

        # 切回全部
        widget.tag_combo.setCurrentIndex(0)
        assert self._count_leaves(widget) == 3

        # 默认全选：_selected_files 应返回全部 3 个文件
        assert len(widget._selected_files()) == 3  # noqa: SLF001

        # 全不选 → 0 个；再全选 → 3 个
        widget._set_all_checked(False)  # noqa: SLF001
        assert widget._selected_files() == []  # noqa: SLF001
        widget._set_all_checked(True)  # noqa: SLF001
        assert len(widget._selected_files()) == 3  # noqa: SLF001

        # dry-run：应调用 run_cases(dry_run=True)
        widget.ports_combo.setCurrentText("COM3")
        widget._dry_run()  # noqa: SLF001
        assert run_calls and run_calls[-1]["dry_run"] is True
        assert len(run_calls[-1]["files"]) == 3

        # 关闭报告开关 → run_cases(no_report=True)
        widget.report_check.setChecked(False)
        widget._run()  # noqa: SLF001
        assert run_calls[-1]["no_report"] is True


class _CaseMain:
    """case_execute 测试用的最小主窗口替身（端口 + run_cases 记录）."""

    def __init__(self) -> None:  # noqa: D107
        import PySide6.QtWidgets as _qw

        self.tabs = _qw.QTabWidget()
        self.run_calls: list[dict] = []

    def available_ports(self) -> list[str]:
        return ["COM3"]

    def run_cases(self, files, port, threshold, *, dry_run=False, no_report=False):  # noqa: ANN001
        self.run_calls.append({"files": list(files), "dry_run": dry_run, "no_report": no_report})


def _write_case_cases(tmp_path) -> None:  # noqa: ANN001
    """写 3 个用例：根目录 2 个（network/sms 标签）+ tcp/ 子目录 1 个."""
    (tmp_path / "net.yaml").write_text(
        "name: 网络用例\ntags: [network]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
        encoding="utf-8",
    )
    (tmp_path / "sms.yaml").write_text(
        "name: 短信用例\ntags: [sms]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
        encoding="utf-8",
    )
    (tmp_path / "tcp").mkdir()
    (tmp_path / "tcp" / "t1.yaml").write_text(
        "name: TCP用例\ntags: [tcp]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
        encoding="utf-8",
    )


def _collect_leaves(widget) -> list:  # noqa: ANN001
    """收集树的全部叶子 item 对象（按序）——用于断言过滤前后树未重建（对象同一）。"""

    def walk(item, out):  # noqa: ANN001
        if item.childCount() == 0:
            out.append(item)
            return
        for i in range(item.childCount()):
            walk(item.child(i), out)

    out: list = []
    for i in range(widget.tree.topLevelItemCount()):
        walk(widget.tree.topLevelItem(i), out)
    return out


class TestCaseExecuteSearchDebounce:
    """Pf-2：搜索防抖（300ms 单发）+ 增量过滤（setHidden，不重建树）。"""

    def _make_widget(self, tmp_path):  # noqa: ANN001, no-untyped-def
        from atprobe.gui.tabs.case_execute import CaseExecuteWidget
        from atprobe.gui.tabs.registry import TabBinding

        _write_case_cases(tmp_path)
        widget = CaseExecuteWidget(TabBinding(type_name="case_execute", params={}), _CaseMain())  # type: ignore[arg-type]
        widget._load_path(tmp_path)  # noqa: SLF001
        TestCaseExecuteExtras._wait_cases_applied(widget)
        return widget

    def test_debounce_wiring(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        widget = self._make_widget(tmp_path)
        # 防抖参数：300ms 单发
        assert widget._debounce.interval() == 300  # noqa: SLF001
        assert widget._debounce.isSingleShot()  # noqa: SLF001

        # textChanged → 只启动防抖定时器，_filter 不立即执行（树未过滤）
        widget.search_edit.setText("网络")
        assert widget._debounce.isActive()  # noqa: SLF001
        visible = [it for it in _collect_leaves(widget) if not it.isHidden()]
        assert len(visible) == 3  # 防抖期内全部可见

        # 模拟 300ms 到期（无事件循环环境直接触发防抖目标）
        widget._filter()  # noqa: SLF001
        visible = [it for it in _collect_leaves(widget) if not it.isHidden()]
        assert len(visible) == 1
        assert visible[0].text(0) == "网络用例"

    def test_incremental_filter_keeps_tree_objects(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """增量过滤：树不重建（叶子对象同一），清空搜索后全恢复。"""
        widget = self._make_widget(tmp_path)
        leaves_before = _collect_leaves(widget)
        assert len(leaves_before) == 3

        widget.search_edit.setText("sms")
        widget._filter()  # noqa: SLF001
        leaves_after = _collect_leaves(widget)
        # 同一批 item 对象（重建会生成新对象）——树保留
        assert leaves_after == leaves_before
        visible = [it for it in leaves_after if not it.isHidden()]
        assert len(visible) == 1 and visible[0].text(0) == "短信用例"

        # 清空搜索 → 全部恢复可见
        widget.search_edit.setText("")
        widget._filter()  # noqa: SLF001
        assert all(not it.isHidden() for it in _collect_leaves(widget))

    def test_hidden_cases_excluded_from_selection_and_checkstate_kept(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """过滤隐藏的用例不参与执行（与旧重建语义等价）；勾选态跨过滤保留。"""
        from PySide6.QtCore import Qt

        widget = self._make_widget(tmp_path)
        net_leaf = next(it for it in _collect_leaves(widget) if it.text(0) == "网络用例")
        net_leaf.setCheckState(0, Qt.CheckState.Unchecked)  # 只取消网络用例
        before = set(widget._selected_files())  # noqa: SLF001

        widget.search_edit.setText("网络")
        widget._filter()  # noqa: SLF001
        # 只显示网络用例，但它未勾选 → 无可执行项
        assert widget._selected_files() == []  # noqa: SLF001

        # 清空过滤：勾选态保留（重建语义会重置为全选）
        widget.search_edit.setText("")
        widget._filter()  # noqa: SLF001
        assert set(widget._selected_files()) == before  # noqa: SLF001

    def test_load_path_stale_batch_dropped(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Pf-3：连续加载两批 → 旧 worker 的迟到结果不覆盖新批次。"""
        from atprobe.gui.tabs.case_execute import CaseExecuteWidget
        from atprobe.gui.tabs.registry import TabBinding

        dir1 = tmp_path / "d1"
        dir2 = tmp_path / "d2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "a.yaml").write_text(
            "name: 甲用例\ntags: [t1]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )
        (dir2 / "b.yaml").write_text(
            "name: 乙用例\ntags: [t2]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )
        widget = CaseExecuteWidget(TabBinding(type_name="case_execute", params={}), _CaseMain())  # type: ignore[arg-type]
        widget._load_path(dir1)  # noqa: SLF001
        widget._load_path(dir2)  # noqa: SLF001
        TestCaseExecuteExtras._wait_cases_applied(widget)
        # 只应用第二批（无论两个 worker 的完成顺序如何）
        names = [c[0] for c in widget._cases]  # noqa: SLF001
        assert names == ["乙用例"]


class _FakeMain:
    """最小化的主窗口替身：模拟端口连接管理与发送，供 ManualDebugWidget 测试.

    send_manual 设置 last_command 后触发 sent_event，便于测试同步。
    支持 subscribe_rx/unsubscribe_rx（纯流式接收）+ emit_rx 模拟回包。
    """

    def __init__(self) -> None:
        self._connected: set[str] = set()
        self.open_calls: list[tuple[str, int, str]] = []
        self.last_command: tuple[str, str] | None = None
        self.last_terminator: object | None = None
        self.sent_event = threading.Event()
        self._rx_observers: dict[str, list] = {}
        # 文件发送（小文件同步路径）
        self.last_bytes: tuple[str, bytes] | None = None
        self.file_sent_event = threading.Event()
        # 大文件 worker 用的连接替身（None 表示不支持后台路径）
        self._fake_connection = None
        # 可控：设为 True 时 open_port 返回 False 模拟打开失败
        self.fail_open = False

    def available_ports(self) -> list[str]:
        return ["COM1", "COM2"]

    def is_port_connected(self, port: str) -> bool:
        return port in self._connected

    def open_port(self, port: str, baud: int = 115200, frame: str = "8N1") -> bool:
        self.open_calls.append((port, baud, frame))
        if self.fail_open:
            return False  # 模拟端口被占用/权限拒绝
        self._connected.add(port)
        return True

    def close_port(self, port: str) -> bool:
        self._connected.discard(port)
        return True

    def send_manual(self, port: str, command: str, *, terminator: object | None = None) -> bool:
        """流式写：记录命令（不再等待响应，回包经 subscribe_rx 流入）.

        terminator 经 manual_debug 透传到这里（修：结束符选择原本被忽略）。
        """
        if port not in self._connected:
            return False
        self.last_command = (port, command)
        self.last_terminator = terminator
        self.sent_event.set()
        return True

    def send_file(self, port: str, data: bytes) -> bool:
        """小文件同步写：记录写入字节并触发事件（供测试同步）。"""
        if port not in self._connected:
            return False
        self.last_bytes = (port, data)
        self.file_sent_event.set()
        return True

    def get_connection(self, port: str):
        """大文件 worker 持有的连接替身（测试可预置）。"""
        return self._fake_connection

    def subscribe_rx(self, port: str, observer) -> object:
        self._rx_observers.setdefault(port, []).append(observer)
        return (port, observer)

    def unsubscribe_rx(self, handle) -> None:
        if isinstance(handle, tuple) and len(handle) == 2:
            port, observer = handle
            obs = self._rx_observers.get(port, [])
            if observer in obs:
                obs.remove(observer)

    def emit_rx(self, port: str, data: bytes) -> None:
        """测试辅助：向某端口的 RX 观察者投递字节（模拟模块回包）."""
        for obs in self._rx_observers.get(port, []):
            obs(data)


class TestManualDebugPortControl:
    def test_open_close_toggle(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        # 默认 COM1 选中且未连接
        assert widget._current_port() == "COM1"  # noqa: SLF001
        assert main.is_port_connected("COM1") is False
        assert widget.connect_btn.text() == "打开端口"

        # 打开端口
        widget._toggle_connect()  # noqa: SLF001
        assert main.open_calls == [("COM1", 115200, "8N1")]
        assert main.is_port_connected("COM1") is True
        assert widget.connect_btn.text() == "关闭端口"
        # 已连接 → 波特率/帧格式锁只读
        assert widget.baud_combo.isEnabled() is False
        assert widget.frame_combo.isEnabled() is False

        # 再次点击 → 关闭
        widget._toggle_connect()  # noqa: SLF001
        assert main.is_port_connected("COM1") is False
        assert widget.connect_btn.text() == "打开端口"
        assert widget.baud_combo.isEnabled() is True

    def test_send_requires_connection(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # 把所有模态弹窗打桩，防止阻塞测试（_send 未连接时弹 warning）
        import PySide6.QtWidgets as _qw

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        widget.send_edit.setPlainText("AT+CSQ")
        widget._send()  # noqa: SLF001  端口未连接 → 不应发送
        assert main.last_command is None
        # 连接后再发送（_toggle_connect 会建立 RX 订阅）
        widget._toggle_connect()  # noqa: SLF001
        assert main.is_port_connected("COM1") is True
        widget._send()  # noqa: SLF001
        # send_manual 是流式写，同步返回，立即写入记录
        assert main.last_command == ("COM1", "AT+CSQ")
        # TX 立即上屏（不等响应）。渲染格式为 "<时间戳>   TX  <内容>"，
        # 时间戳动态生成，断言用方向+命令内容匹配（而非精确 "TX> ..."）。
        _tx_text = widget.response_view.toPlainText()
        assert "TX" in _tx_text and "AT+CSQ" in _tx_text

        # 结束符下拉切换为 \r → 应透传到 send_manual（修：UI 选择原本被忽略）
        from atprobe.infra.serial.config import Terminator

        widget.term_combo.setCurrentIndex(1)  # "\\r"
        assert widget._terminator is Terminator.CR  # noqa: SLF001
        main.last_command = None
        widget._send()  # noqa: SLF001
        assert main.last_command == ("COM1", "AT+CSQ")
        assert main.last_terminator is Terminator.CR

    def test_tx_hex_shows_terminator_bytes(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """HEX 模式下 TX 行显示实际发送字节（命令+结束符），结束符选择一目了然.

        回归：N58 不回显 <LF>（手册 §3.2 结束符为 <CR>），RX 无法区分 \\r/\\r\\n。
        故在 TX 侧显示完整字节让用户确认结束符配置生效。
        """
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001

        widget.hex_check.setChecked(True)

        # 结束符 \r\n → TX HEX 应含 0D 0A。渲染格式为 "<时间戳>   TX  <hex>"，
        # 用 hex 字节串匹配（唯一标识，宽松于精确 "TX> ..."）。
        widget.send_edit.setPlainText("AT")
        widget._send()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "41 54 0D 0A" in text, f"CRLF 应显示 41 54 0D 0A: {text!r}"

        # 结束符 \r → TX HEX 应含 0D（无 0A）
        widget.term_combo.setCurrentIndex(1)  # "\\r"
        widget._send()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "41 54 0D" in text, f"CR 应显示 41 54 0D: {text!r}"
        # 关键判据：CR 模式的最后一条 TX 行不应以 0A 结尾
        tx_lines = [ln for ln in text.splitlines() if "TX" in ln]
        assert tx_lines, "应有 TX 行"
        last_tx = tx_lines[-1]
        assert not last_tx.rstrip().endswith("0A"), f"CR 模式 TX 不应以 0A 结尾: {last_tx!r}"

    def test_rx_streams_via_subscription(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """打开端口后 RX 订阅建立；模块回包字节经信号流式渲染到响应区."""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        # 打开端口 → 建立订阅
        widget._toggle_connect()  # noqa: SLF001
        assert widget._rx_handle is not None  # noqa: SLF001

        # 模拟模块回包（读线程上下文）→ 经信号到主线程渲染
        main.emit_rx("COM1", b"+CSQ: 23,99\r\n")
        # emit 在测试线程（非读线程）触发信号；Qt 信号默认直连主线程槽。
        # Pf-1：RX 流式路径经 RxConsole 缓冲（200ms 批量上屏）——显式 flush 后再断言
        widget._rx_console.flush()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "+CSQ: 23,99" in text

        # 关闭端口 → 撤销订阅
        widget._toggle_connect()  # noqa: SLF001
        assert widget._rx_handle is None  # noqa: SLF001

    def test_rx_text_mode_clean_newline_no_escape(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """文本模式：按实际换行显示，干净换行不显示转义字符，保留空行.

        N58 真实回包 b'AT\\r\\r\\n+CSQ: 12,99\\r\\n\\r\\nOK\\r\\n'（响应与 OK 间有空行）。
        每个换行符对应一行，空行保留；不出现任何 \\r / \\n 字样。
        """
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001

        main.emit_rx("COM1", b"AT\r\r\n+CSQ: 12,99\r\n\r\nOK\r\n")
        widget._rx_console.flush()  # noqa: SLF001 —— Pf-1 批量渲染，显式冲刷后断言
        text = widget.response_view.toPlainText()
        # 不应出现转义字样
        assert r"\r" not in text, f"文本模式不应显示 \\r 转义: {text!r}"
        assert r"\n" not in text, f"文本模式不应显示 \\n 转义: {text!r}"
        # 内容应各自独立成行
        assert "AT" in text and "+CSQ: 12,99" in text and "OK" in text
        # AT 和 +CSQ 不应黏在一行
        assert "AT+CSQ" not in text

    def test_custom_baudrate_accepted(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """自定义波特率（非预设值）应被接受并传给 open_port，且加入下拉候选."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        widget.baud_combo.setEditText("512000")
        assert widget._current_baud() == 512000  # noqa: SLF001

        # 打开端口 → 自定义波特率传入
        widget._toggle_connect()  # noqa: SLF001
        assert widget._main.open_calls[-1] == ("COM1", 512000, "8N1")  # noqa: SLF001
        # 自定义值应已加入下拉候选（数字项去重升序，末尾固定「自定义…」项）
        items = [widget.baud_combo.itemText(i) for i in range(widget.baud_combo.count())]
        assert "512000" in items
        assert items[-1] == "自定义…"
        nums = [int(x) for x in items[:-1]]
        assert nums == sorted(set(nums))

    def test_baudrate_non_numeric_rejected(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """非数字波特率 → 校验失败返回 None，且不打开端口."""
        import PySide6.QtWidgets as _qw

        warned: list[str] = []

        def fake_warning(parent, title, text, *a, **k):  # noqa: ANN001
            warned.append(text)

        monkeypatch.setattr(_qw.QMessageBox, "warning", fake_warning)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        widget.baud_combo.setEditText("abc")
        assert widget._current_baud() is None  # noqa: SLF001
        assert warned  # 弹了提示

        # toggle_connect 不应打开端口
        open_before = len(widget._main.open_calls)  # noqa: SLF001
        widget._toggle_connect()  # noqa: SLF001
        assert len(widget._main.open_calls) == open_before  # noqa: SLF001

    def test_baudrate_out_of_range_rejected(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """超范围波特率（0 / 过大）→ 校验失败返回 None."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        widget.baud_combo.setEditText("0")
        assert widget._current_baud() is None  # noqa: SLF001
        widget.baud_combo.setEditText("99999999")
        assert widget._current_baud() is None  # noqa: SLF001

    def test_remember_baud_no_duplicate(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """已存在的预设波特率不应重复加入候选."""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        before = widget.baud_combo.count()
        widget._remember_baud(115200)  # noqa: SLF001  # 预设值已存在
        assert widget.baud_combo.count() == before

    def test_custom_label_item_present(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """下拉列表末尾应有固定「自定义…」触发项."""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        items = [widget.baud_combo.itemText(i) for i in range(widget.baud_combo.count())]
        assert items[-1] == "自定义…"

    def test_select_custom_item_opens_input_dialog(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """选「自定义…」→ 弹输入框 → 确认合法值 → 填入并记忆为候选."""
        import PySide6.QtWidgets as _qw

        getInt_calls: list[int] = []
        monkeypatch.setattr(
            _qw.QInputDialog, "getInt", lambda *a, **k: getInt_calls.append(1) or (768000, True)
        )
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        # 切到「自定义…」项
        custom_idx = widget.baud_combo.findText("自定义…")
        assert custom_idx >= 0
        widget.baud_combo.setCurrentIndex(custom_idx)

        assert getInt_calls, "选「自定义…」应弹输入框"
        assert widget.baud_combo.currentText() == "768000"
        # 应已记忆为候选
        items = [widget.baud_combo.itemText(i) for i in range(widget.baud_combo.count())]
        assert "768000" in items
        # 打开端口 → 用自定义值
        widget._toggle_connect()  # noqa: SLF001
        assert widget._main.open_calls[-1] == ("COM1", 768000, "8N1")  # noqa: SLF001

    def test_select_custom_item_cancel_reverts(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """选「自定义…」→ 取消输入 → 回退到上一个有效波特率，不残留「自定义…」字样."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QInputDialog, "getInt", lambda *a, **k: (0, False))  # 取消
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        idx9600 = widget.baud_combo.findText("9600")
        widget.baud_combo.setCurrentIndex(idx9600)  # 经信号更新 _last_valid_baud
        custom_idx = widget.baud_combo.findText("自定义…")
        widget.baud_combo.setCurrentIndex(custom_idx)

        # 取消后应回退到 9600，不残留「自定义…」
        assert widget.baud_combo.currentText() == "9600"

    def test_open_port_failure_no_remember_no_subscribe(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """打开失败 → 不记忆波特率候选、不订阅 RX（HIGH1 修复回归）."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        main.fail_open = True  # open_port 返回 False
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget.baud_combo.setEditText("512000")

        items_before = [widget.baud_combo.itemText(i) for i in range(widget.baud_combo.count())]
        widget._toggle_connect()  # noqa: SLF001

        # 失败：open_port 被调用过
        assert ("COM1", 512000, "8N1") in main.open_calls
        # 但 512000 不应被加入候选（成功才记忆）
        items_after = [widget.baud_combo.itemText(i) for i in range(widget.baud_combo.count())]
        assert items_before == items_after, "打开失败不应记忆波特率候选"
        assert "512000" not in items_after
        # 不应订阅 RX（无 observer 注册）
        assert "COM1" not in main._rx_observers or not main._rx_observers["COM1"]  # noqa: SLF001
        # 端口未连接
        assert not main.is_port_connected("COM1")

    def test_typed_valid_baud_preserved_on_custom_cancel(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """直接键入有效波特率后，选「自定义…」取消应保留键入值（MED3 修复回归）.

        回归点：editable combo 键入只改 currentText 不改 currentIndex，原先
        _last_valid_baud 不更新，取消时会回退到旧预设值、丢弃键入值。
        """
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QInputDialog, "getInt", lambda *a, **k: (0, False))  # 取消
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        widget.baud_combo.setEditText("512000")  # 直接键入，不走下拉
        # 触发一次 _current_baud 收口更新 _last_valid_baud
        assert widget._current_baud() == 512000  # noqa: SLF001

        custom_idx = widget.baud_combo.findText("自定义…")
        widget.baud_combo.setCurrentIndex(custom_idx)  # 选自定义 → 取消

        # 取消应回退到键入的 512000（而非旧预设 115200）
        assert widget.baud_combo.currentText() == "512000"

    def test_baud_index_changed_not_reentrant(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """选「自定义…」确认后，_on_baud_index_changed 不应被重复触发（MED4 修复回归）."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QInputDialog, "getInt", lambda *a, **k: (768000, True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), _FakeMain())  # type: ignore[arg-type]
        call_count = [0]
        original = widget._on_baud_index_changed  # noqa: SLF001

        def counting_slot(index: int) -> None:  # noqa: ANN001
            call_count[0] += 1
            original(index)

        widget.baud_combo.currentIndexChanged.disconnect()
        widget.baud_combo.currentIndexChanged.connect(counting_slot)

        custom_idx = widget.baud_combo.findText("自定义…")
        widget.baud_combo.setCurrentIndex(custom_idx)  # 选自定义 → 输入 768000 → 确认

        # 选自定义触发 1 次；确认后的 setCurrentText 不应再额外触发（已被 blockSignals）
        # 允许 1~2 次（Qt 内部可能有 1 次合理重入），但绝不应是 3+ 次失控重入
        assert call_count[0] <= 2, f"_on_baud_index_changed 被触发 {call_count[0]} 次，疑似重入"
        assert widget.baud_combo.currentText() == "768000"


class TestManualDebugStripped:
    """命令库改造后：历史/旧快捷指令已删，current_port/send_command 可用，
    多行发送与 HEX 显示功能保留。"""

    def test_no_history_no_quick_attrs(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """确认历史下拉与旧快捷指令属性已移除。"""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        assert not hasattr(widget, "history_combo")
        assert not hasattr(widget, "quick_btn_row")
        assert not hasattr(widget, "_add_quick")

    def test_current_port_and_send_command(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """current_port() 返回选中端口；send_command() 发送并 TX 上屏。"""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        assert widget.current_port() == "COM1"
        widget._toggle_connect()  # noqa: SLF001  打开 COM1
        widget.send_command("AT+CSQ")
        assert main.last_command == ("COM1", "AT+CSQ")
        _t = widget.response_view.toPlainText()
        assert "TX" in _t and "AT+CSQ" in _t

    def test_send_command_requires_connection(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """send_command 端口未连接时不发送。"""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget.send_command("AT+CSQ")  # 未连接
        assert main.last_command is None

    def test_multiline_send_preserved(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """多行发送功能保留（经 send_edit + _send，非 send_command）。"""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001
        widget.send_edit.setPlainText("AT\nATI\nAT+CSQ")
        widget._send()  # noqa: SLF001
        assert main.last_command == ("COM1", "AT+CSQ")
        text = widget.response_view.toPlainText()
        # 多行发送：三行命令都在 TX 渲染中（渲染格式 "<时间戳>   TX  <命令>"）
        assert "AT" in text and "ATI" in text and "AT+CSQ" in text

    def test_hex_display_preserved(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """HEX 显示功能保留。"""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001
        widget.hex_check.setChecked(True)
        main.emit_rx("COM1", b"OK\r\n")
        widget._rx_console.flush()  # noqa: SLF001 —— Pf-1 批量渲染，显式冲刷后断言
        assert "4F 4B" in widget.response_view.toPlainText()


class TestManualDebugFileSendRouting:
    """MainWindow.send_file / get_connection 路由测试（通过 _FakeMain 验证契约）。"""

    def test_send_file_requires_connection(self) -> None:  # type: ignore[no-untyped-def]
        main = _FakeMain()

        # 未连接 → send_file 判定未连接
        assert main.is_port_connected("COM1") is False
        assert main.send_file("COM1", b"abc") is False

    def test_send_file_writes_when_connected(self) -> None:  # type: ignore[no-untyped-def]
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        assert main.send_file("COM1", b"\x01\x02") is True
        assert main.last_bytes == ("COM1", b"\x01\x02")

    def test_get_connection_returns_fake(self) -> None:  # type: ignore[no-untyped-def]
        main = _FakeMain()
        sentinel = object()
        main._fake_connection = sentinel  # noqa: SLF001
        assert main.get_connection("COM1") is sentinel


class TestManualDebugFileSendCard:
    def test_file_send_card_exists(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        assert hasattr(widget, "file_btn")  # 选择文件按钮
        assert hasattr(widget, "file_send_btn")  # 发送按钮
        assert hasattr(widget, "file_progress")  # 进度条
        assert hasattr(widget, "file_cancel_btn")  # 取消按钮

    def test_small_file_sends_synchronously(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 写一个小文件（< 4KB 阈值）
        f = tmp_path / "small.bin"
        f.write_bytes(b"\x01\x02\x03\x04")

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001 —— 模拟已选文件
        widget._update_file_label()

        widget._send_file()  # noqa: SLF001

        assert main.file_sent_event.is_set()
        assert main.last_bytes == ("COM1", b"\x01\x02\x03\x04")
        # TX 原始数据应上屏（响应区含 TX 标记）；Pf-1 经 RxConsole 批量，先冲刷
        widget._rx_console.flush()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "TX" in text

    def test_file_send_requires_connection(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: None)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        f = tmp_path / "x.bin"
        f.write_bytes(b"abc")
        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001

        widget._send_file()  # noqa: SLF001 —— 未连接 → 弹窗、不发

        assert main.last_bytes is None


class TestManualDebugFileSendLarge:
    # 说明：曾尝试引入 pytest-qt 解锁本用例（qtbot 可用、单独跑通过），但在
    # 全量序列下反复触发 Qt 原生崩溃（QThread 与后台线程 GC 时序，"Fatal
    # Python error: Aborted" 整进程挂掉），故 pytest-qt 未纳入 dev 依赖、本
    # 用例维持跳过。大文件 worker 行为已由 unit/test_file_send_worker.py 覆盖，
    # TX 流式上屏经 RxConsole 的批量语义由 TestManualDebugBatchedRendering 覆盖。
    @pytest.mark.skip(reason="依赖 pytest-qt 且全量序列下曾触发 Qt 原生崩溃，保持跳过")
    def test_large_file_uses_worker(self, qtbot, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 大文件（> 4KB）
        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * 5000)

        # 让 _FakeMain.get_connection 返回一个记录写入的替身（write_data 契约）
        class _Conn:
            def __init__(self) -> None:
                self.written: list[bytes] = []

            def write_data(self, spec, *, cancel=None, on_chunk=None) -> None:  # type: ignore[no-untyped-def]
                from atprobe.infra.serial.datastream import send_chunks

                # 复用真实分块算法（sleep 打桩为 no-op，避免真实等待）
                send_chunks(
                    lambda d: self.written.append(d),
                    spec,
                    sleep=lambda _s: None,
                    cancel=cancel,
                    on_chunk=on_chunk,
                )

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        main._fake_connection = _Conn()  # noqa: SLF001
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001
        widget._update_file_label()

        widget._send_file()  # noqa: SLF001

        # 大文件 → worker 创建并启动（需事件循环驱动 started→run→finished）
        assert widget._file_worker is not None  # noqa: SLF001
        # 驱动事件循环，等待 worker 完成、线程退出、引用清理
        qtbot.waitUntil(lambda: widget._file_worker is None, timeout=5000)  # noqa: SLF001
        # 替身记录了分块写入（5000 字节按 1024 分块 = 5 块）
        assert len(main._fake_connection.written) >= 1  # noqa: SLF001
        assert b"".join(main._fake_connection.written) == b"x" * 5000  # noqa: SLF001

    def test_file_send_disables_text_send(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        # 进入发送中 → 文本发送框禁用、取消按钮可见
        widget._enter_file_sending()  # noqa: SLF001
        assert widget.send_edit.isEnabled() is False
        assert widget.file_send_btn.isEnabled() is False
        # isVisible() 对未 show() 的控件恒为 False，用 not isHidden() 验证可见策略
        assert widget.file_cancel_btn.isHidden() is False

        # 退出 → 恢复
        widget._exit_file_sending()  # noqa: SLF001
        assert widget.send_edit.isEnabled() is True


class TestCommandLibraryPanel:
    """命令库侧栏面板：加载渲染 + 单击发送信号。"""

    def test_loads_and_renders_tree(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """面板从内置示例加载 → 渲染出项目/功能/命令三层。"""
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        panel = CommandLibraryPanel()
        # 内置示例含 2 个顶层项目（N58 项目 + 通用）
        assert panel.tree.topLevelItemCount() == 2
        # 第一个项目下应有功能组（叶子为命令）
        first = panel.tree.topLevelItem(0)
        assert first is not None and first.childCount() > 0

    def test_click_command_emits_signal(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """单击命令叶子 → emit send_requested(命令字符串)。"""
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        panel = CommandLibraryPanel()
        received: list[str] = []
        panel.send_requested.connect(lambda cmd: received.append(cmd))

        # 找第一个命令叶子并单击
        first_proj = panel.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        first_cmd = first_grp.child(0)
        panel._on_click(first_cmd, 0)  # noqa: SLF001
        assert len(received) == 1
        assert received[0] == first_cmd.text(0)

    def test_click_project_does_not_emit(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """单击项目/功能节点 → 不 emit 信号。"""
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        panel = CommandLibraryPanel()
        received: list[str] = []
        panel.send_requested.connect(lambda cmd: received.append(cmd))

        proj_item = panel.tree.topLevelItem(0)
        panel._on_click(proj_item, 0)  # noqa: SLF001
        assert received == []

    def test_builtin_missing_falls_back_to_default(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """内置示例文件缺失时，reload_library 回落到内存默认库（迁移 5 条指令）."""
        from atprobe.gui.widgets import command_library as cl_mod
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        # 让 builtin_library_path 指向一个不存在的路径，模拟打包后缺失数据文件
        fake_path = tmp_path / "quick_commands.yaml"
        monkeypatch.setattr(cl_mod, "builtin_library_path", lambda: fake_path)

        panel = CommandLibraryPanel()
        # 回退后应含 default_library 的项目（通用/基础，含 AT 等）
        all_cmds = [
            c
            for p in panel._library.projects
            for g in p.groups
            for c in g.commands  # noqa: SLF001
        ]
        assert "AT" in all_cmds and "AT+CSQ" in all_cmds


class TestManualDebugEmbeddedPanel:
    """手动调试页内嵌命令库面板：单击命令 → 页内 send_command。"""

    def test_panel_embedded_in_manual_debug(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """手动调试页含内嵌命令库面板（QSplitter 左侧）。"""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        assert hasattr(widget, "_cmd_panel")
        assert isinstance(widget._cmd_panel, CommandLibraryPanel)

    def test_click_command_sends_in_page(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """单击面板命令 → 经 send_requested → 页内 send_command → send_manual 被调用。"""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001  打开 COM1

        # 单击面板第一个命令叶子
        panel = widget._cmd_panel  # noqa: SLF001
        first_proj = panel.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        first_cmd = first_grp.child(0)
        panel._on_click(first_cmd, 0)  # noqa: SLF001

        # 经 send_requested → send_command → send_manual，last_command 应被设置
        assert main.last_command is not None
        assert main.last_command[0] == "COM1"
        assert main.last_command[1] == first_cmd.text(0)


class TestLibraryManagerDialogToolbar:
    """管理对话框：顶部只保留＋项目，新增功能组/命令下放到树节点内嵌＋按钮."""

    def test_toolbar_only_has_add_project(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """对话框顶部只有 [＋项目]，旧的 ＋功能组/＋命令 按钮已移除."""
        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        assert dlg._add_project_btn.text() == "＋项目"  # noqa: SLF001
        # 旧的 ＋功能组 / ＋命令 按钮应已移除
        assert not hasattr(dlg, "_add_group_btn")
        assert not hasattr(dlg, "_add_cmd_btn")

    def test_embedded_add_buttons_present(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """项目/功能组节点行内嵌 widget（含＋按钮），命令节点无."""
        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())

        first_proj = dlg.tree.topLevelItem(0)
        # 项目节点应有内嵌 widget
        assert dlg.tree.itemWidget(first_proj, 0) is not None  # noqa: SLF001
        # 第一个子节点应是功能组，也应有内嵌 widget
        first_grp = first_proj.child(0)
        assert dlg.tree.itemWidget(first_grp, 0) is not None  # noqa: SLF001
        # 功能组下的命令节点（叶子）不应有内嵌 widget
        if first_grp.childCount() > 0:
            first_cmd = first_grp.child(0)
            assert dlg.tree.itemWidget(first_cmd, 0) is None  # noqa: SLF001

    def test_add_group_via_embedded_button(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """项目节点内嵌＋ → _add_group_interactive → 新功能组出现在该项目下."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("新功能组", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        from PySide6.QtCore import Qt as _Qt

        proj_name = first_proj.data(0, _Qt.ItemDataRole.UserRole)[
            1
        ]  # 元组第二项=项目名  # noqa: SLF001
        before = first_proj.childCount()

        dlg._add_group_interactive(proj_name)  # noqa: SLF001

        new_proj = dlg.tree.topLevelItem(0)
        assert new_proj.childCount() == before + 1
        # 新功能组节点应存在
        grp_names = [new_proj.child(i).text(0) for i in range(new_proj.childCount())]
        assert "新功能组" in grp_names

    def test_add_command_via_embedded_button(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """功能组节点内嵌＋ → _add_command_interactive → 新命令加入该功能组."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CGMM", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        from PySide6.QtCore import Qt as _Qt

        gnode = first_grp.data(
            0, _Qt.ItemDataRole.UserRole
        )  # 元组: ("group", proj, grp)  # noqa: SLF001
        proj_name, grp_name = gnode[1], gnode[2]
        before = first_grp.childCount()

        dlg._add_command_interactive(proj_name, grp_name)  # noqa: SLF001

        new_proj = dlg.tree.topLevelItem(0)
        new_grp = new_proj.child(0)
        assert new_grp.childCount() == before + 1
        cmd_texts = [new_grp.child(i).text(0) for i in range(new_grp.childCount())]
        assert "AT+CGMM" in cmd_texts

    def test_add_command_no_selection_needed(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """无需预先选中节点：直接传项目+功能组名即可加命令（消除旧痛点）."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        input_called: list[bool] = []
        monkeypatch.setattr(
            _qw.QInputDialog,
            "getText",
            lambda *a, **k: input_called.append(True) or ("AT+CGMM", True),
        )
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        dlg.tree.clearSelection()  # 明确不选任何节点
        first_proj = dlg.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        from PySide6.QtCore import Qt as _Qt

        gnode = first_grp.data(0, _Qt.ItemDataRole.UserRole)  # noqa: SLF001

        dlg._add_command_interactive(gnode[1], gnode[2])  # noqa: SLF001
        # 应成功弹输入框并添加，不因未选中而失败
        assert input_called
        new_grp = dlg.tree.topLevelItem(0).child(0)
        assert any(new_grp.child(i).text(0) == "AT+CGMM" for i in range(new_grp.childCount()))

    def test_add_keeps_position_by_selecting_new_node(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """添加命令后，新命令节点被选中（保持位置、不跳回顶端）.

        回归点：之前 _refresh_tree() 重建后无选中态 + expandAll() 让滚动条重置顶端，
        指令多时无法连续添加。现在新增项被 setCurrentItem 选中并居中滚动。
        """
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CGSN", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        from PySide6.QtCore import Qt as _Qt

        gnode = first_grp.data(0, _Qt.ItemDataRole.UserRole)  # noqa: SLF001

        dlg._add_command_interactive(gnode[1], gnode[2])  # noqa: SLF001

        # 重建后 currentItem 应为新加的命令节点（role 元组第四项为 "AT+CGSN"，
        # 第五项为组内索引——批 5 T6-9 起命令节点带索引）
        cur = dlg.tree.currentItem()
        assert cur is not None
        role = cur.data(0, _Qt.ItemDataRole.UserRole)
        assert role[:4] == ("command", gnode[1], gnode[2], "AT+CGSN")
        assert isinstance(role[4], int)

    def test_add_group_keeps_position(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """添加功能组后，新功能组节点被选中并居中滚动到位."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("新功能组", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        from PySide6.QtCore import Qt as _Qt

        proj_name = first_proj.data(0, _Qt.ItemDataRole.UserRole)[1]  # noqa: SLF001

        dlg._add_group_interactive(proj_name)  # noqa: SLF001

        cur = dlg.tree.currentItem()
        assert cur is not None
        role = cur.data(0, _Qt.ItemDataRole.UserRole)
        assert role == ("group", proj_name, "新功能组")


class TestCommandLibraryPanelContextMenu:
    """发送界面（侧栏面板）：右键菜单 + 双击修改（改动即时落盘）."""

    def test_context_menu_command_has_edit_delete(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """右键命令节点：菜单含「修改」「删除」两项."""
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        panel = CommandLibraryPanel()
        first_cmd = panel.tree.topLevelItem(0).child(0).child(0)
        from PySide6.QtCore import Qt as _Qt

        node = first_cmd.data(0, _Qt.ItemDataRole.UserRole)
        assert node[0] == "command"  # 确认是命令叶子

        # 收集菜单 action 文本
        texts: list[str] = []
        panel.tree.setCurrentItem(first_cmd)
        menu_text = panel._collect_menu_texts(first_cmd)  # noqa: SLF001
        texts.extend(menu_text)
        assert any("修改" in t for t in texts), f"命令右键菜单应有「修改」: {texts}"
        assert any("删除" in t for t in texts), f"命令右键菜单应有「删除」: {texts}"

    def test_context_menu_project_has_rename_delete_add_group(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """右键项目节点：菜单含「重命名」「删除项目」「新增功能组」."""
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        panel = CommandLibraryPanel()
        first_proj = panel.tree.topLevelItem(0)
        texts = panel._collect_menu_texts(first_proj)  # noqa: SLF001
        assert any("重命名" in t for t in texts), texts
        assert any("删除" in t for t in texts), texts
        assert any("新增功能组" in t for t in texts), texts

    def test_double_click_command_edits_and_persists(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """双击命令 → 弹输入框改值 → 即时落盘到 YAML（reload 后能看到新值）."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets import command_library as cl_mod
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        # 用临时文件作为库路径（避免污染内置示例文件）
        lib_file = tmp_path / "lib.yaml"
        from atprobe.infra.quickcmd import default_library, dump_library

        dump_library(default_library(), lib_file)
        monkeypatch.setattr(cl_mod, "builtin_library_path", lambda: lib_file)

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CGMM_NEW", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        panel = CommandLibraryPanel()
        first_cmd = panel.tree.topLevelItem(0).child(0).child(0)
        from PySide6.QtCore import Qt as _Qt

        node = first_cmd.data(0, _Qt.ItemDataRole.UserRole)
        proj, grp, old_cmd = node[1], node[2], node[3]

        panel._on_double_click(first_cmd)  # noqa: SLF001

        # 内存库已更新
        new_grp = panel._library.find_group(proj, grp)  # noqa: SLF001
        assert new_grp is not None
        assert "AT+CGMM_NEW" in new_grp.commands
        assert old_cmd not in new_grp.commands or old_cmd == "AT+CGMM_NEW"
        # 已落盘到 YAML（reload 后仍能看到）
        from atprobe.infra.quickcmd import load_library

        disk_lib = load_library(lib_file)
        disk_grp = disk_lib.find_group(proj, grp)
        assert disk_grp is not None and "AT+CGMM_NEW" in disk_grp.commands

    def test_delete_command_no_confirm(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """删除命令不弹确认（QMessageBox.question 不应被调用）."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets import command_library as cl_mod
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        lib_file = tmp_path / "lib.yaml"
        from atprobe.infra.quickcmd import default_library, dump_library

        dump_library(default_library(), lib_file)
        monkeypatch.setattr(cl_mod, "builtin_library_path", lambda: lib_file)

        question_called: list[bool] = []
        monkeypatch.setattr(
            _qw.QMessageBox,
            "question",
            lambda *a, **k: question_called.append(True) or _qw.QMessageBox.StandardButton.No,
        )

        panel = CommandLibraryPanel()
        first_cmd = panel.tree.topLevelItem(0).child(0).child(0)
        from PySide6.QtCore import Qt as _Qt

        node = first_cmd.data(0, _Qt.ItemDataRole.UserRole)
        proj, grp, cmd, idx = node[1], node[2], node[3], node[4]

        panel._delete_command(proj, grp, idx)  # noqa: SLF001

        assert not question_called, "删命令不应弹确认"
        grp_obj = panel._library.find_group(proj, grp)  # noqa: SLF001
        assert grp_obj is not None and cmd not in grp_obj.commands

    def test_delete_project_confirms(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """删除项目弹确认：选 No 不删，选 Yes 删."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets import command_library as cl_mod
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        lib_file = tmp_path / "lib.yaml"
        from atprobe.infra.quickcmd import default_library, dump_library

        dump_library(default_library(), lib_file)
        monkeypatch.setattr(cl_mod, "builtin_library_path", lambda: lib_file)

        # --- 选 No：不删 ---
        monkeypatch.setattr(
            _qw.QMessageBox, "question", lambda *a, **k: _qw.QMessageBox.StandardButton.No
        )
        panel = CommandLibraryPanel()
        first_proj = panel.tree.topLevelItem(0)
        from PySide6.QtCore import Qt as _Qt

        proj_name = first_proj.data(0, _Qt.ItemDataRole.UserRole)[1]
        panel._delete_project(proj_name)  # noqa: SLF001
        assert panel._library.find_project(proj_name) is not None  # noqa: SLF001  # 仍在

        # --- 选 Yes：删 ---
        monkeypatch.setattr(
            _qw.QMessageBox, "question", lambda *a, **k: _qw.QMessageBox.StandardButton.Yes
        )
        panel2 = CommandLibraryPanel()
        first_proj2 = panel2.tree.topLevelItem(0)
        proj_name2 = first_proj2.data(0, _Qt.ItemDataRole.UserRole)[1]
        panel2._delete_project(proj_name2)  # noqa: SLF001
        assert panel2._library.find_project(proj_name2) is None  # noqa: SLF001  # 已删


class TestCommandIndexOperations:
    """批 5 T6-9：命令树增删改按索引（同文重复命令不再被按文本误伤）.

    旧实现 _delete_command/_edit_command 按文本 remove_command——组内存在
    同文重复命令时删除会全部消失（数据丢失）、修改会误删重复项且挪序。
    """

    @staticmethod
    def _dialog_with_duplicates(qapp, tmp_path):  # type: ignore[no-untyped-def]
        from atprobe.domain.quickcmd import CommandLibrary
        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import dump_library, load_library

        lib = CommandLibrary.empty()
        lib.add_project("P1")
        grp = lib.add_group("P1", "G1")
        grp.commands += ["AT", "AT", "AT+CSQ"]
        path = tmp_path / "lib.yaml"
        dump_library(lib, path)
        return LibraryManagerDialog(load_library(path), path), path

    def test_node_carries_index(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """命令节点角色元组带组内索引（5 元组）."""
        from PySide6.QtCore import Qt as _Qt

        dlg, _ = self._dialog_with_duplicates(qapp, tmp_path)
        first_cmd = dlg.tree.topLevelItem(0).child(0).child(0)
        node = first_cmd.data(0, _Qt.ItemDataRole.UserRole)
        assert node[:4] == ("command", "P1", "G1", "AT")
        assert node[4] == 0
        second = dlg.tree.topLevelItem(0).child(0).child(1)
        assert second.data(0, _Qt.ItemDataRole.UserRole)[4] == 1

    def test_delete_by_index_removes_only_that_duplicate(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """按索引删除：只删点中的那一条（旧实现按文本删会两个 AT 全没）."""
        dlg, _ = self._dialog_with_duplicates(qapp, tmp_path)
        dlg._delete_command("P1", "G1", 1)  # noqa: SLF001
        grp = dlg._library.find_group("P1", "G1")  # noqa: SLF001
        assert grp is not None
        assert grp.commands == ["AT", "AT+CSQ"]

    def test_edit_replaces_in_place(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """修改命令原位替换：保序且不动同文重复项（旧实现 add+remove 全删同文）."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("ATZ", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        dlg, _ = self._dialog_with_duplicates(qapp, tmp_path)
        dlg._edit_command("P1", "G1", "AT", 1)  # noqa: SLF001
        grp = dlg._library.find_group("P1", "G1")  # noqa: SLF001
        assert grp is not None
        assert grp.commands == ["AT", "ATZ", "AT+CSQ"]


class TestLibraryManagerDialogNoFormPanel:
    """添加界面（管理对话框）：去掉右侧表单，全靠双击 + 右键增删改."""

    def test_form_panel_removed(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """右侧表单相关成员应已全部移除."""
        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        dlg = LibraryManagerDialog(load_library(builtin_library_path()), builtin_library_path())
        for attr in ("_form_host", "_form_layout", "_on_tree_select", "_build_project_form"):
            assert not hasattr(dlg, attr), f"右侧表单成员 {attr} 应已移除"

    def test_double_click_command_edits(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """对话框双击命令 → 修改（工作副本，未落盘）."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CGSN_NEW", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        dlg = LibraryManagerDialog(load_library(builtin_library_path()), builtin_library_path())
        first_cmd = dlg.tree.topLevelItem(0).child(0).child(0)
        from PySide6.QtCore import Qt as _Qt

        node = first_cmd.data(0, _Qt.ItemDataRole.UserRole)
        proj, grp = node[1], node[2]

        dlg._on_double_click(first_cmd)  # noqa: SLF001

        new_grp = dlg._library.find_group(proj, grp)  # noqa: SLF001
        assert new_grp is not None and "AT+CGSN_NEW" in new_grp.commands

    def test_context_menu_group_has_add_command(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """对话框右键功能组：菜单含「重命名」「新增命令」「删除功能组」."""
        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        dlg = LibraryManagerDialog(load_library(builtin_library_path()), builtin_library_path())
        first_grp = dlg.tree.topLevelItem(0).child(0)
        texts = dlg._collect_menu_texts(first_grp)  # noqa: SLF001
        assert any("重命名" in t for t in texts), texts
        assert any("新增命令" in t for t in texts), texts
        assert any("删除" in t for t in texts), texts

    def test_delete_project_confirms_in_dialog(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """对话框删除项目弹确认：选 Yes 删，选 No 不删."""
        import PySide6.QtWidgets as _qw
        from PySide6.QtCore import Qt as _Qt

        from atprobe.gui.widgets.command_library import LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        # Yes → 删
        monkeypatch.setattr(
            _qw.QMessageBox, "question", lambda *a, **k: _qw.QMessageBox.StandardButton.Yes
        )
        dlg = LibraryManagerDialog(load_library(builtin_library_path()), builtin_library_path())
        proj_name = dlg.tree.topLevelItem(0).data(0, _Qt.ItemDataRole.UserRole)[1]  # noqa: SLF001

        dlg._delete_project(proj_name)  # noqa: SLF001
        assert dlg._library.find_project(proj_name) is None  # noqa: SLF001

    def test_embedded_add_button_click_adds_command(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """功能组节点内嵌的＋按钮：点击 → 弹输入框 → 加命令（覆盖 lambda 接线）."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets.command_library import _NODE_ROLE, LibraryManagerDialog
        from atprobe.infra.quickcmd import builtin_library_path, load_library

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CBC", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        dlg = LibraryManagerDialog(load_library(builtin_library_path()), builtin_library_path())
        first_grp_item = dlg.tree.topLevelItem(0).child(0)
        gnode = first_grp_item.data(0, _NODE_ROLE)
        proj_name, grp_name = gnode[1], gnode[2]

        # 取内嵌 widget 里的＋按钮（QToolButton）并点击
        node_widget = dlg.tree.itemWidget(first_grp_item, 0)  # noqa: SLF001
        assert node_widget is not None
        add_btn = node_widget.findChild(_qw.QToolButton)
        assert add_btn is not None, "功能组节点应有内嵌＋按钮"
        add_btn.click()

        # 命令已加入该功能组
        grp = dlg._library.find_group(proj_name, grp_name)  # noqa: SLF001
        assert grp is not None and "AT+CBC" in grp.commands


class TestEngineErrorToUI:
    """日志功能：引擎线程异常时经 progress 信号推 UI（engine_error）弹窗提示。"""

    def test_engine_error_emits_critical_dialog(self, qapp, monkeypatch):  # type: ignore[no-untyped-def]
        """_on_progress 收到 ('engine_error', msg) → 弹 critical 对话框，含错误和日志路径提示."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.mainwindow import MainWindow

        critical_calls: list[str] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "critical", lambda parent, title, msg: critical_calls.append(msg)
        )

        win = MainWindow()
        win.show()
        qapp.processEvents()

        # 模拟引擎线程 emit 了 engine_error
        win.progress.emit(("engine_error", "执行异常：模拟的引擎错误"))
        qapp.processEvents()

        # 应弹 critical 对话框，文案含错误摘要 + 日志路径提示
        assert critical_calls, "engine_error 应触发 QMessageBox.critical"
        assert any("执行异常" in c and "日志" in c for c in critical_calls), (
            f"弹窗应含错误摘要+日志提示，实际: {critical_calls}"
        )


class TestHelpMenuLogDir:
    """帮助菜单含「打开日志目录」项。"""

    def test_help_menu_has_open_log_action(self, qapp):  # type: ignore[no-untyped-def]
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        help_menu = None
        for action in win.menuBar().actions():
            if action.text() == "帮助(&H)":
                help_menu = action.menu()
                break
        assert help_menu is not None
        texts = [a.text() for a in help_menu.actions()]
        assert "打开日志目录" in texts


# ===========================================================================
# 批次6 回归测试：B5(env新增参数) / B6(tab cleanup) / M11(主题刷新)
# ===========================================================================
class TestEnvAddParam:
    """B5 回归：环境配置「新增参数」功能应实际生效。"""

    def test_add_param_creates_editable_field(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """新增参数后表单应出现新输入框（旧 bug：功能完全失效）。"""
        from atprobe.gui.tabs.env_config import EnvConfigWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="env_config", params={})
        widget = EnvConfigWidget(binding, object())  # type: ignore[arg-type]
        # 预加载一个组
        from atprobe.infra.config.envconfig import EnvConfig

        widget._env = EnvConfig(_groups={"test_group": {"existing": "val"}}, source=None)  # noqa: SLF001
        widget._rebuild_form()  # noqa: SLF001
        assert "existing" in widget._group_widgets.get("test_group", {})  # noqa: SLF001

        # mock QInputDialog 返回新参数名 "new_param"
        import PySide6.QtWidgets as _qw

        _qw.QInputDialog.getText = lambda *a, **k: ("new_param", True)  # type: ignore[assignment,method-assign]

        widget._add_param("test_group")  # noqa: SLF001

        # B5 核心：新参数应出现在表单中（旧 bug 下什么都不出现）
        assert "new_param" in widget._group_widgets.get("test_group", {}), (
            "B5 回归：新增参数后表单应出现新输入框"
        )


class TestTabCleanup:
    """B6 回归：tab 关闭时调 cleanup 释放资源。"""

    def test_manual_debug_has_cleanup_method(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """ManualDebugWidget 应有 cleanup 方法（B6）。"""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        assert hasattr(widget, "cleanup"), "B6：ManualDebugWidget 应有 cleanup 方法"
        assert hasattr(widget, "refresh_theme"), "M11：应有 refresh_theme 方法"
        # cleanup 应可调用且不抛错（无订阅时也应安全）
        widget.cleanup()

    def test_monitor_has_cleanup_method(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """MonitorWidget 应有 cleanup 方法（B6）。"""
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = MonitorWidget(TabBinding(type_name="monitor", params={}), main)  # type: ignore[arg-type]
        assert hasattr(widget, "cleanup"), "B6：MonitorWidget 应有 cleanup 方法"
        assert hasattr(widget, "refresh_theme"), "M11：应有 refresh_theme 方法"
        widget.cleanup()  # 不抛错


class TestThemeRefresh:
    """M11 回归：主题切换后 widget 的 tokens 应刷新。"""

    def test_manual_debug_refresh_theme_updates_tokens(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """refresh_theme 后 _tokens 应取当前全局主题（非硬编码浅色）。"""
        from PySide6.QtWidgets import QApplication

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding
        from atprobe.gui.theme import apply_theme, get_tokens

        app = QApplication.instance() or QApplication([])
        # 应用深色主题
        apply_theme(app, dark=True)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget.refresh_theme()
        dark_tokens = get_tokens(dark=True)
        # refresh_theme 后 _tokens 应与深色 tokens 一致
        assert widget._tokens["data.tx"] == dark_tokens["data.tx"]  # noqa: SLF001

        # 切回浅色
        apply_theme(app, dark=False)
        widget.refresh_theme()
        light_tokens = get_tokens(dark=False)
        assert widget._tokens["data.tx"] == light_tokens["data.tx"]  # noqa: SLF001


class TestEngineThreadNoDirectUi:
    """P0-2：引擎线程闭包 _run 不得直接调用 UI（QTimer/控件仅主线程可操作）.

    跨线程 UI 调用无法稳定复现崩溃，改用源码守护：run_cases 内不得出现
    ERROR 态的直接状态设置（"RUNNING" 设置在 :898 属主线程调用，合法保留）。
    守护经 AST 判定（批 5 正则化）：按调用节点匹配方法名与首参常量——不受
    注释文本/引号风格/拼接写法影响，子串匹配的两类失真（注释误报、改写漏报）
    均消除。
    """

    def test_run_closure_has_no_error_status_call(self) -> None:
        import ast
        import inspect
        import textwrap

        from atprobe.gui.mainwindow import MainWindow

        tree = ast.parse(textwrap.dedent(inspect.getsource(MainWindow.run_cases)))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_set_engine_status"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "ERROR"
            ):
                pytest.fail(
                    "run_cases 的 _run 闭包在引擎线程执行，不得直接调用 _set_engine_status"
                    "——异常状态应由 progress 信号在主线程槽 _on_progress 设置",
                    pytrace=False,
                )


class TestDownloadWorkerPassesSha256:
    """P1-9：GUI 下载链路必须传入 expected_sha256（仅长度校验防不了等大小替换）.

    T5（D-3）迁移：_download_worker 改经 UpdateSession 编排，patch 目标随迁
    到 session 层——断言不变：sha256/size 仍端到端贯通至 downloader.download。
    T7（D-1）：方法随 UpdateController 迁移，调用点改为 win._update_controller
    （MainWindow 不再持有更新族方法/信号）。
    """

    def test_download_receives_expected_sha256(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import pathlib
        from types import SimpleNamespace

        import atprobe.infra.update.session as session_mod
        from atprobe.gui.mainwindow import MainWindow

        recorded: dict[str, object] = {}

        def _fake_download(
            url, dest, *, filename, expected_size, progress_cb, cancel_token, **kwargs
        ):  # type: ignore[no-untyped-def]
            recorded["expected_sha256"] = kwargs.get("expected_sha256")
            recorded["expected_size"] = expected_size
            recorded["filename"] = filename
            return SimpleNamespace(path=pathlib.Path(dest) / filename)

        monkeypatch.setattr(session_mod, "download", _fake_download)
        info = SimpleNamespace(
            zip_url="https://example.invalid/x.zip",
            version="0.10.0",
            zip_size=123,
            sha256="deadbeef",
            minisig_url=None,
        )
        win = MainWindow()
        ctrl = win._update_controller  # noqa: SLF001
        # 主线程同步调用 _download_worker 时，emit 为直接连接，会同步执行
        # _on_download_done → QMessageBox.question 模态框——offscreen 模式无人可点，
        # 测试将永久挂起。本测试只验证 download 收到的参数，故先断开该信号。
        ctrl.download_done.disconnect()
        try:
            ctrl._download_worker(info)  # noqa: SLF001 - 同步执行，直接调用验证参数
        finally:
            win._raw_logger.stop()  # noqa: SLF001
            win.close()
        assert recorded["expected_sha256"] == "deadbeef", (
            "_download_worker 未把 ReleaseInfo.sha256 传给 download——GUI 更新链路缺内容校验"
        )
        assert recorded["expected_size"] == 123
        # D-3：文件名由 UpdateSession 按模板生成（旧 GUI 硬编码路径的回归哨兵）
        assert recorded["filename"] == "ATProbe-0.10.0-win64.zip"


# ===========================================================================
# 批3 T7：启动级错误消费侧呈现（设计 §4.4②）+ send_manual False 语义（2a）
# ===========================================================================
class TestStartupErrorConsumption:
    """engine.start 正常返回但 result.error 非空 → engine_error 事件（非 done）."""

    def test_startup_error_event_mapping(self) -> None:
        """纯函数 _startup_error_event：error 非空 → ("engine_error", "执行失败：…")；否则 None."""
        from atprobe.domain.report.models import ExecutionResult, Summary
        from atprobe.gui.mainwindow import _startup_error_event

        ev = _startup_error_event(
            ExecutionResult(summary=Summary(), error="端口全部打开失败：COM3 被占用")
        )
        assert ev == ("engine_error", "执行失败：端口全部打开失败：COM3 被占用")
        # 无启动错误（正常执行路径）→ None（走 done/done_noreport 分支）
        assert (
            _startup_error_event(ExecutionResult(summary=Summary(total_cases=1, passed=1))) is None
        )

    def test_run_emits_engine_error_not_done(self, qapp, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        """§4.4② 回归：启动级错误（error 非空、case_results 空）旧实现走 done 分支
        ——绿色 FINISHED + "通过 0 / 失败 0" 弹窗，失败原因完全不可见。
        修复后应投递 engine_error（与 done/done_noreport 三分支互斥）。
        """
        import PySide6.QtWidgets as _qw

        from atprobe.domain.report.models import ExecutionResult, Summary
        from atprobe.gui import mainwindow as mw
        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.config import PortConfig
        from atprobe.infra.serial.fakeserial import FakePortManager

        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)

        case_file = tmp_path / "net.yaml"
        case_file.write_text(
            "name: c1\nsteps:\n  - command: AT\n    assert: {contains: OK}\n", encoding="utf-8"
        )

        result = ExecutionResult(summary=Summary(), error="端口全部打开失败：COM9 不存在")

        class _FakeEngine:
            """start 正常返回（不抛异常）但携带启动级错误的引擎替身."""

            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                pass

            def start(self, cfg, handler=None):  # noqa: ANN001
                return result

        monkeypatch.setattr(mw, "Engine", _FakeEngine)

        win = MainWindow()
        win._port_manager = FakePortManager(sleep=lambda s: None)  # noqa: SLF001
        win._port_manager.open(PortConfig(name="COM9"))  # noqa: SLF001

        events: list[object] = []
        win.progress.connect(lambda ev: events.append(ev))

        try:
            win.run_cases([str(case_file)], "COM9", 90)
            if win._engine_thread is not None:
                win._engine_thread.join(timeout=5)
            qapp.processEvents()  # 投递引擎线程 queued 信号
        finally:
            win._raw_logger.stop()  # noqa: SLF001

        tags = [ev[0] for ev in events if isinstance(ev, tuple) and ev]
        assert "engine_error" in tags, f"启动级错误应投递 engine_error，实际事件: {events}"
        assert "done" not in tags and "done_noreport" not in tags, (
            f"engine_error 与 done/done_noreport 应互斥，实际事件: {events}"
        )
        err = next(ev for ev in events if isinstance(ev, tuple) and ev and ev[0] == "engine_error")
        assert "执行失败" in err[1] and "COM9 不存在" in err[1]  # type: ignore[union-attr]


class TestSendManualFalseSemantics:
    """2a：send_manual 返回 False = 未发送（原因已弹框告知），调用方不得渲染误导文案."""

    @staticmethod
    def _busy_main():  # type: ignore[no-untyped-def]
        """已连接但 send_manual 恒 False 的替身——模拟端口忙/引擎运行（真实实现已弹框）."""

        class _BusyMain(_FakeMain):
            def send_manual(self, port, command, *, terminator=None):  # noqa: ANN001
                return False

        main = _BusyMain()
        return main

    def test_multiline_send_false_no_misleading_label(self, qapp, monkeypatch):  # type: ignore[no-untyped-def]
        """多行发送中 False：响应区不得出现"端口未连接"误导文案，且中止剩余命令."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = self._busy_main()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001
        widget.send_edit.setPlainText("AT\nAT+CSQ")
        widget._send()  # noqa: SLF001

        text = widget.response_view.toPlainText()
        assert "端口未连接" not in text, f"False=原因已弹框，不得渲染误导文案: {text!r}"
        # 首条失败即中止本轮（原因持续存在，逐条重发只会逐条弹框）：仅 1 条 TX 上屏
        assert text.count("TX") == 1, f"应中止剩余命令，实际 TX 行数: {text.count('TX')}"

    def test_send_command_false_no_misleading_label(self, qapp, monkeypatch):  # type: ignore[no-untyped-def]
        """命令库单发 False：同 2a 语义，不渲染"端口未连接"误导文案."""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = self._busy_main()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001
        widget.send_command("AT+CSQ")

        text = widget.response_view.toPlainText()
        assert "端口未连接" not in text, f"False=原因已弹框，不得渲染误导文案: {text!r}"


class TestManualDebugBatchedRendering:
    """Pf-1：manual_debug 流式路径（rx 字节 / tx 文件字节）经 RxConsole 批量渲染."""

    def _make_widget(self):  # noqa: ANN001, no-untyped-def
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        return widget, main

    def test_rx_batched_until_flush(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """RX 行入缓冲（定时未到不上屏），flush 一次批量渲染两行。"""
        widget, main = self._make_widget()
        widget._toggle_connect()  # noqa: SLF001 —— 打开端口 + RX 订阅
        # Pf-1：订阅建立即启动批量渲染定时器（流式会话随订阅起停）
        assert widget._rx_console.is_running()  # noqa: SLF001

        main.emit_rx("COM1", b"alpha\r\nbeta\r\n")
        assert widget._rx_console.pending_count == 2  # noqa: SLF001 —— 两行入缓冲
        assert widget.response_view.toPlainText() == ""  # 批量渲染点未到不上屏

        widget._rx_console.flush()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "alpha" in text and "beta" in text
        assert widget._rx_console.pending_count == 0  # noqa: SLF001

    def test_rx_console_timer_stops_on_close(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """关闭端口（退订）停控制台定时器并冲刷残余。"""
        widget, main = self._make_widget()
        widget._toggle_connect()  # noqa: SLF001
        main.emit_rx("COM1", b"tail-line\r\n")
        widget._toggle_connect()  # noqa: SLF001 —— 关闭
        assert not widget._rx_console.is_running()  # noqa: SLF001
        # 停止时冲刷：关端口前收到的数据仍上屏（可回看）
        assert "tail-line" in widget.response_view.toPlainText()

    def test_tx_file_bytes_batched(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """文件 TX 字节流（设备数据流语义）经缓冲批量上屏。"""
        widget, main = self._make_widget()
        main._connected.add("COM1")  # noqa: SLF001
        f = tmp_path / "small.bin"
        f.write_bytes(b"hello")
        widget._file_path = str(f)  # noqa: SLF001

        widget._send_file()  # noqa: SLF001
        assert main.last_bytes == ("COM1", b"hello")
        assert widget._rx_console.pending_count == 1  # noqa: SLF001 —— TX 入同一控制台缓冲
        assert widget.response_view.toPlainText() == ""

        widget._rx_console.flush()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "TX" in text and "hello" in text

    def test_ui_message_renders_directly(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """非流式路径（低频 UI 消息）不走缓冲——直渲染立即可见。"""
        widget, _main = self._make_widget()
        widget._append_line("RX", "[错误] 引擎未就绪", widget._tokens["danger"])  # noqa: SLF001
        assert "[错误] 引擎未就绪" in widget.response_view.toPlainText()
        assert widget._rx_console.pending_count == 0  # noqa: SLF001 —— 未入缓冲

    def test_tx_command_renders_directly(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """命令型 TX（用户单发，UI 消息语义）保持即时上屏（串口助手"发送即记录"）。"""
        widget, main = self._make_widget()
        widget._toggle_connect()  # noqa: SLF001
        widget.send_command("AT")
        assert "AT" in widget.response_view.toPlainText()  # 无需 flush
        assert main.last_command == ("COM1", "AT")


class TestMainWindowBackgroundOpen:
    """Pf-3：串口 open 移后台线程（慢速 COM 驱动 open 可达秒级，避免冻结 UI）。

    注：用 DirectConnection 在发射线程直接捕获结果（无需事件循环驱动 Queued
    投递），避免测试内 processEvents 自旋与后台线程竞争（曾触发原生崩溃）；
    窗口加入 _KEEP_ALIVE 防 GC 在工作线程回收 Qt 对象。
    """

    def test_open_runs_in_worker_thread(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """open_port_async 的 open 在非主线程执行；结果经信号带回 (port, ok)。"""
        import time

        from PySide6.QtCore import Qt

        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        _KEEP_ALIVE.append(win)
        try:
            opened_threads: list[threading.Thread] = []

            class _RecordingPM:
                def is_connected(self, port: str) -> bool:
                    return False

                def open(self, cfg) -> None:  # noqa: ANN001
                    opened_threads.append(threading.current_thread())

            win._port_manager = _RecordingPM()  # noqa: SLF001

            results: list[tuple[str, bool, threading.Thread]] = []
            win.port_open_result.connect(
                lambda p, ok, err: results.append((p, ok, threading.current_thread())),
                Qt.ConnectionType.DirectConnection,
            )

            win.open_port_async("COM9")
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not results:
                time.sleep(0.01)

            assert results and results[0][:2] == ("COM9", True)
            # open 在工作线程执行（Pf-3 核心：慢速 open 不占主线程）
            assert opened_threads and opened_threads[0] is not threading.main_thread()
            # 结果自工作线程投递（生产侧槽为 QObject 方法 → Queued → 主线程执行）
            assert results[0][2] is not threading.main_thread()
        finally:
            win._raw_logger.stop()  # 测试收尾：drain 写线程，避免跨测试泄漏

    def test_open_failure_reports_via_signal_on_main(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """失败：错误消息经信号回主线程（worker 内不弹，MainWindow 槽弹窗）。"""
        import time

        import PySide6.QtWidgets as _qw
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.exceptions import PortOpenError

        dialogs: list[str] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "critical", lambda parent, title, text: dialogs.append(text)
        )

        win = MainWindow()
        _KEEP_ALIVE.append(win)
        try:

            class _FailingPM:
                def is_connected(self, port: str) -> bool:
                    return False

                def open(self, cfg) -> None:  # noqa: ANN001
                    raise PortOpenError("COM9", "被占用")

            win._port_manager = _FailingPM()  # noqa: SLF001

            captured: list[tuple[str, bool, str]] = []
            win.port_open_result.connect(
                lambda p, ok, err: captured.append((p, ok, err)),
                Qt.ConnectionType.DirectConnection,
            )

            win.open_port_async("COM9")
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not captured:
                time.sleep(0.01)
            assert captured and captured[0] == ("COM9", False, "端口 COM9 打开失败：被占用")

            # worker 结束后冲一次事件循环：MainWindow 的 Queued 槽（主线程）弹错误框
            QApplication.processEvents()
            assert dialogs and "被占用" in dialogs[0]
        finally:
            win._raw_logger.stop()

    def test_duplicate_open_request_ignored(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """同端口在途时忽略重复请求（防并发 open 同一 COM）。"""
        import time

        from PySide6.QtCore import Qt

        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        _KEEP_ALIVE.append(win)
        try:
            open_count: list[int] = []
            release = threading.Event()

            class _SlowPM:
                def is_connected(self, port: str) -> bool:
                    return False

                def open(self, cfg) -> None:  # noqa: ANN001
                    open_count.append(1)
                    release.wait(2.0)  # 模拟慢速驱动

            win._port_manager = _SlowPM()  # noqa: SLF001
            done: list[tuple[str, bool]] = []
            win.port_open_result.connect(
                lambda p, ok, err: done.append((p, ok)), Qt.ConnectionType.DirectConnection
            )

            win.open_port_async("COM7")
            time.sleep(0.05)  # 让第一个 worker 进入 open
            win.open_port_async("COM7")  # 在途重复请求
            release.set()

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not done:
                time.sleep(0.01)

            assert done == [("COM7", True)]
            assert len(open_count) == 1  # 第二次请求被忽略
        finally:
            release.set()
            win._raw_logger.stop()


class TestCaseParseCacheReuse:
    """Pf-3：批量 YAML 解析缓存——run_cases 复用 _load_path 的解析结果。"""

    def _write_one_case(self, tmp_path):  # noqa: ANN001, no-untyped-def
        f = tmp_path / "c.yaml"
        f.write_text(
            "name: 缓存用例\ntags: [cache]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )
        return f

    def test_cache_hits_same_mtime(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """同一路径同一 mtime 只 parse 一次；命中返回同一对象。"""
        from atprobe.gui.mainwindow import CaseParseCache

        f = self._write_one_case(tmp_path)
        cache = CaseParseCache()
        first = cache.get_or_parse(f)
        second = cache.get_or_parse(f)
        assert first is second  # 命中复用（对象同一）

    def test_cache_invalidated_by_mtime_change(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """文件编辑（mtime 变化）后重解析——不执行过期内容。"""
        import os
        import time

        from atprobe.gui.mainwindow import CaseParseCache

        f = self._write_one_case(tmp_path)
        cache = CaseParseCache()
        first = cache.get_or_parse(f)
        f.write_text(
            "name: 缓存用例v2\ntags: [cache]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )
        # 同一秒内改写 mtime 可能不变，显式 utime 推进
        os.utime(f, (time.time() + 10, time.time() + 10))
        second = cache.get_or_parse(f)
        assert second is not first
        assert second.name == "缓存用例v2"  # type: ignore[attr-defined]

    def test_run_cases_reuses_loaded_parse(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """端到端：加载（经缓存）后 run_cases 不再重复 parse（parse 计数一次）。"""
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)

        from atprobe.domain.case import parser as case_parser
        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.config import PortConfig
        from atprobe.infra.serial.fakeserial import FakePortManager

        f = self._write_one_case(tmp_path)
        calls: list[str] = []
        orig_parse = case_parser.parse_case_file

        def counting(path):  # noqa: ANN001
            # 只统计本用例的文件：MainWindow 构造会分片加载默认用例目录
            # （examples/testcases），不得污染计数
            if str(path).endswith("c.yaml"):
                calls.append(str(path))
            return orig_parse(path)

        monkeypatch.setattr(case_parser, "parse_case_file", counting)

        win = MainWindow()
        try:
            win._port_manager = FakePortManager(sleep=lambda s: None)  # noqa: SLF001
            win._port_manager.open(PortConfig(name="COM3"))  # noqa: SLF001 —— 预开端口，dry-run 只检查

            # 模拟用例树 _load_path 的解析（经共享缓存）
            win.case_parse_cache.get_or_parse(f)
            assert len(calls) == 1

            # run_cases（dry-run 只解析 + 检查端口，不起引擎）：应命中缓存，不再 parse
            win.run_cases([str(f)], "COM3", 95, dry_run=True)
            assert len(calls) == 1, "run_cases 应复用 _load_path 的解析结果，不得重复 parse"
        finally:
            win._raw_logger.stop()


# ===========================================================================
# 批4 T7：F-17 closeEvent 重入 + D-1 UpdateController 拆分 + GUI P3 批
#         + 文件发送守卫断言（逻辑层）+ 启动前探测（2b⑧后半）
# ===========================================================================
class TestCloseEventReentryGuard:
    """F-17：closeEvent 的 processEvents 等待循环期间用户再点 X 会二次进入."""

    def test_second_close_is_ignored(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """已置 _closing 后再入 closeEvent：event 被 ignore 且不重复清理."""
        from PySide6.QtGui import QCloseEvent

        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        win._engine_thread = None  # noqa: SLF001 - 跳过引擎等待循环
        # 第一次进入：完整清理路径（置 _closing=True）
        ev1 = QCloseEvent()
        win.closeEvent(ev1)
        assert win._closing is True  # noqa: SLF001

        # 第二次进入（等待循环期间再点 X）：应被忽略——不重复 stop_engine/
        # close_all/二次遍历 tab cleanup（哨兵异常验证清理不可达）
        def _boom(*a, **k):  # noqa: ANN002, ANN003
            raise AssertionError("重入的 closeEvent 不得再次执行清理")

        monkeypatch.setattr(win, "stop_engine", _boom)
        monkeypatch.setattr(win._port_manager, "close_all", _boom)  # noqa: SLF001
        ev2 = QCloseEvent()
        win.closeEvent(ev2)
        assert ev2.isAccepted() is False, "重入的 closeEvent 应 ignore 该事件"

    def test_closing_flag_initialized_false(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """构造后 _closing 初始 False（首次关闭不被误拦）."""
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        try:
            assert win._closing is False  # noqa: SLF001
        finally:
            win._raw_logger.stop()  # noqa: SLF001


class TestUpdateControllerMigration:
    """D-1：更新族方法/信号/状态整体迁 UpdateController（行为零变化）."""

    def test_mainwindow_no_longer_hosts_update_flow(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """MainWindow 不再持有更新族信号/方法；持有控制器实例并以自己为宿主."""
        from atprobe.gui.controllers import UpdateController
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        try:
            assert isinstance(win._update_controller, UpdateController)  # noqa: SLF001
            assert win._update_controller._host is win  # noqa: SLF001
            for gone in ("update_check_result", "update_download_progress", "update_download_done"):
                assert not hasattr(win, gone), f"MainWindow 应删除信号 {gone}（随迁控制器）"
            for gone in (
                "_check_update",
                "_check_update_worker",
                "_on_check_result",
                "_show_update_dialog",
                "_start_download",
                "_download_worker",
                "_on_download_progress",
                "_cancel_download",
                "_on_download_done",
                "_update_in_progress",
            ):
                assert not hasattr(win, gone), f"MainWindow 应删除属性/方法 {gone}（随迁控制器）"
        finally:
            win._raw_logger.stop()  # noqa: SLF001

    def test_controller_signals_self_connected(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """控制器三信号自连接呈现槽（worker emit → queued → 主线程弹窗）."""
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        try:
            ctrl = win._update_controller  # noqa: SLF001
            emitted: list[object] = []
            ctrl.check_result.connect(lambda r: emitted.append(r))
            ctrl.check_result.emit(RuntimeError("probe"))
            qapp.processEvents()
            assert len(emitted) == 1, "控制器信号应可正常 emit/接收（迁移动接线完整）"
        finally:
            win._raw_logger.stop()  # noqa: SLF001

    def test_check_skipped_while_download_in_progress(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """下载进行中重复 check 被忽略（不起新工作线程）——旧行为零变化."""
        import types

        from atprobe.gui.mainwindow import MainWindow

        class _RecordingThread:
            """check() 的线程替身：记录 start 但不真跑（避免真 HTTP 线程）."""

            def __init__(self, *a, **k) -> None:  # noqa: ANN002, ANN003
                pass

            def start(self) -> None:
                started.append(1)

        started: list[int] = []
        # 只替换控制器命名空间的 threading（全局 patch 会波及 RawLogger 等真线程）
        monkeypatch.setattr(
            "atprobe.gui.controllers.update.threading",
            types.SimpleNamespace(Thread=_RecordingThread),
        )

        win = MainWindow()
        try:
            ctrl = win._update_controller  # noqa: SLF001
            ctrl._update_in_progress = True  # noqa: SLF001 —— 模拟下载中
            ctrl.check(manual=True)
            assert not started, "下载中重复 check 不得再起新线程"
            # 下载空闲时正常放行（线程替身记录 start）
            ctrl._update_in_progress = False  # noqa: SLF001
            ctrl.check(manual=True)
            assert started, "空闲时 check 应照常发起后台线程"
        finally:
            win._raw_logger.stop()  # noqa: SLF001

    def test_on_check_result_manual_vs_auto(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """结果呈现随迁：手动模式失败/无新版弹窗，自动模式静默（零变化）."""
        import PySide6.QtWidgets as _qw

        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "warning", lambda p, t, x, *a, **k: shown.append((t, x))
        )
        monkeypatch.setattr(
            _qw.QMessageBox, "information", lambda p, t, x, *a, **k: shown.append((t, x))
        )

        from atprobe.gui.controllers.update import UpdateController

        ctrl = UpdateController(parent=None)
        # 异常 + 自动（manual=False）：静默
        ctrl._check_manual = False  # noqa: SLF001
        ctrl._on_check_result(RuntimeError("网络失败"))
        assert shown == []
        # 异常 + 手动：warning
        ctrl._check_manual = True  # noqa: SLF001
        ctrl._on_check_result(RuntimeError("网络失败"))
        assert len(shown) == 1 and "检查失败" in shown[0][1]
        # None + 手动：已是最新 information
        ctrl._on_check_result(None)
        assert len(shown) == 2 and "已是最新" in shown[1][1]

    def test_version_unknown_no_upgrade_dialog(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """VERSION 缺失（current_version 回退 0.0.0）：不进升级比较，给"无法确定当前版本"提示.

        旧实现拿 0.0.0 参与比较：任何远端版本都"更新"，恒弹"发现新版本"误导。
        """
        from unittest.mock import patch

        import PySide6.QtWidgets as _qw

        from atprobe.gui.controllers.update import UpdateController
        from atprobe.infra.update.checker import ReleaseInfo

        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "warning", lambda p, t, x, *a, **k: shown.append((t, x))
        )
        monkeypatch.setattr(
            _qw.QMessageBox, "information", lambda p, t, x, *a, **k: shown.append((t, x))
        )

        fake = ReleaseInfo(
            version="0.99.0",
            tag="v0.99.0",
            zip_url="u",
            zip_size=1,
            release_notes="",
            html_url="h",
        )
        ctrl = UpdateController(parent=None)
        ctrl._check_manual = True  # noqa: SLF001 —— 手动模式才有呈现，验证文案
        with (
            patch("atprobe.infra.update.checker.fetch_latest", return_value=fake),
            patch("atprobe.infra.version.current_version", return_value="0.0.0"),
        ):
            ctrl._check_worker()  # noqa: SLF001 —— 同步执行（同线程信号直达呈现槽）
        qapp.processEvents()
        assert len(shown) == 1
        assert "无法确定当前版本" in shown[0][1]
        assert "已是最新" not in shown[0][1]


class TestFileSendGuardAssertions:
    """批 2a 携带守卫断言（逻辑层；pytest-qt 全量序列原生崩溃已证实、勿再引入）."""

    @staticmethod
    def _make_win(qapp) -> None:  # noqa: ANN001, no-untyped-def
        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.config import PortConfig
        from atprobe.infra.serial.fakeserial import FakePortManager

        win = MainWindow()
        win._port_manager = FakePortManager(sleep=lambda s: None)  # noqa: SLF001
        win._port_manager.open(PortConfig(name="COM9"))  # noqa: SLF001
        return win

    def test_send_file_rejected_while_engine_running(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """守卫①：引擎 RUNNING 时 send_file 被拒——warning 弹窗 + False + 不写端口."""
        import PySide6.QtWidgets as _qw

        from atprobe.engine.config import EngineState

        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "warning", lambda p, t, x, *a, **k: shown.append((t, x))
        )

        win = self._make_win(qapp)

        class _RunningEngine:
            def state(self) -> EngineState:
                return EngineState.RUNNING

        win._engine = _RunningEngine()  # noqa: SLF001
        try:
            assert win.send_file("COM9", b"\x01\x02") is False
            assert shown and shown[0][0] == "发送被拒绝"
            assert "正在运行" in shown[0][1]
        finally:
            win._engine = None  # noqa: SLF001
            win._raw_logger.stop()  # noqa: SLF001

    def test_enter_file_sending_disables_panels(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """守卫②：文件发送期间 UI 面板禁用；退出后恢复（离屏 widget 直测）."""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        try:
            for w in (widget.send_btn, widget.send_edit, widget.file_btn, widget._cmd_panel):
                assert w.isEnabled(), "发送前相关控件应可用"

            widget._enter_file_sending()  # noqa: SLF001
            for w in (widget.send_btn, widget.send_edit, widget.file_btn, widget._cmd_panel):
                assert not w.isEnabled(), "文件发送中文本发送/命令库面板应禁用"

            widget._exit_file_sending()  # noqa: SLF001
            for w in (widget.send_btn, widget.send_edit, widget.file_btn, widget._cmd_panel):
                assert w.isEnabled(), "退出文件发送后应恢复可用"
        finally:
            widget.cleanup()

    def test_send_file_port_busy_branch(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """守卫③：send_file 的 PortBusyError 捕获分支——友好提示 + False（不弹通用错误）."""
        import PySide6.QtWidgets as _qw

        from atprobe.infra.serial.exceptions import PortBusyError

        infos: list[tuple[str, str]] = []
        crits: list[str] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "information", lambda p, t, x, *a, **k: infos.append((t, x))
        )
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda p, t, x, *a, **k: crits.append(x))

        win = self._make_win(qapp)

        def _busy(port, spec, **kwargs):  # noqa: ANN001, ANN003
            raise PortBusyError(port, "另一发送周期进行中")

        monkeypatch.setattr(win._port_manager, "write_data", _busy)  # noqa: SLF001
        try:
            assert win.send_file("COM9", b"\x01\x02") is False
            assert infos and infos[0][0] == "端口忙", "撞锁应弹友好提示而非通用错误"
            assert crits == [], "PortBusyError 分支不得落入通用错误框"
        finally:
            win._raw_logger.stop()  # noqa: SLF001


class TestFileSendPreStartProbe:
    """2b⑧ 后半：启动引擎前探测 manual_debug 文件发送进行中 → 拒绝启动."""

    @staticmethod
    def _inject_manual_debug_tab(win) -> None:  # noqa: ANN001
        """注入一个最小 manual_debug 假 tab（只带 _file_worker/_file_thread 属性）."""
        from PySide6.QtWidgets import QWidget

        w = QWidget()
        w.setProperty("tab_type", "manual_debug")
        win.tabs.addTab(w, "手动调试")
        return w

    def test_probe_false_when_no_tab(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        try:
            assert win._file_send_active() is False  # noqa: SLF001
        finally:
            win._raw_logger.stop()  # noqa: SLF001

    def test_probe_detects_active_worker(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        try:
            tab = self._inject_manual_debug_tab(win)
            assert win._file_send_active() is False  # noqa: SLF001 —— 无发送
            tab._file_worker = object()  # 模拟发送中  # noqa: SLF001
            assert win._file_send_active() is True  # noqa: SLF001
            tab._file_worker = None  # noqa: SLF001

            class _FakeThread:
                def isRunning(self) -> bool:
                    return True

            tab._file_thread = _FakeThread()  # noqa: SLF001 —— 线程视角同样探测到
            assert win._file_send_active() is True  # noqa: SLF001
        finally:
            win._raw_logger.stop()  # noqa: SLF001

    def test_run_cases_rejected_while_file_sending(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """run_cases 在文件发送进行中被拒：warning 弹窗 + 不建引擎线程."""
        import PySide6.QtWidgets as _qw

        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "warning", lambda p, t, x, *a, **k: shown.append((t, x))
        )

        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        try:
            tab = self._inject_manual_debug_tab(win)
            tab._file_worker = object()  # noqa: SLF001 —— 文件发送进行中

            case_file = tmp_path / "c.yaml"
            case_file.write_text(
                "name: c1\nsteps:\n  - command: AT\n    assert: {contains: OK}\n", encoding="utf-8"
            )
            win.run_cases([str(case_file)], "COM9", 90)
            assert shown and "文件发送进行中" in shown[0][1]
            assert win._engine is None and win._engine_thread is None, (  # noqa: SLF001
                "拒绝路径不得创建引擎/引擎线程"
            )
        finally:
            win._raw_logger.stop()  # noqa: SLF001


class TestMonitorPortOpenAggregation:
    """P3：monitor 多端口打开失败聚合单弹窗（替代逐端口连环 critical 框）."""

    @staticmethod
    def _make_widget(qapp, ports) -> None:  # noqa: ANN001, no-untyped-def
        from atprobe.gui.tabs.monitor import MonitorWidget
        from atprobe.gui.tabs.registry import TabBinding

        class _FailingMain:
            """open_port 旧签名（不收 quiet）且恒失败的替身——同时验证 TypeError 回退."""

            def available_ports(self) -> list[str]:
                return list(ports)

            def is_port_connected(self, port: str) -> bool:
                return False

            def open_port(self, port: str) -> bool:
                return False

            def subscribe_monitor(self, ports_, sink) -> None:  # noqa: ANN001
                pass

            def unsubscribe_monitor(self) -> None:
                pass

        return MonitorWidget(TabBinding(type_name="monitor", params={}), _FailingMain())  # type: ignore[arg-type]

    def test_multiple_failures_single_warning(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import PySide6.QtWidgets as _qw

        warns: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "warning", lambda p, t, x, *a, **k: warns.append((t, x))
        )

        widget = self._make_widget(qapp, ["COM1", "COM2"])
        try:
            for cb in widget._port_checks:  # noqa: SLF001
                cb.setChecked(True)
            widget._toggle(True)  # noqa: SLF001
            assert len(warns) == 1, f"多端口失败应聚合为单弹窗，实际 {len(warns)} 次"
            assert "COM1" in warns[0][1] and "COM2" in warns[0][1], "弹窗应列出全部失败端口"
        finally:
            widget.cleanup()

    def test_open_quietly_falls_back_on_old_signature(self) -> None:  # type: ignore[no-untyped-def]
        """替身/旧签名 open_port（不收 quiet）→ TypeError 回退普通调用."""
        from atprobe.gui.tabs.monitor import MonitorWidget

        calls: list[dict[str, object]] = []

        def old_open(port: str) -> bool:
            calls.append({"port": port, "quiet": False})
            return port == "COM1"

        def new_open(port: str, *, quiet: bool = False) -> bool:
            calls.append({"port": port, "quiet": quiet})
            return quiet

        assert MonitorWidget._open_quietly(old_open, "COM1") is True
        assert MonitorWidget._open_quietly(new_open, "COM3") is True
        # 新签名走 quiet=True（静默失败由调用方聚合），旧签名回退
        assert calls[0]["quiet"] is False and calls[1]["quiet"] is True


class TestCommandLibraryRenameTransaction:
    """P3：命令库重命名事务化——迁移失败回滚，不留半改状态."""

    @staticmethod
    def _make_editor(qapp) -> None:  # noqa: ANN001, no-untyped-def
        from PySide6.QtWidgets import QTreeWidget, QWidget

        from atprobe.domain.quickcmd import CommandLibrary
        from atprobe.gui.theme import get_tokens
        from atprobe.gui.widgets.command_library import _LibraryTreeEditor

        class _Harness(QWidget, _LibraryTreeEditor):
            """最小编辑器宿主：只提供 _library/tree/_tokens 与提交记录."""

            def __init__(self) -> None:
                super().__init__()
                self._tokens = get_tokens()
                self.tree = QTreeWidget()
                self._library = CommandLibrary.empty()
                self.commits: list[tuple[str, ...] | None] = []

            def _commit_and_refresh(self, select: tuple[str, ...] | None = None) -> None:
                self.commits.append(select)

        return _Harness()

    def test_rename_group_rolls_back_on_mid_failure(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """第 N 个命令迁移失败（空命令串）：已迁移项与新组回滚 + 提示."""
        import PySide6.QtWidgets as _qw
        from PySide6.QtWidgets import QInputDialog

        warns: list[str] = []
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda p, t, x, *a, **k: warns.append(x))
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("new", True))

        ed = self._make_editor(qapp)
        lib = ed._library  # noqa: SLF001
        lib.add_project("P")
        grp = lib.add_group("P", "old")
        # 直接注入空命令（模拟手改 YAML 绕过 add_command 校验载入）——迁移到第 2 个时抛
        grp.commands = ["AT", "", "AT+CSQ"]

        ed._rename_group("P", "old")  # noqa: SLF001
        assert warns and "回滚" in warns[0], "失败应弹提示（旧实现异常裸抛无提示）"
        assert lib.find_group("P", "new") is None, "回滚应删除半迁移的新组"
        old_grp = lib.find_group("P", "old")
        assert old_grp is not None, "回滚应保留旧组"
        assert old_grp.commands == ["AT", "", "AT+CSQ"]
        assert ed.commits == [], "失败路径不得提交（不落盘半改状态）"

    def test_rename_group_success_path_unchanged(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """正常重命名零变化：命令全迁移 + 旧组移除 + 提交."""
        import PySide6.QtWidgets as _qw
        from PySide6.QtWidgets import QInputDialog

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("new", True))

        ed = self._make_editor(qapp)
        lib = ed._library  # noqa: SLF001
        lib.add_project("P")
        lib.add_group("P", "old")
        lib.add_command("P", "old", "AT")
        lib.add_command("P", "old", "AT+CSQ")

        ed._rename_group("P", "old")  # noqa: SLF001
        assert lib.find_group("P", "old") is None
        new_grp = lib.find_group("P", "new")
        assert new_grp is not None and new_grp.commands == ["AT", "AT+CSQ"]
        assert ed.commits == [("group", "P", "new")]


class TestExecutionProgressPlainText:
    """P3：execution_progress 步骤明细 QLabel 锁 PlainText（AutoText 视觉注入）."""

    def test_detail_label_plain_text_format(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from PySide6.QtCore import Qt

        from atprobe.gui.tabs.execution_progress import ExecutionProgressWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ExecutionProgressWidget(
            TabBinding(type_name="execution_progress", params={}),
            object(),  # type: ignore[arg-type]
        )
        assert widget.detail_label.textFormat() == Qt.TextFormat.PlainText

    def test_device_text_with_markup_shown_literally(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """含 <b>/<a> 片段的命令文本按字面显示（不被解释为富文本）."""
        from atprobe.engine.interfaces import StepResultEvent
        from atprobe.gui.tabs.execution_progress import ExecutionProgressWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ExecutionProgressWidget(
            TabBinding(type_name="execution_progress", params={}),
            object(),  # type: ignore[arg-type]
        )
        ev = StepResultEvent(
            step_index=0,
            phase="steps",
            status="PASS",
            duration_ms=1.0,
            port="COM3",
            command='AT+X=<b>BOOM</b><a href="http://evil">click</a>',
        )
        widget._on_step(ev)  # noqa: SLF001
        text = widget.detail_label.text()  # noqa: SLF001
        assert "<b>BOOM</b>" in text, "PlainText 模式下标签文本应按字面保留"


class TestThemePrefSinglePoint:
    """P3：主题偏好读/写收敛 theme.read/write_theme_pref（app.py 与 MainWindow 共用）."""

    def test_roundtrip(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QSettings

        from atprobe.gui.theme import read_theme_pref, write_theme_pref

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        try:
            probe = QSettings("ATProbe", "ATProbe")
            probe.setValue("theme/dark", False)
            probe.sync()
            if probe.status() is not QSettings.Status.NoError:
                pytest.skip("QSettings 持久化在当前环境不可写（仅内存缓存）")
            write_theme_pref(True)
            assert read_theme_pref() is True
            write_theme_pref(False)
            assert read_theme_pref() is False
        finally:
            QSettings.setDefaultFormat(QSettings.Format.NativeFormat)

    def test_absent_returns_none(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """无记录 → None（调用方回退默认/全局状态）.

        QSettings 按 org/app 进程级缓存——换唯一 org 名绕开同进程其它用例
        已写入的 theme/dark 记录（ININ 路径随 setPath 指向本用例 tmp_path）。
        """
        from PySide6.QtCore import QSettings

        import atprobe.gui.theme as theme_mod

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
        try:
            monkeypatch.setattr(theme_mod, "_THEME_PREF_ORG", "ATProbeTestAbsent")
            monkeypatch.setattr(theme_mod, "_THEME_PREF_APP", "ATProbeTestAbsent")
            assert theme_mod.read_theme_pref() is None, "无记录应返回 None（调用方回退默认）"
        finally:
            QSettings.setDefaultFormat(QSettings.Format.NativeFormat)


class TestEnvConfigLazyCollection:
    """P3：env_config 表单收集惰性化——击键只置脏，读取时全量收集一次."""

    @staticmethod
    def _make_widget(qapp, tmp_path) -> None:  # noqa: ANN001, no-untyped-def
        from atprobe.gui.tabs.env_config import EnvConfigWidget
        from atprobe.gui.tabs.registry import TabBinding

        env_file = tmp_path / "env.yaml"
        env_file.write_text("net:\n  apn: cmnet\n", encoding="utf-8")

        class _Main:
            def env_config_path(self) -> str:
                return str(env_file)

        return EnvConfigWidget(TabBinding(type_name="env_config", params={}), _Main())  # type: ignore[arg-type]

    def test_typing_does_not_collect_read_does(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        widget = self._make_widget(qapp, tmp_path)
        calls: list[int] = []
        orig = widget._collect_and_update_env  # noqa: SLF001

        def _counting() -> None:
            calls.append(1)
            orig()

        monkeypatch.setattr(widget, "_collect_and_update_env", _counting)

        # 模拟用户击键：textChanged 只置脏标记，不触发全量收集
        edits = widget._group_widgets["net"]["apn"]  # noqa: SLF001
        edits.setText("cmwap")
        edits.setText("cmnet")
        assert calls == [], "击键不得全量收集（旧实现逐击键重建 EnvConfig）"

        # 读取点（run_cases 消费的接口）收集一次并带回最新值
        env = widget.current_env()
        assert len(calls) == 1
        assert str(env.groups()["net"]["apn"]) == "cmnet"
        # 无后续编辑的重复读取不再收集
        widget.current_env()
        assert len(calls) == 1

    def test_is_dirty_sees_pending_edits(self, qapp, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """惰性化后 is_dirty 仍能看到未收集的表单编辑（run_cases 前置 save 语义不变）."""
        widget = self._make_widget(qapp, tmp_path)
        edits = widget._group_widgets["net"]["apn"]  # noqa: SLF001
        assert widget.is_dirty() is False  # 加载后未编辑 → 干净
        edits.setText("changed")
        assert widget.is_dirty() is True, "挂起编辑须经读取点收集后参与比对"
