"""SerialConnection URC 结构化分类专项回归测试（N58 真机驱动修复）.

背景（修复前行为，COM5 + N58 GPS 循环上报实测）：
  1. URC 丢失：旧 URC 识别用前缀正则 ^\\s*\\+[A-Z]——只认 3GPP ``+`` 前缀，
     Neoway ``$MYGPSPOS`` 等 $ 前缀厂商 URC 在等待响应期间到达时既不派发给
     订阅者（事件丢失），还被并入响应文本（污染字节级断言）。
     实测：设备发 10 条 $MYGPSPOS，订阅者仅收到 9 条。
  2. 断言污染：GPS 行与 OK 同 chunk 到达时，整段并入响应文本——
     ``^\\r\\n\\+CSQ: \\d+,\\d+\\r\\nOK\\r\\n$`` 严格断言间歇性失败（8 次中 1 次）。

修复：按「结构位置」分类（零前缀知识，见 connection.py 模块头）：
  - 空闲：所有完整非空行 = URC；
  - 等待中、终结行之后：必是主动上报——立即派发，响应文本精确切到终结行；
  - 等待中、终结行之前：双交付（文本 + 事件），结构性排除空行/终结行/回显行。

另覆盖 urc_filter（噪声剥离）：匹配行照常派发（不丢失）但从断言文本整段
剥离（含吸附紧邻空行），默认空配置零行为变化。
"""

from __future__ import annotations

import re

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


def _make_connection(monkeypatch, urc_filter: tuple[str, ...] = ()) -> SerialConnection:
    cfg = PortConfig(
        name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"), urc_filter=urc_filter
    )
    conn = SerialConnection(cfg)
    monkeypatch.setattr(conn, "_serial", _StubSerial())
    monkeypatch.setattr(conn, "_connected", True)
    return conn


_GPS = b"$MYGPSPOS: $GPGSA,A,1,,,,,,,,,,,,,25.5,25.5,25.5,1*1F"


