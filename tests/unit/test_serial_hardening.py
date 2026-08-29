"""串口层加固测试（批 2a Task 9）：urc_filter 异常体系 + 迟到响应收割窗口条件化.

    - PortConfig.urc_filter 非法正则在构造期即抛 SerialError（带「urc_filter 正则
      无效」上下文），不留到运行期首条命令才炸；
    - 收割窗口仅对小超时预算（to < _STALE_REAP_MIN_TIMEOUT_S=0.2s）开启：大超时
      命令的超时预算已含设备时延，固定 +150ms 收割会系统性拖慢轮询类用例（P3）；
      小超时路径（0.05s 钳位预算 + 设备典型时延场景）收割行为不回归。

桩串口模式沿用 test_connection_wait_urc.py（_connected=True + _StubSerial，
直接 _process_incoming 喂字节）。假 clock 无该文件先例（其用真实 monotonic），
大超时用例改用脚本时钟：首次调用（_await_response 的 deadline 计算）返回 0，
其后冻结在大值——超时立达且收割窗口永不到期，收割是否被跳过即「能否返回」。
"""

from __future__ import annotations

import threading

import pytest

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import SerialError
from atprobe.infra.serial.interfaces import ResponseStatus


class _StubSerial:
    """最小串口替身：记录 write，flush 空操作（绕过 pyserial I/O）。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass


def _make_connection(monkeypatch, *, clock=None) -> tuple[SerialConnection, _StubSerial]:  # type: ignore[no-untyped-def]
    """构造已连接、底层为 _StubSerial 的 SerialConnection（不真开 pyserial）。

    clock 为 None 时用默认 time.monotonic（真实时间，小超时收割用例需要）。
    """
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    conn = SerialConnection(cfg) if clock is None else SerialConnection(cfg, clock=clock)
    stub = _StubSerial()
    monkeypatch.setattr(conn, "_serial", stub)
    monkeypatch.setattr(conn, "_connected", True)
    return conn, stub


def _wait_awaiting_set(conn: SerialConnection, timeout_s: float = 2.0) -> None:
    """等待 send_command 进入等待态（awaiting set）."""
    for _ in range(int(timeout_s / 0.005)):
        if conn._awaiting.is_set():  # noqa: SLF001
            return
        threading.Event().wait(0.005)
    raise AssertionError("send_command 未在预期时间内进入等待态")


def _wait_written(stub: _StubSerial, count: int, timeout_s: float = 2.0) -> None:
    """等待桩串口完成第 count 次 write——send_command 的 write 在排空队列之后，
    以此为界保证后续喂入的响应不会被入口 drain 误清。"""
    for _ in range(int(timeout_s / 0.005)):
        if len(stub.written) >= count:
            return
        threading.Event().wait(0.005)
    raise AssertionError(f"write 未在预期时间内发生（期望 ≥{count} 次）")


class _StepClock:
    """脚本时钟：首次调用返回 0.0（_await_response 的 deadline 计算），其后冻结
    在大值（任何有限 deadline 均视为已过）。

    效果：超时路径立即到达；若收割窗口被（错误地）进入，reap_deadline 在冻结
    时钟下永不到期 → 永不返回——「能否及时返回」即「收割是否被跳过」的确定性
    判据（无需真实等待 5s 超时再掐 150ms 表）。
    """

    def __init__(self) -> None:
        self._calls = 0

    def __call__(self) -> float:
        self._calls += 1
        return 0.0 if self._calls == 1 else 1000.0


class TestUrcFilterValidation:
    """urc_filter 编译失败 → SerialError（解析期口径，与 expect/wait_urc 同族）."""

    def test_invalid_regex_raises_serial_error(self) -> None:
        """PortConfig(urc_filter=("(",)) 构造 SerialConnection 即抛，消息含上下文."""
        cfg = PortConfig(name="X", urc_filter=("(",))
        with pytest.raises(SerialError, match="urc_filter 正则无效"):
            SerialConnection(cfg)

    def test_valid_regex_still_compiles(self) -> None:
        """合法正则照常编译（回归锁：消毒不误伤正常配置）."""
        cfg = PortConfig(name="X", urc_filter=(r"\$MYGPSPOS", r"\+QIND"))
        conn = SerialConnection(cfg)
        assert len(conn._urc_filter_res) == 2  # noqa: SLF001


class TestStaleReapConditional:
    """收割窗口条件化：大超时（to ≥ 0.2s）跳过，小超时（< 0.2s）不回归."""

    def test_large_timeout_skips_reap_window(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """timeout=5.0 超时后不进入收割窗口：脚本时钟下收割永不到期也能及时返回；
        返回后通道干净（else 分支的清理与收割尾部等价）。"""
        conn, _ = _make_connection(monkeypatch, clock=_StepClock())
        done = threading.Event()
        result: dict[str, object] = {}

        def _run() -> None:
            result["resp"] = conn.send_command("AT+CGATT?", timeout=5.0)
            done.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # 若收割窗口未被跳过：reap_deadline 在冻结时钟下永不到期，永不返回
        assert done.wait(2.0), "大超时超时路径疑似进入收割窗口（冻结时钟下不可返回）"
        resp = result["resp"]
        assert resp.status is ResponseStatus.TIMEOUT  # type: ignore[union-attr]
        # 清理路径等价性：awaiting 已清、响应队列排空、缓冲已清
        assert not conn._awaiting.is_set()  # noqa: SLF001
        assert conn._response_q.empty()  # noqa: SLF001
        with conn._buffer_lock:  # noqa: SLF001
            assert len(conn._assembler.buffer) == 0  # noqa: SLF001

    def test_large_timeout_next_command_receives_late_response(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """大超时超时返回后立即喂入迟到 OK：无收割窗口吞吃，下一条命令正常收到
        （=未收割）。冻结时钟下后续命令的等待经队列 put 直接唤醒，不受影响。"""
        conn, stub = _make_connection(monkeypatch, clock=_StepClock())
        done1 = threading.Event()

        def _run1() -> None:
            conn.send_command("AT+CGATT?", timeout=5.0)
            done1.set()

        t1 = threading.Thread(target=_run1, daemon=True)
        t1.start()
        # 修前（无条件收割）：冻结时钟下收割永不到期 → 此处失败而非挂死整个测试
        assert done1.wait(2.0), "大超时超时路径疑似进入收割窗口（冻结时钟下不可返回）"
        _wait_written(stub, 1)

        done = threading.Event()
        result: dict[str, object] = {}

        def _run() -> None:
            result["resp"] = conn.send_command("ATE0", timeout=2.0)
            done.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # write 完成后（入口 drain 已过）喂入迟到 OK——若无收割窗口拦截，它就是
        # 下一条命令的正常响应
        _wait_written(stub, 2)
        conn._process_incoming(b"\r\nOK\r\n")  # noqa: SLF001 - 模拟读线程喂字节
        assert done.wait(2.0), "下一条命令未收到喂入的响应（疑似被残留收割窗口吞吃）"
        resp = result["resp"]
        assert resp.status is ResponseStatus.COMPLETE  # type: ignore[union-attr]
        assert resp.text == "\r\nOK\r\n"  # type: ignore[union-attr]

    def test_small_timeout_still_reaps_late_response(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """小超时（0.05s < 0.2s 阈值）收割不回归：迟到响应在收割窗口内被静默
        消费，下一条命令只收到自己的响应（真时钟端到端，锁 N58 修复语义）。"""
        conn, _ = _make_connection(monkeypatch)

        def _feed_late() -> None:
            # awaiting set 后 +0.10s 喂：> 0.05s 超时预算（迟到）、< 0.20s 收割
            # 窗尾（两侧余量 50ms/100ms，覆盖 CI 负载下的线程调度抖动）
            _wait_awaiting_set(conn)
            threading.Event().wait(0.10)
            conn._process_incoming(b"\r\n+CEREG: 0,2\r\nOK\r\n")  # noqa: SLF001

        t1 = threading.Thread(target=_feed_late, daemon=True)
        t1.start()
        r1 = conn.send_command("AT+CEREG?", timeout=0.05)
        t1.join(timeout=2.0)
        assert r1.status is ResponseStatus.TIMEOUT

        # 下一条命令必须拿到自己的响应，而不是上一条的迟到响应
        def _feed_second() -> None:
            _wait_awaiting_set(conn)
            threading.Event().wait(0.01)
            conn._process_incoming(b"\r\nOK\r\n")  # noqa: SLF001

        t2 = threading.Thread(target=_feed_second, daemon=True)
        t2.start()
        r2 = conn.send_command("ATE0", timeout=2.0)
        t2.join(timeout=2.0)
        assert r2.status is ResponseStatus.COMPLETE
        assert r2.text == "\r\nOK\r\n", "不得吃到上一条命令的迟到响应"
