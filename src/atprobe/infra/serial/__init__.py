"""M1 串口通信管理（REQ-M1）.

子模块：
    interfaces — ISerialPort 族 Protocol（接口隔离，TSD §5.2.2）
    config     — PortConfig（连接级参数，M1 §2.1）/ DataStreamSpec（§3.2）
    connection — SerialConnection（pyserial 实现，连接管理 §4.1）
    receiver   — ResponseReceiver（后台读线程 + 完整性判定 §7.5）
    urc        — URCDispatcher（URC 分流 §6）
    datastream — DataStreamSender（分块发送 §3.2）
    rawlog     — RawLogger（HEX+TEXT 落盘 §7）
    portmanager — PortManager（多端口 §5、热插拔重连 §4.2）
"""
from atprobe.infra.serial.config import (
    DataStreamSpec,
    FlowControl,
    FrameFormat,
    Parity,
    PortConfig,
    Terminator,
)
from atprobe.infra.serial.interfaces import (
    CancelToken,
    ICommandSender,
    IConnectionManager,
    IURCSubscriber,
    PortInfo,
    Response,
    ResponseStatus,
    URCEvent,
)

__all__ = [
    "CancelToken",
    "DataStreamSpec",
    "FlowControl",
    "FrameFormat",
    "ICommandSender",
    "IConnectionManager",
    "IURCSubscriber",
    "Parity",
    "PortConfig",
    "PortInfo",
    "Response",
    "ResponseStatus",
    "Terminator",
    "URCEvent",
]
