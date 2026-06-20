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


class PortDisconnected(SerialError):
    """串口断连（M1 §8.1，触发自动重连）."""

    def __init__(self, port: str, reason: str = "") -> None:
        self.port = port
        super().__init__(f"端口 {port} 断连：{reason}" if reason else f"端口 {port} 断连")


class PortReconnectFailed(SerialError):
    """重连超限（M1 §8.1）."""

    def __init__(self, port: str, attempts: int) -> None:
        self.port = port
        self.attempts = attempts
        super().__init__(f"端口 {port} 重连 {attempts} 次仍失败")


class SendError(SerialError):
    """发送失败（M1 §8.1）."""

    def __init__(self, port: str, reason: str) -> None:
        self.port = port
        super().__init__(f"端口 {port} 发送失败：{reason}")


class DataSourceError(SerialError):
    """数据源文件不存在/读取失败（M1 §8.1）."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        super().__init__(f"数据源 {path}：{reason}")


class OperationCancelled(SerialError):
    """阻塞操作被取消（M1 §4.3，stop 触发）."""
