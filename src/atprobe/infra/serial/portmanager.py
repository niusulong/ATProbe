"""M1 多端口管理与重连（REQ-M1 §4.2 热插拔、§5 多串口）.

PortManager 实现 IConnectionManager / ICommandSender / IURCSubscriber 接口，
内部管理多个 SerialConnection。重连策略见 §4.2（固定间隔、最大重试、安全阀）。

执行模型为串行（M1 §5.1）：一个时刻只有一个步骤在执行，端口间无并发竞争。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import (
    PortOpenError,
)
from atprobe.infra.serial.interfaces import (
    CancelToken,
    ICommandSender,
    IConnectionManager,
    IURCSubscriber,
    PortInfo,
    Response,
    ResponseStatus,
    URCHandler,
)
from atprobe.infra.serial.rawlog import RawLogger

try:
    from serial.tools import list_ports  # type: ignore[import-not-found]

    _HAS_LISTPORTS = True
except ImportError:  # pragma: no cover
    list_ports = None  # type: ignore[assignment]
    _HAS_LISTPORTS = False


class PortManager(ICommandSender, IConnectionManager, IURCSubscriber):
    """多端口管理器（实现 M1 对外接口族）."""

    def __init__(
        self,
        raw_logger: RawLogger | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._connections: dict[str, SerialConnection] = {}
        self._configs: dict[str, PortConfig] = {}
        self._raw_logger = raw_logger
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        # 用例级日志文件绑定：port -> Path（由引擎在每用例开始时设置）
        self._log_files: dict[str, Path | None] = {}

    # ------------------------------------------------------------------
    # §4.1 连接管理
    # ------------------------------------------------------------------
    def open(self, config: PortConfig) -> None:
        with self._lock:
            if config.name in self._connections:
                raise PortOpenError(config.name, "端口已打开")
            conn = SerialConnection(config, raw_logger=self._raw_logger, clock=self._clock)
            conn.open()
            self._connections[config.name] = conn
            self._configs[config.name] = config

    def close(self, port: str) -> None:
        with self._lock:
            conn = self._connections.pop(port, None)
            self._configs.pop(port, None)
            self._log_files.pop(port, None)
        if conn is not None:
            conn.close()

    def close_all(self) -> None:
        with self._lock:
            ports = list(self._connections.keys())
        for p in ports:
            self.close(p)

    def is_connected(self, port: str) -> bool:
        conn = self._connections.get(port)
        return conn is not None and conn.is_connected

    def config_of(self, port: str) -> PortConfig:
        return self._configs[port]

    def enumerate_ports(self) -> list[PortInfo]:
        """枚举系统串口（M5 list ports）."""
        if not _HAS_LISTPORTS:  # pragma: no cover
            return []
        result: list[PortInfo] = []
        for info in list_ports.comports():  # type: ignore[union-attr]
            in_use = False
            try:
                # 尝试独占打开判断占用
                import serial as _serial  # type: ignore[import-not-found]

                s = _serial.Serial(info.device, timeout=0)
                s.close()
            except Exception:  # noqa: BLE001
                in_use = True
            result.append(
                PortInfo(name=info.device, description=str(info.description), in_use=in_use)
            )
        return result

    def set_case_log(self, port: str, log_file: Path | None) -> None:
        """引擎在每用例开始时绑定该端口的用例日志文件."""
        self._log_files[port] = log_file
        conn = self._connections.get(port)
        if conn is not None:
            conn._log_file = log_file  # noqa: SLF001 - 内部协作

    def clear_case_log(self, port: str) -> None:
        self._log_files.pop(port, None)
        conn = self._connections.get(port)
        if conn is not None:
            conn._log_file = None  # noqa: SLF001

    # ------------------------------------------------------------------
    # §3.1 命令发送（含重连，§4.2）
    # ------------------------------------------------------------------
    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        conn = self._connections.get(port)
        if conn is None:
            return Response(text="", status=ResponseStatus.ERROR, error=f"端口 {port} 未打开")

        if not conn.is_connected:
            # 触发重连（用例级重试由上层 M3 决定，此处只尝试恢复连接）
            if not self._reconnect(port):
                return Response(
                    text="", status=ResponseStatus.ERROR, error=f"端口 {port} 重连失败"
                )

        resp = conn.send_command(command, timeout=timeout, cancel=cancel)
        # 断连错误 → 尝试重连后重发一次（重连计入次数，§4.2）
        if resp.status is ResponseStatus.ERROR and "断连" in resp.error:
            if self._reconnect(port):
                resp = conn.send_command(command, timeout=timeout, cancel=cancel)
        return resp

    # ------------------------------------------------------------------
    # §4.2 重连
    # ------------------------------------------------------------------
    def _reconnect(self, port: str, *, max_retries: int | None = None) -> bool:
        conn = self._connections.get(port)
        if conn is None:
            return False
        cfg = self._configs.get(port)
        if cfg is None:
            return False
        tries = cfg.reconnect_max_retries if max_retries is None else max_retries
        for _ in range(tries):
            if conn.reconnect():
                return True
            self._sleep(cfg.reconnect_interval_s)
        return False

    def get_connection(self, port: str) -> SerialConnection | None:
        return self._connections.get(port)

    # ------------------------------------------------------------------
    # §6.2 原始 RX 字节流订阅（手动调试/实时监控的纯流式接收）
    # ------------------------------------------------------------------
    def subscribe_rx(self, port: str, observer: Callable[[bytes], None]) -> object:
        """订阅端口原始 RX 字节流（每读到 chunk 即回调，读线程上下文）."""
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        conn.add_rx_observer(observer)
        return (port, observer)

    def unsubscribe_rx(self, handle: object) -> None:
        if not isinstance(handle, tuple) or len(handle) != 2:
            return
        port, observer = handle  # type: ignore[misc]
        conn = self._connections.get(port)  # type: ignore[arg-type]
        if conn is not None:
            conn.remove_rx_observer(observer)  # type: ignore[arg-type]

    def write_command(self, port: str, command: str) -> None:
        """写字符串命令（追加结束符），不等待响应——供手动调试/串口助手用."""
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        conn.write_command(command)

    # ------------------------------------------------------------------
    # §6 URC 订阅
    # ------------------------------------------------------------------
    def subscribe_urc(self, port: str, handler: URCHandler) -> object:
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        conn.add_urc_handler(handler)
        return (port, handler)

    def unsubscribe_urc(self, handle: object) -> None:
        if not isinstance(handle, tuple) or len(handle) != 2:
            return
        port, handler = handle  # type: ignore[misc]
        conn = self._connections.get(port)  # type: ignore[arg-type]
        if conn is not None:
            conn.remove_urc_handler(handler)  # type: ignore[arg-type]
