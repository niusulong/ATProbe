"""PortManager 持久订阅层测试（改动 B 回归）.

验证订阅在 connection 销毁重建（close+open）后自动恢复。
用真 PortManager + mock SerialConnection（避免 FakePortManager 的假阳性：
Fake 无 connection 概念，测不到 open 时 re-attach 的真实路径）。
"""

from __future__ import annotations

import threading
import unittest.mock as mock
from pathlib import Path

import pytest

from atprobe.infra.serial.config import FlowControl, FrameFormat, PortConfig
from atprobe.infra.serial.portmanager import PortManager


def _make_cfg(name: str = "TESTPORT") -> PortConfig:
    return PortConfig(
        name=name, baudrate=115200, frame=FrameFormat.parse("8N1"), flow_control=FlowControl("none")
    )


@pytest.fixture
def pm_with_mock_conn():
    """真 PortManager，但 SerialConnection.open 被 mock（不真开串口）.

    mock 后 connection 的观察者机制（add/remove/notify）仍用真实实现，
    仅跳过 pyserial 真实 I/O。这样能验证 PortManager 的持久订阅 re-attach 逻辑。
    """
    from atprobe.infra.serial import connection as conn_mod

    real_open = conn_mod.SerialConnection.open

    def _fake_open(self):
        # 不真开 pyserial，仅标记已连接 + 起一个无操作读线程占位
        self._connected = True
        self._serial = None

    with mock.patch.object(conn_mod.SerialConnection, "open", _fake_open):
        pm = PortManager()
        yield pm


class TestPersistentSubscribe:
    """持久订阅：close+open 后订阅自动恢复。"""

    def test_rx_subscribe_survives_close_reopen(self, pm_with_mock_conn) -> None:
        """RX 订阅在 close+open 后仍能收到数据（核心目标）."""
        pm = pm_with_mock_conn
        received: list[bytes] = []

        pm.open(_make_cfg())
        handle = pm.subscribe_rx("TESTPORT", received.append)
        conn1 = pm._connections["TESTPORT"]
        conn1._notify_rx_observers(b"data1")
        assert received == [b"data1"]

        # close 销毁 conn1（持久层保留订阅）
        pm.close("TESTPORT")
        assert not pm.is_connected("TESTPORT")
        assert len(pm._rx_observers["TESTPORT"]) == 1  # 持久层仍在

        # 重新 open → 自动 re-attach
        received.clear()
        pm.open(_make_cfg())
        conn2 = pm._connections["TESTPORT"]
        assert conn2 is not conn1  # 新对象
        assert len(conn2._rx_observers) == 1  # re-attach 成功
        conn2._notify_rx_observers(b"data2")
        assert received == [b"data2"]  # 订阅自愈

    def test_tx_subscribe_survives_close_reopen(self, pm_with_mock_conn) -> None:
        """TX 订阅同样持久化."""
        pm = pm_with_mock_conn
        received: list[bytes] = []

        pm.open(_make_cfg())
        pm.subscribe_tx("TESTPORT", received.append)
        conn1 = pm._connections["TESTPORT"]
        conn1._notify_tx_observers(b"tx1")
        assert received == [b"tx1"]

        pm.close("TESTPORT")
        received.clear()
        pm.open(_make_cfg())
        conn2 = pm._connections["TESTPORT"]
        conn2._notify_tx_observers(b"tx2")
        assert received == [b"tx2"]

    def test_unsubscribe_prevents_reattach(self, pm_with_mock_conn) -> None:
        """unsubscribe 后，close+open 不应再 re-attach."""
        pm = pm_with_mock_conn
        received: list[bytes] = []

        pm.open(_make_cfg())
        handle = pm.subscribe_rx("TESTPORT", received.append)
        pm.unsubscribe_rx(handle)
        # 持久层已移除
        assert len(pm._rx_observers["TESTPORT"]) == 0

        pm.close("TESTPORT")
        received.clear()
        pm.open(_make_cfg())
        conn3 = pm._connections["TESTPORT"]
        assert len(conn3._rx_observers) == 0  # 未 re-attach
        conn3._notify_rx_observers(b"nope")
        assert received == []

    def test_multiple_observers_all_reattached(self, pm_with_mock_conn) -> None:
        """多个观察者在 close+open 后全部恢复."""
        pm = pm_with_mock_conn
        rx_a: list[bytes] = []
        rx_b: list[bytes] = []

        pm.open(_make_cfg())
        pm.subscribe_rx("TESTPORT", rx_a.append)
        pm.subscribe_rx("TESTPORT", rx_b.append)
        pm.close("TESTPORT")
        pm.open(_make_cfg())
        conn = pm._connections["TESTPORT"]
        assert len(conn._rx_observers) == 2
        conn._notify_rx_observers(b"hi")
        assert rx_a == [b"hi"]
        assert rx_b == [b"hi"]

    def test_per_port_isolation(self, pm_with_mock_conn) -> None:
        """不同端口的订阅互不干扰."""
        pm = pm_with_mock_conn
        rx_a: list[bytes] = []
        rx_b: list[bytes] = []

        pm.open(_make_cfg("PORTA"))
        pm.open(_make_cfg("PORTB"))
        pm.subscribe_rx("PORTA", rx_a.append)
        pm.subscribe_rx("PORTB", rx_b.append)

        # 只重建 PORTA，PORTB 不受影响
        pm.close("PORTA")
        pm.open(_make_cfg("PORTA"))
        pm._connections["PORTA"]._notify_rx_observers(b"a")
        pm._connections["PORTB"]._notify_rx_observers(b"b")
        assert rx_a == [b"a"]
        assert rx_b == [b"b"]

    def test_subscribe_dedup(self, pm_with_mock_conn) -> None:
        """同一 observer 重复 subscribe 不应重复登记（持久层去重）."""
        pm = pm_with_mock_conn
        pm.open(_make_cfg())
        obs = lambda c: None  # noqa: E731
        pm.subscribe_rx("TESTPORT", obs)
        pm.subscribe_rx("TESTPORT", obs)  # 同一对象
        assert len(pm._rx_observers["TESTPORT"]) == 1
        conn = pm._connections["TESTPORT"]
        assert len(conn._rx_observers) == 1


