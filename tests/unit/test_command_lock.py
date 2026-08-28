"""P1-3/P1-8：端口级命令互斥——发送入口 try-acquire，撞锁快速失败（PortBusyError）."""

from __future__ import annotations

import threading
import time

import pytest

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import OperationCancelled, PortBusyError
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


def _assert_lock_free(c: SerialConnection) -> None:
    """断言命令锁空闲（可立即获锁）——acquire 成功后随即释放，不残留。"""
    assert c._command_lock.acquire(blocking=False), "命令锁未释放（早退路径残留）"  # noqa: SLF001
    c._command_lock.release()  # noqa: SLF001


class TestCommandLock:
    def test_send_command_fails_fast_when_locked(self, conn) -> None:  # type: ignore[no-untyped-def]
        conn._command_lock.acquire()  # noqa: SLF001 - 模拟另一线程持锁（如文件发送）
        try:
            # 严格全串匹配：类型化异常的消息是格式化单串（[port] reason），非元组 repr
            with pytest.raises(PortBusyError, match=r"^\[COM9\] 端口正忙：并发发送不支持$"):
                conn.send_command("AT", timeout=0.1)
        finally:
            conn._command_lock.release()  # noqa: SLF001

    def test_write_command_shares_lock(self, conn) -> None:  # type: ignore[no-untyped-def]
        conn._command_lock.acquire()  # noqa: SLF001
        try:
            with pytest.raises(PortBusyError, match="端口正忙"):
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

    def test_lock_released_after_write_failure_returns_error(self, conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """write 失败返回 ERROR（send_command 不抛 SendError）后锁必须释放——无残留。"""

        def _raise(_data: bytes) -> None:
            raise OSError("发送失败")

        monkeypatch.setattr(conn._serial, "write", _raise)  # noqa: SLF001
        resp = conn.send_command("AT", timeout=0.1)
        assert resp.status is ResponseStatus.ERROR
        _assert_lock_free(conn)

    def test_lock_released_after_write_command_send_error(self, conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """write_command 的 SendError 路径（write 抛 OSError）后锁必须释放。"""

        def _raise(_data: bytes) -> None:
            raise OSError("发送失败")

        monkeypatch.setattr(conn._serial, "write", _raise)  # noqa: SLF001
        from atprobe.infra.serial.exceptions import SendError

        with pytest.raises(SendError):
            conn.write_command("AT")
        _assert_lock_free(conn)

    def test_lock_released_after_operation_cancelled(self, conn) -> None:  # type: ignore[no-untyped-def]
        """OperationCancelled 传播路径（等待期取消触发）后锁必须释放——无残留。"""
        from atprobe.infra.serial.interfaces import CancelToken

        cancel = CancelToken()
        errors: list[BaseException] = []

        def _send() -> None:
            try:
                conn.send_command("AT", timeout=5.0, cancel=cancel)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t = threading.Thread(target=_send, daemon=True)
        t.start()
        # 等命令进入等待态（已持锁、置 _awaiting）后取消 → OperationCancelled 传播
        for _ in range(100):
            if conn._awaiting.is_set():  # noqa: SLF001
                break
            time.sleep(0.01)
        cancel.cancel()
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], OperationCancelled)
        _assert_lock_free(conn)

    def test_write_bytes_bypasses_lock(self, conn) -> None:  # type: ignore[no-untyped-def]
        """write_bytes 是裸字节接口：持锁期间也可写（供持锁周期内分块写）。"""
        conn._command_lock.acquire()  # noqa: SLF001
        try:
            conn.write_bytes(b"\x01\x02")
        finally:
            conn._command_lock.release()  # noqa: SLF001
        assert conn._serial.written == [b"\x01\x02"]  # noqa: SLF001


