#!/usr/bin/env python3
"""COM5 真实硬件端到端冒烟测试（核心收发链路，无 GUI/无头依赖）.

复刻 GUI manual_debug / monitor 共用的底层链路（PortManager）：
  1. pm.open(PortConfig(COM5))                → 连接建立
  2. pm.subscribe_rx(COM5, rx_sink)           → 读线程就绪
  3. pm.subscribe_tx(COM5, tx_sink)           → TX 观察者就绪
  4. pm.write_command(COM5, "AT")             → 字节写出，TX 观察者收到 "AT"
  5. 读线程收到模组应答 → rx_sink 收到含 "OK" 的字节
  6. pm.close(COM5)                          → 干净退出

判定：rx_sink 收到含 "OK" 的字节 + tx_sink 收到 "AT" → PASS。
这等价于 GUI manual_debug 打开 COM5 后发 AT 看到响应。

用法：
    uv run python tools/e2e_com5.py            # 默认 COM5
    uv run python tools/e2e_com5.py COM6
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from atprobe.infra.serial.config import FlowControl, FrameFormat, PortConfig  # noqa: E402
from atprobe.infra.serial.portmanager import PortManager  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
BAUD = 115200


def main() -> int:
    pm = PortManager()
    rx_chunks: list[bytes] = []
    tx_chunks: list[bytes] = []
    rx_lock = threading.Lock()

    def rx_sink(chunk: bytes) -> None:
        with rx_lock:
            rx_chunks.append(chunk)

    def tx_sink(chunk: bytes) -> None:
        tx_chunks.append(chunk)

    # 1. open（镜像 MainWindow.open_port 的 cfg 构造）
    try:
        cfg = PortConfig(
            name=PORT,
            baudrate=BAUD,
            frame=FrameFormat.parse("8N1"),
            flow_control=FlowControl("none"),
        )
        pm.open(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: open 抛异常: {type(e).__name__}: {e}")
        return 2
    print(f"[1] open({PORT}@{BAUD},8N1) OK | connected={pm.is_connected(PORT)}")

    # 2/3. subscribe
    try:
        rx_handle = pm.subscribe_rx(PORT, rx_sink)
        tx_handle = pm.subscribe_tx(PORT, tx_sink)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: subscribe 抛异常: {type(e).__name__}: {e}")
        pm.close(PORT)
        return 2
    print("[2] subscribe_rx / subscribe_tx OK")

    # 4. write AT（write_command 无返回值；底层失败会抛异常）
    try:
        pm.write_command(PORT, "AT")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: write_command 抛异常: {type(e).__name__}: {e}")
        pm.close(PORT)
        return 2
    print('[3] write_command("AT") OK')

    # 5. 等响应（最多 2.5s）
    deadline = time.time() + 2.5
    got_ok = False
    while time.time() < deadline:
        time.sleep(0.05)
        with rx_lock:
            joined = b"".join(rx_chunks)
        if b"OK" in joined:
            got_ok = True
            break

    # 6. close + 撤销订阅
    try:
        pm.unsubscribe_rx(rx_handle)
        pm.unsubscribe_tx(tx_handle)
    except Exception as e:  # noqa: BLE001
        print(f"warn: unsubscribe 异常: {type(e).__name__}: {e}")
    try:
        pm.close(PORT)
    except Exception as e:  # noqa: BLE001
        print(f"warn: close 异常: {type(e).__name__}: {e}")
    print("[4] close + unsubscribe OK")

    with rx_lock:
        rx_bytes = b"".join(rx_chunks)
    tx_text = b"".join(tx_chunks).decode("utf-8", "replace")

    print("\n=== RX 观察者收到的字节（原始）===")
    print(repr(rx_bytes))
    print("\n=== TX 观察者收到的字节（原始）===")
    print(repr(b"".join(tx_chunks)))

    tx_has_at = "AT" in tx_text
    print("\n--- 断言 ---")
    print(f"  RX 含 'OK': {'YES' if got_ok else 'NO'}")
    print(f"  TX 含 'AT': {'YES' if tx_has_at else 'NO'}")

    if got_ok and tx_has_at:
        print("\nPASS: COM5 流式收发链路正常（TX→AT，RX→OK，双向观察者均生效）")
        return 0
    print("\nFAIL: 收发链路异常")
    return 1


if __name__ == "__main__":
    sys.exit(main())