class TestEnginePreservesExternalPorts:
    """改动 A：引擎只关本次新开端口，不破坏外部（GUI）已连接的端口。"""

    def test_engine_does_not_close_preconnected_port(self) -> None:
        """GUI 预先开的端口，执行用例后保持连接。"""
        from atprobe.domain.case import parse_case
        from atprobe.engine import Engine, EngineConfig
        from atprobe.infra.serial import connection as conn_mod
        from atprobe.infra.serial.interfaces import Response, ResponseStatus

        # 真串口 I/O mock：send_command 直接返回 OK
        def _fake_open(self):
            self._connected = True
            self._serial = None

        def _fake_send(self, command, *, timeout=None, cancel=None):
            return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)

        with mock.patch.object(conn_mod.SerialConnection, "open", _fake_open), \
             mock.patch.object(conn_mod.SerialConnection, "send_command", _fake_send):
            pm = PortManager()
            # GUI 预先开端口（模拟用户手动连接/监控）
            pm.open(_make_cfg("COMX"))
            assert pm.is_connected("COMX")

            case = parse_case("name: t\ntags: [x]\nsteps:\n  - command: AT\n    assert: { contains: OK }")
            ecfg = EngineConfig(
                ports=(_make_cfg("COMX"),), cases=(case,), log_dir="./logs_test_e"
            )
            engine = Engine(sender_factory=lambda: pm)
            result = engine.start(ecfg)

            # 核心：执行后端口仍连接（改动 A 目标）
            assert pm.is_connected("COMX"), "执行用例后 GUI 端口应保持连接"
            assert result.summary.passed == 1
            pm.close("COMX")
