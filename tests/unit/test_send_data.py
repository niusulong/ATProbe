"""批 2b Task 3：持锁分块数据 API send_data / write_data（设计 §2.3 硬性条目）.

覆盖：整周期持锁（含等待段不提前释放）、分块策略接线（sleep 注入 / on_chunk /
连接级终结符）、取消与写失败的锁释放及错误语义、expect/wait_urc 端到端、
write_data 不置等待态、超时。桩串口模式照抄 tests/unit/test_command_lock.py
（_StubSerial + monkeypatch _serial/_connected，RX 经 _process_incoming 注入）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from atprobe.infra.serial.config import DataStreamSpec, FrameFormat, PortConfig, Terminator
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import (
    OperationCancelled,
    PortBusyError,
    SendError,
    SerialError,
)
from atprobe.infra.serial.interfaces import (
    ERROR_KIND_SEND,
    CancelToken,
    Response,
    ResponseStatus,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch


class _StubSerial:
    """最小串口替身：记录 write，flush 空操作（绕过 pyserial I/O）。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass


def _no_sleep(_seconds: float) -> None:
    """注入用零休眠（分块间隔不真等）。"""


def _make_conn(
    monkeypatch: MonkeyPatch,
    *,
    sleep: Callable[[float], None] | None = None,
    terminator: Terminator = Terminator.CRLF,
) -> SerialConnection:
    """构造已连接、底层为 _StubSerial 的 SerialConnection（不真开 pyserial）。"""
    cfg = PortConfig(
        name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"), terminator=terminator
    )
    conn = SerialConnection(cfg) if sleep is None else SerialConnection(cfg, sleep=sleep)
    monkeypatch.setattr(conn, "_serial", _StubSerial())
    monkeypatch.setattr(conn, "_connected", True)
    return conn


def _assert_lock_free(conn: SerialConnection) -> None:
    """断言命令锁空闲（可立即获锁）——acquire 成功后随即释放，不残留。"""
    assert conn._command_lock.acquire(blocking=False), "命令锁未释放（路径残留）"  # noqa: SLF001
    conn._command_lock.release()  # noqa: SLF001


def _run_and_feed_ok(
    conn: SerialConnection, send: Callable[[], object], timeout: float = 3.0
) -> object:
    """线程内发起发送，主线程循环喂 ``\\r\\nOK\\r\\n`` 直到完成（command_lock 模式）。

    循环喂入消时序依赖：早于等待态建立的喂入被 drain/空闲分流消化，无害；
    等待态建立后的一次喂入即终结周期。
    """
    results: list[object] = []
    done = threading.Event()

    def _run() -> None:
        results.append(send())
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    for _ in range(150):
        if done.is_set():
            break
        conn._process_incoming(b"\r\nOK\r\n")  # noqa: SLF001 - 模拟读线程喂字节
        done.wait(0.02)
    assert done.wait(timeout), "发送周期未在时限内完成"
    t.join(timeout=2.0)
    assert not t.is_alive()
    return results[0]


def _send_command_ok(conn: SerialConnection) -> Response:
    """发起一次 send_command 并喂 OK——用于「锁已释放、通道零污染」复核。"""

    def _send() -> Response:
        return conn.send_command("AT", timeout=3.0)

    result = _run_and_feed_ok(conn, _send)
    assert isinstance(result, Response)
    return result


