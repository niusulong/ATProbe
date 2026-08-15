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


class OperationCancelled(SerialError):
    """阻塞操作被取消（M1 §4.3，stop 触发）."""
