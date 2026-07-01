"""M1 单端口串口连接（REQ-M1 §3 数据收发、§4.1 连接管理、§7.5 响应完整性判定）.

SerialConnection 封装一个端口的完整通信能力：
    - 后台读线程持续读字节 → 按终结标志判定响应完整性（§7.5）
    - send_command 同步等待完整响应（带超时 + 取消，§3.1）
    - URC 分流（§6.4：等待响应期间也提取 URC）
    - 原始日志（§7）
    - 热插拔检测 + 自动重连（§4.2）

依赖 pyserial（仅在此层 import，上层只见接口 —— DIP，TSD §2.2）。
"""

from __future__ import annotations

import queue
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from atprobe.infra.serial.config import PortConfig, Terminator
from atprobe.infra.serial.exceptions import (
    PortOpenError,
    SendError,
)
from atprobe.infra.serial.interfaces import (
    CancelToken,
    Response,
    ResponseStatus,
    URCEvent,
    URCHandler,
)
from atprobe.infra.serial.rawlog import RawLogger

try:
    import serial  # type: ignore[import-not-found]
    from serial import SerialException  # type: ignore[import-not-found]
    from serial.tools import list_ports  # type: ignore[import-not-found]

    _PYSERIAL_AVAILABLE = True
except ImportError:  # pragma: no cover - 仅无 pyserial 时
    serial = None  # type: ignore[assignment]
    SerialException = OSError  # type: ignore[misc, assignment]
    list_ports = None  # type: ignore[assignment]
    _PYSERIAL_AVAILABLE = False


# ---------------------------------------------------------------------------
# 响应完整性判定（§7.5）：收到终结标志或超时
# ---------------------------------------------------------------------------
# AT 响应终结标志行：OK / ERROR / +CME ERROR / +CMS ERROR 等（按行匹配）
_TERMINATOR_RE = re.compile(rb"^(OK|ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)\s*$")

# 等待响应期间提取 URC（§6.4）：以 + 开头的行
_URC_LINE_RE = re.compile(rb"^\s*\+[A-Z]")


