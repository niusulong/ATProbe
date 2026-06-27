"""FileSendWorker 单元测试 —— 后台分块发送、逐块信号、取消。

worker 持有 SerialConnection 替身（记录每次 write_bytes 调用），
直接调 run() 同步验证分块/信号/取消/错误。
"""

from __future__ import annotations

import pytest

from atprobe.gui.widgets.file_send import FileSendWorker
from atprobe.infra.serial.interfaces import CancelToken


class _FakeConn:
    """SerialConnection 替身：记录所有 write_bytes 调用，可注入异常。"""

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.written: list[bytes] = []
        self.call_count = 0
        self._fail_on_call = fail_on_call

    def write_bytes(self, data: bytes) -> None:
        self.call_count += 1
        if self._fail_on_call is not None and self.call_count == self._fail_on_call:
            from atprobe.infra.serial.exceptions import SendError

            raise SendError("COM9", "模拟断连")
        self.written.append(data)


@pytest.fixture
def no_sleep(monkeypatch):
    """把 worker 的 sleep 打桩为 no-op，避免测试真实等待 5ms。"""
    monkeypatch.setattr("atprobe.gui.widgets.file_send.time.sleep", lambda _s: None)


class TestFileSendWorkerChunking:
    def test_small_data_single_write(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        conn = _FakeConn()
        chunks_sent: list[bytes] = []
        progress_vals: list[int] = []
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(conn, b"hello", chunk_threshold=4096, chunk_size=1024)
        worker.chunk_sent.connect(lambda c: chunks_sent.append(c))
        worker.progress.connect(lambda p: progress_vals.append(p))
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        worker.run()

        assert len(conn.written) == 1
        assert conn.written[0] == b"hello"
        assert chunks_sent == [b"hello"]
        assert results == [(True, "已发送 5 字节")]
        assert progress_vals[-1] == 100

    def test_large_data_chunked(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        data = b"x" * 5000  # 超过阈值 4096
        conn = _FakeConn()
        chunks_sent: list[bytes] = []
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(conn, data, chunk_threshold=4096, chunk_size=1024)
        worker.chunk_sent.connect(lambda c: chunks_sent.append(c))
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        worker.run()

        # 5000 字节按 1024 分块 = 5 块（1024+1024+1024+1024+904）
        assert len(conn.written) == 5
        assert b"".join(conn.written) == data
        assert len(chunks_sent) == 5
        assert results[0][0] is True

    def test_cancel_midway(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        data = b"x" * 5000
        conn = _FakeConn()
        token = CancelToken()
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(
            conn, data, chunk_threshold=4096, chunk_size=1024, cancel_token=token
        )
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        # 在第一块发出后取消
        original_write = conn.write_bytes
        call_state = {"n": 0}

        def write_then_cancel(data: bytes) -> None:
            original_write(data)
            call_state["n"] += 1
            if call_state["n"] == 1:
                token.cancel()  # 第一块后触发取消

        conn.write_bytes = write_then_cancel  # type: ignore[method-assign]

        worker.run()

        assert results[0][0] is False
        assert "已取消" in results[0][1]
        # 取消后不再继续写
        assert len(conn.written) == 1

    def test_senderror_reports_partial(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        data = b"x" * 5000
        conn = _FakeConn(fail_on_call=2)  # 第二块断连
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(conn, data, chunk_threshold=4096, chunk_size=1024)
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        worker.run()

        assert results[0][0] is False
        assert "发送中断" in results[0][1]
        assert len(conn.written) == 1  # 第一块成功，第二块抛异常
