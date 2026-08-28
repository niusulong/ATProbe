"""FileSendWorker 单元测试 —— 持锁 write_data 迁移后的分块信号、取消、异常映射.

worker 持有 SerialConnection 替身（提供 write_data(spec, *, cancel, on_chunk)，
内部模拟 send_chunks 分块算法并记录调用），直接调 run() 同步验证
spec 构造/透传、逐块信号、取消传播与异常文案映射。
"""

from __future__ import annotations

from collections.abc import Callable

from atprobe.gui.widgets.file_send import FileSendWorker
from atprobe.infra.serial.config import DataStreamSpec
from atprobe.infra.serial.exceptions import (
    OperationCancelled,
    PortBusyError,
    SendError,
)
from atprobe.infra.serial.interfaces import CancelToken


class _FakeConn:
    """SerialConnection 替身：write_data 记录调用并模拟 send_chunks 分块算法.

    - 正常路径：按 spec 参数分块写（≤chunk_threshold 单块），每块驱动
      on_chunk(块字节, 已发, 总量)；
    - raise_busy=True：入口即抛 PortBusyError（模拟撞端口命令锁）；
    - fail_on_call=N：第 N 块写时抛 SendError（模拟中途断连）；
    - cancel_after_write=N：第 N 块写完触发 cancel（模拟发送中途取消）。
    """

    def __init__(
        self,
        *,
        fail_on_call: int | None = None,
        raise_busy: bool = False,
        cancel_after_write: int | None = None,
    ) -> None:
        self.written: list[bytes] = []
        self.specs: list[DataStreamSpec] = []
        self.cancel_seen: list[CancelToken | None] = []
        self.call_count = 0
        self._fail_on_call = fail_on_call
        self._raise_busy = raise_busy
        self._cancel_after_write = cancel_after_write

    def write_data(
        self,
        spec: DataStreamSpec,
        *,
        cancel: CancelToken | None = None,
        on_chunk: Callable[[bytes, int, int], None] | None = None,
    ) -> None:
        self.specs.append(spec)
        self.cancel_seen.append(cancel)
        if self._raise_busy:
            raise PortBusyError("COM9", "端口正忙：并发发送不支持")

        data = spec.data
        n = len(data)
        offset = 0
        if n <= spec.chunk_threshold:
            self._check_cancel(cancel, offset, n)
            self._write_one(data, cancel)
            offset = n
            if on_chunk is not None:
                on_chunk(data, offset, n)
        else:
            while offset < n:
                self._check_cancel(cancel, offset, n)
                end = min(offset + spec.chunk_size, n)
                chunk = data[offset:end]
                self._write_one(chunk, cancel)
                offset = end
                if on_chunk is not None:
                    on_chunk(chunk, offset, n)

    @staticmethod
    def _check_cancel(cancel: CancelToken | None, offset: int, total: int) -> None:
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled(f"数据流发送被取消（已发送 {offset}/{total} 字节）")

    def _write_one(self, chunk: bytes, cancel: CancelToken | None) -> None:
        self.call_count += 1
        if self._fail_on_call is not None and self.call_count == self._fail_on_call:
            raise SendError("COM9", "模拟断连")
        self.written.append(chunk)
        if (
            self._cancel_after_write is not None
            and self.call_count == self._cancel_after_write
            and cancel is not None
        ):
            cancel.cancel()


def _make_worker(
    conn: _FakeConn, data: bytes, *, cancel_token: CancelToken | None = None
) -> tuple[FileSendWorker, list[bytes], list[int], list[tuple[bool, str]]]:
    chunks_sent: list[bytes] = []
    progress_vals: list[int] = []
    results: list[tuple[bool, str]] = []
    worker = FileSendWorker(
        conn, data, chunk_threshold=4096, chunk_size=1024, cancel_token=cancel_token
    )
    worker.chunk_sent.connect(lambda c: chunks_sent.append(c))
    worker.progress.connect(lambda p: progress_vals.append(p))
    worker.finished.connect(lambda ok, msg: results.append((ok, msg)))
    return worker, chunks_sent, progress_vals, results


