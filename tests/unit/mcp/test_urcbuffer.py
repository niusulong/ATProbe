"""UrcRegistry 游标语义测试（M8 §6）+ 订阅治理（Pf-4，设计 §4.8）."""

from __future__ import annotations

import time

import pytest

from atprobe.infra.serial.interfaces import URCEvent
from atprobe.mcp import urcbuffer as urcbuffer_mod
from atprobe.mcp.errors import McpError
from atprobe.mcp.urcbuffer import MAX_SUBSCRIPTIONS, UrcRegistry


def _ev(port: str, text: str) -> URCEvent:
    return URCEvent(port=port, text=text, timestamp="2026-08-16 00:00:00")


def test_subscribe_feed_poll_flow():
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=None)
    reg.feed(_ev("COM5", "$MYGPSPOS: 1"))
    reg.feed(_ev("COM5", "$MYGPSPOS: 2"))
    out = reg.poll(sub_id, cursor=0)
    assert [e["text"] for e in out["events"]] == ["$MYGPSPOS: 1", "$MYGPSPOS: 2"]
    assert out["next_cursor"] == 2
    assert "truncated" not in out

    # 游标推进后只取增量
    reg.feed(_ev("COM5", "$MYGPSPOS: 3"))
    out2 = reg.poll(sub_id, cursor=out["next_cursor"])
    assert [e["text"] for e in out2["events"]] == ["$MYGPSPOS: 3"]
    assert out2["next_cursor"] == 3

    # 消费尽后的空页轮询：游标不回退、不虚进
    empty = reg.poll(sub_id, cursor=out2["next_cursor"])
    assert empty["events"] == []
    assert empty["next_cursor"] == out2["next_cursor"]


def test_pattern_filters_events():
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=r"^\$MYGPSPOS")
    reg.feed(_ev("COM5", "+CEREG: 1"))
    reg.feed(_ev("COM5", "$MYGPSPOS: 1"))
    out = reg.poll(sub_id, cursor=0)
    assert [e["text"] for e in out["events"]] == ["$MYGPSPOS: 1"]


def test_other_port_not_delivered():
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=None)
    reg.feed(_ev("COM7", "+CSQ: 20,0"))
    assert reg.poll(sub_id, cursor=0)["events"] == []


def test_limit_truncates():
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=None)
    for i in range(5):
        reg.feed(_ev("COM5", f"u{i}"))
    out = reg.poll(sub_id, cursor=0, limit=2)
    assert [e["text"] for e in out["events"]] == ["u0", "u1"]
    assert out["next_cursor"] == 2
    assert "truncated" not in out


def test_ring_truncated_flag():
    reg = UrcRegistry(buffer_size=3)
    sub_id = reg.subscribe("COM5", pattern=None)
    for i in range(5):
        reg.feed(_ev("COM5", f"u{i}"))
    out = reg.poll(sub_id, cursor=0)  # cursor=0 早于缓冲最早事件
    assert out["truncated"] is True
    assert [e["text"] for e in out["events"]] == ["u2", "u3", "u4"]
    assert out["next_cursor"] == 5


def test_poll_unknown_subscription():
    reg = UrcRegistry()
    with pytest.raises(McpError) as ei:
        reg.poll("nope", cursor=0)
    assert ei.value.kind == "NOT_FOUND"


def test_unsubscribe_idempotent():
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=None)
    reg.unsubscribe(sub_id)
    reg.unsubscribe(sub_id)  # 幂等，不抛
    with pytest.raises(McpError):
        reg.poll(sub_id, cursor=0)


def test_bad_pattern_invalid_input():
    reg = UrcRegistry()
    with pytest.raises(McpError) as ei:
        reg.subscribe("COM5", pattern="[unclosed")
    assert ei.value.kind == "INVALID_INPUT"


# ---- Pf-4：订阅上限 256 + 30 分钟未轮询惰性清理（设计 §4.8） ----


def _age_sub(reg: UrcRegistry, sub_id: str, seconds: float = 2000.0) -> None:
    """把订阅的 last_poll 直接改老（绕过 poll 刷新），驱动 gc 判定."""
    reg._subs[sub_id].last_poll = time.monotonic() - seconds


