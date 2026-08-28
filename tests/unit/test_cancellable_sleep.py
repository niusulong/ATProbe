"""cancellable_sleep 统一取消原语（设计 §4.5，批 3 T1）专项测试.

注入 sleep 计数器替代真实休眠（零真实等待、时长可断言）；CancelToken 是
threading.Event 封装，取消可在注入的 sleep 回调里触发——模拟"睡眠中途
取消"（stop 恰落在重试间隔内的真实时序）。
"""

from __future__ import annotations

import pytest

from atprobe.infra.serial.interfaces import CancelToken
from atprobe.infra.serial.sleep import cancellable_sleep


class SleepRecorder:
    """记录每次 sleep 时长的注入替身（即时返回，不真睡）。"""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class TestCancellableSleep:
    def test_sleep_full_returns_true(self) -> None:
        """睡满返回 True；分片时长累计等于预算，尾片截断为剩余量。"""
        rec = SleepRecorder()
        assert cancellable_sleep(0.25, None, slice_s=0.1, sleep=rec) is True
        assert len(rec.calls) == 3
        assert rec.calls[:2] == [0.1, 0.1]  # 整片
        assert rec.calls[2] == pytest.approx(0.05)  # 尾片 = min(slice, remaining)
        assert sum(rec.calls) == pytest.approx(0.25)

    def test_zero_or_negative_returns_true_without_sleep(self) -> None:
        """seconds<=0 无睡眠窗口：直接 True（默认 sleep 注入路径也不被调用）。"""
        rec = SleepRecorder()
        assert cancellable_sleep(0.0, None, sleep=rec) is True
        assert cancellable_sleep(-1.0, None, sleep=rec) is True
        assert rec.calls == []

    def test_pre_cancelled_returns_false_without_sleep(self) -> None:
        """进入前令牌已置：首个分片前即返回 False，零 sleep 调用。"""
        tok = CancelToken()
        tok.cancel()
        rec = SleepRecorder()
        assert cancellable_sleep(1.0, tok, sleep=rec) is False
        assert rec.calls == []

    def test_cancel_mid_sleep_returns_false_after_one_slice(self) -> None:
        """睡眠中途取消（注入 sleep 回调内置令牌）：只睡一个 slice 即返回 False。

        取消后最长滞留一个 slice 而非整段预算——F-1 停止引擎的关键性质。
        """
        tok = CancelToken()
        rec = SleepRecorder()

        def _sleep_and_cancel(seconds: float) -> None:
            rec.calls.append(seconds)
            if len(rec.calls) == 1:
                tok.cancel()  # 首片睡完即取消

        assert cancellable_sleep(10.0, tok, slice_s=0.1, sleep=_sleep_and_cancel) is False
        assert rec.calls == [0.1]  # 未睡满 10s 预算，只睡了一个分片

    def test_none_token_never_cancels(self) -> None:
        """cancel=None（无令牌可查）：任何时长都睡满返回 True。"""
        rec = SleepRecorder()
        assert cancellable_sleep(0.1, None, slice_s=0.03, sleep=rec) is True
        assert len(rec.calls) == 4
        assert rec.calls[-1] == pytest.approx(0.01)

    def test_default_slice_is_tenth_of_second(self) -> None:
        """默认 slice_s=0.1：0.2s 预算分两整片（不传 slice 参数）。"""
        rec = SleepRecorder()
        assert cancellable_sleep(0.2, None, sleep=rec) is True
        assert rec.calls == [0.1, 0.1]