class TestSendDataBasic:
    def test_send_data_writes_all_bytes_and_completes(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch)

        def _send() -> Response:
            return conn.send_data(DataStreamSpec(data=b"\x01\x02\x03"), timeout=2.0)

        result = _run_and_feed_ok(conn, _send)
        assert isinstance(result, Response)
        assert result.status is ResponseStatus.COMPLETE
        assert "OK" in result.text
        # 全部字节到达桩串口（≤ threshold → 整体单块写，无终结符追加）
        assert conn._serial.written == [b"\x01\x02\x03"]  # noqa: SLF001
        assert not conn._awaiting.is_set()  # noqa: SLF001 - 周期结束等待态已清

    def test_send_data_not_connected_returns_error(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch)
        monkeypatch.setattr(conn, "_connected", False)
        resp = conn.send_data(DataStreamSpec(data=b"x"), timeout=0.1)
        assert resp.status is ResponseStatus.ERROR
        assert resp.error_kind == ERROR_KIND_SEND
        assert resp.error == "端口未连接"
        assert conn._serial.written == []  # noqa: SLF001 - 未连接零写入
        _assert_lock_free(conn)

    def test_send_data_chunked_writes_arrive(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch, sleep=_no_sleep)
        spec = DataStreamSpec(data=b"123456", chunk_threshold=4, chunk_size=2, chunk_interval_ms=10)
        resp = conn.send_data(spec, timeout=0.1)  # 无 RX → 超时（写路径已验证）
        assert resp.status is ResponseStatus.TIMEOUT
        assert conn._serial.written == [b"12", b"34", b"56"]  # noqa: SLF001