class SerialConnection:
    """单端口串口连接（pyserial 实现）.

    线程模型（TSD §6）：
        - 调用方线程（引擎线程）：send_command 同步等待响应队列
        - 内部读线程：持续 read 字节，组装响应，分流 URC
    """

    def __init__(
        self,
        config: PortConfig,
        raw_logger: RawLogger | None = None,
        log_file: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._raw_logger = raw_logger
        self._log_file = log_file
        self._clock = clock

        self._serial = None  # type: ignore[assignment]
        self._read_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._connected = False

        # 响应队列：读线程 put 完整响应，send_command get
        self._response_q: queue.Queue[Response] = queue.Queue()
        # 当前正在累积的响应缓冲（读线程写，send_command 切换时清空）
        self._buffer = bytearray()
        self._buffer_lock = threading.Lock()
        # 标记当前是否在「等待响应」状态
        self._awaiting = threading.Event()

        # URC 订阅
        self._urc_handlers: list[URCHandler] = []
        self._urc_lock = threading.Lock()

        # 原始 RX 字节观察者（手动调试/实时监控的纯流式接收，M6 §6.2）
        self._rx_observers: list[Callable[[bytes], None]] = []
        self._rx_observer_lock = threading.Lock()
        # 原始 TX 字节观察者（监控页显示发送侧，M6 §6.2）
        self._tx_observers: list[Callable[[bytes], None]] = []
        self._tx_observer_lock = threading.Lock()

        # 重连
        self._reconnecting = threading.Lock()

    def add_rx_observer(self, observer: Callable[[bytes], None]) -> None:
        """订阅原始 RX 字节流（每个读到 chunk 即回调，读线程上下文）."""
        with self._rx_observer_lock:
            if observer not in self._rx_observers:
                self._rx_observers.append(observer)

    def remove_rx_observer(self, observer: Callable[[bytes], None]) -> None:
        with self._rx_observer_lock:
            if observer in self._rx_observers:
                self._rx_observers.remove(observer)

    def add_tx_observer(self, observer: Callable[[bytes], None]) -> None:
        """订阅原始 TX 字节流（每次写入即回调，写线程上下文）."""
        with self._tx_observer_lock:
            if observer not in self._tx_observers:
                self._tx_observers.append(observer)

    def remove_tx_observer(self, observer: Callable[[bytes], None]) -> None:
        with self._tx_observer_lock:
            if observer in self._tx_observers:
                self._tx_observers.remove(observer)

    def _notify_tx_observers(self, chunk: bytes) -> None:
        with self._tx_observer_lock:
            observers = list(self._tx_observers)
        for obs in observers:
            try:
                obs(chunk)
            except Exception:  # noqa: BLE001 - 观察者错误不影响写线程
                pass

    def write_command(self, command: str, *, terminator: Terminator | None = None) -> None:
        """写字符串命令（自动追加结束符），不等待响应——供手动调试/串口助手用.

        与 send_command 区别：本方法立即返回，响应须经 rx_observer 自行接收。

        Args:
            command: 命令文本（不含结束符）。
            terminator: 逐命令覆盖的结束符；None 时回退到连接级 PortConfig.terminator。
                手动调试页结束符下拉即经此参数透传（连接级配置固定，逐命令可变）。
        """
        if not self._connected or self._serial is None:
            raise SendError(self.config.name, "端口未连接")
        term = self.config.terminator if terminator is None else terminator
        terminator_bytes = term.value.encode("ascii")
        payload = command.encode("utf-8") + terminator_bytes
        self._log_tx(payload)
        self._notify_tx_observers(payload)
        try:
            self._serial.write(payload)  # type: ignore[union-attr]
            self._serial.flush()  # type: ignore[union-attr]
        except (SerialException, OSError) as exc:
            raise SendError(self.config.name, str(exc)) from exc

    # ------------------------------------------------------------------
    # §4.1 连接管理
    # ------------------------------------------------------------------
    def open(self) -> None:
        if not _PYSERIAL_AVAILABLE:  # pragma: no cover
            raise PortOpenError(self.config.name, "pyserial 未安装")
        try:
            f = self.config.frame
            self._serial = serial.Serial(  # type: ignore[union-attr]
                port=self.config.name,
                baudrate=self.config.baudrate,
                bytesize=f.databits,
                parity=f.parity.value,
                stopbits=f.stopbits,
                xonxoff=(self.config.flow_control.value == "xon_xoff"),
                rtscts=(self.config.flow_control.value == "rts_cts"),
                timeout=0.1,  # 非阻塞读循环的轮询间隔
                write_timeout=5.0,
            )
        except (SerialException, OSError) as exc:
            raise PortOpenError(self.config.name, str(exc)) from exc

        self._connected = True
        self._stop_event.clear()
        self._read_thread = threading.Thread(
            target=self._read_loop, name=f"atprobe-read-{self.config.name}", daemon=True
        )
        self._read_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._connected = False
        # 先让读线程退出（serial.read 有 100ms 超时，最多等 ~100ms 它会看到 stop_event），
        # 再关闭 serial——避免读线程阻塞在 read 中时底层 overlapped 结构被释放，
        # 引发 "byref() argument must be NoneType" 的 TypeError（Windows pyserial）。
        if self._read_thread is not None and self._read_thread is not threading.current_thread():
            self._read_thread.join(timeout=2.0)
        if self._serial is not None:
            try:
                self._serial.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 - 关闭容错
                pass
        self._read_thread = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # §3.1 发送命令 + 等待完整响应
    # ------------------------------------------------------------------
    def send_command(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        """发送命令（自动追加结束符）并等待完整响应."""
        if not self._connected or self._serial is None:
            return Response(text="", status=ResponseStatus.ERROR, error="端口未连接")

        to = self.config.response_timeout if timeout is None else timeout
        terminator = self.config.terminator.value.encode("ascii")
        payload = command.encode("utf-8") + terminator

        # 切换到「等待响应」状态，清空缓冲
        with self._buffer_lock:
            self._buffer.clear()
        self._awaiting.set()

        self._log_tx(payload)
        self._notify_tx_observers(payload)
        try:
            self._serial.write(payload)  # type: ignore[union-attr]
            self._serial.flush()  # type: ignore[union-attr]
        except (SerialException, OSError) as exc:
            self._awaiting.clear()
            return Response(text="", status=ResponseStatus.ERROR, error=f"发送失败：{exc}")

        # 等待响应队列（带超时 + 取消轮询）
        deadline = self._clock() + to
        while True:
            if cancel is not None and cancel.cancelled:
                self._awaiting.clear()
                return Response(text="", status=ResponseStatus.CANCELLED)
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            try:
                resp = self._response_q.get(timeout=min(remaining, 0.2))
                self._awaiting.clear()
                return resp
            except queue.Empty:
                continue
        # 超时：把当前缓冲作为超时响应交付（§7.5：完整但超时）
        self._awaiting.clear()
        with self._buffer_lock:
            partial = bytes(self._buffer)
            self._buffer.clear()
        text = partial.decode("utf-8", errors="replace")
        return Response(text=text, status=ResponseStatus.TIMEOUT, error="响应超时")

    # ------------------------------------------------------------------
    # §3.2 数据流发送（分块）—— 供 DataStreamSender 调用的底层写
    # ------------------------------------------------------------------
    def write_bytes(self, data: bytes) -> None:
        """直接写字节（不分块、不加结束符，供数据流发送用）.

        与 write_command 一样通知 TX 观察者：SerialConnection 是所有字节写入的
        唯一咽喉点，订阅 TX 流应能看到这条链路上的所有写入（含原始字节/文件发送）。
        """
        if not self._connected or self._serial is None:
            raise SendError(self.config.name, "端口未连接")
        self._log_tx(data)
        self._notify_tx_observers(data)
        try:
            self._serial.write(data)  # type: ignore[union-attr]
            self._serial.flush()  # type: ignore[union-attr]
        except (SerialException, OSError) as exc:
            raise SendError(self.config.name, str(exc)) from exc

    # ------------------------------------------------------------------
    # §6 URC 订阅
    # ------------------------------------------------------------------
    def add_urc_handler(self, handler: URCHandler) -> None:
        with self._urc_lock:
            self._urc_handlers.append(handler)

    def remove_urc_handler(self, handler: URCHandler) -> None:
        with self._urc_lock:
            if handler in self._urc_handlers:
                self._urc_handlers.remove(handler)

    # ------------------------------------------------------------------
    # 后台读线程
    # ------------------------------------------------------------------
    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._serial is None:
                    break
                chunk = self._serial.read(256)  # type: ignore[union-attr]
            except (SerialException, OSError):
                # 断连：退避后再重试，避免 read 立即抛错导致的忙循环（100% CPU 空转）
                self._handle_disconnect()
                self._stop_event.wait(0.1)  # 100ms 退避，且响应停止信号
                continue
            except Exception:
                # 其他异常（如 close 期间 overlapped 结构释放引发的 TypeError）：
                # 若已请求停止则安静退出，否则按断连处理并退避
                if self._stop_event.is_set():
                    break
                self._handle_disconnect()
                self._stop_event.wait(0.1)
                continue
            if not chunk:
                # 无数据：短暂退避，避免 read 立即返回空导致的忙循环
                self._stop_event.wait(0.01)  # 10ms
                continue
            self._log_rx(chunk)
            # 原始 RX 字节流：先通知观察者（手动调试/监控的纯流式接收，读线程上下文）
            self._notify_rx_observers(chunk)
            self._process_incoming(chunk)

    def _notify_rx_observers(self, chunk: bytes) -> None:
        """把原始 RX chunk 派发给所有观察者（读线程上下文，回调需自行线程安全）."""
        with self._rx_observer_lock:
            observers = list(self._rx_observers)
        for obs in observers:
            try:
                obs(chunk)
            except Exception:  # noqa: BLE001 - 观察者错误不影响读线程
                pass

    def _process_incoming(self, chunk: bytes) -> None:
        """处理读到的字节：累积、判定完整性、分流 URC."""
        with self._buffer_lock:
            self._buffer.extend(chunk)
            data = bytes(self._buffer)

        # 按行处理
        awaiting = self._awaiting.is_set()
        # 寻找最后一个终结行
        lines = data.split(b"\n")
        # 最后一行可能不完整
        *complete_lines, tail = lines

        found_terminator = False
        for line in complete_lines:
            stripped = line.strip()
            if not stripped:
                continue
            # 等待响应期间，URC 行同时提取（§6.4）
            if _URC_LINE_RE.match(line):
                self._dispatch_urc(line.decode("utf-8", errors="replace").strip())
            if _TERMINATOR_RE.match(stripped) and awaiting:
                # 响应完整：交付
                with self._buffer_lock:
                    # 完整响应 = 从缓冲头到该终结行（含）
                    resp_bytes = bytes(self._buffer)
                    # 保留终结行之后的数据（tail）作为下一轮缓冲
                    self._buffer = bytearray(tail)
                resp_text = resp_bytes.decode("utf-8", errors="replace")
                self._response_q.put(Response(text=resp_text, status=ResponseStatus.COMPLETE))
                found_terminator = True
                break

        if not found_terminator:
            # 非等待响应状态：空闲收到的数据全部按 URC 处理（§6.4 基本策略）
            if not awaiting:
                for line in complete_lines:
                    stripped = line.strip()
                    if stripped:
                        self._dispatch_urc(line.decode("utf-8", errors="replace").strip())

    def _dispatch_urc(self, text: str) -> None:
        evt = URCEvent(port=self.config.name, text=text, timestamp="")
        with self._urc_lock:
            handlers = list(self._urc_handlers)
        for h in handlers:
            try:
                h(evt)
            except Exception:  # noqa: BLE001 - URC 回调错误不影响读线程
                pass

    def _handle_disconnect(self) -> None:
        self._connected = False
        # 仅在有 send_command 等待响应时通知，避免无人等待时往队列堆积陈旧 ERROR
        # （否则下一次 send_command 的 get 会立即拿到这个过期断连响应）
        if self._awaiting.is_set():
            self._response_q.put(
                Response(text="", status=ResponseStatus.ERROR, error="端口断连")
            )

    # ------------------------------------------------------------------
    # 原始日志
    # ------------------------------------------------------------------
    def _log_tx(self, data: bytes) -> None:
        if self._raw_logger is not None and self._log_file is not None:
            self._raw_logger.log(self._log_file, "TX", data)  # type: ignore[arg-type]

    def _log_rx(self, data: bytes) -> None:
        if self._raw_logger is not None and self._log_file is not None:
            self._raw_logger.log(self._log_file, "RX", data)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # 重连支持（§4.2）—— 由 PortManager 调用
    # ------------------------------------------------------------------
    def reconnect(self) -> bool:
        """尝试重新打开端口（不阻塞读线程太久）."""
        with self._reconnecting:
            try:
                if self._serial is not None:
                    try:
                        self._serial.close()  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        pass
                return self._try_open_once()
            except PortOpenError:
                return False

    def _try_open_once(self) -> bool:
        if not _PYSERIAL_AVAILABLE:  # pragma: no cover
            return False
        try:
            f = self.config.frame
            self._serial = serial.Serial(  # type: ignore[union-attr]
                port=self.config.name,
                baudrate=self.config.baudrate,
                bytesize=f.databits,
                parity=f.parity.value,
                stopbits=f.stopbits,
                xonxoff=(self.config.flow_control.value == "xon_xoff"),
                rtscts=(self.config.flow_control.value == "rts_cts"),
                timeout=0.1,
                write_timeout=5.0,
            )
            self._connected = True
            return True
        except (SerialException, OSError):
            return False
