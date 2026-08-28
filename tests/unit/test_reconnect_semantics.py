"""F-2/P3：reconnect 自愈检查与时钟注入贯穿."""

from __future__ import annotations

from datetime import datetime

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection


class _StubSerial:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.is_open = True
        self.closed = 0

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed += 1
        self.is_open = False


def _make(monkeypatch, *, clock, now_wall=None) -> tuple[SerialConnection, _StubSerial]:  # type: ignore[no-untyped-def]
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    conn = SerialConnection(cfg, clock=clock, now_wall=now_wall)
    stub = _StubSerial()
    monkeypatch.setattr(conn, "_serial", stub)
    monkeypatch.setattr(conn, "_connected", True)
    return conn, stub


class TestReconnectSelfHealCheck:
    def test_reconnect_returns_true_without_touching_healed_connection(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """F-2：读线程已自愈（连接活着）时 reconnect 直接 True，不 close 句柄——
        DTR/RTS 翻转会使模组软复位/掉承载。"""
        conn, stub = _make(monkeypatch, clock=lambda: 0.0)
        assert conn.reconnect() is True
        assert stub.closed == 0  # 修前：无条件 close（DTR 翻转）

    def test_reconnect_proceeds_when_disconnected(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn, _ = _make(monkeypatch, clock=lambda: 0.0)
        monkeypatch.setattr(conn, "_connected", False)
        # _build_serial 失败（无 pyserial 环境）→ False；关键是它走到了尝试路径
        assert conn.reconnect() is False


class TestClockInjection:
    def test_maybe_reconnect_rate_limit_uses_injected_clock(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        t = [0.0]
        conn, _ = _make(monkeypatch, clock=lambda: t[0])
        conn._last_reconnect_attempt = 0.0  # noqa: SLF001
        t[0] = 0.5  # 距上次尝试 0.5s < 1s
        assert conn._maybe_reconnect() is False  # noqa: SLF001 - 修前：time.monotonic 真时钟恒过限频
        t[0] = 2.0  # ≥1s → 尝试重连（_connected=True 自愈短路返回 True）
        assert conn._maybe_reconnect() is True  # noqa: SLF001

    def test_dispatch_urc_timestamp_uses_injected_wall_clock(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        stamps: list[str] = []
        fixed = datetime(2026, 8, 28, 12, 0, 0, 123456)

        def _wall() -> datetime:
            return fixed

        conn, _ = _make(monkeypatch, clock=lambda: 0.0, now_wall=_wall)
        conn.add_urc_handler(lambda evt: stamps.append(evt.timestamp))
        conn._dispatch_urc("+EVT: x")  # noqa: SLF001
        assert stamps == [fixed.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]]
