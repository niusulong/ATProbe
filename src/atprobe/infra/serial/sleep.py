"""可取消睡眠原语（设计 §4.5：单一实现——retry/poll/重连/压测 interval 全部换用）.

分片睡眠、片间查取消令牌：取消时提前返回 False（不抛——调用方循环头的既有
取消检查接管）；睡满返回 True。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from atprobe.infra.serial.interfaces import CancelToken


def cancellable_sleep(
    seconds: float,
    cancel: CancelToken | None,
    *,
    slice_s: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """睡 seconds 秒；期间 cancel 触发立即返回 False，睡满返回 True.

    seconds<=0 无睡眠窗口，直接返回 True（零时长不存在取消检查点）。其余按
    slice_s 分片睡、片间轮询令牌——取消后最长滞留一个 slice 而非整段预算。
    不抛 OperationCancelled：提前返回 False 即「未睡满」，取消语义由调用方
    循环头的既有取消检查（或断连错误路径）接管，避免双层取消处理。
    """
    remaining = seconds
    while remaining > 0:
        if cancel is not None and cancel.cancelled:
            return False
        d = min(slice_s, remaining)
        sleep(d)
        remaining -= d
    return True
