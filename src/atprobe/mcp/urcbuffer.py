"""M8 URC 订阅注册表：游标式环形缓冲（最近 N 条，M8 §6）.

每订阅独立缓冲与单调 seq；poll(sub_id, cursor) 返回 seq > cursor 的最早 limit 条。
cursor 早于缓冲最早事件 → 返回现存全部并置 truncated=true（调用方感知丢帧）。

线程模型（M8 §6）：
    feed() 由串口读线程回调进入；subscribe/unsubscribe/poll 由 MCP SDK 工具
    线程池线程进入。锁策略取简单方案：
    - 注册表 ``_subs`` 仅做单步 dict 操作（get / pop / 赋值），CPython 下由 GIL
      保证原子，无需注册表级锁；feed 遍历前先取 ``tuple(...)`` 快照，避免
      遍历期间并发退订触发 "dictionary changed size during iteration"。
    - 每订阅一把 ``threading.Lock``：poll 与 feed 对同一订阅互斥，保证分页
      读取期间 (seq, deque) 快照一致、页内 seq 单调无交错。
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import deque
from typing import Any

from atprobe.domain.case.redos import check_pattern
from atprobe.infra.serial.interfaces import URCEvent
from atprobe.mcp.errors import invalid_input, not_found

_log = logging.getLogger("atprobe.mcp")

DEFAULT_BUFFER_SIZE = 500
# 订阅数上限（Pf-4，设计 §4.8）：LLM 循环 subscribe 不退订是常见模式，注册表
# 只增不减会让 feed() 快照遍历越来越长；超限拒绝并提示先 unsubscribe。
MAX_SUBSCRIPTIONS = 256
# 超过该秒数未 poll 的订阅视为陈旧，可被惰性清理（30 分钟）。
STALE_SUBSCRIPTION_S = 1800.0


class _Subscription:
    """单个订阅的私有状态（订阅身份由注册表 ``_subs`` 的 dict 键 sid 承载）."""

    def __init__(self, port: str, pattern: re.Pattern[str] | None, size: int) -> None:
        self.port = port
        self.pattern = pattern
        # (seq, timestamp, text) 三元组；maxlen 满后自动挤掉最旧事件（环形缓冲）
        self.events: deque[tuple[int, str, str]] = deque(maxlen=size)
        self.seq = 0  # 订阅内单调递增事件序号（不回绕）
        self.lock = threading.Lock()
        # 最近一次 poll 的单调时钟：subscribe 时初始化，poll 时刷新（含空页）
        self.last_poll: float = time.monotonic()


class UrcRegistry:
    """线程安全（feed 来自串口读线程，poll 来自 MCP 工具线程）."""

    def __init__(self, buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        self._subs: dict[str, _Subscription] = {}
        self._buffer_size = buffer_size

    def _gc_stale(self) -> None:
        """惰性清理超时未轮询的订阅（subscribe/poll 入口调用，feed 不调用）.

        被清理订阅后续 poll 得 NOT_FOUND——与显式退订同语义。仅删 ``_subs``
        条目；PortManager 层按端口开启的 URC 转发不受影响（转发随 close_port
        拆除）。纯 dict 操作，GIL 原子性同既有锁策略；遍历前取 ``tuple``
        快照，避免并发 subscribe/unsubscribe 触发迭代期间字典变更。
        """
        now = time.monotonic()
        stale = [
            sid
            for sid, sub in tuple(self._subs.items())
            if now - sub.last_poll > STALE_SUBSCRIPTION_S
        ]
        for sid in stale:
            self._subs.pop(sid, None)

    def subscribe(self, port: str, pattern: str | None) -> str:
        """注册订阅，返回 sub_id；pattern 非法或超订阅上限抛 INVALID_INPUT."""
        compiled: re.Pattern[str] | None = None
        if pattern:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise invalid_input(f"URC 过滤正则无效：{exc}", pattern=pattern) from exc
            # S-2（设计 §5）：feed 在串口读线程对每行 URC 逐订阅匹配，嵌套量词
            # 会被噪声持续触发灾难性回溯卡死读线程——硬拒；重叠交替类仅告警。
            hard, warnings = check_pattern(pattern)
            if hard is not None:
                raise invalid_input(f"URC 过滤正则存在灾难性回溯风险：{hard}", pattern=pattern)
            for w in warnings:
                _log.warning("URC 过滤正则 %r 存在回溯风险：%s", pattern, w)
        self._gc_stale()  # 先清理再查上限：惰性清出的名额可用
        if len(self._subs) >= MAX_SUBSCRIPTIONS:
            raise invalid_input(f"URC 订阅数超上限（{MAX_SUBSCRIPTIONS}），请先 unsubscribe 释放")
        sub_id = uuid.uuid4().hex[:12]
        self._subs[sub_id] = _Subscription(port, compiled, self._buffer_size)
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """退订（幂等：不存在时静默返回）."""
        self._subs.pop(sub_id, None)  # 幂等

    def feed(self, event: URCEvent) -> None:
        """串口读线程回调入口：按端口与可选正则过滤后写入各订阅缓冲.

        pattern 对剥离首尾空白后的文本 search（容忍行尾 CRLF 与行首空白）。
        """
        stripped = event.text.strip()
        for sub in tuple(self._subs.values()):  # 快照遍历，并发退订安全
            if sub.port != event.port:
                continue
            if sub.pattern is not None and not sub.pattern.search(stripped):
                continue
            with sub.lock:
                sub.seq += 1
                sub.events.append((sub.seq, event.timestamp, event.text))

    def poll(self, sub_id: str, cursor: int = 0, limit: int = 100) -> dict[str, Any]:
        """按游标增量拉取；订阅不存在抛 NOT_FOUND."""
        self._gc_stale()
        sub = self._subs.get(sub_id)
        if sub is None:
            raise not_found(f"订阅不存在或已退订：{sub_id}")
        with sub.lock:
            items = [(s, ts, text) for (s, ts, text) in sub.events if s > cursor]
            truncated = False
            if cursor < sub.seq - len(sub.events):
                truncated = True  # 请求的游标早于缓冲最早事件（环形已丢帧）
            page = items[:limit]
            # 空页：无新事件可推进，游标保持调用值不变（调用方下次再轮询）
            next_cursor = page[-1][0] if page else cursor
            # 空页也算"轮询过"：刷新活跃时间戳，防活跃订阅被惰性清理
            sub.last_poll = time.monotonic()
        return {
            "events": [{"seq": s, "timestamp": ts, "text": text} for (s, ts, text) in page],
            "next_cursor": next_cursor,
            **({"truncated": True} if truncated else {}),
        }