class TestDollarPrefixUrcNotLost:
    """$ 前缀厂商 URC 不丢失（等待响应期间照常派发）."""

    def test_dollar_urc_during_await_dispatched(self, monkeypatch) -> None:
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n")

        assert received == [_GPS.decode()]

    def test_dollar_urc_before_payload_dispatched_and_kept(self, monkeypatch) -> None:
        """URC 插队在载荷之前：事件派发 + 文本保留（双交付，无法区分载荷/URC）."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        # GPS 先到，随后命令应答
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n\r\n+CSQ: 10,99\r\nOK\r\n")

        assert _GPS.decode() in received
        assert "+CSQ: 10,99" in received  # 载荷行照旧派发（原 + 前缀行为不变）
        resp = conn._response_q.get_nowait()
        assert resp.status is ResponseStatus.COMPLETE
        # 无 filter 时文本保持原样（载荷可能在其中，用户负责断言）
        assert "+CSQ: 10,99" in resp.text
        assert "OK" in resp.text


class TestPostTerminatorUrcHandling:
    """终结行之后同 chunk 到达的 URC：立即派发 + 不污染响应文本."""

    def test_urc_after_ok_same_chunk_not_in_response(self, monkeypatch) -> None:
        """实机污染场景复现：GPS 行紧跟 OK 同 chunk 到达.

        修复前：响应文本 = 整个 buffer（含 GPS 行）→ 严格断言间歇失败。
        修复后：文本精确切到 OK，GPS 行派发给订阅者。
        """
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        conn._process_incoming(b"\r\n+CSQ: 10,99\r\nOK\r\n\r\n" + _GPS + b"\r\n\r\n")

        resp = conn._response_q.get_nowait()
        assert resp.status is ResponseStatus.COMPLETE
        assert resp.text == "\r\n+CSQ: 10,99\r\nOK\r\n", "响应必须精确切到终结行"
        assert received == ["+CSQ: 10,99", _GPS.decode()], "GPS 行必须立即派发"

    def test_urc_after_ok_separate_chunk_unaffected(self, monkeypatch) -> None:
        """GPS 在响应交付之后的 chunk 到达（旧路径已正确）：行为不变."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        conn._process_incoming(b"\r\n+CSQ: 10,99\r\nOK\r\n")
        resp = conn._response_q.get_nowait()
        conn._awaiting.clear()
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n")

        assert resp.text == "\r\n+CSQ: 10,99\r\nOK\r\n"
        assert received == ["+CSQ: 10,99", _GPS.decode()]

    def test_no_loss_count_invariant(self, monkeypatch) -> None:
        """不丢一报：设备发 N 条 $ URC，订阅者必收 N 条（跨等待/交付/空闲态）."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        # 空闲期 2 条
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n")
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n")
        # 等待期（载荷前）1 条
        conn._awaiting.set()
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n")
        # 命令应答 + 同 chunk 尾随 2 条
        conn._process_incoming(b"\r\nOK\r\n\r\n" + _GPS + b"\r\n\r\n\r\n" + _GPS + b"\r\n\r\n")
        resp = conn._response_q.get_nowait()
        # 交付后再来 1 条（空闲）
        conn._awaiting.clear()
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n")

        got_gps = [u for u in received if u.startswith("$MYGPSPOS")]
        assert len(got_gps) == 6, f"6 条 URC 必须全数到达，实收 {len(got_gps)}"
        # 等待期插队的那条按双交付留在文本（可能是载荷，不能静默删）；
        # 终结行之后的 2 条只派发、不入文本
        assert resp.text.count("$MYGPSPOS") == 1
        assert resp.text.endswith("\r\nOK\r\n")


class TestEchoLineExclusion:
    """回显行不派发为 URC（结构性识别，与命令逐字相等）."""

    def test_echo_not_dispatched_but_in_text(self, monkeypatch) -> None:
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        # 模拟 send_command：awaiting + echo_line（读线程快照路径）
        conn._awaiting.set()
        with conn._buffer_lock:
            conn._echo_line = b"AT+CSQ"
        # ATE1 场景：回显 + 载荷 + 终结
        conn._process_incoming(b"\r\nAT+CSQ\r\r\n+CSQ: 10,99\r\nOK\r\n")

        assert "AT+CSQ" not in received, "回显行不是 URC"
        assert "+CSQ: 10,99" in received
        resp = conn._response_q.get_nowait()
        assert "AT+CSQ" in resp.text, "回显仍留在响应文本（与旧行为一致）"

    def test_non_echo_command_like_line_still_dispatched(self, monkeypatch) -> None:
        """与在途命令不相等的相似行（可能是 URC）仍派发——不因排除回显而误杀."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        with conn._buffer_lock:
            conn._echo_line = b"AT+CSQ"
        conn._process_incoming(b"\r\nAT+CSQX\r\nOK\r\n")

        assert "AT+CSQX" in received


