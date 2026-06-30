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

    def test_new_run_clears_previous_results(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """新运行首个用例（case_index==1）自动清空上一轮结果（防跨运行累积）."""
        from atprobe.engine.interfaces import CaseStartEvent
        from atprobe.gui.tabs.execution_progress import ExecutionProgressWidget
        from atprobe.gui.tabs.registry import TabBinding

        widget = ExecutionProgressWidget(TabBinding(type_name="execution_progress", params={}), object())  # type: ignore[arg-type]
        # 第一轮：2 个用例
        widget.on_event(CaseStartEvent(case_name="A", case_index=1, total_cases=2, case_type="regular"))
        widget.on_event(CaseStartEvent(case_name="B", case_index=2, total_cases=2, case_type="regular"))
        assert widget.table.rowCount() == 2

        # 第二轮：case_index==1 应触发清空，只保留本轮首个用例
        widget.on_event(CaseStartEvent(case_name="C", case_index=1, total_cases=1, case_type="regular"))
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
        # TX 立即上屏（不等响应）
        assert "TX> AT+CSQ" in widget.response_view.toPlainText()

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

        # 结束符 \r\n → TX HEX 应含 0D 0A
        widget.send_edit.setPlainText("AT")
        widget._send()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "TX> 41 54 0D 0A" in text, f"CRLF 应显示 41 54 0D 0A: {text!r}"

        # 结束符 \r → TX HEX 应含 0D（无 0A）
        widget.term_combo.setCurrentIndex(1)  # "\\r"
        widget._send()  # noqa: SLF001
        text = widget.response_view.toPlainText()
        assert "TX> 41 54 0D" in text, f"CR 应显示 41 54 0D: {text!r}"
        # 关键判据：CR 模式的最后一条 TX 不应含结尾的 0A
        last_tx = [ln for ln in text.splitlines() if "TX>" in ln][-1]
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
        # emit 在测试线程（非读线程）触发信号；Qt 信号默认直连主线程槽
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

    def test_select_custom_item_opens_input_dialog(
        self, qapp, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
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

    def test_select_custom_item_cancel_reverts(
        self, qapp, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
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
    """管理对话框：顶部只保留＋项目，新增功能组/命令下放到树节点内嵌＋按钮."""

    def test_toolbar_only_has_add_project(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """对话框顶部只有 [＋项目]，旧的 ＋功能组/＋命令 按钮已移除."""
        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        assert dlg._add_project_btn.text() == "＋项目"  # noqa: SLF001
        # 旧的 ＋功能组 / ＋命令 按钮应已移除
        assert not hasattr(dlg, "_add_group_btn")
        assert not hasattr(dlg, "_add_cmd_btn")

    def test_embedded_add_buttons_present(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """项目/功能组节点行内嵌 widget（含＋按钮），命令节点无."""
        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

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

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("新功能组", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        from PySide6.QtCore import Qt as _Qt

        proj_name = first_proj.data(0, _Qt.ItemDataRole.UserRole)[1]  # 元组第二项=项目名  # noqa: SLF001
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

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CGMM", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        from PySide6.QtCore import Qt as _Qt

        gnode = first_grp.data(0, _Qt.ItemDataRole.UserRole)  # 元组: ("group", proj, grp)  # noqa: SLF001
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

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

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

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        monkeypatch.setattr(_qw.QInputDialog, "getText", lambda *a, **k: ("AT+CGSN", True))
        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: 0)

        lib = load_library(builtin_library_path())
        dlg = LibraryManagerDialog(lib, builtin_library_path())
        first_proj = dlg.tree.topLevelItem(0)
        first_grp = first_proj.child(0)
        from PySide6.QtCore import Qt as _Qt

        gnode = first_grp.data(0, _Qt.ItemDataRole.UserRole)  # noqa: SLF001

        dlg._add_command_interactive(gnode[1], gnode[2])  # noqa: SLF001

        # 重建后 currentItem 应为新加的命令节点（其 role 元组第四项为 "AT+CGSN"）
        cur = dlg.tree.currentItem()
        assert cur is not None
        role = cur.data(0, _Qt.ItemDataRole.UserRole)
        assert role == ("command", gnode[1], gnode[2], "AT+CGSN")

    def test_add_group_keeps_position(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """添加功能组后，新功能组节点被选中并居中滚动到位."""
        import PySide6.QtWidgets as _qw

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

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

    def test_double_click_command_edits_and_persists(
        self, qapp, monkeypatch, tmp_path
    ) -> None:  # type: ignore[no-untyped-def]
        """双击命令 → 弹输入框改值 → 即时落盘到 YAML（reload 后能看到新值）."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets import command_library as cl_mod
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        # 用临时文件作为库路径（避免污染内置示例文件）
        lib_file = tmp_path / "lib.yaml"
        from atprobe.domain.quickcmd import default_library, dump_library

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
        from atprobe.domain.quickcmd import load_library

        disk_lib = load_library(lib_file)
        disk_grp = disk_lib.find_group(proj, grp)
        assert disk_grp is not None and "AT+CGMM_NEW" in disk_grp.commands

    def test_delete_command_no_confirm(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """删除命令不弹确认（QMessageBox.question 不应被调用）."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets import command_library as cl_mod
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        lib_file = tmp_path / "lib.yaml"
        from atprobe.domain.quickcmd import default_library, dump_library

        dump_library(default_library(), lib_file)
        monkeypatch.setattr(cl_mod, "builtin_library_path", lambda: lib_file)

        question_called: list[bool] = []
        monkeypatch.setattr(
            _qw.QMessageBox, "question", lambda *a, **k: question_called.append(True) or _qw.QMessageBox.StandardButton.No
        )

        panel = CommandLibraryPanel()
        first_cmd = panel.tree.topLevelItem(0).child(0).child(0)
        from PySide6.QtCore import Qt as _Qt

        node = first_cmd.data(0, _Qt.ItemDataRole.UserRole)
        proj, grp, cmd = node[1], node[2], node[3]

        panel._delete_command(proj, grp, cmd)  # noqa: SLF001

        assert not question_called, "删命令不应弹确认"
        grp_obj = panel._library.find_group(proj, grp)  # noqa: SLF001
        assert grp_obj is not None and cmd not in grp_obj.commands

    def test_delete_project_confirms(self, qapp, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """删除项目弹确认：选 No 不删，选 Yes 删."""
        import PySide6.QtWidgets as _qw

        from atprobe.gui.widgets import command_library as cl_mod
        from atprobe.gui.widgets.command_library import CommandLibraryPanel

        lib_file = tmp_path / "lib.yaml"
        from atprobe.domain.quickcmd import default_library, dump_library

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


class TestLibraryManagerDialogNoFormPanel:
    """添加界面（管理对话框）：去掉右侧表单，全靠双击 + 右键增删改."""

    def test_form_panel_removed(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """右侧表单相关成员应已全部移除."""
        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

        dlg = LibraryManagerDialog(load_library(builtin_library_path()), builtin_library_path())
        for attr in ("_form_host", "_form_layout", "_on_tree_select", "_build_project_form"):
            assert not hasattr(dlg, attr), f"右侧表单成员 {attr} 应已移除"

    def test_double_click_command_edits(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """对话框双击命令 → 修改（工作副本，未落盘）."""
        import PySide6.QtWidgets as _qw

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

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
        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

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

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import LibraryManagerDialog

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

        from atprobe.domain.quickcmd import builtin_library_path, load_library
        from atprobe.gui.widgets.command_library import _NODE_ROLE, LibraryManagerDialog

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

