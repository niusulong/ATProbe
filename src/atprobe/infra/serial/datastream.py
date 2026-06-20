"""M1 数据流分块发送（REQ-M1 §3.2）.

发送任意字节流，超阈值自动分块（§3.2 发送行为）。发送期间断连即失败，不续传（§3.2
发送中断处理）。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from atprobe.infra.serial.config import DataStreamSpec, Terminator
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.interfaces import CancelToken


def send_data_stream(
    conn: SerialConnection,
    spec: DataStreamSpec,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    cancel: CancelToken | None = None,
) -> None:
    """按规格发送数据流（分块，§3.2）.

    Raises:
        SendError: 发送失败（含断连）。
        OperationCancelled: 被取消。
    """
    if cancel is not None and cancel.cancelled:
        from atprobe.infra.serial.exceptions import OperationCancelled

        raise OperationCancelled("数据流发送被取消")

    data = spec.data
    n = len(data)

    if n <= spec.chunk_threshold:
        # 整体发送
        _write_with_cancel(conn, data, cancel)
    else:
        # 分块发送
        offset = 0
        chunk_idx = 0
        while offset < n:
            if cancel is not None and cancel.cancelled:
                from atprobe.infra.serial.exceptions import OperationCancelled

                raise OperationCancelled(
                    f"数据流发送被取消（已发送 {offset}/{n} 字节）"
                )
            end = min(offset + spec.chunk_size, n)
            _write_with_cancel(conn, data[offset:end], cancel)
            chunk_idx += 1
            offset = end
            if offset < n:
                sleep(spec.chunk_interval_ms / 1000.0)

    if spec.append_terminator:
        term = Terminator.CRLF.value.encode("ascii")
        _write_with_cancel(conn, term, cancel)


def _write_with_cancel(
    conn: SerialConnection, data: bytes, cancel: CancelToken | None
) -> None:
    if cancel is not None and cancel.cancelled:
        from atprobe.infra.serial.exceptions import OperationCancelled

        raise OperationCancelled("数据流发送被取消")
    conn.write_bytes(data)  # 失败抛 SendError（断连即失败）
