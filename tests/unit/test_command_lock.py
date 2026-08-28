"""P1-3/P1-8：端口级命令互斥——发送入口 try-acquire，撞锁快速失败."""

from __future__ import annotations

import threading

import pytest

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import SerialError
from atprobe.infra.serial.interfaces import ResponseStatus


class _StubSerial:
    """最小串口替身：记录 write，flush 空操作（绕过 pyserial I/O）。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass


@pytest.fixture
def conn(monkeypatch) -> SerialConnection:
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    c = SerialConnection(cfg)
    monkeypatch.setattr(c, "_serial", _StubSerial())
    monkeypatch.setattr(c, "_connected", True)
    return c


class TestCommandLock:
    def test_send_command_fails_fast_when_locked(self, conn) -> None:  # type: ignore[no-untyped-def]
        conn._command_lock.acquire()  # noqa: SLF001 - 模拟另一线程持锁（如文件发送）
        try:
            with pytest.raises(SerialError, match="端口正忙"):
                conn.send_command("AT", timeout=0.1)
        finally:
            conn._command_lock.release()  # noqa: SLF001

    def test_write_command_shares_lock(self, conn) -> None:  # type: ignore[no-untyped-def]
        conn._command_lock.acquire()  # noqa: SLF001
        try:
            with pytest.raises(SerialError, match="端口正忙"):
                conn.write_command("AT")
        finally:
            conn._command_lock.release()  # noqa: SLF001

    def test_sequential_commands_not_blocked(self, conn) -> None:  # type: ignore[no-untyped-def]
        """顺序使用无锁残留：完整命令周期正常（喂入 OK 响应）。"""
        done = threading.Event()
        holder: list[object] = []

        def _send() -> None:
            holder.append(conn.send_command("AT", timeout=1.0))
            done.set()

        t = threading.Thread(target=_send, daemon=True)
        t.start()
        for _ in range(50):
            if done.is_set():
                break
            conn._process_incoming(b"\r\nOK\r\n")  # noqa: SLF001 - 模拟读线程喂字节
            done.wait(0.02)
        assert done.wait(2.0)
        assert holder[0].status is ResponseStatus.COMPLETE  # type: ignore[attr-defined]
        t.join(timeout=2.0)

    def test_lock_released_after_send_error_path(self, conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """SendError 早退路径（write 抛 OSError）后锁必须释放——无残留。"""

        def _raise(_data: bytes) -> None:
            raise OSError("发送失败")

        monkeypatch.setattr(conn._serial, "write", _raise)  # noqa: SLF001
        resp = conn.send_command("AT", timeout=0.1)
        assert resp.status is ResponseStatus.ERROR
        # 前一条失败后锁已释放：下一条命令不再撞锁
        conn2_resp = conn.send_command("AT", timeout=0.05)
        assert conn2_resp.error != "端口正忙"

    def test_write_bytes_bypasses_lock(self, conn) -> None:  # type: ignore[no-untyped-def]
        """write_bytes 是裸字节接口：持锁期间也可写（供持锁周期内分块写）。"""
        conn._command_lock.acquire()  # noqa: SLF001
        try:
            conn.write_bytes(b"\x01\x02")
        finally:
            conn._command_lock.release()  # noqa: SLF001
        assert conn._serial.written == [b"\x01\x02"]  # noqa: SLF001


class TestPortManagerPreCheck:
    """PortManager.send_command 的 pre_check 钩子（批 3 MCP 锁内重检的接口预留）."""

    def test_pre_check_invoked_before_send(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        order: list[str] = []

        class _FakeConn:
            is_connected = True

            def send_command(self, command: str, **kwargs: object) -> object:  # noqa: ARG002
                order.append("send")
                from atprobe.infra.serial.interfaces import Response

                return Response(text="OK")

        monkeypatch.setitem(pm._connections, "COM3", _FakeConn())  # noqa: SLF001
        resp = pm.send_command("COM3", "AT", pre_check=lambda: order.append("pre_check"))
        assert order == ["pre_check", "send"]
        assert resp.text == "OK"

    def test_pre_check_exception_propagates(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        sent: list[str] = []

        class _FakeConn:
            is_connected = True

            def send_command(self, command: str, **kwargs: object) -> object:  # noqa: ARG002
                sent.append(command)
                from atprobe.infra.serial.interfaces import Response

                return Response(text="OK")

        monkeypatch.setitem(pm._connections, "COM3", _FakeConn())  # noqa: SLF001

        def _busy() -> None:
            raise SerialError("COM3", "端口正忙：并发发送不支持")

        with pytest.raises(SerialError, match="端口正忙"):
            pm.send_command("COM3", "AT", pre_check=_busy)
        assert sent == []  # pre_check 抛错则不发送
