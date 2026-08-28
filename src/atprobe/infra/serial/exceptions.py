"""M1 串口异常体系（M1 §8，TSD §5.4）."""

from __future__ import annotations


class SerialError(Exception):
    """M1 异常根类."""


class PortOpenError(SerialError):
    """串口打开失败（M1 §8.1）."""

    def __init__(self, port: str, reason: str) -> None:
        self.port = port
        self.reason = reason
        super().__init__(f"端口 {port} 打开失败：{reason}")


class SendError(SerialError):
    """发送失败（M1 §8.1）."""

    def __init__(self, port: str, reason: str) -> None:
        self.port = port
        super().__init__(f"端口 {port} 发送失败：{reason}")


class PortBusyError(SerialError):
    """端口命令互斥撞锁（并发发送不支持，P1-3/P1-8）."""

    def __init__(self, port: str, reason: str) -> None:
        # 结构化端口名（GUI/MCP 据此定位冲突端口；消息格式不变——批 3 前只拼了 message）
        self.port = port
        super().__init__(f"[{port}] {reason}")


class InvalidArgumentError(SerialError):
    """调用方参数错误（expect/wait_urc 互斥或正则非法）.

    SerialError 子类：MCP 层据此区分 INVALID_INPUT 而非 DEVICE_ERROR
    （批 3 T9 接线）；既有 catch SerialError 的调用方行为不变。
    """


class OperationCancelled(SerialError):
    """阻塞操作被取消（M1 §4.3，stop 触发）."""