class TestUrcFilterStripping:
    """urc_filter 噪声剥离：事件不丢失 + 断言文本字节级还原."""

    def _conn(self, monkeypatch):
        conn = _make_connection(monkeypatch, urc_filter=(r"^\$MYGPSPOS:",))
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))
        return conn, received

    def test_interleaved_before_payload_stripped(self, monkeypatch) -> None:
        """URC 插队在载荷之前：文本中整段剥离（含空行吸附），字节级还原."""
        conn, received = self._conn(monkeypatch)

        conn._awaiting.set()
        # 设备发射单元：\r\n LINE \r\n\r\n（吸附前后各一个空行）
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n\r\n+CSQ: 10,99\r\nOK\r\n")

        resp = conn._response_q.get_nowait()
        assert resp.text == "\r\n+CSQ: 10,99\r\nOK\r\n", "剥离后必须字节级等于无 URC 时的文本"
        assert received == [_GPS.decode(), "+CSQ: 10,99"], "事件仍全数派发"

    def test_filter_disabled_by_default(self, monkeypatch) -> None:
        """默认无 filter：文本保留插队 URC（存量行为，向后兼容）."""
        conn = _make_connection(monkeypatch)
        conn._awaiting.set()
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n\r\n+CSQ: 10,99\r\nOK\r\n")
        resp = conn._response_q.get_nowait()
        assert "$MYGPSPOS" in resp.text

    def test_timeout_partial_with_noise_stripped(self, monkeypatch) -> None:
        """超时交付（业务码模式）：噪声剥离后业务码完整、尾部 \\r\\n 语义保留."""
        conn, _ = self._conn(monkeypatch)
        conn._awaiting.set()
        # 业务码行（无 OK 终结）+ 插队噪声 URC 单元
        conn._process_incoming(b"\r\n+UPDATETIME: No PPP Link\r\n" + b"\r\n" + _GPS + b"\r\n\r\n")
        # 模拟 send_command 超时路径：快照并清缓冲（生产同款入口 snapshot_and_reset）
        with conn._buffer_lock:
            partial = conn._assembler.snapshot_and_reset()
        text = conn._strip_filtered_urcs(partial.decode("utf-8", errors="replace"))
        assert text == "\r\n+UPDATETIME: No PPP Link\r\n"
        assert text.endswith("\r\n"), "step_runner 业务码判定依赖尾部 CRLF"

    def test_half_received_noise_line_dropped(self, monkeypatch) -> None:
        """超时边界恰好切在噪声行中间（半行）：剥离后业务码判定不受影响."""
        conn, _ = self._conn(monkeypatch)
        conn._awaiting.set()
        conn._process_incoming(
            b"\r\n+UPDATETIME: No PPP Link\r\n\r\n" + _GPS[:20]
        )  # GPS 行只到一半
        with conn._buffer_lock:
            partial = conn._assembler.snapshot_and_reset()
        text = conn._strip_filtered_urcs(partial.decode("utf-8", errors="replace"))
        assert text == "\r\n+UPDATETIME: No PPP Link\r\n"

    def test_non_matching_lines_untouched(self, monkeypatch) -> None:
        """filter 只动匹配行：其它内容（含空行结构）原样保留（无前导空行时）."""
        conn, _ = self._conn(monkeypatch)
        text = "\r\n+FOO\r\n\r\n+BAR\r\nOK\r\n"
        assert conn._strip_filtered_urcs(text) == text

    def test_orphan_crlf_collapsed(self, monkeypatch) -> None:
        """孤儿 CRLF 收敛：入口清缓冲截断在途 URC 单元的行尾时残留的前导空行
        被收敛为一个（规范 AT 响应至多一个前导空行；COM5 实测 ATE0 污染）."""
        conn, _ = self._conn(monkeypatch)
        # 一个孤儿空行
        assert conn._strip_filtered_urcs("\r\n\r\nOK\r\n") == "\r\nOK\r\n"
        # 两个孤儿空行（切断点更靠前）
        assert conn._strip_filtered_urcs("\r\n\r\n\r\nOK\r\n") == "\r\nOK\r\n"
        # 载荷场景
        out = conn._strip_filtered_urcs("\r\n\r\n+CSQ: 10,99\r\nOK\r\n")
        assert out == "\r\n+CSQ: 10,99\r\nOK\r\n"
        # 正常单前导空行不受影响
        assert conn._strip_filtered_urcs("\r\nOK\r\n") == "\r\nOK\r\n"


