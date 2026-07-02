"""SerialConnection 并发竞态测试：陈旧响应污染防护.

复现并验证修复 connection.py 的并发竞态 bug：
    - 竞态 A：send_command 超时后，读线程在「get 超时 → break」窗口内 put 的响应
      被遗弃在 _response_q，污染下一次 send_command（错命令拿到对命令的响应）。
    - 竞态 D：断连 ERROR 在同一窗口被遗弃，同源变体。

修复方案：入口排空 _response_q + 超时 break 前末次 get_nowait + cancel 返回前排空。

用「_connected=True + 桩串口」绕过真实 pyserial（沿用 test_write_bytes.py mock 模式）。
用确定性注入（直接 put _response_q）稳定复现，避免脆弱的时序依赖。
"""

from __future__ import annotations

import threading
import time

import pytest

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.interfaces import Response, ResponseStatus


class _StubSerial:
    """最小串口替身：记录 write，flush/read 空操作（绕过 pyserial I/O）。"""

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
    return conn


def _send_in_thread(conn: SerialConnection, command: str, *, timeout: float = 5.0,
                    wait_urc: str | None = None, cancel=None) -> tuple[threading.Thread, dict]:
    """子线程跑 send_command，返回（线程对象，结果字典）。结果字典 done/resp 在完成时填充。"""
    result: dict = {"resp": None}

    def _runner() -> None:
        result["resp"] = conn.send_command(
            command, timeout=timeout, wait_urc=wait_urc, cancel=cancel
        )

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    return t, result


