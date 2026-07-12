"""rawlog.py 句柄缓存测试（B4 回归）.

验证 RawLogger 缓存文件句柄而非每条记录重开（I/O 放大修复）。
"""

from __future__ import annotations

import time
from pathlib import Path

from atprobe.infra.serial.rawlog import RawLogger


def test_rawlog_writes_text_and_hex(tmp_path: Path) -> None:
    """正常写入：TEXT 和 HEX 两个文件都有内容。"""
    logger = RawLogger()
    logger.start()
    stem = tmp_path / "case1"
    logger.log(stem, "TX", b"AT\r\n")
    logger.log(stem, "RX", b"OK\r\n")
    logger.stop()

    text_log = tmp_path / "case1.text.log"
    hex_log = tmp_path / "case1.hex.log"
    assert text_log.exists()
    assert hex_log.exists()
    text_content = text_log.read_text(encoding="utf-8")
    hex_content = hex_log.read_text(encoding="utf-8")
    assert "TX" in text_content and "AT" in text_content
    assert "RX" in text_content and "OK" in text_content
    # HEX 文件应含字节的十六进制表示
    assert "41 54" in hex_content  # 'AT' 的 hex
    assert "4F 4B" in hex_content  # 'OK' 的 hex


def test_rawlog_appends_multiple_records(tmp_path: Path) -> None:
    """多条记录追加到同一文件（验证句柄复用）。"""
    logger = RawLogger()
    logger.start()
    stem = tmp_path / "multi"
    for i in range(10):
        logger.log(stem, "TX", f"CMD{i}\r\n".encode())
    logger.stop()

    content = (tmp_path / "multi.text.log").read_text(encoding="utf-8")
    # 10 条都应存在（验证句柄缓存模式下追加正确）
    for i in range(10):
        assert f"CMD{i}" in content, f"记录 {i} 丢失（句柄缓存可能有问题）"


def test_rawlog_stop_flushes_buffer(tmp_path: Path) -> None:
    """stop() 确保缓冲落盘（哨兵 + drain）。"""
    logger = RawLogger()
    logger.start()
    stem = tmp_path / "flush"
    logger.log(stem, "TX", b"data1\r\n")
    # 给写入线程一点时间处理
    time.sleep(0.05)
    logger.stop()

    content = (tmp_path / "flush.text.log").read_text(encoding="utf-8")
    assert "data1" in content


def test_rawlog_multiple_files(tmp_path: Path) -> None:
    """多个 file_path 各自独立写入（句柄按 path 缓存）。"""
    logger = RawLogger()
    logger.start()
    stem1 = tmp_path / "case_a"
    stem2 = tmp_path / "case_b"
    logger.log(stem1, "TX", b"aaa\r\n")
    logger.log(stem2, "TX", b"bbb\r\n")
    logger.stop()

    assert (tmp_path / "case_a.text.log").exists()
    assert (tmp_path / "case_b.text.log").exists()
    assert "aaa" in (tmp_path / "case_a.text.log").read_text(encoding="utf-8")
    assert "bbb" in (tmp_path / "case_b.text.log").read_text(encoding="utf-8")
