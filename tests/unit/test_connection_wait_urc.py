"""SerialConnection.wait_urc 异步指令 URC 终结逻辑专项测试.

验证 connection.py 核心行为：
    - wait_urc 启用：遇 OK 不终结，继续读到匹配 URC 立即返回（整段 text 含 OK+URC）
    - 不空等：URC 一到立即返回，不等满 timeout
    - URC 超时：timeout 内无 URC → status=TIMEOUT，text 含已收 OK 段
    - 默认模式（wait_urc=None）不回归：OK 即终结
    - OK 与 URC 跨 chunk 送达（异步典型场景）

用「_connected=True + 桩串口」绕过真实 pyserial（沿用 test_write_bytes.py 的 mock 模式）。
直接调 _process_incoming(chunk) 模拟读线程喂入字节（该方法是同步的）。
send_command 在子线程等待 _response_q，主线程按节奏喂 chunk。
"""

from __future__ import annotations

import threading
import time

import pytest

from atprobe.infra.serial.config import DataStreamSpec, FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import InvalidArgumentError, SerialError
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
    """构造已连接、底层为 _StubSerial 的 SerialConnection（不真开 pyserial）。"""
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    conn = SerialConnection(cfg)
    stub = _StubSerial()
    monkeypatch.setattr(conn, "_serial", stub)
    monkeypatch.setattr(conn, "_connected", True)
    # 用真实的 time.monotonic / time.sleep（测试需要真实时间控制空等判定）
    return conn


def _send_and_feed(
    conn: SerialConnection,
    command: str,
    chunks: list[bytes],
    *,
    timeout: float = 5.0,
    wait_urc: str | None = None,
    expect: str | None = None,
    feed_delay: float = 0.0,
) -> object:
    """子线程跑 send_command，主线程按节奏喂 chunk（模拟读线程）。

    chunks: 依次调用 _process_incoming 喂入的字节块。
    feed_delay: 每个 chunk 之间的间隔（秒），用于测试「不空等」（URC 到了立即返回）。
    """
    result: dict[str, object] = {}
    exc: list[Exception] = []

    def _runner() -> None:
        try:
            resp = conn.send_command(command, timeout=timeout, wait_urc=wait_urc, expect=expect)
            result["resp"] = resp
            result["done"] = threading.Event()
        except Exception as e:  # noqa: BLE001
            exc.append(e)

    done = threading.Event()
    t = threading.Thread(
        target=lambda: (
            result.update(
                {
                    "resp": conn.send_command(
                        command, timeout=timeout, wait_urc=wait_urc, expect=expect
                    )
                }
            ),
            done.set(),
        )
    )
    t.daemon = True
    t.start()

    # 给 send_command 一点时间进入等待状态（设置 _awaiting）
    time.sleep(0.05)

    for ch in chunks:
        conn._process_incoming(ch)  # noqa: SLF001 - 模拟读线程喂字节
        if feed_delay:
            time.sleep(feed_delay)

    # 等待 send_command 返回（URC 到了应立即返回；超时则等满 timeout）
    done.wait(timeout=timeout + 2.0)
    t.join(timeout=timeout + 2.0)

    if exc:
        raise exc[0]
    return result.get("resp")


