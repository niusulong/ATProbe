#!/usr/bin/env python3
"""虚拟 AT 应答器的自检（无需实串口、无需 com0com）.

直接对 AtResponder 喂指令，断言回包帧格式与正文，验证：
1. 终结符识别（connection.py 依赖的 OK/ERROR 结尾 + \\r\\n）
2. examples/testcases/ 用到的关键指令（AT+CSQ 的 rssi、AT+CEREG? 的 stat）
3. 提取器正则能在回包里命中（复用 ATProbe 的 connection 取帧逻辑）

运行：uv run python tools/vsim/selftest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让脚本既能独立运行，也能复用项目源
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from atprobe.infra.serial.atresponder import CRLF, AtResponder  # noqa: E402


def _frame_lines(frame: bytes) -> list[str]:
    return [ln.decode("utf-8", "replace") for ln in frame.split(CRLF) if ln]


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  ✗ FAIL: {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def main() -> int:
    print("== AtResponder 自检 ==")
    r = AtResponder(rssi=23, cereg=1)

    # 1) AT → 回显 + OK
    frame = r.respond("AT")
    lines = _frame_lines(frame)
    _assert("AT" in lines, "AT 回显存在")
    _assert(lines[-1] == "OK", "AT 以 OK 结尾")

    # 2) AT+CSQ → +CSQ: 23,99 且能被用例正则命中
    frame = r.respond("AT+CSQ")
    lines = _frame_lines(frame)
    _assert(any(ln.startswith("+CSQ:") for ln in lines), "AT+CSQ 返回 +CSQ 行")
    import re

    csq_line = next(ln for ln in lines if ln.startswith("+CSQ:"))
    m = re.search(r"\+CSQ:\s*(\d+)", csq_line)
    _assert(m is not None and int(m.group(1)) >= 10, f"rssi 提取值 >=10（满足用例断言）：{m.group(1) if m else None}")

    # 3) AT+CEREG? → +CEREG: <n>,<stat>，stat 正则命中且 ==1
    frame = r.respond("AT+CEREG?")
    lines = _frame_lines(frame)
    cereg_line = next((ln for ln in lines if ln.startswith("+CEREG:")), "")
    m = re.search(r"CEREG:\s*\d,(\d)", cereg_line)
    _assert(m is not None and m.group(1) == "1", f"CEREG stat 提取==1（已注册）：{cereg_line}")

    # 4) AT+CPIN? → +CPIN: READY
    frame = r.respond("AT+CPIN?")
    _assert("+CPIN: READY" in _frame_lines(frame), "AT+CPIN? 返回 READY")

    # 5) AT+CGDCONT? → 至少一行 +CGDCONT
    frame = r.respond("AT+CGDCONT?")
    _assert(any(ln.startswith("+CGDCONT:") for ln in _frame_lines(frame)), "AT+CGDCONT? 返回 PDP 上下文")

    # 6) 写指令 AT+CEREG=1 → OK 且 n 被置位
    _assert(r.respond("AT+CEREG=1").rstrip().endswith(b"OK"), "AT+CEREG=1 返回 OK")
    frame = r.respond("AT+CEREG?")
    cereg_line = next((ln for ln in _frame_lines(frame) if ln.startswith("+CEREG:")), "")
    _assert(cereg_line.startswith("+CEREG: 1,"), "AT+CEREG=1 后查询 n=1")

    # 7) 未知指令 → ERROR
    _assert(r.respond("AT+UNKNOWN=1").rstrip().endswith(b"ERROR"), "未知指令返回 ERROR")

    # 8) rssi 可配
    r2 = AtResponder(rssi=8, cereg=2)
    csq = next(ln for ln in _frame_lines(r2.respond("AT+CSQ")) if ln.startswith("+CSQ:"))
    _assert("+CSQ: 8,99" in csq, "rssi 参数可配置为 8")

    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
