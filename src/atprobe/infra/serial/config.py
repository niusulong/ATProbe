"""M1 串口配置与数据结构（REQ-M1 §2.1 连接级参数、§3.2 数据流参数）."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# §2.1 连接级参数
# ---------------------------------------------------------------------------
class Parity(str, Enum):
    NONE = "N"
    EVEN = "E"
    ODD = "O"
    MARK = "M"
    SPACE = "S"


class FlowControl(str, Enum):
    NONE = "none"
    RTS_CTS = "rts_cts"
    XON_XOFF = "xon_xoff"


class Terminator(str, Enum):
    """命令结束符（M1 §2.1：仅 \\r / \\r\\n 两种枚举，AT 标准）."""

    CR = "\r"
    CRLF = "\r\n"


@dataclass(frozen=True)
class FrameFormat:
    """帧格式：数据位/校验位/停止位（紧凑 8N1 等）."""

    databits: int = 8  # 5/6/7/8
    parity: Parity = Parity.NONE
    stopbits: float = 1  # 1 / 1.5 / 2

    @classmethod
    def parse(cls, compact: str) -> FrameFormat:
        """解析紧凑写法 ``8N1`` / ``7E2`` / ``8N1.5``（M5 §3.3 FRAME）."""
        s = compact.strip()
        # F-4 修复：旧实现的 len(s)!=3 早退使 "8N1.5" 永远解析失败、1.5 停止位
        # 分支不可达（与 __str__ 的 round-trip 断裂）。改为正则整体解析。
        m = re.fullmatch(r"([5-8])([NEOMSneoms])(1(?:\.5)?|2)", s)
        if m is None:
            raise ValueError(f"帧格式应为紧凑写法（如 8N1 / 8N1.5 / 7E2），实际：{compact!r}")
        databits = int(m.group(1))
        parity = Parity(m.group(2).upper())
        sb = m.group(3)
        stopbits = 1.5 if sb == "1.5" else float(sb)
        return cls(databits=databits, parity=parity, stopbits=stopbits)

    def __str__(self) -> str:  # noqa: D401
        sb = "1.5" if self.stopbits == 1.5 else str(int(self.stopbits))
        return f"{self.databits}{self.parity.value}{sb}"


@dataclass(frozen=True)
class PortConfig:
    """串口连接级配置（M1 §2.1）."""

    name: str  # COM3 / /dev/ttyUSB0
    baudrate: int = 115200
    frame: FrameFormat = field(default_factory=FrameFormat)
    flow_control: FlowControl = FlowControl.NONE
    terminator: Terminator = Terminator.CRLF
    # 行为级参数（§2.2）—— 这些在连接后也可即时改，但归集于此便于传递
    response_timeout: float = 5.0  # 秒（步骤级默认超时来源）
    send_interval_ms: int = 0
    # 噪声 URC 过滤（正则字符串元组，匹配「行」内容）：匹配行在任何模式下都派发给
    # URC 订阅者（不丢失），且从交付给断言的响应文本中整段剥离（含前后紧邻空行，
    # 不污染字节级严格断言）。用于设备存在持续性主动上报的场景（如 N58 开启
    # AT$MYGPSPOS=<TYPE>,1 循环定位输出后，$MYGPSPOS 行每秒到达）。
    # 默认空 = 不剥离（存量行为；URC 行仍按前缀识别正常派发）。
    urc_filter: tuple[str, ...] = ()
    # 重连参数（§4.2）
    reconnect_interval_s: float = 3.0
    reconnect_max_retries: int = 10
    reconnect_safety_threshold: int = 3  # 同用例连续断连安全阀


# ---------------------------------------------------------------------------
# §3.2 数据流参数（对应 M2 DataInput 的基础设施层表达）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DataStreamSpec:
    """数据流发送规格（M1 §3.2）.

    source  字件路径 或 内联字节（二选一，已在外层解析）。
    chunk_threshold / chunk_size / chunk_interval / append_terminator 同 M2。
    """

    data: bytes  # 已解析为字节的数据（文件或内联在此前读取）
    chunk_threshold: int = 4096
    chunk_size: int = 1024
    chunk_interval_ms: int = 50
    append_terminator: bool = False

    def __post_init__(self) -> None:
        # F-5 修复：chunk 参数此前无校验——chunk_size<=0 使 send_data_stream
        # 死循环（offset 不前进）、chunk_interval_ms<0 使 sleep 抛 ValueError。
        if self.chunk_size < 1:
            raise ValueError(f"chunk_size 须 ≥1，实际：{self.chunk_size}")
        if self.chunk_threshold < 1:
            raise ValueError(f"chunk_threshold 须 ≥1，实际：{self.chunk_threshold}")
        if self.chunk_interval_ms < 0:
            raise ValueError(f"chunk_interval_ms 须 ≥0，实际：{self.chunk_interval_ms}")