class TestWaitUrcTermination:
    def test_urc_after_ok_completes_with_full_text(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """OK 与目标 URC 分属不同 chunk（异步典型）：整段 text 含 OK+URC，status=COMPLETE。"""
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+CTM2MDEREG",
            chunks=[b"\r\nOK\r\n", b"\r\n+CTM2M:dereg,0,5\r\n"],
            timeout=3.0,
            wait_urc=r"\+CTM2M:dereg,0,\d+",
        )
        assert resp.status is ResponseStatus.COMPLETE
        assert "+CTM2M:dereg,0,5" in resp.text
        assert "OK" in resp.text

    def test_urc_returns_immediately_not_waiting_full_timeout(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """不空等：URC 到达立即返回，耗时应远小于 timeout。"""
        conn = _make_connection(monkeypatch)
        t0 = time.monotonic()
        resp = _send_and_feed(
            conn,
            "AT+X",
            chunks=[b"\r\nOK\r\n", b"\r\n+X:done\r\n"],
            timeout=5.0,
            wait_urc=r"\+X:done",
            feed_delay=0.1,  # 第二个 chunk 延迟 0.1s 后喂入
        )
        elapsed = time.monotonic() - t0
        assert resp.status is ResponseStatus.COMPLETE
        # URC 在 ~0.1s+0.05s 后到达即返回，远小于 5s timeout
        assert elapsed < 2.0, f"应立即返回，实际耗时 {elapsed:.2f}s（疑似空等到 timeout）"

    def test_ok_and_urc_same_chunk(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """OK 与 URC 同一 chunk 送达：也能正确终结，text 含两者。"""
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+X",
            chunks=[b"\r\nOK\r\n\r\n+X:ok\r\n"],
            timeout=3.0,
            wait_urc=r"\+X:ok",
        )
        assert resp.status is ResponseStatus.COMPLETE
        assert "OK" in resp.text
        assert "+X:ok" in resp.text

    def test_timeout_without_urc_returns_timeout_with_ok(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """timeout 内只收到 OK、无目标 URC → status=TIMEOUT，text 含 OK 段。"""
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+X",
            chunks=[b"\r\nOK\r\n"],  # 只有 OK，永远没有 URC
            timeout=0.4,
            wait_urc=r"\+X:never",
        )
        assert resp.status is ResponseStatus.TIMEOUT
        assert "OK" in resp.text  # 已收到的 OK 段保留在 text
        assert resp.error == "等待 URC 超时"

    def test_response_line_then_ok_then_urc(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """数据行 + OK + URC 组合（如 +CTM2MSEND:<id> / OK / +CTM2M:send,0,<id>）。"""
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+CTM2MSEND",
            chunks=[b"\r\n+CTM2MSEND:5\r\nOK\r\n", b"\r\n+CTM2M:send,0,5\r\n"],
            timeout=3.0,
            wait_urc=r"\+CTM2M:send,0,\d+",
        )
        assert resp.status is ResponseStatus.COMPLETE
        assert "+CTM2MSEND:5" in resp.text
        assert "OK" in resp.text
        assert "+CTM2M:send,0,5" in resp.text

    def test_unrelated_urc_does_not_terminate(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """无关 URC 不触发终结（方案 B 精准匹配），继续等目标 URC。"""
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+X",
            chunks=[
                b"\r\nOK\r\n",
                b"\r\n+OTHER:event\r\n",  # 无关 URC，不应终结
                b"\r\n+X:target\r\n",  # 目标 URC，才终结
            ],
            timeout=3.0,
            wait_urc=r"\+X:target",
        )
        assert resp.status is ResponseStatus.COMPLETE
        assert "+X:target" in resp.text
        assert "+OTHER:event" in resp.text  # 无关 URC 也进了 text（累积）


class TestWaitUrcDefaultBehavior:
    """wait_urc=None（默认）保持原行为：OK 即终结，不回归。"""

    def test_default_ok_terminates(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+CSQ",
            chunks=[b"\r\n+CSQ: 23,0\r\nOK\r\n"],
            timeout=3.0,
            wait_urc=None,
        )
        assert resp.status is ResponseStatus.COMPLETE
        assert "+CSQ: 23,0" in resp.text
        assert "OK" in resp.text

    def test_state_reset_after_command(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """wait_urc 状态在命令结束后复位，不污染下一条命令（默认模式正常）。"""
        conn = _make_connection(monkeypatch)
        # 第一条：wait_urc 模式
        resp1 = _send_and_feed(
            conn,
            "AT+X",
            chunks=[b"\r\nOK\r\n", b"\r\n+X:ok\r\n"],
            timeout=3.0,
            wait_urc=r"\+X:ok",
        )
        assert resp1.status is ResponseStatus.COMPLETE
        # 状态应已复位
        assert conn._wait_urc_re is None  # noqa: SLF001
        # 第二条：默认模式（OK 即终结），不应受前一条 wait_urc 影响
        resp2 = _send_and_feed(
            conn,
            "AT+CSQ",
            chunks=[b"\r\nOK\r\n"],
            timeout=3.0,
            wait_urc=None,
        )
        assert resp2.status is ResponseStatus.COMPLETE

    def test_send_failure_resets_wait_urc_state(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """wait_urc 模式下发送失败（write 抛 OSError），_wait_urc_re 必须复位。

        覆盖 send_command 的 except 分支：若发送失败不复位 wait_urc 状态，
        _wait_urc_re 会残留，污染下一条命令（下条命令误走 wait_urc 分支）。
        """

        conn = _make_connection(monkeypatch)

        # 让 write 抛 OSError（模拟发送失败）
        def _raise(_data: bytes) -> None:
            raise OSError("发送失败")

        monkeypatch.setattr(conn._serial, "write", _raise)  # noqa: SLF001

        resp = conn.send_command("AT+X", timeout=2.0, wait_urc=r"\+X:ok")

        assert resp.status is ResponseStatus.ERROR
        # 关键：发送失败路径必须复位 wait_urc 状态
        assert conn._wait_urc_re is None, "发送失败后 _wait_urc_re 未复位，会污染下条命令"  # noqa: SLF001


class TestExpectCompletion:
    """send_command(expect=) 附加完成条件（设计 §2.3，批 2a Task 5 连接层接线）.

    expect 的字节级检测在 LineAssembler（2a-T3）已实现，本组锁定连接层入口：
    expect 参数从 send_command 接到 _expect_re，命中即 COMPLETE、优先于终结行，
    周期结束复位。
    """

    def test_expect_prompt_without_newline_completes(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """TCPSEND 提示符场景：expect 命中无换行的 \\r\\n> 即 COMPLETE。

        不依赖换行、不等终结行、不等超时——纯字节级匹配（设计 §2.3 推荐精确
        写法 '\\r\\n>'）。
        """
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+TCPSEND=0,5",
            chunks=[b"\r\n>"],  # 无换行：终结行判定永远不触发
            timeout=3.0,
            expect=r"\r\n>",
        )
        assert resp.status is ResponseStatus.COMPLETE
        assert "\r\n>" in resp.text
        # 周期结束状态复位（不污染下一条命令）
        assert conn._expect_re is None  # noqa: SLF001

    def test_expect_priority_over_terminator(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """expect 与终结行同 chunk：expect 优先，交付截至命中点（不含其后的 OK）。"""
        conn = _make_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+TCPSEND=0,5",
            chunks=[b"\r\n> \r\nOK\r\n"],
            timeout=3.0,
            expect=r"\r\n>",
        )
        assert resp.status is ResponseStatus.COMPLETE
        assert "\r\n>" in resp.text
        assert "OK" not in resp.text  # 命中点之后的字节属余量，不进本次响应

    def test_wait_urc_error_immediately_completes(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """wait_urc 模式收到 ERROR 立即 COMPLETE（设计 §2.1 行为变更）。

        锁定量变更，实现于 2a-T3/T4（LineAssembler._ERROR_RE 任何等待模式终结），
        本用例在连接层锁定：不再等目标 URC 到超时，text 含已收 OK 段。
        """
        conn = _make_connection(monkeypatch)
        t0 = time.monotonic()
        resp = _send_and_feed(
            conn,
            "AT+X",
            chunks=[b"\r\nOK\r\n\r\nERROR\r\n"],
            timeout=5.0,
            wait_urc=r"\+X: ok",
        )
        elapsed = time.monotonic() - t0
        assert resp.status is ResponseStatus.COMPLETE
        assert "OK" in resp.text
        assert "ERROR" in resp.text
        assert elapsed < 2.0, f"应立即终结，实际耗时 {elapsed:.2f}s（疑似等到超时）"


class TestExpectValidation:
    """入口校验：expect × wait_urc 互斥、expect 正则编译失败转 SerialError（解析期口径）."""

    def test_expect_wait_urc_mutex_rejected(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """两者同传（均为自定义完成语义）→ SerialError；且通道状态零污染、锁已释放。"""
        conn = _make_connection(monkeypatch)
        with pytest.raises(SerialError, match="互斥"):
            conn.send_command("AT+X", timeout=1.0, wait_urc=r"\+X:ok", expect=r"\r\n>")
        # 校验在置等待态之前抛出：等待态/expect 状态零污染
        assert not conn._awaiting.is_set()  # noqa: SLF001
        assert conn._expect_re is None  # noqa: SLF001
        # 命令锁必须已释放（acquire→try→校验抛错→finally release 平衡）：
        # 校验抛错后立即再发一条常规命令应正常完成，而非 PortBusyError
        resp = _send_and_feed(conn, "AT+X", chunks=[b"\r\nOK\r\n"], timeout=3.0)
        assert resp.status is ResponseStatus.COMPLETE

    def test_invalid_expect_regex_rejected(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """expect="("（非法正则）→ SerialError 带「正则无效」上下文。"""
        conn = _make_connection(monkeypatch)
        with pytest.raises(SerialError, match="正则无效"):
            conn.send_command("AT+X", timeout=1.0, expect="(")


class TestInvalidArgumentErrorTyping:
    """入口参数错误类型化（InvalidArgumentError，SerialError 子类，批 3 T1）.

    _compile_cycle_params 为 send_command/send_data 共用——两个入口的互斥与
    正则错误均抛 InvalidArgumentError；MCP 层据此区分 INVALID_INPUT 而非
    DEVICE_ERROR（批 3 T9 接线）。既有 pytest.raises(SerialError) 用例不受
    影响（子类兼容）。
    """

    def test_is_subclass_of_serial_error(self) -> None:
        assert issubclass(InvalidArgumentError, SerialError)

    def test_mutex_raises_invalid_argument_error(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_connection(monkeypatch)
        with pytest.raises(InvalidArgumentError, match="互斥") as ei:
            conn.send_command("AT+X", timeout=1.0, wait_urc=r"\+X:ok", expect=r"\r\n>")
        assert isinstance(ei.value, SerialError)

    def test_invalid_regex_raises_invalid_argument_error(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_connection(monkeypatch)
        with pytest.raises(InvalidArgumentError, match="正则无效"):
            conn.send_command("AT+X", timeout=1.0, expect="(")

    def test_send_data_mutex_raises_invalid_argument_error(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """send_data 共用 _compile_cycle_params——数据入口同样类型化。"""
        conn = _make_connection(monkeypatch)
        with pytest.raises(InvalidArgumentError, match="互斥"):
            conn.send_data(DataStreamSpec(data=b"x"), wait_urc=r"\+X:ok", expect=r"\r\n>")


class TestExpectTimeoutKeepReExemption:
    """expect 等待周期超时：匹配 expect 的行豁免 urc_filter 剥离（批 3 T1）.

    与 wait_urc 对称——expect 匹配的是本周期显式声明的期待内容，比全局噪声
    声明更具体。特征构造：expect 用 ``$`` 锚点实现「行级命中、字节流未命中」
    ——expect 检测（LineAssembler）作用于原始 RX 字节（行尾 \\r 仍在，
    ``\\d+$`` 不中）→ 等到超时；剥离豁免（_strip_filtered_urcs）作用于
    strip 后的行（``$MYX: 1`` 命中 ``\\$MYX: \\d+$``）→ 不被 urc_filter 剥。
    """

    def _make_filtered_connection(self, monkeypatch) -> SerialConnection:  # type: ignore[no-untyped-def]
        cfg = PortConfig(
            name="COM9",
            baudrate=115200,
            frame=FrameFormat.parse("8N1"),
            urc_filter=(r"\$MY",),
        )
        conn = SerialConnection(cfg)
        monkeypatch.setattr(conn, "_serial", _StubSerial())
        monkeypatch.setattr(conn, "_connected", True)
        return conn

    def test_expect_matched_line_kept_in_timeout_text(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """同时命中 urc_filter 与 expect 的行保留在超时 text（豁免生效）。"""
        conn = self._make_filtered_connection(monkeypatch)
        resp = _send_and_feed(
            conn,
            "AT+X",
            chunks=[b"\r\n$MYX: 1\r\n"],
            timeout=0.3,
            expect=r"\$MYX: \d+$",
        )
        assert resp.status is ResponseStatus.TIMEOUT
        assert "$MYX: 1" in resp.text  # 未被 urc_filter 剥离
        assert resp.error == "响应超时"  # expect 超时文案不冒充「等待 URC 超时」

    def test_filter_line_still_stripped_without_expect(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """对照：无 expect 的普通周期超时，同一行照常被 urc_filter 剥离。"""
        conn = self._make_filtered_connection(monkeypatch)
        resp = _send_and_feed(conn, "AT+X", chunks=[b"\r\n$MYX: 1\r\n"], timeout=0.3)
        assert resp.status is ResponseStatus.TIMEOUT
        assert "$MYX: 1" not in resp.text
