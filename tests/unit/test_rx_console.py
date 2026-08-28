"""RxConsole 共享组件单测（Pf-1）.

不依赖事件循环：定时器不可控 → 直接调 flush() 测 drain；QTimer 仅做弱断言
（存在性/interval，offscreen QApplication 下 start/stop 走真路径）。
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class TestRxConsoleDrain:
    def test_append_n_flush_renders_n(self) -> None:
        """append N 条 → flush 一次 renderer 收 N 条（顺序保持）。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        con = RxConsole(rendered.extend)
        for i in range(50):
            con.append("RX", f"line{i}", f"ts{i}")
        assert con.pending_count == 50
        con.flush()
        assert len(rendered) == 50
        assert rendered[0] == ("RX", "ts0", "line0")
        assert rendered[-1] == ("RX", "ts49", "line49")
        assert con.pending_count == 0

    def test_flush_empty_skips_renderer(self) -> None:
        """空缓冲 flush 不调 renderer（monitor 旧行为锁：不产生空 append）。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        calls: list[object] = []
        con = RxConsole(lambda items: calls.append(items))
        con.flush()
        con.flush()
        assert calls == []

    def test_flush_drains_only_once(self) -> None:
        """二次 flush 不重复投递（drain 语义）。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        con = RxConsole(rendered.extend)
        con.append("TX", "a")
        con.flush()
        con.flush()
        assert rendered == [("TX", "", "a")]

    def test_timestamp_optional(self) -> None:
        """timestamp 缺省为空串（宿主 renderer 决定空时间码的回退行为）。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        con = RxConsole(rendered.extend)
        con.append("RX", "no-ts")
        con.flush()
        assert rendered == [("RX", "", "no-ts")]

    def test_clear_drops_pending_without_render(self) -> None:
        """clear 丢弃待渲染缓冲且不调 renderer（清屏语义）。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        con = RxConsole(rendered.extend)
        con.append("RX", "stale")
        con.clear()
        con.flush()
        assert rendered == []
        assert con.pending_count == 0


class TestRxConsoleMaxPending:
    def test_drops_oldest_and_counts(self) -> None:
        """超出 max_pending 丢最旧并计数（防高波特率无界增长）。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        con = RxConsole(rendered.extend, max_pending=3)
        for i in range(5):
            con.append("RX", f"l{i}")
        assert con.pending_count == 3
        con.flush()
        # 最旧的 l0/l1 被丢，保留最后 3 条
        assert [t for _, _, t in rendered] == ["l2", "l3", "l4"]
        assert con.dropped_count == 2

    def test_within_limit_no_drop(self) -> None:
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        con = RxConsole(rendered.extend, max_pending=100)
        for i in range(100):
            con.append("RX", f"l{i}")
        con.flush()
        assert len(rendered) == 100
        assert con.dropped_count == 0


class TestRxConsoleThreadSafety:
    def test_concurrent_append_flush_smoke(self) -> None:
        """多线程并发 append + 主线程并发 flush：不炸、不重复、不丢（未触上限）。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        lock = threading.Lock()

        def render(items: list[tuple[str, str, str]]) -> None:
            with lock:
                rendered.extend(items)

        con = RxConsole(render, max_pending=10_000)
        n_threads, per_thread = 4, 500

        def producer(tid: int) -> None:
            for i in range(per_thread):
                con.append("RX", f"t{tid}-{i}")

        threads = [threading.Thread(target=producer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            con.flush()  # 模拟主线程定时器与写侧并发
        for t in threads:
            t.join()
        con.flush()
        # 精确记账：无上限丢弃时，总条数 = 发出条数（append 原子、drain 恰一次）
        assert len(rendered) == n_threads * per_thread
        texts = [t for _, _, t in rendered]
        assert len(set(texts)) == n_threads * per_thread  # 无重复
        assert con.dropped_count == 0


class TestRxConsoleTimer:
    def test_start_stop_lifecycle_and_stop_flushes(self, qapp) -> None:
        """QTimer 弱断言：start 后在跑、interval 正确、stop 冲刷残余。"""
        from atprobe.gui.widgets.rx_console import RxConsole

        rendered: list[tuple[str, str, str]] = []
        con = RxConsole(rendered.extend, interval_ms=250)
        assert not con.is_running()
        con.append("RX", "pending")
        con.start()
        try:
            assert con.is_running()
            assert con._timer is not None  # noqa: SLF001
            assert con._timer.interval() == 250  # noqa: SLF001
            assert con._timer.isSingleShot() is False  # noqa: SLF001
            assert rendered == []  # 定时器到期前不上屏（200ms 批量语义）
        finally:
            con.stop()
        assert not con.is_running()
        assert [t for _, _, t in rendered] == ["pending"]  # stop 冲刷残余

    def test_start_idempotent(self, qapp) -> None:
        from atprobe.gui.widgets.rx_console import RxConsole

        con = RxConsole(lambda items: None)
        con.start()
        con.start()
        assert con.is_running()
        con.stop()
