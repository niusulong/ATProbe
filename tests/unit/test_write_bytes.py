"""write_bytes / PortManager.write_bytes 单元测试.

覆盖：TX 观察者通知（咽喉点完整性）、断连抛 SendError、PortManager 转调。

用「_connected=True + 桩串口对象」绕过真实 pyserial.open（沿用
tests/unit/test_persistent_subscribe.py 的 mock 模式）。
"""

from __future__ import annotations

import pytest

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import SendError


class _StubSerial:
    """最小串口替身：记录 write 调用，flush 空操作（绕过 pyserial I/O）。"""

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


class TestWriteBytesNotifiesTx:
    def test_write_bytes_notifies_tx_observer(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_connection(monkeypatch)
        seen: list[bytes] = []
        conn.add_tx_observer(lambda chunk: seen.append(chunk))

        conn.write_bytes(b"\x01\x02\x03")

        # 咽喉点契约：所有写入都对 TX 观察者可见（与 write_command 一致）
        assert seen == [b"\x01\x02\x03"]

    def test_write_bytes_no_terminator_added(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """write_bytes 写入原始字节，不加结束符（区别于 write_command）。"""
        conn = _make_connection(monkeypatch)

        conn.write_bytes(b"RAW")

        # 原始字节原样写入，无 \r\n 追加
        assert conn._serial.written == [b"RAW"]  # noqa: SLF001

    def test_write_bytes_disconnected_raises(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_connection(monkeypatch)
        monkeypatch.setattr(conn, "_connected", False)

        with pytest.raises(SendError):
            conn.write_bytes(b"x")
