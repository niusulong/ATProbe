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
        # §2.3 第一阶段选项卡（含执行进度，执行时自动弹出）
        for t in ("manual_debug", "case_execute", "monitor", "execution_progress", "report_view", "env_config"):
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
    """B2：标签筛选、dry-run、报告开关、_selected_files 正确性."""

    def test_tag_filter_and_dry_run(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import PySide6.QtWidgets as _qw

        from atprobe.gui.tabs.case_execute import CaseExecuteWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 弹窗打桩（dry-run 会弹 information）
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)

        # 写两个用例，一个带 network 标签，一个带 sms 标签
        (tmp_path / "net.yaml").write_text(
            "name: 网络用例\ntags: [network]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
            encoding="utf-8",
        )
        (tmp_path / "sms.yaml").write_text(
            "name: 短信用例\ntags: [sms]\nsteps:\n  - command: AT\n    assert: {contains: OK}\n",
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

        # 标签聚合：下拉应含 network、sms
        tag_items = [widget.tag_combo.itemText(i) for i in range(widget.tag_combo.count())]
        assert "network" in tag_items and "sms" in tag_items

        # 默认（全部）两个用例都显示
        assert widget.table.rowCount() == 2

        # 选 network 标签 → 只显示网络用例
        widget.tag_combo.setCurrentText("network")
        assert widget.table.rowCount() == 1
        assert widget.table.item(0, 1).text() == "网络用例"  # type: ignore[union-attr]

        # 切回全部，dry-run：应调用 run_cases(dry_run=True)
        widget.tag_combo.setCurrentIndex(0)
        widget.ports_combo.setCurrentText("COM3")
        widget._dry_run()  # noqa: SLF001
        assert run_calls and run_calls[-1]["dry_run"] is True

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
        from PySide6.QtCore import QSettings

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 隔离 QSettings：用独立 key，避免污染其它测试/用户环境
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)

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
        from PySide6.QtCore import QSettings

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)
        monkeypatch.setattr(_qw.QMessageBox, "information", lambda *a, **k: 0)

        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)
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
        from PySide6.QtCore import QSettings

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)
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


class TestManualDebugQuickCommands:
    def test_add_remove_persist(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QSettings

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 清空自定义，回落默认
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)
        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        assert widget._quick_commands == ["AT", "AT+CSQ", "AT+CEREG?", "AT+CPIN?", "AT+CGDCONT?"]  # noqa: SLF001

        # 添加一条自定义
        widget._add_quick("AT+CGMM")  # noqa: SLF001
        assert "AT+CGMM" in widget._quick_commands  # noqa: SLF001
        # 持久化到 QSettings
        saved = QSettings("ATProbe", "ATProbe").value("manual_debug/quick_commands")
        assert saved is not None and "AT+CGMM" in list(saved)

        # 删除一条
        widget._remove_quick("AT+CGMM")  # noqa: SLF001
        assert "AT+CGMM" not in widget._quick_commands  # noqa: SLF001

    def test_loads_persisted_on_construct(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QSettings

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 预置持久化值
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", ["ATI", "ATZ"])
        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        assert widget._quick_commands == ["ATI", "ATZ"]  # noqa: SLF001
        # 清理：恢复默认，避免污染其它测试
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)


class TestManualDebugExtras:
    """B3：历史指令、HEX 显示、多行发送."""

    def test_multiline_send_and_history(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import PySide6.QtWidgets as _qw
        from PySide6.QtCore import QSettings

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/history", None)

        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001  打开 COM1

        # 多行：三行依次发送
        widget.send_edit.setPlainText("AT\nATI\nAT+CSQ")
        widget._send()  # noqa: SLF001
        # last_command 捕获最后一次（AT+CSQ）
        assert main.last_command == ("COM1", "AT+CSQ")
        # TX 三行都应上屏
        text = widget.response_view.toPlainText()
        assert "TX> AT" in text and "TX> ATI" in text and "TX> AT+CSQ" in text

        # 历史：最后一次指令入历史下拉并持久化
        items = [widget.history_combo.itemText(i) for i in range(widget.history_combo.count())]
        assert "AT+CSQ" in items
        saved = QSettings("ATProbe", "ATProbe").value("manual_debug/history")
        assert saved is not None and "AT+CSQ" in list(saved)
        # 清理
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/history", None)

    def test_hex_display(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QSettings

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        QSettings("ATProbe", "ATProbe").setValue("manual_debug/quick_commands", None)
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/history", None)
        main = _FakeMain()
        widget = ManualDebugWidget(TabBinding(type_name="manual_debug", params={}), main)  # type: ignore[arg-type]
        widget._toggle_connect()  # noqa: SLF001

        widget.hex_check.setChecked(True)
        main.emit_rx("COM1", b"OK\r\n")
        text = widget.response_view.toPlainText()
        # HEX 模式：显示 4F 4B（OK 的十六进制），不显示明文 OK 行
        assert "4F 4B" in text
        QSettings("ATProbe", "ATProbe").setValue("manual_debug/history", None)

