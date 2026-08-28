"""M1 数据流分块发送策略（REQ-M1 §3.2，批 2b Task 3 重构为纯函数）.

纯分块策略：不持有连接，由 SerialConnection.send_data / write_data 在
_command_lock 持锁周期内调用（连接以 write 回调注入）。发送期间断连即失败，
不续传（§3.2 发送中断处理）——write 回调抛 SendError 时部分字节已上线，
由调用方决定返回 ERROR Response（send_data）或传播（write_data）。
"""

from __future__ import annotations

from collections.abc import Callable

from atprobe.infra.serial.config import DataStreamSpec
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import CancelToken


def send_chunks(
    write: Callable[[bytes], None],
    spec: DataStreamSpec,
    *,
    sleep: Callable[[float], None],
    cancel: CancelToken | None,
    terminator: bytes | None = None,
    on_chunk: Callable[[bytes, int, int], None] | None = None,
) -> int:
    """按规格分块写入（§3.2；连接的 write_bytes 经 write 注入，失败抛 SendError）.

    n ≤ chunk_threshold 整体单块写；否则按 chunk_size 分块、块间
    sleep(chunk_interval_ms/1000)。每块写前查 cancel，触发抛
    ``OperationCancelled("数据流发送被取消（已发送 {offset}/{n} 字节）")``。

    append_terminator=True 且 terminator 提供时尾写终结符（连接级
    PortConfig.terminator 的字节序列，由调用方传入——本函数无连接依赖）；
    终结符不算块：不触发 on_chunk、不计入返回值。

    Args:
        write: 字节写入回调（连接的 write_bytes；断连/IO 失败抛 SendError）。
        spec: 数据流规格（data + 分块参数）。
        sleep: 块间休眠回调（秒；连接注入，测试可替换为记录器）。
        cancel: 取消令牌；每块（含终结符）写前轮询。
        terminator: 追加的终结符字节；None 且 append_terminator=True 时不追加。
        on_chunk: 每块写完后回调 (块字节, 已发, 总量)——整体单块写亦回调一次。

    Returns:
        已写数据字节数（不含终结符）。

    Raises:
        SendError: write 回调失败（断连即失败，不重试不续传）。
        OperationCancelled: 块间被取消。
    """

    def _check_cancel(offset: int, total: int) -> None:
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled(f"数据流发送被取消（已发送 {offset}/{total} 字节）")

    data = spec.data
    n = len(data)
    offset = 0

    if n <= spec.chunk_threshold:
        # 整体单块写
        _check_cancel(offset, n)
        write(data)
        offset = n
        if on_chunk is not None:
            on_chunk(data, offset, n)
    else:
        # 分块写
        while offset < n:
            _check_cancel(offset, n)
            end = min(offset + spec.chunk_size, n)
            chunk = data[offset:end]
            write(chunk)
            offset = end
            if on_chunk is not None:
                on_chunk(chunk, offset, n)
            if offset < n:
                sleep(spec.chunk_interval_ms / 1000.0)

    if spec.append_terminator and terminator is not None:
        _check_cancel(offset, n)
        write(terminator)
    return offset