class TestStaleResponsePollution:
    """竞态 A 核心复现：陈旧响应不得污染下一次 send_command。"""

    def test_stale_response_does_not_pollute_next_command(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """复现竞态 A：命令 A 超时后残留的响应，不得被命令 B 误取。

        场景模拟：往 _response_q 注入一个「命令 A 的陈旧响应」（带特征文本），
        然后跑命令 B。B 应排空这条陈旧响应，而不是把它当自己的结果返回。
        """
        conn = _make_connection(monkeypatch)

        # 模拟竞态 A 的残留：命令 A 超时后，一条 COMPLETE 响应被遗弃在队列里
        stale = Response(text="\r\nSTALE_FROM_A\r\nOK\r\n", status=ResponseStatus.COMPLETE)
        conn._response_q.put(stale)  # noqa: SLF001

        # 命令 B：用极短 timeout，让它几乎立即超时（不喂数据）
        # 修复前：B 首次 get 立即取到陈旧 stale → resp.text 含 "STALE_FROM_A"（BUG）
        # 修复后：B 入口排空清掉 stale → resp 是 TIMEOUT，text 不含 "STALE_FROM_A"
        resp_b = conn.send_command("AT+B", timeout=0.1)

        assert "STALE_FROM_A" not in resp_b.text, (
            f"命令 B 误取了命令 A 的陈旧响应（竞态 A）：{resp_b.text!r}"
        )

    def test_multiple_stale_responses_all_drained(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """队列里多条陈旧响应（含断连 ERROR），入口应全部排空。"""
        conn = _make_connection(monkeypatch)

        # 模拟多条残留（竞态 A + 断连 ERROR 变体）
        conn._response_q.put(Response(text="STALE_1", status=ResponseStatus.COMPLETE))  # noqa: SLF001
        conn._response_q.put(Response(text="", status=ResponseStatus.ERROR, error="端口断连"))  # noqa: SLF001
        conn._response_q.put(Response(text="STALE_2", status=ResponseStatus.COMPLETE))  # noqa: SLF001

        resp = conn.send_command("AT+X", timeout=0.1)
        # 应返回 TIMEOUT（队列已被排空，无新数据），且 text 不含任何陈旧内容
        assert resp.status is ResponseStatus.TIMEOUT
        assert "STALE_1" not in resp.text
        assert "STALE_2" not in resp.text
        # 队列已排空
        assert conn._response_q.qsize() == 0  # noqa: SLF001


class TestTimeoutFinalGet:
    """超时 break 前的末次 get_nowait：捕获刚好到达的响应。"""

    def test_timeout_final_get_captures_just_arrived_response(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """命令超时窗口末尾恰好有响应入队，应被末次 get 捕获返回 COMPLETE（而非 TIMEOUT）。

        时序：send_command 用短 timeout；在它即将超时前，另一线程往 _response_q put
        一个响应。末次 get_nowait 应取到它。
        """
        conn = _make_connection(monkeypatch)
        result: dict = {"resp": None}

        def _runner() -> None:
            result["resp"] = conn.send_command("AT+X", timeout=0.3)

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        # 等待 send_command 进入等待循环（设了 _awaiting）
        for _ in range(50):
            if conn._awaiting.is_set():  # noqa: SLF001
                break
            time.sleep(0.005)
        # 在超时前注入响应（模拟读线程刚好 put）
        time.sleep(0.1)
        conn._response_q.put(  # noqa: SLF001
            Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)
        )
        t.join(timeout=2.0)

        resp = result["resp"]
        assert resp is not None
        assert resp.status is ResponseStatus.COMPLETE, (
            f"末次 get 应捕获刚到达的响应，实际 status={resp.status}"
        )
        assert "OK" in resp.text


class TestCancelDrainsPending:
    """cancel 返回前排空队列，避免响应遗弃。"""

    def test_cancel_returns_cancelled_and_drains(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """send_command 被 cancel 时返回 CANCELLED，且不残留响应在队列。

        时序：预先 cancel，send_command 首次循环即检测到 cancelled → 返回 CANCELLED。
        验证 cancel 分支执行了排空（队列 qsize==0）。
        """
        from atprobe.infra.serial.interfaces import CancelToken

        conn = _make_connection(monkeypatch)
        cancel = CancelToken()
        cancel.cancel()  # 预先取消

        resp = conn.send_command("AT+X", timeout=2.0, cancel=cancel)

        assert resp.status is ResponseStatus.CANCELLED
        # cancel 分支排空了队列
        assert conn._response_q.qsize() == 0  # noqa: SLF001

    def test_cancel_after_drain_no_pollution(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """cancel 排空后，下次 send_command 不被残留污染。

        场景：命令 A 被 cancel，cancel 前队列里有一条响应；命令 A 返回 CANCELLED 并排空。
        命令 B 执行时不应取到 A 残留的响应。
        """
        from atprobe.infra.serial.interfaces import CancelToken

        conn = _make_connection(monkeypatch)
        cancel = CancelToken()
        cancel.cancel()
        # 模拟 cancel 时队列里的残留（即便有，cancel 分支也应排空）
        conn._response_q.put(  # noqa: SLF001
            Response(text="SHOULD_BE_DRAINED", status=ResponseStatus.COMPLETE)
        )

        resp_a = conn.send_command("AT+A", timeout=2.0, cancel=cancel)
        assert resp_a.status is ResponseStatus.CANCELLED

        # 命令 B 不应取到 "SHOULD_BE_DRAINED"
        resp_b = conn.send_command("AT+B", timeout=0.1)
        assert "SHOULD_BE_DRAINED" not in resp_b.text


class TestNormalPathUnaffected:
    """正常路径（无竞态）不受排空影响。"""

    def test_normal_complete_response(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """无陈旧残留时，正常 OK 终结响应应正确返回。"""
        conn = _make_connection(monkeypatch)
        result: dict = {"resp": None}

        def _runner() -> None:
            result["resp"] = conn.send_command("AT+CSQ", timeout=2.0)

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        for _ in range(50):
            if conn._awaiting.is_set():  # noqa: SLF001
                break
            time.sleep(0.005)
        # 模拟读线程喂入正常响应
        conn._process_incoming(b"\r\n+CSQ: 23,0\r\nOK\r\n")  # noqa: SLF001
        t.join(timeout=2.0)

        resp = result["resp"]
        assert resp is not None
        assert resp.status is ResponseStatus.COMPLETE
        assert "+CSQ: 23,0" in resp.text
        assert "OK" in resp.text