class TestSendDataWholeCycleLock:
    def test_send_data_fails_fast_when_locked(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch)
        conn._command_lock.acquire()  # noqa: SLF001 - 模拟另一发送周期持锁
        try:
            with pytest.raises(PortBusyError, match=r"^\[COM9\] 端口正忙：并发发送不支持$"):
                conn.send_data(DataStreamSpec(data=b"x"), timeout=0.1)
        finally:
            conn._command_lock.release()  # noqa: SLF001

    def test_send_data_holds_lock_through_wait_phase(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """等待段（无 RX、大 timeout）不提前释放锁：并发 send_command 撞锁快速失败。"""
        conn = _make_conn(monkeypatch)
        results: list[Response] = []
        done = threading.Event()

        def _send() -> None:
            results.append(conn.send_data(DataStreamSpec(data=b"DATA"), timeout=5.0))
            done.set()

        t = threading.Thread(target=_send, daemon=True)
        t.start()
        # 等进入等待段：awaiting 已置且字节已写
        for _ in range(200):
            if conn._awaiting.is_set() and conn._serial.written:  # noqa: SLF001
                break
            time.sleep(0.01)
        assert conn._awaiting.is_set()  # noqa: SLF001
        assert conn._serial.written == [b"DATA"]  # noqa: SLF001
        # 锁由 send_data 全周期持有（分块写 + 等待段）：send_command 不得插入
        with pytest.raises(PortBusyError, match="端口正忙"):
            conn.send_command("AT", timeout=0.1)
        # feed RX 让 send_data 收尾
        conn._process_incoming(b"\r\nOK\r\n")  # noqa: SLF001
        assert done.wait(3.0)
        assert results[0].status is ResponseStatus.COMPLETE
        t.join(timeout=2.0)
        assert not t.is_alive()


class TestChunking:
    def test_chunked_write_sleep_and_on_chunk(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        sleeps: list[float] = []
        conn = _make_conn(monkeypatch, sleep=sleeps.append)
        chunks: list[tuple[bytes, int, int]] = []
        spec = DataStreamSpec(data=b"123456", chunk_threshold=4, chunk_size=2, chunk_interval_ms=10)

        conn.write_data(spec, on_chunk=lambda c, sent, total: chunks.append((c, sent, total)))

        assert conn._serial.written == [b"12", b"34", b"56"]  # noqa: SLF001 - 3 次写
        assert sleeps == [0.01, 0.01]  # 块间 2 次（interval=10ms）
        assert chunks == [(b"12", 2, 6), (b"34", 4, 6), (b"56", 6, 6)]

    def test_single_chunk_on_chunk_once_no_sleep(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        sleeps: list[float] = []
        conn = _make_conn(monkeypatch, sleep=sleeps.append)
        chunks: list[tuple[bytes, int, int]] = []
        conn.write_data(
            DataStreamSpec(data=b"ab"),
            on_chunk=lambda c, sent, total: chunks.append((c, sent, total)),
        )
        assert conn._serial.written == [b"ab"]  # noqa: SLF001 - n ≤ threshold 整体单块写
        assert sleeps == []
        assert chunks == [(b"ab", 2, 2)]


class TestCancelDuringChunks:
    def test_cancel_mid_chunks_raises_and_releases_lock(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        cancel = CancelToken()

        def _sleep_then_cancel(_seconds: float) -> None:
            cancel.cancel()  # 首个块间隔后取消 → 下一块前检查命中

        conn = _make_conn(monkeypatch, sleep=_sleep_then_cancel)
        spec = DataStreamSpec(data=b"123456", chunk_threshold=4, chunk_size=2, chunk_interval_ms=10)
        with pytest.raises(OperationCancelled, match="已发送 2/6"):
            conn.send_data(spec, timeout=1.0, cancel=cancel)
        assert not conn._awaiting.is_set()  # noqa: SLF001 - 取消后等待态已清
        # 锁已释放：随后 send_command 正常完成
        resp = _send_command_ok(conn)
        assert resp.status is ResponseStatus.COMPLETE


class TestAppendTerminator:
    def test_append_terminator_uses_connection_terminator(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """尾部追加连接级终结符（CR 配置 → b"\\r"），且终结符不算块（不回调 on_chunk）。"""
        conn = _make_conn(monkeypatch, terminator=Terminator.CR)
        chunks: list[tuple[bytes, int, int]] = []
        conn.write_data(
            DataStreamSpec(data=b"ABC", append_terminator=True),
            on_chunk=lambda c, sent, total: chunks.append((c, sent, total)),
        )
        assert conn._serial.written == [b"ABC", b"\r"]  # noqa: SLF001
        assert chunks == [(b"ABC", 3, 3)]  # 终结符不触发 on_chunk

    def test_send_data_append_terminator_default_crlf(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch, sleep=_no_sleep)

        def _send() -> Response:
            return conn.send_data(
                DataStreamSpec(
                    data=b"123456", chunk_threshold=4, chunk_size=2, append_terminator=True
                ),
                timeout=0.1,
            )

        result = _run_and_feed_ok(conn, _send)
        assert isinstance(result, Response)
        assert result.status is ResponseStatus.COMPLETE
        assert conn._serial.written == [b"12", b"34", b"56", b"\r\n"]  # noqa: SLF001


class TestWriteFailure:
    def test_write_failure_returns_error_and_releases_lock(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch)
        stub = conn._serial  # noqa: SLF001
        original_write = stub.write

        def _raise(_data: bytes) -> None:
            raise OSError("发送失败")

        monkeypatch.setattr(stub, "write", _raise)
        resp = conn.send_data(DataStreamSpec(data=b"xy"), timeout=0.5)
        assert resp.status is ResponseStatus.ERROR
        assert resp.error_kind == ERROR_KIND_SEND
        assert "发送失败" in resp.error
        assert not conn._awaiting.is_set()  # noqa: SLF001
        assert conn._expect_re is None and conn._wait_urc_re is None  # noqa: SLF001 - 周期态已复位
        # 恢复写能力后锁已释放：随后 send_command 正常完成
        monkeypatch.setattr(stub, "write", original_write)
        follow = _send_command_ok(conn)
        assert follow.status is ResponseStatus.COMPLETE
        _assert_lock_free(conn)


class TestExpectEndToEnd:
    def test_expect_hits_prompt_completes(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """expect=r"\\r\\n>"：feed 提示符 → COMPLETE 且 text 至命中点（数据流场景）。"""
        conn = _make_conn(monkeypatch)
        results: list[Response] = []
        done = threading.Event()

        def _run() -> None:
            results.append(conn.send_data(DataStreamSpec(data=b"P"), timeout=3.0, expect=r"\r\n>"))
            done.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        for _ in range(150):
            if done.is_set():
                break
            conn._process_incoming(b"\r\n>")  # noqa: SLF001
            done.wait(0.02)
        assert done.wait(3.0)
        t.join(timeout=2.0)
        resp = results[0]
        assert resp.status is ResponseStatus.COMPLETE
        assert resp.text == "\r\n>"  # 响应文本 = 缓冲至命中点


class TestWaitUrcEndToEnd:
    def test_wait_urc_returns_whole_segment(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """wait_urc：feed OK+目标 URC → 整段（OK+URC）COMPLETE 返回。"""
        conn = _make_conn(monkeypatch)
        results: list[Response] = []
        done = threading.Event()

        def _run() -> None:
            results.append(
                conn.send_data(DataStreamSpec(data=b"D"), timeout=3.0, wait_urc=r"\+RECV: \d+")
            )
            done.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        for _ in range(150):
            if done.is_set():
                break
            conn._process_incoming(b"\r\nOK\r\n+RECV: 5\r\n")  # noqa: SLF001
            done.wait(0.02)
        assert done.wait(3.0)
        t.join(timeout=2.0)
        resp = results[0]
        assert resp.status is ResponseStatus.COMPLETE
        assert "OK" in resp.text and "+RECV: 5" in resp.text

    def test_expect_wait_urc_mutex_zero_pollution(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """expect×wait_urc 同传 → SerialError 且通道状态零污染（随后命令正常）。"""
        conn = _make_conn(monkeypatch)
        with pytest.raises(SerialError, match="互斥"):
            conn.send_data(
                DataStreamSpec(data=b"x"),
                timeout=0.5,
                wait_urc=r"\+X:ok",
                expect=r"\r\n>",
            )
        assert not conn._awaiting.is_set()  # noqa: SLF001
        assert conn._expect_re is None  # noqa: SLF001
        assert conn._wait_urc_re is None  # noqa: SLF001
        resp = _send_command_ok(conn)
        assert resp.status is ResponseStatus.COMPLETE


class TestWriteData:
    def test_write_data_bytes_and_on_chunk(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch, sleep=_no_sleep)
        chunks: list[tuple[bytes, int, int]] = []
        spec = DataStreamSpec(data=b"abcdef", chunk_threshold=4, chunk_size=3, chunk_interval_ms=5)
        conn.write_data(spec, on_chunk=lambda c, sent, total: chunks.append((c, sent, total)))
        assert conn._serial.written == [b"abc", b"def"]  # noqa: SLF001
        assert chunks == [(b"abc", 3, 6), (b"def", 6, 6)]

    def test_write_data_busy(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch)
        conn._command_lock.acquire()  # noqa: SLF001
        try:
            with pytest.raises(PortBusyError, match="端口正忙"):
                conn.write_data(DataStreamSpec(data=b"x"))
        finally:
            conn._command_lock.release()  # noqa: SLF001

    def test_write_data_not_connected_raises(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch)
        monkeypatch.setattr(conn, "_connected", False)
        with pytest.raises(SendError, match="端口未连接"):
            conn.write_data(DataStreamSpec(data=b"x"))
        _assert_lock_free(conn)

    def test_write_data_no_waiting_state_urc_dispatched(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """不置等待态：feed RX 后响应队列空（完整行走 URC 派发，不入响应队列）。"""
        from atprobe.infra.serial.interfaces import URCEvent

        conn = _make_conn(monkeypatch)
        urcs: list[URCEvent] = []
        conn.add_urc_handler(lambda evt: urcs.append(evt))
        conn.write_data(DataStreamSpec(data=b"D"))
        assert not conn._awaiting.is_set()  # noqa: SLF001 - 只写不等，不置等待态
        conn._process_incoming(b"\r\n+NOTIFY: 1\r\n")  # noqa: SLF001
        assert conn._response_q.empty()  # noqa: SLF001 - 空闲态：不作为命令响应入队
        assert len(urcs) == 1
        assert "+NOTIFY: 1" in urcs[0].text
        _assert_lock_free(conn)


class TestTimeout:
    def test_send_data_no_rx_times_out(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_conn(monkeypatch)
        resp = conn.send_data(DataStreamSpec(data=b"Q"), timeout=0.3)
        assert resp.status is ResponseStatus.TIMEOUT
        assert resp.error == "响应超时"
        assert not conn._awaiting.is_set()  # noqa: SLF001
        _assert_lock_free(conn)
