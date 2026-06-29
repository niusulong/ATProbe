"""GUI 模块导入与构造冒烟测试（offscreen 模式）."""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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

    def test_new_tab_creates_widget(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        initial = win.tabs.count()
        win.new_tab("manual_debug")
        assert win.tabs.count() == initial + 1
        win.new_tab("env_config")
        assert win.tabs.count() == initial + 2

    def test_theme_toggle_persists(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """C1：主题切换更新全局状态 + QSettings 记忆."""
        from PySide6.QtCore import QSettings

        from atprobe.gui.mainwindow import MainWindow
        from atprobe.gui.theme import current_theme_is_dark

        QSettings("ATProbe", "ATProbe").setValue("theme/dark", False)
        win = MainWindow()
        assert win._dark is False  # noqa: SLF001
        # 切到深色
        win._toggle_theme(True)  # noqa: SLF001
        assert current_theme_is_dark() is True
        assert bool(QSettings("ATProbe", "ATProbe").value("theme/dark", False, type=bool)) is True
        assert win._theme_action.text() == "切换浅色主题"  # noqa: SLF001
        # 切回浅色
        win._toggle_theme(False)  # noqa: SLF001
        assert current_theme_is_dark() is False
        # 清理
        QSettings("ATProbe", "ATProbe").setValue("theme/dark", False)

    def test_subscribe_monitor_wires_tx_rx(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """监控订阅同时接 TX（写侧）与 RX（读侧），双向数据都到 sink（REQ-M6 §6.2）."""
        from atprobe.gui.mainwindow import MainWindow
        from atprobe.infra.serial.config import PortConfig
        from atprobe.infra.serial.fakeserial import FakePortManager

        win = MainWindow()
        win._port_manager = FakePortManager(sleep=lambda s: None)  # noqa: SLF001
        win._port_manager.open(PortConfig(name="COM9"))  # noqa: SLF001

        received: list[tuple[str, str, bytes]] = []
        win.subscribe_monitor(["COM9"], lambda port, direction, data: received.append((port, direction, data)))
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
            QMessageBox, "about",
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

        widget = ExecutionProgressWidget(TabBinding(type_name="execution_progress", params={}), object())  # type: ignore[arg-type]

        # 2 个用例：用例1 PASS，用例2 FAIL
        widget.on_event(CaseStartEvent(case_name="网络注册", case_index=1, total_cases=2, case_type="regular"))
        assert widget.table.rowCount() == 1
        assert widget._case_names[1] == "网络注册"  # noqa: SLF001

        widget.on_event(StepResultEvent(
            step_index=1, phase="steps", status="PASS", duration_ms=120,
            port="COM3", command="AT+CSQ",
        ))
        assert "AT+CSQ" in widget.detail_label.text() and "✓" in widget.detail_label.text()

        widget.on_event(CaseResultEvent(case_name="网络注册", status="PASS", duration_ms=500.0))
        row0 = widget._find_row_by_name("网络注册")  # noqa: SLF001
        assert row0 == 0
        assert widget.table.item(row0, 2).text() == "PASS"  # type: ignore[union-attr]

        widget.on_event(CaseStartEvent(case_name="PDP激活", case_index=2, total_cases=2, case_type="regular"))
        widget.on_event(CaseResultEvent(case_name="PDP激活", status="FAIL", duration_ms=300.0, error_msg="超时"))
        assert widget.table.rowCount() == 2

        # 进度条应在第二个用例开始时推进
        assert 0 < widget.progress_bar.value() <= 100

        # 完成
        widget.on_event(EngineFinishedEvent(summary=Summary(total_cases=2, passed=1, failed=1)))
        assert widget.progress_bar.value() == 100


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
    def _count_leaves(widget) -> int:  # noqa: ANN001
        """递归统计树中用例叶子数."""
        count = 0

        def walk(item) -> None:  # noqa: ANN001
            nonlocal count
            if item.childCount() == 0:
                count += 1
                return
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(widget.tree.topLevelItemCount()):
            walk(widget.tree.topLevelItem(i))
        return count

    @staticmethod
    def _first_leaf_name(widget) -> str | None:  # noqa: ANN001
        """取树中第一个用例叶子的用例名（第 0 列文本）."""
        def walk(item):  # noqa: ANN001
            if item.childCount() == 0:
                return item.text(0)
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


class _FakeMain:
    """最小化的主窗口替身：模拟端口连接管理与发送，供 ManualDebugWidget 测试.

    send_manual 设置 last_command 后触发 sent_event，便于测试同步。
    支持 subscribe_rx/unsubscribe_rx（纯流式接收）+ emit_rx 模拟回包。
    """

    def __init__(self) -> None:
        self._connected: set[str] = set()
        self.open_calls: list[tuple[str, int, str]] = []
        self.last_command: tuple[str, str] | None = None
        self.sent_event = threading.Event()
        self._rx_observers: dict[str, list] = {}
        # 文件发送（小文件同步路径）
        self.last_bytes: tuple[str, bytes] | None = None
        self.file_sent_event = threading.Event()
        # 大文件 worker 用的连接替身（None 表示不支持后台路径）
        self._fake_connection = None

    def available_ports(self) -> list[str]:
        return ["COM1", "COM2"]

    def is_port_connected(self, port: str) -> bool:
        return port in self._connected

    def open_port(self, port: str, baud: int = 115200, frame: str = "8N1") -> bool:
        self.open_calls.append((port, baud, frame))
        self._connected.add(port)
        return True

    def close_port(self, port: str) -> bool:
        self._connected.discard(port)
        return True

    def send_manual(self, port: str, command: str) -> bool:
        """流式写：记录命令（不再等待响应，回包经 subscribe_rx 流入）."""
        if port not in self._connected:
            return False
        self.last_command = (port, command)
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
        # TX 立即上屏（不等响应）
        assert "TX> AT+CSQ" in widget.response_view.toPlainText()

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
        # emit 在测试线程（非读线程）触发信号；Qt 信号默认直连主线程槽
        text = widget.response_view.toPlainText()
        assert "+CSQ: 23,99" in text

        # 关闭端口 → 撤销订阅
        widget._toggle_connect()  # noqa: SLF001
        assert widget._rx_handle is None  # noqa: SLF001


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
        assert "TX> AT+CSQ" in widget.response_view.toPlainText()

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
        assert "TX> AT" in text and "TX> ATI" in text and "TX> AT+CSQ" in text

    def test_hex_display_preserved(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """HEX 显示功能保留。"""
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001
        widget.hex_check.setChecked(True)
        main.emit_rx("COM1", b"OK\r\n")
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
        # TX 原始数据应上屏（响应区含 TX 标记）
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
    def test_large_file_uses_worker(self, qtbot, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 大文件（> 4KB）
        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * 5000)

        # 让 _FakeMain.get_connection 返回一个记录写入的替身
        class _Conn:
            def __init__(self) -> None:
                self.written: list[bytes] = []

            def write_bytes(self, d: bytes) -> None:
                self.written.append(d)

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        main._fake_connection = _Conn()  # noqa: SLF001
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001
        widget._update_file_label()

        # 桩掉 time.sleep 避免 worker 真实等待
        monkeypatch.setattr("atprobe.gui.widgets.file_send.time.sleep", lambda _s: None)

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
            c for p in panel._library.projects for g in p.groups for c in g.commands  # noqa: SLF001
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
    """管理对话框顶部工具栏：新增入口始终可见 + 智能定位目标。"""

    def test_toolbar_has_add_buttons(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """对话框顶部有 [＋项目][＋功能组][＋命令] 始终可见。"""
        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        assert dlg._add_project_btn.text() == "＋项目"  # noqa: SLF001
        assert dlg._add_group_btn.text() == "＋功能组"  # noqa: SLF001
        assert dlg._add_cmd_btn.text() == "＋命令"  # noqa: SLF001

    def test_add_command_needs_group_selection(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """未选功能组时点＋命令 → 提示需先选功能组（不弹 QInputDialog）。"""
        import PySide6.QtWidgets as _qw

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        info_shown: list[str] = []
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: info_shown.append("info"))
        input_called: list[bool] = []
        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: input_called.append(True) or ("", False))

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        dlg.tree.clearSelection()  # 不选任何节点
        dlg._add_command_under_selection()  # noqa: SLF001
        assert info_shown and not input_called  # 提示了且没弹输入框

    def test_add_command_under_selected_group(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """选中功能组后点＋命令 → 弹输入框 → 命令加入该功能组。"""
        import PySide6.QtWidgets as _qw

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CGMM", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        first_grp.setSelected(True)
        before = first_grp.childCount()
        dlg._add_command_under_selection()  # noqa: SLF001
        new_proj = dlg.tree.topLevelItem(0)
        new_grp = new_proj.child(0)
        assert new_grp.childCount() == before + 1
        assert any(new_grp.child(i).text(0) == "AT+CGMM" for i in range(new_grp.childCount()))