class TestOrphanContinuationDrop:
    """入口清缓冲截断在途半行 → 续行字节级静默丢弃（残缺行不进响应/不派发）.

    场景（COM5 实测）：send_command 入口 clear() 恰好切在 GPS 单元行中间，
    '$M' 被清掉，续行 'YGPSPOS: $GPGSA,...*1F\\r\\n' 丢失前缀、不匹配
    urc_filter，旧实现直接污染响应（'YGPSPOS...\\r\\n\\r\\n\\r\\nOK\\r\\n'）。
    """

    def test_split_urc_line_dropped_at_byte_level(self, monkeypatch) -> None:
        conn = _make_connection(monkeypatch, urc_filter=(r"^\$MYGPSPOS:",))
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        # 空闲期：GPS 单元只到了前半截（无行尾）→ 留在 buffer 作 tail
        conn._process_incoming(b"\r\n$MY")  # 半行：'\r\n$MY'（无 \n）
        # 入口清缓冲（等价 send_command 开头）：半行被清、置孤儿标记
        with conn._buffer_lock:
            conn._reset_buffer_locked()
        assert conn._assembler.orphan_pending is True

        # 续行到达（补上 GPS 行剩余部分 + 尾随 CRLF），随后命令应答
        conn._awaiting.set()
        conn._process_incoming(
            b"GPSPOS: $GPGSA,A,1,,,,,,,,,,,,,25.5,25.5,25.5,1*1F\r\n\r\n\r\nOK\r\n"
        )

        resp = conn._response_q.get_nowait()
        assert resp.text == "\r\nOK\r\n", "残缺续行必须被整体丢弃，响应字节级干净"
        assert all("YGPSPOS" not in u and "GPSPOS" not in u for u in received), "残缺行不派发"

    def test_no_flag_when_buffer_ends_with_newline(self, monkeypatch) -> None:
        """缓冲以完整行结尾时清缓冲不置孤儿标记（不会误吃下一行）."""
        conn = _make_connection(monkeypatch)
        conn._process_incoming(b"\r\n+DONE: 1\r\n")  # 完整行（idle 已截断为 tail=''）
        with conn._buffer_lock:
            conn._reset_buffer_locked()
        assert conn._assembler.orphan_pending is False

    def test_orphan_spanning_multiple_chunks(self, monkeypatch) -> None:
        """续行跨多个 chunk：全部丢弃直至行尾，之后的 chunk 正常处理."""
        conn = _make_connection(monkeypatch)
        conn._process_incoming(b"\r\n$MYGP")  # 半行
        with conn._buffer_lock:
            conn._reset_buffer_locked()
        conn._awaiting.set()
        conn._process_incoming(b"SPOS: xx")  # 续行仍未结束
        conn._process_incoming(b"yy\r\n")  # 续行结束
        conn._process_incoming(b"\r\nOK\r\n")  # 命令应答
        resp = conn._response_q.get_nowait()
        assert resp.text == "\r\nOK\r\n"

    def test_stale_orphan_flag_cleared_on_empty_buffer_reset(self, monkeypatch) -> None:
        """自审 R1：孤儿标记为赋值语义——缓冲空时重置必须清位，否则 stale 标记
        吞掉下一命令响应的首个 \\n（\\r\\nOK\\r\\n 变 OK\\r\\n，严格断言必挂）.

        场景：超时收割窗口内续行未到达 → 标记残留 True；收割尾部与下条命令
        入口的清缓冲（缓冲为空）都必须把它清掉。
        """
        conn = _make_connection(monkeypatch)
        # 制造 stale：半行清缓冲置位后，模拟续行一直未来（收割期无数据）
        conn._process_incoming(b"\r\n$MY")  # idle：tail 半行留在缓冲
        with conn._buffer_lock:
            conn._reset_buffer_locked()
        assert conn._assembler.orphan_pending is True
        # 收割尾部/入口的清缓冲：缓冲空 → 赋值语义清 stale
        with conn._buffer_lock:
            conn._reset_buffer_locked()
        assert conn._assembler.orphan_pending is False
        # 下一命令响应不再被吞前缀
        conn._awaiting.set()
        conn._process_incoming(b"\r\nOK\r\n")
        resp = conn._response_q.get_nowait()
        assert resp.text == "\r\nOK\r\n"

    def test_reconnect_does_not_set_orphan(self, monkeypatch) -> None:
        """自审 R2：重连对死链半行不得置孤儿标记——新会话首行是真实数据."""
        conn = _make_connection(monkeypatch)
        conn._process_incoming(b"\r\n$MY")  # 死链半行残留在缓冲
        with conn._buffer_lock:
            conn._reset_buffer_locked()
            conn._assembler.clear_orphan()  # _maybe_reconnect 的显式覆写（生产同款入口）
        assert conn._assembler.orphan_pending is False
        # 重连后新会话首行完整保留
        conn._awaiting.set()
        conn._process_incoming(b"\r\n+CFUN: 1\r\n\r\nOK\r\n")
        resp = conn._response_q.get_nowait()
        assert "+CFUN: 1" in resp.text


