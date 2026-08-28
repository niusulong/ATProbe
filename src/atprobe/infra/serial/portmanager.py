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

from atprobe.infra.serial.config import PortConfig, Terminator
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import (
    PortOpenError,
)
from atprobe.infra.serial.interfaces import (
    ERROR_KIND_DISCONNECT,
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
        # 持久订阅层（port -> [observer]）：观察者按 port 持久化，
        # connection 销毁重建（close+open）后由 open 自动重新 attach，
        # 使订阅不随 connection 生命周期丢失（监控/手动调试在端口重开后仍生效）。
        self._rx_observers: dict[str, list[Callable[[bytes], None]]] = {}
        self._tx_observers: dict[str, list[Callable[[bytes], None]]] = {}
        self._urc_handlers: dict[str, list[URCHandler]] = {}
        # P1 修复：持久订阅桶的并发保护。GUI 线程 subscribe/unsubscribe 与引擎线程
        # open()（re-attach 迭代）并发时，裸 dict/list 会 RuntimeError（迭代中修改）
        # 或静默丢订阅。锁序恒为 _lock → _observers_lock（仅 open 同时持两锁，
        # subscribe/unsubscribe 只持 _observers_lock，无反向获取，无死锁）。
        self._observers_lock = threading.Lock()

    # ------------------------------------------------------------------
    # §4.1 连接管理
    # ------------------------------------------------------------------
    def open(self, config: PortConfig) -> None:
        """打开端口。M4 修复：已用相同配置打开则幂等返回，配置不同才抛错。

        旧实现对已开端口无条件 raise PortOpenError，破坏"外部已连端口复用"语义
        （scheduler.start 先 is_connected 判断 already_open 再无条件 open，导致 GUI
        已连端口被引擎复用时误判为打开失败）。现改为幂等：同名且配置一致直接返回。
        """
        with self._lock:
            existing = self._connections.get(config.name)
            if existing is not None:
                # 已用相同配置打开 → 幂等返回（不破坏外部已建立的连接与订阅）
                old = self._configs.get(config.name)
                if old is not None and old == config:
                    return
                # 配置不同 → 抛错（无法在不中断现有连接的情况下切换配置）
                raise PortOpenError(config.name, "端口已用不同配置打开")
            conn = SerialConnection(config, raw_logger=self._raw_logger, clock=self._clock)
            conn.open()
            self._connections[config.name] = conn
            self._configs[config.name] = config
            # 把该端口持久订阅重新 attach 到新 connection（新 connection 观察者列表为空，
            # 直接 add 即可）。使 close+open 重建后订阅自动恢复。
            # P1 修复：re-attach 迭代持 _observers_lock，与 subscribe/unsubscribe 互斥，
            # 消除「GUI 订阅 vs 引擎 open 并发」的迭代中修改风险。
            with self._observers_lock:
                for obs in list(self._rx_observers.get(config.name, [])):
                    conn.add_rx_observer(obs)
                for obs in list(self._tx_observers.get(config.name, [])):
                    conn.add_tx_observer(obs)
                for h in list(self._urc_handlers.get(config.name, [])):
                    conn.add_urc_handler(h)

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
        """返回端口配置；端口未知时返回默认 PortConfig（L12：与 Fake 对齐，便于安全阀回退）."""
        cfg = self._configs.get(port)
        if cfg is not None:
            return cfg
        return PortConfig(name=port)

    def enumerate_ports(self) -> list[PortInfo]:
        """枚举系统串口（M5 list ports）.

        P3/P2 修复：旧实现对每个系统串口做**独占打开探测**判占用——Windows 上
        短暂触碰他人进程占用的端口（可能引发对方驱动异常），且 USB 串口多时
        秒级阻塞（GUI 构造路径直接调用）。改为非侵入式：in_use 仅反映本进程
        已打开的端口（系统级占用不再探测；显示语义从「被谁占用」变为「被本
        程序占用」，枚举本身用 comports() 不需要打开设备）。
        """
        if not _HAS_LISTPORTS:  # pragma: no cover
            return []
        # F-3 修复：与 open/close 并发时 dict 结构可变，须持锁收集
        # （close_all 已在锁内收集，此处此前遗漏 → GUI 刷新偶发
        #   RuntimeError: dictionary changed size during iteration）
        with self._lock:
            ours = set(self._connections.keys())
        return [
            PortInfo(
                name=info.device, description=str(info.description), in_use=info.device in ours
            )
            for info in list_ports.comports()  # type: ignore[union-attr]
        ]

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
        wait_urc: str | None = None,
        cancel: CancelToken | None = None,
        pre_check: Callable[[], None] | None = None,
    ) -> Response:
        """发送命令并等待响应（含断连重发，§4.2）.

        Args:
            pre_check: 获连接后、每次实际发送前调用的回调；抛异常则透传、不发送。
                供上层（MCP）做锁内占用重检，消除 check-then-act TOCTOU
                （批 3 接线，本批留接口）。
        """
        conn = self._connections.get(port)
        if conn is None:
            return Response(text="", status=ResponseStatus.ERROR, error=f"端口 {port} 未打开")

        if not conn.is_connected:
            # 触发重连（用例级重试由上层 M3 决策，此处只尝试恢复连接）
            if not self._reconnect(port):
                return Response(
                    text="",
                    status=ResponseStatus.ERROR,
                    error=f"端口 {port} 重连失败",
                    error_kind=ERROR_KIND_DISCONNECT,
                )

        # pre_check：获连接后、发送前调用——供上层（MCP）做锁内占用重检，
        # 消除 check-then-act TOCTOU（批 3 接线，本批留接口）。
        if pre_check is not None:
            pre_check()
        resp = conn.send_command(command, timeout=timeout, wait_urc=wait_urc, cancel=cancel)
        # 断连错误 → 尝试重连后重发一次（重连计入次数，§4.2）。
        # M3 修复：基于结构化 error_kind 判定，而非脆弱的中文字符串匹配。
        if resp.status is ResponseStatus.ERROR and resp.error_kind == ERROR_KIND_DISCONNECT:
            if self._reconnect(port):
                # 重发前同样过 pre_check：重连窗口内占用状态可能变化（TOCTOU 同源）
                if pre_check is not None:
                    pre_check()
                resp = conn.send_command(command, timeout=timeout, wait_urc=wait_urc, cancel=cancel)
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
    # §6.4/M6 §6.2 原始 RX 字节流订阅（手动调试/实时监控的纯流式接收）
    # ------------------------------------------------------------------
    def subscribe_rx(self, port: str, observer: Callable[[bytes], None]) -> object:
        """订阅端口原始 RX 字节流（每读到 chunk 即回调，读线程上下文）.

        订阅持久化到 PortManager 层：connection 销毁重建后自动恢复。
        """
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        # 持久层登记（去重，与 connection 的 add 同样基于身份/相等判定）
        with self._observers_lock:
            bucket = self._rx_observers.setdefault(port, [])
            if observer not in bucket:
                bucket.append(observer)
        conn.add_rx_observer(observer)
        return (port, observer)

    def unsubscribe_rx(self, handle: object) -> None:
        if not isinstance(handle, tuple) or len(handle) != 2:
            return
        port, observer = handle  # type: ignore[misc]
        # 从持久层移除（确保 close+open 后不再 re-attach）
        with self._observers_lock:
            bucket = self._rx_observers.get(port)  # type: ignore[arg-type]
            if bucket and observer in bucket:
                bucket.remove(observer)
        conn = self._connections.get(port)  # type: ignore[arg-type]
        if conn is not None:
            conn.remove_rx_observer(observer)  # type: ignore[arg-type]

    def subscribe_tx(self, port: str, observer: Callable[[bytes], None]) -> object:
        """订阅端口原始 TX 字节流（每次写入即回调，写线程上下文，M6 §6.2）.

        订阅持久化到 PortManager 层：connection 销毁重建后自动恢复。
        """
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        with self._observers_lock:
            bucket = self._tx_observers.setdefault(port, [])
            if observer not in bucket:
                bucket.append(observer)
        conn.add_tx_observer(observer)
        return (port, observer)

    def unsubscribe_tx(self, handle: object) -> None:
        if not isinstance(handle, tuple) or len(handle) != 2:
            return
        port, observer = handle  # type: ignore[misc]
        with self._observers_lock:
            bucket = self._tx_observers.get(port)  # type: ignore[arg-type]
            if bucket and observer in bucket:
                bucket.remove(observer)
        conn = self._connections.get(port)  # type: ignore[arg-type]
        if conn is not None:
            conn.remove_tx_observer(observer)  # type: ignore[arg-type]

    def write_command(
        self, port: str, command: str, *, terminator: Terminator | None = None
    ) -> None:
        """写字符串命令（追加结束符），不等待响应——供手动调试/串口助手用.

        Args:
            terminator: 逐命令覆盖的结束符；None 时用连接级 PortConfig.terminator。
        """
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        conn.write_command(command, terminator=terminator)

    def write_bytes(self, port: str, data: bytes) -> None:
        """写原始字节（不加结束符、不分块），供文件/二进制数据流发送用.

        与 write_command 区别：原样写字节，不追加结束符；发送的原始字节同样
        通知 TX 观察者（由 SerialConnection.write_bytes 负责，咽喉点一致性）。
        """
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        conn.write_bytes(data)

    # ------------------------------------------------------------------
    # §6 URC 订阅
    # ------------------------------------------------------------------
    def subscribe_urc(self, port: str, handler: URCHandler) -> object:
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        with self._observers_lock:
            bucket = self._urc_handlers.setdefault(port, [])
            if handler not in bucket:
                bucket.append(handler)
        conn.add_urc_handler(handler)
        return (port, handler)

    def unsubscribe_urc(self, handle: object) -> None:
        if not isinstance(handle, tuple) or len(handle) != 2:
            return
        port, handler = handle  # type: ignore[misc]
        with self._observers_lock:
            bucket = self._urc_handlers.get(port)  # type: ignore[arg-type]
            if bucket and handler in bucket:
                bucket.remove(handler)
        conn = self._connections.get(port)  # type: ignore[arg-type]
        if conn is not None:
            conn.remove_urc_handler(handler)  # type: ignore[arg-type]
