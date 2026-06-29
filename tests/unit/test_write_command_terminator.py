"""write_command 结束符逐命令覆盖测试.

回归：手动调试页结束符下拉选 \\r 或 \\r\\n 时，实际发送字节应相应变化。
修复前：write_command 全程用 PortConfig.terminator（连接级默认），UI 选择被忽略。

覆盖：
    - SerialConnection.write_command(command, terminator=...) 逐命令覆盖
    - 不传 terminator 时回退到 PortConfig.terminator（向后兼容）
    - PortManager.write_command(port, command, terminator=...) 透传
    - FakePortManager.write_command(port, command, terminator=...) 透传
"""

from __future__ import annotations

from atprobe.infra.serial.config import FrameFormat, PortConfig, Terminator
from atprobe.infra.serial.connection import SerialConnection


class _StubSerial:
    """最小串口替身：记录 write 调用，flush 空操作（绕过 pyserial I/O）。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass


def _make_connection(monkeypatch, terminator: Terminator = Terminator.CRLF) -> SerialConnection:
    """构造已连接、底层为 _StubSerial 的 SerialConnection（不真开 pyserial）。"""
    cfg = PortConfig(
        name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"), terminator=terminator
    )
    conn = SerialConnection(cfg)
    stub = _StubSerial()
    monkeypatch.setattr(conn, "_serial", stub)
    monkeypatch.setattr(conn, "_connected", True)
    return conn


class TestSerialConnectionWriteCommandTerminator:
    def test_default_uses_config_terminator(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """不传 terminator 时回退到 PortConfig.terminator（向后兼容）。"""
        conn = _make_connection(monkeypatch, terminator=Terminator.CRLF)

        conn.write_command("AT")

        assert conn._serial.written == [b"AT\r\n"]  # noqa: SLF001

    def test_override_to_cr(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """逐命令覆盖为 \\r：即使 config 是 CRLF 也只用 \\r。"""
        conn = _make_connection(monkeypatch, terminator=Terminator.CRLF)

        conn.write_command("AT", terminator=Terminator.CR)

        assert conn._serial.written == [b"AT\r"]  # noqa: SLF001

    def test_override_to_crlf(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """逐命令覆盖为 \\r\\n：即使 config 是 CR 也只用 \\r\\n。"""
        conn = _make_connection(monkeypatch, terminator=Terminator.CR)

        conn.write_command("AT", terminator=Terminator.CRLF)

        assert conn._serial.written == [b"AT\r\n"]  # noqa: SLF001


class TestPortManagerWriteCommandTerminator:
    def test_pm_passes_terminator_through(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.portmanager import PortManager

        conn = _make_connection(monkeypatch, terminator=Terminator.CRLF)
        captured: list[Terminator | None] = []
        monkeypatch.setattr(
            conn, "write_command", lambda command, terminator=None: captured.append(terminator)
        )

        pm = PortManager()
        monkeypatch.setattr(pm, "_connections", {"COM9": conn})

        pm.write_command("COM9", "AT", terminator=Terminator.CR)

        assert captured == [Terminator.CR]

    def test_pm_default_no_terminator(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.portmanager import PortManager

        conn = _make_connection(monkeypatch)
        captured: list[Terminator | None] = []
        monkeypatch.setattr(
            conn, "write_command", lambda command, terminator=None: captured.append(terminator)
        )

        pm = PortManager()
        monkeypatch.setattr(pm, "_connections", {"COM9": conn})

        pm.write_command("COM9", "AT")

        assert captured == [None]


class TestFakePortManagerWriteCommandTerminator:
    def test_fake_passes_terminator_to_payload(self) -> None:  # type: ignore[no-untyped-def]
        """FakePortManager.write_command 用传入 terminator 构造 TX payload。"""
        from atprobe.infra.serial.fakeserial import FakePortManager

        pm = FakePortManager(sleep=lambda s: None)
        pm.open(PortConfig(name="COM9"))  # 默认 CRLF

        seen: list[bytes] = []
        pm.subscribe_tx("COM9", lambda chunk: seen.append(chunk))

        # 覆盖为 CR：TX payload 应只含 \r
        pm.write_command("COM9", "AT", terminator=Terminator.CR)
        assert seen == [b"AT\r"]
