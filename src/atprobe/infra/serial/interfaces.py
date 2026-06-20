"""M1 串口操作接口（Protocol，接口隔离原则 ISP，TSD §5.2.2）.

高层（M3 引擎、M6 手动调试）依赖这些抽象接口而非 pyserial 具体类。
测试可注入 FakeSerial 实现这些接口（TSD §8.5）。

按消费方需要拆分（ISP）：
    ICommandSender     发送命令并等待完整响应（直接输入，§3.1）
    IConnectionManager 连接管理 / 端口枚举
    IURCSubscriber     URC 订阅（§6）
    IDataObserver      原始字节流监听（M6 §6.2 实时监控）

注：数据流分块发送（§3.2）由 DataStreamSender 直接操作连接实现，未抽象为 Protocol。
原始 RX 字节流订阅（手动调试/实时监控，M6 §6.2）经 SerialConnection.add_rx_observer
提供；write_command（只写不等响应，供手动调试）为 SerialConnection/PortManager 的具体方法。

所有阻塞操作接收 CancelToken（M1 §4.3 操作取消）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from atprobe.infra.serial.config import PortConfig


# ---------------------------------------------------------------------------
# 取消令牌（M1 §4.3 / TSD §6.4）
# ---------------------------------------------------------------------------
class CancelToken:
    """线程安全的取消令牌，包装 threading.Event.

    多个阻塞操作可共享同一令牌；stop(mode) 触发后，所有持有该令牌的阻塞操作立即取消。
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def clear(self) -> None:
        self._event.clear()


# ---------------------------------------------------------------------------
# 响应（M1 §7.5：M1 判定响应完整后交付）
# ---------------------------------------------------------------------------
class ResponseStatus(str, Enum):
    COMPLETE = "complete"  # 收到终结标志（OK/ERROR 等）的完整响应
    TIMEOUT = "timeout"  # 完整但超时
    ERROR = "error"  # 发送失败 / 断连等异常
    CANCELLED = "cancelled"  # 被取消（stop）


@dataclass(frozen=True)
class Response:
    """M1 交付给上层的完整响应（M1 §7.5）.

    text   完整响应文本（已按终结标志或超时界定边界）。
    status 完整性状态。
    error  异常时的原因（ERROR/CANCELLED/TIMEOUT 时填写）。
    """

    text: str
    status: ResponseStatus = ResponseStatus.COMPLETE
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否成功收到（完整或超时，非异常/取消）—— 引擎据此决定是否做 extract/assert."""
        return self.status in (ResponseStatus.COMPLETE, ResponseStatus.TIMEOUT)


# ---------------------------------------------------------------------------
# 端口信息（M5 list ports）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PortInfo:
    name: str
    description: str = ""
    in_use: bool = False


# ---------------------------------------------------------------------------
# URC（§6）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class URCEvent:
    port: str
    text: str
    rule_name: str = ""
    timestamp: str = ""


URCHandler = Callable[[URCEvent], None]


# ---------------------------------------------------------------------------
# 协议定义
# ---------------------------------------------------------------------------
@runtime_checkable
class ICommandSender(Protocol):
    """发送命令（直接输入，§3.1）并等待完整响应."""

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        """发送命令（不含结束符，由实现按 PortConfig.terminator 自动追加）并等待完整响应.

        Args:
            port: 目标端口名（须已连接）。
            command: 命令文本（不含结束符）。
            timeout: 单次响应超时（秒）；None 用端口默认。
            cancel: 取消令牌；触发后阻塞立即返回 Response(status=CANCELLED)。
        """
        ...


@runtime_checkable
class IConnectionManager(Protocol):
    """连接管理（M1 §4.1）/ 端口枚举（M5 list ports）."""

    def open(self, config: PortConfig) -> None:
        """打开端口（已打开则抛错）."""
        ...

    def close(self, port: str) -> None:
        """关闭端口并释放资源（幂等）."""
        ...

    def is_connected(self, port: str) -> bool: ...

    def enumerate_ports(self) -> list[PortInfo]:
        """枚举系统可用串口（含占用检测，M5 list ports）."""
        ...

    def config_of(self, port: str) -> PortConfig: ...


@runtime_checkable
class IURCSubscriber(Protocol):
    """URC 订阅（§6）."""

    def subscribe_urc(self, port: str, handler: URCHandler) -> Any:
        """订阅端口 URC，返回订阅句柄（用于取消订阅）."""
        ...

    def unsubscribe_urc(self, handle: Any) -> None: ...


@runtime_checkable
class IDataObserver(Protocol):
    """原始字节流监听（M6 §6.2 实时监控，独立于命令收发）."""

    def observe(self, port: str, sink: Callable[[str, bytes, float], None]) -> Any:
        """订阅端口原始字节流。sink(direction, data, ts)：direction 'TX'/'RX'."""
        ...

    def stop_observe(self, handle: Any) -> None: ...
