"""FakePortManager/VsimPortManager 原始日志与 observer 派发对齐测试（M8 日志修复）.

Fake 的 send_command 此前不派发 TX/RX observer、不写用例日志——与真实
SerialConnection 行为不一致，共享 PM 模式（GUI/MCP）下日志链路无法在测试中
覆盖。本文件钉住对齐后的双路径：observer 派发（监控语义，M6 §6.2）+
用例日志（raw_logger + set_case_log 语义，M1 §7）。
"""

from __future__ import annotations

from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import Response
from atprobe.infra.serial.rawlog import RawLogger
from atprobe.infra.serial.vsim import VSIM_PORT, VsimPortManager


def test_send_command_notifies_tx_rx_observers():
    fake = FakePortManager()
    fake.open(PortConfig(name="V0"))
    tx: list[bytes] = []
    rx: list[bytes] = []
    fake.subscribe_tx("V0", tx.append)
    fake.subscribe_rx("V0", rx.append)
    fake.script("V0", Response(text="\r\nOK\r\n"))

    fake.send_command("V0", "AT")

    assert tx == [b"AT\r\n"]  # 命令 + 默认结束符（与真实写线程同构）
    assert rx == [b"\r\nOK\r\n"]  # 响应文本原样


def test_send_command_no_response_tx_only():
    fake = FakePortManager()
    fake.open(PortConfig(name="V0"))
    tx: list[bytes] = []
    rx: list[bytes] = []
    fake.subscribe_tx("V0", tx.append)
    fake.subscribe_rx("V0", rx.append)

    resp = fake.send_command("V0", "AT")  # 无预设脚本 → ERROR 空响应

    assert tx == [b"AT\r\n"]
    assert rx == []  # 无响应不派发 RX（对齐真实超时语义）
    assert resp.status.value == "error"


def test_send_command_writes_case_log(tmp_path):
    logger = RawLogger()
    logger.start()
    try:
        fake = FakePortManager(raw_logger=logger)
        fake.open(PortConfig(name="V0"))
        fake.set_case_log("V0", tmp_path / "case1")
        fake.script("V0", Response(text="\r\nOK\r\n"))

        fake.send_command("V0", "AT")
    finally:
        logger.stop()  # drain 确保落盘

    content = (tmp_path / "case1.text.log").read_text(encoding="utf-8")
    assert "[TX] AT" in content
    assert "[RX]" in content and "OK" in content
    hex_content = (tmp_path / "case1.hex.log").read_text(encoding="utf-8")
    assert "41 54 0D 0A" in hex_content  # 'AT\r\n' 的十六进制


def test_no_case_log_bound_no_file(tmp_path):
    """未 set_case_log（如手动通道）时 send_command 不写用例日志文件."""
    logger = RawLogger()
    logger.start()
    try:
        fake = FakePortManager(raw_logger=logger)
        fake.open(PortConfig(name="V0"))
        fake.script("V0", Response(text="OK\r\n"))
        fake.send_command("V0", "AT")
    finally:
        logger.stop()
    assert not (tmp_path / "case1.text.log").exists()


def test_vsim_send_command_logs_and_notifies(tmp_path):
    logger = RawLogger()
    logger.start()
    tx: list[bytes] = []
    rx: list[bytes] = []
    try:
        vsim = VsimPortManager(raw_logger=logger)
        vsim.open(PortConfig(name=VSIM_PORT))
        vsim.subscribe_tx(VSIM_PORT, tx.append)
        vsim.subscribe_rx(VSIM_PORT, rx.append)
        vsim.set_case_log(VSIM_PORT, tmp_path / "vcase")

        resp = vsim.send_command(VSIM_PORT, "AT")
        assert resp.ok
    finally:
        logger.stop()

    assert tx == [b"AT\r\n"]
    assert any(b"OK" in d for d in rx)
    content = (tmp_path / "vcase.text.log").read_text(encoding="utf-8")
    assert "[TX] AT" in content
    assert "OK" in content


def test_vsim_constructor_accepts_raw_logger():
    """VsimPortManager 构造透传 raw_logger（McpService vsim 分支接线用）."""
    vsim = VsimPortManager(raw_logger=None)
    vsim.open(PortConfig(name=VSIM_PORT))
    assert vsim.is_connected(VSIM_PORT)
