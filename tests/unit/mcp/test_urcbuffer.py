"""UrcRegistry 游标语义测试（M8 §6）."""

from __future__ import annotations

import pytest

from atprobe.infra.serial.interfaces import URCEvent
from atprobe.mcp.errors import McpError
from atprobe.mcp.urcbuffer import UrcRegistry


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