class TestPreCheckInLock:
    """pre_check 获命令锁后、状态突变前执行（设计 §3.2"锁内重检"）。"""

    def test_pre_check_runs_inside_command_lock(self, conn) -> None:  # type: ignore[no-untyped-def]
        """证明锁内执行：回调内 try-acquire 应失败（False）——命令周期持有锁。"""
        attempts: list[bool] = []

        def _probe() -> None:
            # 记录此刻能否获锁：应为 False（send_command 已持有）。成功则立即释放，
            # 保证无论实现正确与否都不会死锁/残留。
            got = conn._command_lock.acquire(blocking=False)  # noqa: SLF001
            attempts.append(got)
            if got:
                conn._command_lock.release()  # noqa: SLF001

        resp = conn.send_command("AT", timeout=0.05, pre_check=_probe)
        assert attempts == [False], "pre_check 须在 _command_lock 之内执行"
        assert resp.status is ResponseStatus.TIMEOUT
        _assert_lock_free(conn)

    def test_pre_check_exception_propagates_before_mutation(self, conn) -> None:  # type: ignore[no-untyped-def]
        """pre_check 抛错透传：不写入任何字节（先于状态突变/写），锁随后释放。"""

        def _busy() -> None:
            raise PortBusyError("COM9", "被 MCP 判定占用")

        with pytest.raises(PortBusyError):
            conn.send_command("AT", timeout=0.1, pre_check=_busy)
        assert conn._serial.written == []  # noqa: SLF001 - pre_check 先于 write
        _assert_lock_free(conn)


class TestPortManagerPreCheck:
    """PortManager.send_command 把 pre_check 透传到连接层锁内（批 3 MCP 接口预留）."""

    def test_pre_check_passthrough_invoked_before_send(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        order: list[str] = []

        class _FakeConn:
            is_connected = True

            def send_command(self, command: str, **kwargs: object) -> object:
                # 模拟 SerialConnection：pre_check 在实际发送前调用
                pre = kwargs.get("pre_check")
                if pre is not None:
                    pre()
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

            def send_command(self, command: str, **kwargs: object) -> object:
                pre = kwargs.get("pre_check")
                if pre is not None:
                    pre()  # 抛错透传，先于发送记录
                sent.append(command)
                from atprobe.infra.serial.interfaces import Response

                return Response(text="OK")

        monkeypatch.setitem(pm._connections, "COM3", _FakeConn())  # noqa: SLF001

        def _busy() -> None:
            raise PortBusyError("COM3", "端口正忙：并发发送不支持")

        with pytest.raises(PortBusyError):
            pm.send_command("COM3", "AT", pre_check=_busy)
        assert sent == []  # pre_check 抛错则不发送

    def test_pre_check_runs_again_before_resend_after_reconnect(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """断连重发场景：pre_check 随透传在第二次发送前再次执行（TOCTOU 同源）。"""
        from atprobe.infra.serial.interfaces import (
            ERROR_KIND_DISCONNECT,
            Response,
        )
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        calls: list[str] = []

        class _FakeConn:
            is_connected = True

            def reconnect(self) -> bool:
                calls.append("reconnect")
                return True

            def send_command(self, command: str, **kwargs: object) -> object:
                pre = kwargs.get("pre_check")
                if pre is not None:
                    pre()
                calls.append("send")
                if calls.count("send") == 1:
                    return Response(
                        text="",
                        status=ResponseStatus.ERROR,
                        error="端口断连",
                        error_kind=ERROR_KIND_DISCONNECT,
                    )
                from atprobe.infra.serial.interfaces import Response as _R

                return _R(text="OK")

        monkeypatch.setitem(pm._connections, "COM3", _FakeConn())  # noqa: SLF001
        monkeypatch.setitem(pm._configs, "COM3", PortConfig(name="COM3"))  # noqa: SLF001
        resp = pm.send_command("COM3", "AT", pre_check=lambda: calls.append("pre_check"))
        # 首发送(pre_check+send) → 断连 → reconnect → 重发(pre_check+send)：
        # pre_check 在每次实际发送前各执行一次（重连窗口内占用可能变化）
        assert calls == ["pre_check", "send", "reconnect", "pre_check", "send"]
        assert resp.text == "OK"
