"""F-1/F-2/P3：重连取消贯通、reconnect 自愈检查与时钟注入贯穿."""

from __future__ import annotations

from datetime import datetime

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.interfaces import (
    ERROR_KIND_DISCONNECT,
    CancelToken,
    ResponseStatus,
)
from atprobe.infra.serial.portmanager import PortManager


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


# ===========================================================================
# F-1（批 3 T1）：重连重试间隔经 cancellable_sleep——停止令牌触发后立即放弃，
# 停止引擎后 send_command 最长滞留一个 slice（0.1s）而非整个重连预算
# （默认 10 次 × reconnect_interval_s=3s）。
# ===========================================================================
class _DeadConn:
    """断连桩连接：is_connected 恒 False、reconnect 恒失败（记录尝试次数）。"""

    is_connected = False

    def __init__(self) -> None:
        self.reconnect_attempts = 0

    def reconnect(self) -> bool:
        self.reconnect_attempts += 1
        return False


def _make_pm_with_dead_conn(monkeypatch, sleep) -> tuple[PortManager, _DeadConn]:  # type: ignore[no-untyped-def]
    """PortManager + 注入 _connections/_configs 的断连桩连接（绕过真实串口）."""
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    conn = _DeadConn()
    pm = PortManager(sleep=sleep)
    monkeypatch.setattr(pm, "_connections", {"COM9": conn})
    monkeypatch.setattr(pm, "_configs", {"COM9": cfg})
    return pm, conn


class TestReconnectCancelPropagation:
    def test_pre_cancelled_send_command_returns_disconnect_without_sleep(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """cancel 已置 → send_command 立即返回 DISCONNECT 错误且零 sleep 调用。

        修前：_sleep(reconnect_interval_s) 不响应令牌，重试满 10 次（sleep
        计数 10、reconnect 尝试 10 次）才返回——停止引擎后被拖住 30s。
        """
        sleeps: list[float] = []
        pm, conn = _make_pm_with_dead_conn(monkeypatch, sleeps.append)

        tok = CancelToken()
        tok.cancel()
        resp = pm.send_command("COM9", "AT", cancel=tok)

        assert resp.status is ResponseStatus.ERROR
        assert resp.error_kind == ERROR_KIND_DISCONNECT
        assert "重连失败" in resp.error
        assert conn.reconnect_attempts == 1  # 循环结构照旧：首轮先试 reconnect
        assert sleeps == []  # 首个分片前即退出——未睡任何 interval

    def test_cancel_during_interval_aborts_after_one_slice(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """取消恰落在重试间隔内：只睡一个 slice 即放弃，不再进入下一轮尝试。"""
        tok = CancelToken()
        sleeps: list[float] = []

        def _sleep_and_cancel(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 1:
                tok.cancel()  # 首片睡完即取消

        pm, conn = _make_pm_with_dead_conn(monkeypatch, _sleep_and_cancel)

        assert pm._reconnect("COM9", cancel=tok) is False  # noqa: SLF001
        assert conn.reconnect_attempts == 1  # 第二轮循环未发生
        assert sleeps == [0.1]  # 只睡一个默认 slice，而非整个 3s interval

    def test_reconnect_without_cancel_still_full_retry(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """无令牌（cancel=None）行为不变：重试满 reconnect_max_retries 次、
        睡满整个 interval 预算（分片粒度——cancellable_sleep 逐片转发给注入 sleep）。"""
        import pytest as _pytest

        sleeps: list[float] = []
        pm, conn = _make_pm_with_dead_conn(monkeypatch, sleeps.append)

        assert pm._reconnect("COM9") is False  # noqa: SLF001
        assert conn.reconnect_attempts == 10
        # 10 次 × 3.0s interval 全部睡满（每片 0.1s，即 300 片）
        assert sum(sleeps) == _pytest.approx(30.0)
        assert all(d <= 0.1 for d in sleeps)
