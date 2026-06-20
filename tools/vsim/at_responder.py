#!/usr/bin/env python3
"""虚拟 AT 模组应答器（无实板联调用）—— 串口 I/O 版.

配合虚拟串口对（com0com / socat）使用：ATProbe 连一端，本脚本守另一端，
把 ATProbe 发来的 AT 指令按真实模组的帧格式回包，从而在无开发板的情况下
跑通 M1 串口 → M3 引擎 → M4 报告全链路。

响应生成逻辑（``AtResponder``）已上移到库内 ``atprobe/infra/serial/atresponder.py``，
本脚本只负责串口读写 + CLI；进程内零驱动模式（``VsimPortManager``，CLI ``--vsim``）
与自检（``selftest.py``）共用同一份逻辑。

用法：
    # com0com 建好对后（如 COM20 <-> COM21），ATProbe 连 COM20，本脚本守 COM21：
    python at_responder.py COM21
    python at_responder.py COM21 --rssi 15 --cereg 1 --urc-interval 5

参数：
    --rssi        CSQ 信号强度 0..31（默认 23，需 >=10 才过 network 用例）
    --cereg       CEREG 注册状态 0..5（默认 1=已注册，需 !=0/2 才算成功）
    --baud        波特率（默认 115200，需与 ATProbe 端一致）
    --urc-interval  随机 URC 上报间隔秒（0=关闭，默认 0）
    --quiet       不打印每个收发行
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from pathlib import Path

# 让脚本能 import 库内模块（独立运行时补 src 到 path）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from atprobe.infra.serial.atresponder import CRLF, AtResponder, _line  # noqa: E402

try:
    import serial  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "缺少 pyserial，请在 ATProbe 环境里运行：uv run python tools/vsim/at_responder.py ...\n"
    )
    raise


def _read_command(ser: "serial.Serial") -> str:
    """阻塞读取一条 AT 指令.

    ATProbe 总是以 ``\\r\\n`` 结尾发送，故按行读取到 ``\\n`` 即一条完整指令，
    再剥掉尾部的 ``\\r``。对裸 ``\\r`` 终结符同样兼容（读到 \\r 后下一字节
    非 \\n 时也能结束）。
    """
    buf = bytearray()
    while True:
        ch = ser.read(1)
        if not ch:
            # 读超时无数据：继续等（不返回半截，避免把噪声当指令）
            continue
        if ch == b"\n":
            break
        if ch == b"\r":
            # 看紧跟字节：是 \n 则正常成对结束；否则把当前行就当作结束
            # （裸 \r 终结符场景），并把那个非 \n 字节留到下一轮读。
            nxt = ser.read(1)
            if nxt != b"\n" and nxt:
                buf.extend(nxt)
            break
        buf.extend(ch)
    # 剥掉误累积的尾部 \r（按 \n 结束时 \r 可能被 extend 进来）
    return buf.decode("utf-8", errors="replace").rstrip("\r")


def main() -> int:
    ap = argparse.ArgumentParser(description="虚拟 AT 模组应答器")
    ap.add_argument("port", help="串口设备名，如 COM21 / /dev/pts/3")
    ap.add_argument("--baud", type=int, default=115200, help="波特率（默认 115200）")
    ap.add_argument("--rssi", type=int, default=23, help="CSQ 信号 0..31（默认 23）")
    ap.add_argument("--cereg", type=int, default=1, help="CEREG 注册状态 0..5（默认 1）")
    ap.add_argument("--urc-interval", type=float, default=0.0, help="随机 URC 间隔秒（0=关闭）")
    ap.add_argument("--quiet", action="store_true", help="不打印收发行")
    args = ap.parse_args()

    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr, flush=True))

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.5)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"打开 {args.port} 失败：{exc}\n")
        return 2

    res = AtResponder(rssi=args.rssi, cereg=args.cereg)
    log(f"[vsim] {args.port} @ {args.baud}bps | rssi={res.rssi} cereg={res.cereg} "
        f"urc={'on ' + str(args.urc_interval) + 's' if args.urc_interval else 'off'}")

    stop = threading.Event()

    def urc_injector() -> None:
        if not args.urc_interval:
            return
        urcs = [
            "+CEREG: 1",
            "+CMTI: \"ME\",12",
            "+CGEV: NW DETACH",
            "RING",
        ]
        while not stop.is_set():
            time.sleep(args.urc_interval + random.random())
            try:
                ser.write(_line(random.choice(urcs)))
                log(f"[vsim] <URC> {random.choice(urcs)}")
            except Exception:  # noqa: BLE001
                break

    t = threading.Thread(target=urc_injector, daemon=True)
    t.start()

    try:
        while True:
            cmd = _read_command(ser)
            if not cmd.strip():
                continue
            log(f"[vsim] > {cmd!r}")
            frame = res.respond(cmd)
            if frame:
                ser.write(frame)
                for line in frame.split(CRLF):
                    if line:
                        log(f"[vsim] < {line.decode('utf-8', 'replace')}")
    except KeyboardInterrupt:
        log("[vsim] 收到 Ctrl+C，退出。")
    finally:
        stop.set()
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
