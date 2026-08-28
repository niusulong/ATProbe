"""锁纪律测试：持锁阻塞式验证（F-3 及批 2a Task 7 追加）.

跨线程 dict 变更竞态难以稳定复现，改为确定性验证锁纪律：主线程持有 _lock 时，
被测方法必须阻塞等待（未获锁即返回 = 无并发防御）。

- F-3：enumerate_ports 持锁收集连接集合（并发 open/close 不再 RuntimeError）；
- Task 7：set_case_log 入锁；configs() 快照持锁收集（替代 GUI 裸迭代 _configs）；
  另含 FakePortManager 契约对齐断言（close_all 清 _log_files / emit_urc 带
  timestamp，对齐真实 _dispatch_urc）。
"""

from __future__ import annotations

import threading
from pathlib import Path

from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import URCEvent
from atprobe.infra.serial.portmanager import PortManager


def test_enumerate_ports_acquires_lock() -> None:
    pm = PortManager()
    pm._lock.acquire()  # noqa: SLF001 - 测试直接持锁，验证 enumerate_ports 会等待
    done = threading.Event()

    def _call() -> None:
        pm.enumerate_ports()
        done.set()

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    try:
        assert not done.wait(0.2), "enumerate_ports 未获取 _lock 即返回——并发防御缺失(F-3)"
    finally:
        pm._lock.release()
    assert done.wait(2.0)
    t.join(timeout=2.0)


def test_set_case_log_acquires_lock() -> None:
    """Task 7：set_case_log 须持 _lock（与 open/close 对 _log_files 的变更互斥）."""
    pm = PortManager()
    pm._lock.acquire()  # noqa: SLF001 - 测试直接持锁，验证 set_case_log 会等待
    done = threading.Event()
    threading.Thread(
        target=lambda: (pm.set_case_log("COM1", None), done.set()), daemon=True
    ).start()
    try:
        assert not done.wait(0.2), "set_case_log 未获取 _lock 即返回"
    finally:
        pm._lock.release()
    assert done.wait(2.0)


def test_configs_returns_snapshot_under_lock() -> None:
    """Task 7：configs() 持锁收集 _configs 快照（GUI connected_ports 的安全视图）."""
    pm = PortManager()
    pm._lock.acquire()  # noqa: SLF001 - 测试直接持锁，验证 configs 会等待
    done = threading.Event()
    threading.Thread(target=lambda: (pm.configs(), done.set()), daemon=True).start()
    try:
        assert not done.wait(0.2), "configs() 未获取 _lock 即返回"
    finally:
        pm._lock.release()
    assert done.wait(2.0)


def test_fake_close_all_clears_log_files() -> None:
    """Fake 对齐：close_all 后 _log_files 为空（真实 close_all 经 close(p) 逐口清）."""
    fake = FakePortManager()
    fake.set_case_log("COM3", Path("case.log"))
    fake.close_all()
    assert not fake._log_files, "Fake close_all 未清除 _log_files（对齐真实 close 路径）"  # noqa: SLF001


def test_fake_emit_urc_carries_timestamp() -> None:
    """Fake 对齐：emit_urc 事件 timestamp 非空（真实 _dispatch_urc 已填时间戳）."""
    fake = FakePortManager()
    events: list[URCEvent] = []
    fake.subscribe_urc("COM3", events.append)
    fake.emit_urc("COM3", "+CEREG: 1")
    assert events, "URC handler 未被调用"
    assert events[0].timestamp, "Fake emit_urc 未填 timestamp（真实 _dispatch_urc 已填）"
