"""F-3：enumerate_ports 持锁收集连接集合（并发 open/close 不再 RuntimeError）.

跨线程 dict 变更竞态难以稳定复现，改为确定性验证锁纪律：主线程持有 _lock 时，
enumerate_ports 必须阻塞等待（未获锁即返回 = 无并发防御）。
"""

from __future__ import annotations

import threading

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