class TestStaleResponseReap:
    """超时命令的迟到响应不得错投给下一条命令（收割窗口）.

    场景（COM5 实测）：poll 末次 attempt 预算钳位 0.05s，设备 ~60-90ms 才回；
    超时返回后迟到响应在下一条命令的等待窗口到达 → 被错投（下一条命令 0ms
    即回、内容是上一命令的应答）。修复：超时后保持等待态收割 150ms，静默
    消费迟到响应。
    """

    @staticmethod
    def _wait_awaiting_set(conn: SerialConnection) -> None:
        """等待 send_command 进入等待态（awaiting set）."""
        import threading

        for _ in range(400):
            if conn._awaiting.is_set():
                return
            threading.Event().wait(0.005)

    def test_late_response_not_misdelivered(self, monkeypatch) -> None:
        import threading

        conn = _make_connection(monkeypatch)

        def _feed_late() -> None:
            # 入口 set 后延时 100ms 喂：> 30ms 超时预算（迟到）、< 180ms 收割
            # 窗尾（两侧余量 70ms/80ms，覆盖 CI 负载下的线程调度抖动）
            self._wait_awaiting_set(conn)
            threading.Event().wait(0.10)
            conn._process_incoming(b"\r\n+CEREG: 0,2\r\nOK\r\n")

        # 第一次：超时命令（预算 0.03s），迟到响应在收割窗口内到达
        t = threading.Thread(target=_feed_late)
        t.start()
        r1 = conn.send_command("AT+CEREG?", timeout=0.03)
        t.join(timeout=2.0)
        assert r1.status is ResponseStatus.TIMEOUT

        # 第二次：下一条命令必须拿到自己的响应，而不是上一条的迟到响应
        def _feed_second() -> None:
            self._wait_awaiting_set(conn)
            threading.Event().wait(0.01)
            conn._process_incoming(b"\r\nOK\r\n")

        t2 = threading.Thread(target=_feed_second)
        t2.start()
        r2 = conn.send_command("ATE0", timeout=2.0)
        t2.join(timeout=2.0)
        assert r2.status is ResponseStatus.COMPLETE
        assert r2.text == "\r\nOK\r\n", "不得吃到上一条命令的迟到响应"

    def test_reap_window_consumes_and_clears(self, monkeypatch) -> None:
        """收割窗口结束后：队列空、缓冲空，下一条命令从干净状态开始."""
        import threading

        conn = _make_connection(monkeypatch)

        def _feed_late() -> None:
            self._wait_awaiting_set(conn)
            threading.Event().wait(0.10)
            conn._process_incoming(b"\r\n+CEREG: 0,2\r\nOK\r\n")

        t = threading.Thread(target=_feed_late)
        t.start()
        r1 = conn.send_command("AT+CGATT?", timeout=0.03)
        t.join(timeout=2.0)
        assert r1.status is ResponseStatus.TIMEOUT
        assert conn._response_q.empty()
        with conn._buffer_lock:
            assert len(conn._assembler.buffer) == 0


