"""RawLogger 生命周期测试（P1-2 回归）.

锁四项行为：句柄 LRU 上限（evicted 观测）、end_case 关闭后 append 重开、
有界队列满时非阻塞丢弃计数、start 前排空陈旧记录；以及 PortManager
clear_case_log → end_case 的协作触发。
"""

from __future__ import annotations

import queue
import time
from pathlib import Path

from atprobe.infra.serial.portmanager import PortManager
from atprobe.infra.serial.rawlog import RawLogger, _Record


class _SpyRawLogger(RawLogger):
    """记录 end_case 调用的真 RawLogger（仅测试观测，不改变行为）."""

    def __init__(self) -> None:
        super().__init__()
        self.end_case_calls: list[Path] = []

    def end_case(self, stem: Path) -> None:
        self.end_case_calls.append(stem)
        super().end_case(stem)


def test_lru_closes_oldest_handles(tmp_path: Path, monkeypatch) -> None:
    """句柄超上限时按插入序逐出最旧（内容已逐条 flush，不丢失）."""
    monkeypatch.setattr(RawLogger, "_MAX_STEMS", 4)
    logger = RawLogger()
    logger.start()
    stems = [tmp_path / f"case{i}" for i in range(6)]
    for i, stem in enumerate(stems):
        logger.log(stem, "TX", f"DATA{i}\r\n".encode())
    time.sleep(0.1)  # 等写入线程消费完并执行 LRU 逐出
    assert len(logger.evicted) >= 2
    assert stems[0] in logger.evicted  # 最早的 stem 被逐出
    logger.stop()
    # 逐出只关句柄不删数据：全部文件存在且内容完整（每次写后已 flush）
    for i, stem in enumerate(stems):
        content = stem.with_name(f"{stem.name}.text.log").read_text(encoding="utf-8")
        assert f"DATA{i}" in content


def test_end_case_closes_and_reopens_append(tmp_path: Path) -> None:
    """end_case 关闭句柄后，同 stem 再 log 重开文件且追加不覆盖."""
    logger = RawLogger()
    logger.start()
    stem = tmp_path / "case"
    logger.log(stem, "TX", b"before\r\n")
    logger.end_case(stem)
    time.sleep(0.05)  # 给写入线程消费 end_case 消息的时间
    logger.log(stem, "TX", b"after\r\n")
    logger.stop()

    content = stem.with_name(f"{stem.name}.text.log").read_text(encoding="utf-8")
    assert "before" in content
    assert "after" in content  # 重开为 append 模式，首条未被覆盖


def test_queue_full_drops_and_counts(tmp_path: Path) -> None:
    """队列满时 log 非阻塞丢弃并计数（best-effort 通道）."""
    logger = RawLogger()
    # 白盒构造：置 _started 但不起写入线程——隔离验证 log() 的满队丢弃路径
    # （无消费者，maxsize=1 填满后两条 log 必然命中 Full，确定性成立）
    logger._started = True
    logger._queue = queue.Queue(maxsize=1)
    logger._queue.put_nowait(object())
    t0 = time.monotonic()
    logger.log(tmp_path / "x", "TX", b"aaa\r\n")
    logger.log(tmp_path / "x", "TX", b"bbb\r\n")
    elapsed = time.monotonic() - t0
    assert logger.dropped_count >= 1
    assert elapsed < 1.0  # 非阻塞：不得卡在 put 上


def test_start_drains_stale_records(tmp_path: Path) -> None:
    """start 前排空上次会话残留——陈旧记录不得进入新会话."""
    logger = RawLogger()
    stale = tmp_path / "stale"
    fresh = tmp_path / "fresh"
    # 直接向队列投递一条陈旧记录（模拟上次 stop 后未消费的残留）
    logger._queue.put(_Record(direction="TX", data=b"stale\r\n", timestamp="ts", file_path=stale))
    logger.start()
    logger.log(fresh, "TX", b"fresh\r\n")
    logger.stop()

    assert not stale.with_name("stale.text.log").exists()
    content = fresh.with_name("fresh.text.log").read_text(encoding="utf-8")
    assert "fresh" in content


class TestBeginCaseSanitization:
    """S-1：session/port 片段消毒——不可信输入不可写任意目录.

    begin_case 的三个片段中 case_name 一直过 _sanitize，但 session/port 此前
    直接拼接（port 来自用例 step.port，不可信）：session="../../evil" 或
    Windows 反斜杠变体可翻出 log_dir 任意写；Linux 绝对端口 /dev/ttyUSB0
    嵌套出 dev/ttyUSB0 两级目录。修复：三者均消毒，port 先取 basename。
    """

    def test_traversal_session_port_sanitized(self, tmp_path: Path) -> None:
        logger = RawLogger()
        logger.start()
        try:
            for bad_session in ("../../evil", "..\\..\\evil"):
                # port 同为 Windows 反斜杠遍历变体：Path(..\..\evil).name → evil
                stem = logger.begin_case(tmp_path, bad_session, "..\\..\\evil", "case")
                # 遍历被封：消毒后路径仍严格位于 log_dir 之下
                assert stem.resolve().is_relative_to(tmp_path.resolve()), f"遍历未封：{stem}"
                # session/port/case 各占一个安全片段（无 .. 路径成分、无嵌套翻出）
                parts = stem.relative_to(tmp_path).parts
                assert len(parts) == 3, f"片段数异常：{stem}"
                assert all(p != ".." for p in parts)
        finally:
            logger.stop()

    def test_linux_dev_port_no_nested_dirs(self, tmp_path: Path) -> None:
        logger = RawLogger()
        logger.start()
        try:
            stem = logger.begin_case(tmp_path, "s1", "/dev/ttyUSB0", "case")
            # port 取 basename：ttyUSB0 是单一片段，不再嵌套 dev/ttyUSB0 目录
            assert stem.relative_to(tmp_path).parts == ("s1", "ttyUSB0", "case")
        finally:
            logger.stop()

    def test_pure_dots_rejected(self, tmp_path: Path) -> None:
        logger = RawLogger()
        logger.start()
        try:
            stem = logger.begin_case(tmp_path, "...", "COM3", "case")
            # 纯点号（点在字符白名单内但构成遍历成分）→ 占位 case
            assert stem.relative_to(tmp_path).parts == ("case", "COM3", "case")
            assert ".." not in str(stem.relative_to(tmp_path))
        finally:
            logger.stop()


def test_portmanager_clear_triggers_end_case(tmp_path: Path) -> None:
    """clear_case_log 弹出绑定时触发 raw_logger.end_case(stem)."""
    logger = _SpyRawLogger()
    logger.start()
    pm = PortManager(raw_logger=logger)
    stem = tmp_path / "case"
    logger.log(stem, "TX", b"before\r\n")
    pm.set_case_log("COMX", stem)
    assert logger.end_case_calls == []  # 绑定不触发
    pm.clear_case_log("COMX")
    assert logger.end_case_calls == [stem]
    pm.clear_case_log("COMX")  # 无绑定再 clear 不重复触发
    assert logger.end_case_calls == [stem]
    # 全链路：end_case 后续写重开追加（前一条不丢）
    time.sleep(0.05)
    logger.log(stem, "TX", b"after\r\n")
    logger.stop()
    content = stem.with_name(f"{stem.name}.text.log").read_text(encoding="utf-8")
    assert "before" in content and "after" in content