class TestFileSendWorkerChunking:
    def test_small_data_single_write(self) -> None:
        conn = _FakeConn()
        worker, chunks_sent, progress_vals, results = _make_worker(conn, b"hello")

        worker.run()

        # 替身收到 1 次单块写
        assert conn.written == [b"hello"]
        assert chunks_sent == [b"hello"]
        assert results == [(True, "已发送 5 字节")]
        assert progress_vals[-1] == 100
        # spec 按构造参数透传（默认紧凑值：块 1024/阈值 4096/间隔 5ms）
        assert conn.specs[0].data == b"hello"
        assert conn.specs[0].chunk_threshold == 4096
        assert conn.specs[0].chunk_size == 1024
        assert conn.specs[0].chunk_interval_ms == 5
        assert conn.specs[0].append_terminator is False

    def test_large_data_chunked(self) -> None:
        data = b"x" * 5000  # 超过阈值 4096
        conn = _FakeConn()
        worker, chunks_sent, progress_vals, results = _make_worker(conn, data)

        worker.run()

        # 5000 字节按 1024 分块 = 5 块（1024×4 + 904）
        assert len(conn.written) == 5
        assert b"".join(conn.written) == data
        assert len(chunks_sent) == 5
        assert b"".join(chunks_sent) == data
        assert results == [(True, "已发送 5000 字节")]
        # 逐块进度序列（int 截断）：20/40/61/81/100 + 末尾统一 100
        assert progress_vals == [20, 40, 61, 81, 100, 100]


class TestFileSendWorkerCancel:
    def test_cancel_token_forwarded_to_write_data(self) -> None:
        """cancel_token 经构造参数传入 → write_data 收到同一令牌（传播契约）。"""
        conn = _FakeConn()
        token = CancelToken()
        worker, _, _, _ = _make_worker(conn, b"hello", cancel_token=token)

        worker.run()

        assert conn.cancel_seen == [token]

    def test_cancel_before_run(self) -> None:
        """预先取消：替身首块前轮询到 → OperationCancelled，零字节写出。"""
        data = b"x" * 5000
        conn = _FakeConn()
        token = CancelToken()
        token.cancel()
        worker, _, _, results = _make_worker(conn, data, cancel_token=token)

        worker.run()

        assert results[0][0] is False
        assert "已取消" in results[0][1]
        assert "已发 0/5000" in results[0][1]
        assert conn.written == []

    def test_cancel_midway(self) -> None:
        """第一块写完后取消：下一块前轮询到 → 已取消（已发 1024/5000）。"""
        data = b"x" * 5000
        conn = _FakeConn(cancel_after_write=1)
        token = CancelToken()
        worker, _, _, results = _make_worker(conn, data, cancel_token=token)

        worker.run()

        assert results[0][0] is False
        assert "已取消" in results[0][1]
        assert "已发 1024/5000" in results[0][1]
        # 取消后不再继续写
        assert len(conn.written) == 1


class TestFileSendWorkerErrors:
    def test_port_busy_reported_distinctly(self) -> None:
        """PortBusyError 非 SendError 子类——显式分支给出"端口忙"文案（非兜底）。"""
        conn = _FakeConn(raise_busy=True)
        worker, _, _, results = _make_worker(conn, b"x" * 5000)

        worker.run()

        assert results[0][0] is False
        assert results[0][1].startswith("端口忙：")
        assert "已发 0/5000" in results[0][1]

    def test_senderror_reports_partial(self) -> None:
        data = b"x" * 5000
        conn = _FakeConn(fail_on_call=2)  # 第二块断连
        worker, _, _, results = _make_worker(conn, data)

        worker.run()

        assert results[0][0] is False
        assert results[0][1].startswith("发送中断：")
        assert "已发 1024/5000" in results[0][1]
        assert len(conn.written) == 1  # 第一块成功，第二块抛异常

    def test_arbitrary_exception_fallback(self) -> None:
        """任意异常走兜底分支——finished 必发出（UI 不永久卡"发送中"）。"""

        class _BoomConn(_FakeConn):
            def write_data(  # type: ignore[override]
                self,
                spec: DataStreamSpec,
                *,
                cancel: CancelToken | None = None,
                on_chunk: Callable[[bytes, int, int], None] | None = None,
            ) -> None:
                raise RuntimeError("连接对象被替换")

        conn = _BoomConn()
        worker, _, _, results = _make_worker(conn, b"hello")

        worker.run()

        assert results[0][0] is False
        assert results[0][1].startswith("发送失败：")
        assert "RuntimeError" in results[0][1]