class TestWaitUrcTargetPriorityOverFilter:
    """wait_urc 优先级规则：目标行（期待响应）不被 urc_filter 剥离.

    冲突场景：全局 filter 把 $MYGPSPOS 当噪声（其余用例），GPS 用例走
    wait_urc 等待同一行作为期待响应——逐命令声明比全局声明更具体，必须胜出。
    """

    def test_target_line_kept_in_wait_urc_delivery(self, monkeypatch) -> None:
        """wait_urc 交付文本含目标行（即使 filter 匹配它）."""
        conn = _make_connection(monkeypatch, urc_filter=(r"^\$MYGPSPOS:",))
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        with conn._buffer_lock:
            conn._wait_urc_re = re.compile(rb"\$MYGPSPOS")
        conn._process_incoming(b"\r\nOK\r\n")
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n")

        resp = conn._response_q.get_nowait()
        assert resp.status is ResponseStatus.COMPLETE
        assert "$MYGPSPOS" in resp.text, "目标行是期待响应，filter 不得剥离"
        assert "OK" in resp.text

    def test_non_target_noise_still_stripped_in_wait_urc(self, monkeypatch) -> None:
        """wait_urc 等待期间插队的其它 filter 行仍被剥离（只有目标行豁免）."""
        conn = _make_connection(monkeypatch, urc_filter=(r"^\$MYGPSPOS:", r"^\+NOISE:"))
        conn._awaiting.set()
        with conn._buffer_lock:
            conn._wait_urc_re = re.compile(rb"\+TARGET: 1")
        conn._process_incoming(b"\r\nOK\r\n")
        conn._process_incoming(b"\r\n+NOISE: x\r\n\r\n")
        conn._process_incoming(b"\r\n+TARGET: 1\r\n")

        resp = conn._response_q.get_nowait()
        assert "+NOISE" not in resp.text, "非目标 filter 行照常剥离"
        assert "+TARGET: 1" in resp.text
        assert resp.text == "\r\nOK\r\n\r\n+TARGET: 1\r\n"

    def test_wait_urc_timeout_partial_keeps_target(self, monkeypatch) -> None:
        """wait_urc 超时的部分交付同样豁免目标行（超时路径传 keep_re）."""
        conn = _make_connection(monkeypatch, urc_filter=(r"^\$MYGPSPOS:",))
        conn._awaiting.set()
        with conn._buffer_lock:
            conn._wait_urc_re = re.compile(rb"\$MYGPSPOS")
        # 只到半条目标行即超时（悬置尾行）；快照并清缓冲（生产超时路径同款）
        conn._process_incoming(b"\r\nOK\r\n\r\n" + _GPS[:20])
        with conn._buffer_lock:
            partial = conn._assembler.snapshot_and_reset()
            keep_re = conn._wait_urc_re
        text = conn._strip_filtered_urcs(partial.decode("utf-8", errors="replace"), keep_re=keep_re)
        # OK 段保留 + 悬置的半条目标行保留（keep_re 豁免使其不被当噪声剥离）
        assert text.startswith("\r\nOK\r\n")
        assert "$MYGPSPOS" in text

    def test_normal_mode_unaffected_by_keep(self, monkeypatch) -> None:
        """常规模式（无 wait_urc）不传 keep_re：filter 行照常剥离."""
        conn = _make_connection(monkeypatch, urc_filter=(r"^\$MYGPSPOS:",))
        conn._awaiting.set()
        conn._process_incoming(b"\r\n" + _GPS + b"\r\n\r\n\r\n+CSQ: 10,99\r\nOK\r\n")
        resp = conn._response_q.get_nowait()
        assert "$MYGPSPOS" not in resp.text
        assert resp.text == "\r\n+CSQ: 10,99\r\nOK\r\n"


class TestWaitUrcModeWithVendorPrefix:
    """wait_urc 异步模式下的 $ 前缀与尾随行派发."""

    def test_vendor_prefix_target_and_trailing(self, monkeypatch) -> None:
        """$ 前缀目标 URC 终结等待；其后同行到达的行也派发（不丢失）."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        with conn._buffer_lock:
            conn._wait_urc_re = re.compile(rb"\+CIPOPEN: 0,0")
        conn._process_incoming(b"\r\nOK\r\n")
        conn._process_incoming(b"\r\n+CIPOPEN: 0,0\r\n\r\n" + _GPS + b"\r\n\r\n")

        resp = conn._response_q.get_nowait()
        assert resp.status is ResponseStatus.COMPLETE
        assert "+CIPOPEN: 0,0" in resp.text
        assert _GPS.decode() in received, "目标 URC 之后的厂商 URC 行也必须派发"

    def test_wait_urc_vendor_prefix_noise_kept_in_text(self, monkeypatch) -> None:
        """wait_urc 等待期间插队的 $ URC：派发 + 留在文本（双交付）."""
        conn = _make_connection(monkeypatch)
        received: list[str] = []
        conn.add_urc_handler(lambda evt: received.append(evt.text))

        conn._awaiting.set()
        with conn._buffer_lock:
            conn._wait_urc_re = re.compile(rb"\+TARGET: 1")
        conn._process_incoming(b"\r\nOK\r\n\r\n" + _GPS + b"\r\n\r\n")
        conn._process_incoming(b"\r\n+TARGET: 1\r\n")

        assert _GPS.decode() in received
        resp = conn._response_q.get_nowait()
        assert "$MYGPSPOS" in resp.text or "+TARGET" in resp.text
