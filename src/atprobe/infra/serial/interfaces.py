"""M1 串口操作接口（Protocol，接口隔离原则 ISP，TSD §5.2.2）.

高层（M3 引擎、M6 手动调试）依赖这些抽象接口而非 pyserial 具体类。
测试可注入 FakeSerial 实现这些接口（TSD §8.5）。

按消费方需要拆分（ISP）：
    ICommandSender     发送命令并等待完整响应（直接输入，§3.1）
    IConnectionManager 连接管理 / 端口枚举
    IURCSubscriber     URC 订阅（§6）

注：数据流分块发送（§3.2）经 ICommandSender.send_data 抽象（spec 携带数据与分块参数，
引擎数据步骤通道）；GUI 只写不等路径（M6 文件发送/串口助手）用具体 PortManager.write_data
（非 Protocol 成员）。原始 RX/TX 字节流订阅（手动调试/实时监控，M6 §6.2）经
SerialConnection.add_rx_observer / add_tx_observer 提供；write_command（只写不等响应，
供手动调试）为 SerialConnection/PortManager 的具体方法。

所有阻塞操作接收 CancelToken（M1 §4.3 操作取消）；取消时统一抛 ``OperationCancelled``。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from atprobe.infra.serial.config import DataStreamSpec, PortConfig


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
    CANCELLED = (
        "cancelled"  # 被取消（stop）—— 保留枚举值以兼容存量调用，新代码改抛 OperationCancelled
    )


# Response.error_kind 的取值（结构化错误分类，供上层基于枚举判定而非脆弱的字符串匹配）。
#   NONE        无错误（ok=True）
#   DISCONNECT  端口断连 / 重连失败（§4.2 热插拔路径）—— 触发断连安全阀与重发判定
#   SEND        发送侧失败（写超时、I/O 错误等）—— 不触发断连安全阀
#   TIMEOUT     响应超时（引擎侧：部分缓冲不参与断言，step_runner 产出）
ERROR_KIND_NONE = "NONE"
ERROR_KIND_DISCONNECT = "DISCONNECT"
ERROR_KIND_SEND = "SEND"
ERROR_KIND_TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class Response:
    """M1 交付给上层的完整响应（M1 §7.5）.

    text       完整响应文本（已按终结标志或超时界定边界）。
    status     完整性状态。
    error      异常时的原因（ERROR/CANCELLED/TIMEOUT 时填写）。
    error_kind 结构化错误分类（NONE/DISCONNECT/SEND）。DISCONNECT 用于断连/重连失败，
               上层据此判定安全阀与重发，避免依赖 error 文案的字符串匹配（文案改动即失效）。
    """

    text: str
    status: ResponseStatus = ResponseStatus.COMPLETE
    error: str = ""
    error_kind: str = ERROR_KIND_NONE

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
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
        pre_check: Callable[[], None] | None = None,
    ) -> Response:
        """发送命令（不含结束符，由实现按 PortConfig.terminator 自动追加）并等待完整响应.

        Args:
            port: 目标端口名（须已连接）。
            command: 命令文本（不含结束符）。
            timeout: 单次响应超时（秒）；None 用端口默认。
            wait_urc: 异步指令 URC 终结正则（可空）。非空时遇 OK 不返回，继续读到
                匹配此正则的 URC 立即返回（整段响应文本含 OK+URC）；为空时 OK 即终结。
            expect: 附加完成条件正则（可空，设计 §2.3）。非空时对发送后的原始字节流
                做字节级匹配（不依赖换行），命中即交付 COMPLETE（响应文本=缓冲至命中
                点，优先于终结行判定）；与 wait_urc 互斥，同传或正则非法由实现抛
                ``InvalidArgumentError``（``SerialError`` 子类）。
            cancel: 取消令牌；触发后阻塞操作立即抛 ``OperationCancelled``（与 Fake/vsim 一致，
                统一取消语义，上层据此判 INTERRUPTED 而非 FAIL）。
            pre_check: 获命令锁后、状态突变前调用的回调（设计 §3.2"锁内重检"），
                供上层（MCP）做占用重检，消除 check-then-act TOCTOU（批 3 接线）。
                抛异常则透传且不发送（每次实际发送——含断连重发——前各执行一次）。
                send_data 不设此参数（数据路径无 MCP 直连需求）。
        """
        ...

    def send_data(
        self,
        port: str,
        spec: DataStreamSpec,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        """发送数据流（分块，持端口命令锁整个周期）并等待响应（设计 §2.3）.

        Args 与返回语义同 send_command；spec 携带数据与分块参数。
        断连语义差异：发送前重连尝试与 send_command 一致，但**无断连自动重发**
        （数据流不续传——设备可能已收部分字节，重发会当 AT 命令解析）。
        """
        ...


@runtime_checkable
class IConnectionManager(Protocol):
    """连接管理（M1 §4.1）/ 端口枚举（M5 list ports）."""

    def open(self, config: PortConfig) -> None:
        """打开端口；已用相同配置打开则幂等返回，配置不同则抛错."""
        ...

    def close(self, port: str) -> None:
        """关闭端口并释放资源（幂等）."""
        ...

    def is_connected(self, port: str) -> bool: ...

    def enumerate_ports(self) -> list[PortInfo]:
        """枚举系统可用串口（含占用检测，M5 list ports）."""
        ...

    def config_of(self, port: str) -> PortConfig:
        """返回端口配置；端口未知时返回默认 PortConfig（不抛错，便于安全阀回退）."""
        ...


@runtime_checkable
class IURCSubscriber(Protocol):
    """URC 订阅（§6）."""

    def subscribe_urc(self, port: str, handler: URCHandler) -> Any:
        """订阅端口 URC，返回订阅句柄（用于取消订阅）."""
        ...

    def unsubscribe_urc(self, handle: Any) -> None: ...
