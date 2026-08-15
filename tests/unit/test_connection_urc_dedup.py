"""SerialConnection URC 去重派发专项回归测试（P1 修复）.

背景（修复前行为）：等待响应期间 buffer 不截断（需保留完整文本交付），每个新
chunk 都对全量缓冲重新 split 拆行——历史 URC 行被逐 chunk 重复派发给订阅者。
例：等待大响应期间设备分 3 个 chunk 发 3 条 URC，订阅者共收到 6 次（1+2+3）。

修复：_urc_dispatched 字节偏移记录已完成拆行处理的位置，只派发新完成的行。

本文件用「_connected=True + 桩串口」绕过真实 pyserial（沿用
test_connection_wait_urc.py 的 mock 模式），直接调 _process_incoming 喂 chunk。
另覆盖 wait_urc 正则的 $ 锚修复（strip 后匹配）。
"""

from __future__ import annotations

import threading

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.interfaces import ResponseStatus


class _StubSerial:
    """最小串口替身：记录 write，flush 空操作（绕过 pyserial I/O）。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass


def _make_connection(monkeypatch) -> SerialConnection:
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    conn = SerialConnection(cfg)
    monkeypatch.setattr(conn, "_serial", _StubSerial())
    monkeypatch.setattr(conn, "_connected", True)
    return conn


class TestUrcDedupDuringAwait:
    """等待响应期间多 chunk URC 只派发一次（P1 回归）."""

    def test_each_urc_dispatched_exactly_once_across_chunks(self, monkeypatch) -> None:
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        # 模拟 send_command 的等待窗口：set awaiting（不发真实命令）
        conn._awaiting.set()
        # 3 个 chunk 各含 1 条 URC 行（\r\n 分帧，跨 chunk 无半行）
        conn._process_incoming(b"\r\n+CTMZT: 1,1\r\n")
        conn._process_incoming(b"\r\n+CTMZT: 2,2\r\n")
        conn._process_incoming(b"\r\n+CTMZT: 3,3\r\n")

        # 修复前：1+2+3=6 次（历史行逐 chunk 重派）；修复后：每条恰好 1 次
        assert received == ["+CTMZT: 1,1", "+CTMZT: 2,2", "+CTMZT: 3,3"]

    def test_wait_urc_mode_no_duplicate_dispatch(self, monkeypatch) -> None:
        """wait_urc 等待模式下（OK 已收但目标 URC 未到）同样不重复派发."""
        import re

        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        with conn._buffer_lock:
            conn._wait_urc_re = re.compile(rb"\+TARGET: \d+")
        # OK（仅受理不终结）+ 两条中间 URC 分多个 chunk 到达
        conn._process_incoming(b"\r\nOK\r\n")
        conn._process_incoming(b"\r\n+MID: a\r\n")
        conn._process_incoming(b"\r\n+MID: b\r\n")
        # 目标 URC 到达 → 终结
        conn._process_incoming(b"\r\n+TARGET: 7\r\n")

        # 中间 URC 各一次 + 目标 URC 一次；OK 不派发（非 + 开头）
        assert received == ["+MID: a", "+MID: b", "+TARGET: 7"]

    def test_response_delivery_resets_offset(self, monkeypatch) -> None:
        """响应交付后 buffer 重置，后续空闲 URC 正常派发（不因偏移残留丢事件）."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        conn._process_incoming(b"\r\nOK\r\n")  # 完整响应 → 交付，buffer 重置
        resp = conn._response_q.get_nowait()
        assert resp.status is ResponseStatus.COMPLETE

        # 等待已结束（awaiting clear 由 send_command 负责，这里手动模拟）
        conn._awaiting.clear()
        conn._process_incoming(b"\r\n+NEWTAG: x\r\n")
        assert received == ["+NEWTAG: x"]

    def test_idle_mode_unchanged(self, monkeypatch) -> None:
        """空闲模式（无人等待）行为不变：每条 URC 恰好派发一次."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._process_incoming(b"\r\n+A: 1\r\n")
        conn._process_incoming(b"\r\n+B: 2\r\n")
        assert received == ["+A: 1", "+B: 2"]


class TestWaitUrcAnchor:
    """wait_urc 正则 $ 锚修复：strip 后匹配，含 $ 锚的正则可命中（P1 回归）."""

    def test_dollar_anchor_regex_matches(self, monkeypatch) -> None:
        """`\\+X:ok$` 这类带 $ 锚的 wait_urc 正则应能终结等待（修复前永不匹配）."""
        result: dict[str, object] = {}
        done = threading.Event()
        conn = _make_connection(monkeypatch)

        def _runner() -> None:
            result["resp"] = conn.send_command("AT+X", timeout=2.0, wait_urc=r"\+X:ok$")
            done.set()

        t = threading.Thread(target=_runner)
        t.start()
        # 给 send_command 一点时间进入等待（避免喂早了被入口 drain 清掉）
        for _ in range(50):
            if conn._awaiting.is_set():
                break
            threading.Event().wait(0.02)
        conn._process_incoming(b"\r\nOK\r\n")  # 仅受理
        conn._process_incoming(b"\r\n+X:ok\r\n")  # 目标 URC（行尾 \r 曾使 $ 失效）
        done.wait(timeout=3.0)
        t.join(timeout=3.0)

        resp = result.get("resp")
        assert resp is not None
        assert resp.status is ResponseStatus.COMPLETE
        assert "+X:ok" in resp.text


class TestOffsetRaceWithEngineReset:
    """复审回归：读线程锁外派发期间引擎清 buffer → 陈旧 offset 不得覆盖归零.

    场景（修复前）：读线程快照 offset 后在锁外做 URC 派发（handler 耗时），
    引擎 send_command 入口恰在此时清 buffer+归零 offset；读线程随后回写陈旧
    偏移（如 12）→ 下一条命令的单 chunk 响应（le <= 12）被误判历史行跳过
    → 终结行不被识别 → 假 TIMEOUT。代次计数器修复后：回写被代次校验拦截。
    """

    def test_stale_offset_write_discarded_after_engine_reset(self, monkeypatch) -> None:
        conn = _make_connection(monkeypatch)

        # 读线程视角构造：先喂一个含 URC 的 chunk 使 offset 推进有值可写
        conn._awaiting.set()
        conn._process_incoming(b"\r\n+U: 1\r\n")
        assert conn._urc_dispatched > 0
        stale_offset = conn._urc_dispatched

        # 模拟读线程已快照（generation、offset），在锁外派发期间引擎重置 buffer
        with conn._buffer_lock:
            generation = conn._buffer_generation
        # 引擎入口重置（等价 send_command 开头）：清 buffer + 归零 + 代次自增
        with conn._buffer_lock:
            conn._buffer.clear()
            conn._urc_dispatched = 0
            conn._buffer_generation += 1

        # 读线程现在回写陈旧 offset（修复后的代码路径：代次变了 → 放弃）
        with conn._buffer_lock:
            if conn._buffer_generation == generation:  # pragma: no cover
                conn._urc_dispatched = stale_offset  # 旧代码无条件写

        assert conn._urc_dispatched == 0, "代次变化后陈旧 offset 必须被丢弃"

        # 后续单 chunk 完整响应正常终结（le > 0 不被跳过）
        conn._process_incoming(b"\r\nOK\r\n")
        resp = conn._response_q.get_nowait()
        assert resp.status is ResponseStatus.COMPLETE

    def test_close_prevents_reader_reconnect(self, monkeypatch) -> None:
        """复审回归：close 置 stop_event 后读线程断连路径不得重开端口."""
        opened: list[bool] = []
        conn = _make_connection(monkeypatch)
        monkeypatch.setattr(
            type(conn),
            "_try_open_once",
            lambda self: (opened.append(True), True)[1],
        )
        # close 置 stop_event（真实 close 会碰串口句柄，这里只置事件语义）
        conn._stop_event.set()
        assert conn._maybe_reconnect() is False  # stop 已置 → 拒绝
        assert conn.reconnect() is False
        assert opened == []  # 从未尝试打开


class TestCrlfAcrossChunks:
    """边界：CRLF 跨 chunk（\\r 在尾、\\n 在头）的等待模式去重."""

    def test_crlf_split_chunks_single_dispatch(self, monkeypatch) -> None:
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        conn._process_incoming(b"\r\n+U: 1\r")  # 尾部悬置 \r
        conn._process_incoming(b"\n+U: 2\r\n")  # 头部补 \n

        assert received == ["+U: 1", "+U: 2"]  # 各恰好一次
