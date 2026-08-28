"""RX/TX 流式控制台共享组件（Pf-1）—— 任意线程写入、主线程定时批量渲染.

从 monitor 的行缓冲泛化而来：条目 ``(direction, timestamp, text)``；写侧只入
缓冲（快），渲染集中到主线程 QTimer 每 200ms 一次批量上屏——高波特率持续流
不再每 chunk 富文本 append（旧 manual_debug 的卡顿根因）。

上屏方式是宿主 widget 的事：构造时注入渲染回调 ``renderer(items)``（monitor
注入 HTML 批量渲染、manual_debug 注入逐行仪器屏渲染），组件只管缓冲与节流。
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Sequence

from PySide6.QtCore import QTimer

_log = logging.getLogger("atprobe.gui.rx_console")

# 条目：(direction, timestamp, text) —— 与 monitor 历史缓冲元组格式一致
ConsoleItem = tuple[str, str, str]

# 批量渲染间隔（ms）：与 monitor 历史 200ms 节流一致（视觉无延迟感 + 低开销）
_DEFAULT_INTERVAL_MS = 200
# 待渲染条目上限兜底：921600bps ≈ 92KB/s → 200ms 窗口约 18KB，按短行折算数千条；
# 5000 条防渲染端持续滞后时的无界增长（渲染端 QTextDocument 块上限另兜底总行数）
_DEFAULT_MAX_PENDING = 5000


class RxConsole:
    """RX/TX 流式控制台（Pf-1）：写侧任意线程 append，主线程 200ms 批量渲染。

    泛化 monitor 的行缓冲：条目 ``(direction, timestamp, text)``；flush 一次性把
    缓冲交给渲染回调（由宿主 widget 注入——如何上屏是宿主的事）。

    线程边界：append 仅在锁内 deque.append（任意线程安全）；flush 在主线程
    QTimer 回调（或宿主显式调用），drain 后调 ``renderer(items)``（锁外回调，
    渲染耗时/异常不阻塞写侧）。

    ``max_pending`` 上限防高波特率无界增长：超出**丢最旧**并计数
    （``dropped_count`` 累计）——行为注记：宁可丢最旧保新数据，不给滞后的渲染
    队列无限累积内存；总上屏行数由宿主 QTextDocument 块上限兜底。
    """

    def __init__(
        self,
        renderer: Callable[[Sequence[ConsoleItem]], None],
        *,
        interval_ms: int = _DEFAULT_INTERVAL_MS,
        max_pending: int = _DEFAULT_MAX_PENDING,
    ) -> None:
        self._renderer = renderer
        self._interval_ms = interval_ms
        self._max_pending = max_pending
        self._lock = threading.Lock()
        self._pending: deque[ConsoleItem] = deque()
        # QTimer 懒创建：构造不依赖 QApplication/QThread（纯逻辑测试可直接
        # append/flush），start() 才在主线程建定时器
        self._timer: QTimer | None = None
        self.dropped_count = 0  # 上限触发丢最旧的累计条数（诊断/测试用）
        self._dropped_reported = 0  # 已随 flush 记过日志的条数（算本批增量用）

    # ------------------------------------------------------------------
    # 写侧（任意线程）
    # ------------------------------------------------------------------
    def append(self, direction: str, text: str, timestamp: str = "") -> None:
        """写入一条（任意线程）。缓冲满时丢最旧并计数。"""
        with self._lock:
            if len(self._pending) >= self._max_pending:
                self._pending.popleft()
                self.dropped_count += 1
            self._pending.append((direction, timestamp, text))

    # ------------------------------------------------------------------
    # 渲染侧（主线程）
    # ------------------------------------------------------------------
    def flush(self) -> None:
        """排空缓冲交给 renderer（主线程；未 start 时宿主显式调用同样有效）。"""
        with self._lock:
            if not self._pending:
                return
            items: list[ConsoleItem] = list(self._pending)
            self._pending.clear()
            dropped = self.dropped_count - self._dropped_reported
            self._dropped_reported = self.dropped_count
        if dropped:
            _log.warning("RxConsole 渲染滞后，本批丢弃最旧 %d 条", dropped)
        self._renderer(items)

    def clear(self) -> None:
        """清空未渲染缓冲（不调 renderer）——宿主清屏时用。"""
        with self._lock:
            self._pending.clear()

    # ------------------------------------------------------------------
    # QTimer 生命周期（主线程）
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动批量渲染定时器（主线程调用；幂等）。"""
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setInterval(self._interval_ms)
            self._timer.timeout.connect(self.flush)
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """停止定时器并冲刷残余（主线程调用；空缓冲不调 renderer）。"""
        if self._timer is not None:
            self._timer.stop()
        self.flush()

    def is_running(self) -> bool:
        """定时器是否在跑（宿主懒启动守卫用）。"""
        return self._timer is not None and self._timer.isActive()

    @property
    def pending_count(self) -> int:
        """当前未渲染条数（测试/诊断用）。"""
        with self._lock:
            return len(self._pending)
