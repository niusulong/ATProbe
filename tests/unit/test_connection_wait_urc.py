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
            resp = conn.send_command(command, timeout=timeout, wait_urc=wait_urc)
            result["resp"] = resp
            result["done"] = threading.Event()
        except Exception as e:  # noqa: BLE001
            exc.append(e)

    done = threading.Event()
    t = threading.Thread(
        target=lambda: (
            result.update({"resp": conn.send_command(command, timeout=timeout, wait_urc=wait_urc)}),
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
