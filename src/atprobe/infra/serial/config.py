"""M1 串口配置与数据结构（REQ-M1 §2.1 连接级参数、§3.2 数据流参数）.
"""

from __future__ import annotations

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
        """解析紧凑写法 ``8N1`` / ``7E2``（M5 §3.3 FRAME）."""
        s = compact.strip()
        if len(s) != 3:
            raise ValueError(f"帧格式应为 3 字符紧凑写法（如 8N1），实际：{compact!r}")
        db_ch, par_ch, sb_ch = s[0], s[1], s[2]
        try:
            databits = int(db_ch)
        except ValueError as exc:
            raise ValueError(f"数据位应为数字，实际：{db_ch!r}") from exc
        if databits not in (5, 6, 7, 8):
            raise ValueError(f"数据位应为 5/6/7/8，实际：{databits}")
        try:
            parity = Parity(par_ch.upper())
        except ValueError as exc:
            raise ValueError(
                f"校验位应为 N/E/O/M/S，实际：{par_ch!r}"
            ) from exc
        if sb_ch == "1":
            stopbits = 1.0
        elif sb_ch == "2":
            stopbits = 2.0
        elif sb_ch == "1.5" or s.endswith("1.5"):
            stopbits = 1.5
        else:
            raise ValueError(f"停止位应为 1/1.5/2，实际：{sb_ch!r}")
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
