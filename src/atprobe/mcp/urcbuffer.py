"""M8 URC 订阅注册表：游标式环形缓冲（最近 N 条，M8 §4.4）.

每订阅独立缓冲与单调 seq；poll(sub_id, cursor) 返回 seq > cursor 的最早 limit 条。
cursor 早于缓冲最早事件 → 返回现存全部并置 truncated=true（调用方感知丢帧）。

线程模型（M8 §4.4）：
    feed() 由串口读线程回调进入；subscribe/unsubscribe/poll 由 MCP SDK 工具
    线程池线程进入。锁策略取简单方案：
    - 注册表 ``_subs`` 仅做单步 dict 操作（get / pop / 赋值），CPython 下由 GIL
      保证原子，无需注册表级锁；feed 遍历前先取 ``tuple(...)`` 快照，避免
      遍历期间并发退订触发 "dictionary changed size during iteration"。
    - 每订阅一把 ``threading.Lock``：poll 与 feed 对同一订阅互斥，保证分页
      读取期间 (seq, deque) 快照一致、页内 seq 单调无交错。
"""

from __future__ import annotations

import re
import threading
import uuid
from collections import deque
from typing import Any

from atprobe.infra.serial.interfaces import URCEvent
from atprobe.mcp.errors import invalid_input, not_found

DEFAULT_BUFFER_SIZE = 500


class _Subscription:
    """单个订阅的私有状态（id 字段保留作调试自描述，当前无消费方）."""

    def __init__(self, sub_id: str, port: str, pattern: re.Pattern[str] | None, size: int) -> None:
        self.id = sub_id
        self.port = port
        self.pattern = pattern
        # (seq, timestamp, text) 三元组；maxlen 满后自动挤掉最旧事件（环形缓冲）
        self.events: deque[tuple[int, str, str]] = deque(maxlen=size)
        self.seq = 0  # 订阅内单调递增事件序号（不回绕）
        self.lock = threading.Lock()


class UrcRegistry:
    """线程安全（feed 来自串口读线程，poll 来自 MCP 工具线程）."""

    def __init__(self, buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        self._subs: dict[str, _Subscription] = {}
        self._buffer_size = buffer_size

    def subscribe(self, port: str, pattern: str | None) -> str:
        """注册订阅，返回 sub_id；pattern 非法抛 INVALID_INPUT."""
        compiled: re.Pattern[str] | None = None
        if pattern:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise invalid_input(f"URC 过滤正则无效：{exc}", pattern=pattern) from exc
        sub_id = uuid.uuid4().hex[:12]
        self._subs[sub_id] = _Subscription(sub_id, port, compiled, self._buffer_size)
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """退订（幂等：不存在时静默返回）."""
        self._subs.pop(sub_id, None)  # 幂等

    def feed(self, event: URCEvent) -> None:
        """串口读线程回调入口：按端口与可选正则过滤后写入各订阅缓冲."""
        for sub in tuple(self._subs.values()):  # 快照遍历，并发退订安全
            if sub.port != event.port:
                continue
            if sub.pattern is not None and not sub.pattern.search(event.text.strip()):
                continue
            with sub.lock:
                sub.seq += 1
                sub.events.append((sub.seq, event.timestamp, event.text))

    def poll(self, sub_id: str, cursor: int = 0, limit: int = 100) -> dict[str, Any]:
        """按游标增量拉取；订阅不存在抛 NOT_FOUND."""
        sub = self._subs.get(sub_id)
        if sub is None:
            raise not_found(f"订阅不存在或已退订：{sub_id}")
        with sub.lock:
            items = [(s, ts, text) for (s, ts, text) in sub.events if s > cursor]
            truncated = False
            if cursor < sub.seq - len(sub.events):
                truncated = True  # 请求的游标早于缓冲最早事件（环形已丢帧）
            page = items[:limit]
            # 空页语义：无新事件时推进到当前 seq，缓冲溢出丢帧后老 cursor
            # 不会在后续 poll 反复触发 truncated
            next_cursor = page[-1][0] if page else max(cursor, sub.seq)
        return {
            "events": [{"seq": s, "timestamp": ts, "text": text} for (s, ts, text) in page],
            "next_cursor": next_cursor,
            **({"truncated": True} if truncated else {}),
        }