def test_subscribe_limit_rejects_beyond_256():
    reg = UrcRegistry()
    ids = [reg.subscribe("COM5", pattern=None) for _ in range(MAX_SUBSCRIPTIONS)]
    with pytest.raises(McpError) as ei:
        reg.subscribe("COM5", pattern=None)
    assert ei.value.kind == "INVALID_INPUT"
    assert "上限" in str(ei.value)

    # 退订一个释放名额后可再订阅
    reg.unsubscribe(ids[0])
    extra = reg.subscribe("COM5", pattern=None)
    assert extra in reg._subs
    assert len(reg._subs) == MAX_SUBSCRIPTIONS


def test_gc_removes_stale_subscription():
    reg = UrcRegistry()
    old = reg.subscribe("COM5", pattern=None)
    fresh = reg.subscribe("COM5", pattern=None)
    _age_sub(reg, old)  # 老 2000s > 1800s
    reg.poll(fresh, cursor=0)  # poll 入口触发 gc
    assert old not in reg._subs
    with pytest.raises(McpError) as ei:
        reg.poll(old, cursor=0)  # 与退订同语义：NOT_FOUND
    assert ei.value.kind == "NOT_FOUND"


def test_gc_keeps_fresh_and_actively_polled(monkeypatch):
    """刚 subscribe 的与常 poll 的不被清；空页 poll 也算活跃（防误清）.

    fake 时钟推演：poll(active) 空页刷新其 last_poll。若刷新缺失，active
    的未轮询时长将在 gc 时超 1800s 而被清；刷新存在则存活。
    """

    class _Clock:
        now = 1000.0

        def monotonic(self) -> float:
            return self.now

    clock = _Clock()
    monkeypatch.setattr(urcbuffer_mod, "time", clock)
    reg = UrcRegistry()
    active = reg.subscribe("COM5", pattern=None)  # last_poll=1000
    clock.now = 2000.0
    reg.poll(active, cursor=0)  # 空页：无事件，但刷新 last_poll=2000
    clock.now = 3500.0  # active 距上次轮询 1500s（未刷新则为 2500s > 1800s）
    fresh = reg.subscribe("COM5", pattern=None)  # 刚 subscribe，不老
    reg.poll(fresh, cursor=0)  # 触发 gc
    assert fresh in reg._subs
    assert active in reg._subs  # 空页轮询刷新过 → 未达陈旧阈值
    assert reg.poll(active, cursor=0)["events"] == []


def test_poll_empty_page_refreshes_last_poll():
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=None)
    _age_sub(reg, sub_id, seconds=1700.0)  # 尚未陈旧（< 1800s）
    before = reg._subs[sub_id].last_poll
    reg.poll(sub_id, cursor=0)  # 空页（无事件）也刷新自己
    assert reg._subs[sub_id].last_poll > before
    other = reg.subscribe("COM5", pattern=None)
    reg.poll(other, cursor=0)  # 触发 gc
    reg.poll(sub_id, cursor=0)  # 未被清：不抛 NOT_FOUND


def test_poll_of_already_stale_subscription_not_found():
    """已陈旧（> 1800s 未轮询）的订阅：poll 入口 gc 先行 → NOT_FOUND（与退订同语义）."""
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=None)
    _age_sub(reg, sub_id)  # 老 2000s
    with pytest.raises(McpError) as ei:
        reg.poll(sub_id, cursor=0)  # 自身 poll 也会先经入口 gc 被清
    assert ei.value.kind == "NOT_FOUND"
    assert sub_id not in reg._subs


def test_feed_does_not_trigger_gc():
    reg = UrcRegistry()
    sub_id = reg.subscribe("COM5", pattern=None)
    _age_sub(reg, sub_id)
    reg.feed(_ev("COM5", "+CSQ: 20,0"))  # feed 读线程零开销：不触发 gc
    assert sub_id in reg._subs  # 老订阅仍在


def test_subscribe_gcs_before_limit_check():
    reg = UrcRegistry()
    for _ in range(MAX_SUBSCRIPTIONS):
        reg.subscribe("COM5", pattern=None)
    first = next(iter(reg._subs))
    _age_sub(reg, first)  # 满员 + 一个老订阅
    new_id = reg.subscribe("COM5", pattern=None)  # 先清出名额 → 成功
    assert new_id in reg._subs
    assert first not in reg._subs
    assert len(reg._subs) == MAX_SUBSCRIPTIONS
