"""文件发送后台 worker（QObject）—— 大文件分块发送、逐块信号、可取消.

算法同 infra/serial/datastream.py 的 send_data_stream（while 偏移切块），
但内联以获得逐块信号插桩点（chunk_sent / progress）—— send_data_stream 外壳
无逐块回调，无法驱动 GUI 进度/TX 流式上屏。

默认块大小 1024、阈值 4096、间隔 5ms（紧凑默认值，UI 不可调；设计 §2/§3）。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal

from atprobe.infra.serial.exceptions import OperationCancelled, SendError
from atprobe.infra.serial.interfaces import CancelToken

# 紧凑默认值（设计 §2/§3）：块 1024 字节、阈值 4096、间隔 5ms
_DEFAULT_CHUNK_SIZE = 1024
_DEFAULT_CHUNK_THRESHOLD = 4096
_DEFAULT_INTERVAL_MS = 5


class FileSendWorker(QObject):
    """后台分块发送文件字节到 SerialConnection。

    在 worker 线程内调用 run() 执行发送。信号跨线程安全（Qt 自动 QueuedConnection）：

        chunk_sent(bytes)   每写完一块发出，主线程据此流式上屏 TX（同 RX 渲染）
        progress(int)       0-100，按已写字节占比（分块路径每块后发一次）
        finished(bool, str) ok=True 正常完成；ok=False 含已发字节数的失败/取消消息

    connection 为 SerialConnection（或测试替身，需提供 write_bytes(bytes)）。
    """

    chunk_sent = Signal(bytes)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(
        self,
        connection: object,
        data: bytes,
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        chunk_threshold: int = _DEFAULT_CHUNK_THRESHOLD,
        interval_ms: int = _DEFAULT_INTERVAL_MS,
        cancel_token: CancelToken | None = None,
    ) -> None:
        super().__init__()
        self._conn = connection
        self._data = data
        self._chunk_size = chunk_size
        self._chunk_threshold = chunk_threshold
        self._interval_ms = interval_ms
        self._cancel = cancel_token

    def run(self) -> None:
        """执行分块发送。在 worker 线程内调用。"""
        data = self._data
        n = len(data)
        sent = 0
        try:
            if self._cancel is not None and self._cancel.cancelled:
                raise OperationCancelled("文件发送被取消")

            if n <= self._chunk_threshold:
                # 整体发送（小文件）
                self._conn.write_bytes(data)  # type: ignore[attr-defined]
                self.chunk_sent.emit(data)
                sent = n
            else:
                # 分块发送（大文件）
                offset = 0
                while offset < n:
                    if self._cancel is not None and self._cancel.cancelled:
                        raise OperationCancelled(
                            f"文件发送被取消（已发送 {offset}/{n} 字节）"
                        )
                    end = min(offset + self._chunk_size, n)
                    chunk = data[offset:end]
                    self._conn.write_bytes(chunk)  # type: ignore[attr-defined]
                    self.chunk_sent.emit(chunk)
                    offset = end
                    sent = offset
                    if n > 0:
                        self.progress.emit(int(sent * 100 / n))
                    if offset < n:
                        time.sleep(self._interval_ms / 1000.0)

            self.progress.emit(100)
            self.finished.emit(True, f"已发送 {n} 字节")
        except OperationCancelled as exc:
            self.finished.emit(False, f"已取消（已发 {sent}/{n} 字节）：{exc}")
        except SendError as exc:
            self.finished.emit(False, f"发送中断：{exc}（已发 {sent}/{n} 字节）")
