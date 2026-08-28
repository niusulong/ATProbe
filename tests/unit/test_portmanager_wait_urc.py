"""PortManager.send_command 的 wait_urc 参数转发测试.

覆盖生产路径的盲区：集成测试用 FakePortManager 绕过了 PortManager → SerialConnection
的真实转发链路。本测试直接验证 PortManager.send_command 把 wait_urc 正确转发给
SerialConnection.send_command 的两处调用点（首次发送 + 断连重发）。

沿用 test_write_bytes.py 的 PortManager mock 模式。
"""

from __future__ import annotations

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.interfaces import Response, ResponseStatus
from atprobe.infra.serial.portmanager import PortManager


def _make_connected_portmanager(monkeypatch) -> tuple[PortManager, SerialConnection]:
    """构造已连接的 PortManager + 其底层 SerialConnection（mock 已连接状态）."""
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    conn = SerialConnection(cfg)
    monkeypatch.setattr(conn, "_connected", True)
    monkeypatch.setattr(
        conn,
        "_serial",
        type("S", (), {"write": lambda self, d: None, "flush": lambda self: None})(),
    )
    pm = PortManager()
    monkeypatch.setattr(pm, "_connections", {"COM9": conn})
    return pm, conn


class TestPortManagerWaitUrcForwarding:
    def test_wait_urc_forwarded_to_connection(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """首次发送路径：wait_urc 必须转发给 conn.send_command。"""
        pm, conn = _make_connected_portmanager(monkeypatch)
        captured: dict = {}

        def _capture(
            command, *, timeout=None, wait_urc=None, expect=None, cancel=None, pre_check=None
        ):
            captured["wait_urc"] = wait_urc
            captured["expect"] = expect
            captured["command"] = command
            return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)

        monkeypatch.setattr(conn, "send_command", _capture)

        resp = pm.send_command("COM9", "AT+X", wait_urc=r"\+X:done", timeout=5)

        assert captured["wait_urc"] == r"\+X:done"
        assert captured["expect"] is None  # 未启用 expect 时转发 None（不误置）
        assert resp.status is ResponseStatus.COMPLETE

    def test_wait_urc_none_forwarded_by_default(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """不传 wait_urc 时转发 None（默认行为不变）。"""
        pm, conn = _make_connected_portmanager(monkeypatch)
        captured: dict = {}

        def _capture(
            command, *, timeout=None, wait_urc=None, expect=None, cancel=None, pre_check=None
        ):
            captured["wait_urc"] = wait_urc
            captured["expect"] = expect
            return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)

        monkeypatch.setattr(conn, "send_command", _capture)

        pm.send_command("COM9", "AT")

        assert captured["wait_urc"] is None
        assert captured["expect"] is None

    def test_wait_urc_forwarded_on_reconnect_resend(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """断连重发路径（第二处调用）：首次断连 ERROR，重连后重发也必须带 wait_urc。

        覆盖 PortManager.send_command 第166行的重发调用点——若漏改 wait_urc 转发，
        重发命令会丢掉异步等待语义。
        """
        pm, conn = _make_connected_portmanager(monkeypatch)
        calls: list[dict] = []

        def _capture(
            command, *, timeout=None, wait_urc=None, expect=None, cancel=None, pre_check=None
        ):
            calls.append({"wait_urc": wait_urc, "is_disconnect_error": False})
            if len(calls) == 1:
                # 首次返回断连 ERROR，触发 PortManager 重连重发
                # M3：基于 error_kind 判定断连，需设 DISCONNECT（与真实 connection._handle_disconnect 一致）
                return Response(
                    text="",
                    status=ResponseStatus.ERROR,
                    error="端口断连",
                    error_kind="DISCONNECT",
                )
            return Response(text="\r\nOK\r\n\r\n+X:done\r\n", status=ResponseStatus.COMPLETE)

        monkeypatch.setattr(conn, "send_command", _capture)
        # mock 重连成功
        monkeypatch.setattr(pm, "_reconnect", lambda port, **kw: True)

        resp = pm.send_command("COM9", "AT+X", wait_urc=r"\+X:done", timeout=5)

        assert len(calls) == 2, "应触发断连重发（第二次调用）"
        # 关键：两次调用都必须带 wait_urc（第二次是重发路径）
        assert calls[0]["wait_urc"] == r"\+X:done"
        assert calls[1]["wait_urc"] == r"\+X:done", "重发路径漏传 wait_urc"
        assert resp.status is ResponseStatus.COMPLETE


class TestVsimWaitUrcAcceptance:
    """VsimPortManager.send_command 接受 wait_urc 参数（保持接口一致）。"""

    def test_vsim_accepts_wait_urc_without_error(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """vsim.send_command 接受 wait_urc 参数不报错（签名一致性）。"""
        from atprobe.infra.serial.vsim import VsimPortManager

        vsim = VsimPortManager()
        monkeypatch.setattr(
            vsim, "_responder", type("R", (), {"respond": lambda self, cmd: b"\r\nOK\r\n"})()
        )
        # 应正常返回，不因 wait_urc 参数报 TypeError
        resp = vsim.send_command("COM9", "AT+X", wait_urc=r"\+X:done", timeout=2)
        assert resp.status is ResponseStatus.COMPLETE
