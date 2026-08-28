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
from typing import Any

from atprobe.infra.serial.config import PortConfig, Terminator
from atprobe.infra.serial.exceptions import (
    OperationCancelled,
    PortOpenError,
    SendError,
)
from atprobe.infra.serial.interfaces import (
    ERROR_KIND_DISCONNECT,
    ERROR_KIND_SEND,
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
# AT 响应终结标志行：OK / ERROR / +CME ERROR / +CMS ERROR 等（按行匹配）。
# 注（L3）：仅覆盖 3GPP TS 27.007 的常用结果码。拨号/语音场景的 NO CARRIER /
# NO DIALTONE / BUSY / NO ANSWER / CONNECT（数据模式）未纳入——这些场景下设备发这些
# 码后不再发 OK，ATProbe 会等到超时。纯数据/语音测试工具按需扩展此正则。
_TERMINATOR_RE = re.compile(rb"^(OK|ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)\s*$")

# URC 行识别：**结构化分类，零前缀知识**（N58 实机验证修订）。
#
# 旧实现用前缀正则（^\s*\+[A-Z]）判定 URC——只认 3GPP 风格的 ``+`` 前缀，
# 厂商 URC 用其它前缀（Neoway ``$MYGPSPOS``、Quectel ``+QIND``/``%QIND``、
# u-blox/华为 ``^SYSSTAT`` 等）时：等待响应期间到达的行既不派发给订阅者
# （URC 事件丢失），还可能被并入响应文本（污染字节级断言）。
#
# 现改为按「行在交换中的结构位置」分类，对任何前缀成立：
#   1. 空闲（无在途命令）：所有完整非空行都是主动上报——本就无前缀检查；
#   2. 等待中、终结行之后：命令应答已在 OK/ERROR 结束，其后到达的行结构上
#      必是主动上报——响应文本精确切到终结行，其余行立即派发（不丢失、不污染）；
#   3. 等待中、终结行之前：双交付——行既累积进响应文本（可能是命令载荷），
#      又派发为 URC 事件（可能是插队的主动上报）。仅排除三类结构性非 URC 行：
#      空行、终结行（_TERMINATOR_RE）、在途命令的回显行（与刚发送的命令
#      逐字相等，可无前缀识别）。
# 前缀识别从此不参与正确性判定；新增任何厂商前缀无需改代码。

# 迟到响应收割窗口（秒）：send_command 超时后保持等待态的时长，用于静默消费
# 本命令迟到的响应（超时预算 < 设备实际时延时产生，如 poll 末次 0.05s 钳位预算），
# 防止其被错投给下一条命令（见 send_command 超时路径注释）。
_STALE_REAP_GRACE_S = 0.15


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
        # 异步指令 URC 等待状态（wait_urc 模式）：非 None 时 OK 不终结，须等匹配此正则的
        # URC 才把整段响应（OK+URC）入队。由 send_command 进入时设置、退出时复位。
        # 读线程在 _process_incoming 持有 _buffer_lock 时读写，无需额外锁。
        self._wait_urc_re: re.Pattern[bytes] | None = None
        # P1 修复（URC 去重）：等待模式下 buffer 不截断，每个新 chunk 会对全量缓冲
        # 重新拆行处理——若无状态，历史 URC 行会被逐 chunk 重复派发给订阅者。
        # 本字段记录「当前 buffer 内已完成拆行处理的字节偏移」，只派发新完成的行；
        # buffer 被替换/清空的时刻同步归零（响应交付/非等待截断/入口清排/超时清空）。
        # 与 _buffer 同受 _buffer_lock 保护。
        self._urc_dispatched = 0
        # 复审回归修复（offset 竞态）：读线程在锁外拆行/派发（handler 可耗时），
        # 期间引擎线程可能清空 buffer 并归零 offset（命令切换/超时）——读线程
        # 回写陈旧偏移会覆盖归零，下一条命令的单 chunk 响应被误判"历史行"跳过
        # → 假 TIMEOUT。代次计数器：buffer 每次被清/换自增；回写 offset 前校验
        # 代次未变，变了（buffer 已被引擎重置）则放弃本次回写。
        self._buffer_generation = 0

        # 在途命令的回显行（strip 后的 bytes）：send_command 进入等待时设置、
        # 返回时清除。URC 结构化分类用——与刚发送命令逐字相等的行是回显，
        # 不派发为 URC 事件（其余行不按前缀过滤，见模块头注释）。与 buffer
        # 同受 _buffer_lock 保护（send_command 入口设置、读线程快照读取）。
        self._echo_line: bytes | None = None

        # 孤儿续行丢弃（N58 实测第三类间歇污染）：send_command 入口清空缓冲时，
        # 若缓冲存在未完结半行（不以 \n 结尾），说明一个在途数据行的前半已被
        # 清掉——其续行（到下一个 \n 为止）必属命令前数据，不能进入本命令的
        # 响应文本（残缺行不匹配 urc_filter，行级不可识别）。标记后由读线程
        # 在字节级静默丢弃该续行。与 _buffer 同受 _buffer_lock 保护。
        self._orphan_pending = False

        # 噪声 URC 过滤（PortConfig.urc_filter 编译产物）：匹配行照常派发给
        # URC 订阅者（不丢失），但会从交付给断言的响应文本中整段剥离（含
        # 吸附紧邻空行，字节级还原"如同该 URC 从未到达"）。默认空 = 不剥离。
        self._urc_filter_res: tuple[re.Pattern[str], ...] = tuple(
            re.compile(p) for p in config.urc_filter
        )

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
        # P1 修复（热插拔自愈）：上次主动重连尝试时刻（monotonic），限频 1 次/秒
        self._last_reconnect_attempt = 0.0

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
        # P3 修复：二次 open 防护——直接 open→open（不经 close）会静默替换 _serial
        # 并泄漏旧句柄（PortManager 幂等逻辑挡住常规路径，连接对象被直接使用时无防护）
        if self._serial is not None:
            self.close()
        try:
            self._serial = self._build_serial()
        except (SerialException, OSError) as exc:
            raise PortOpenError(self.config.name, str(exc)) from exc

        self._connected = True
        self._ensure_reader()

    def _build_serial(self) -> Any:
        """根据 PortConfig 构造 pyserial.Serial 句柄（L14：open/reconnect 共用，消除重复）."""
        f = self.config.frame
        return serial.Serial(  # type: ignore[union-attr]
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

    def _ensure_reader(self) -> None:
        """保证读线程存活（open / reconnect 共用，B2 修复）.

        若读线程已死（如 close 期间被 set 的 _stop_event）或不存在，则 clear stop_event
        并新建+start 读线程。reconnect 重开串口后必须调用，否则新句柄永无读线程消费。
        """
        if self._read_thread is not None and self._read_thread.is_alive():
            return  # 读线程仍存活，无需重建
        self._stop_event.clear()
        self._read_thread = threading.Thread(
            target=self._read_loop, name=f"atprobe-read-{self.config.name}", daemon=True
        )
        self._read_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._connected = False
        # P3 修复：close 唤醒等待中的 send_command——否则阻塞在 _response_q.get 的
        # 调用方只能等满自己的超时才返回 TIMEOUT（而非立即感知断连）
        if self._awaiting.is_set():
            self._response_q.put(
                Response(
                    text="",
                    status=ResponseStatus.ERROR,
                    error="端口已关闭",
                    error_kind=ERROR_KIND_DISCONNECT,
                )
            )
        # 先让读线程退出（serial.read 有 100ms 超时，最多等 ~100ms 它会看到 stop_event），
        # 再关闭 serial——避免读线程阻塞在 read 中时底层 overlapped 结构被释放，
        # 引发 "byref() argument must be NoneType" 的 TypeError（Windows pyserial）。
        called_from_reader = (
            self._read_thread is not None and self._read_thread is threading.current_thread()
        )
        if self._read_thread is not None and not called_from_reader:
            self._read_thread.join(timeout=2.0)
        if self._serial is not None:
            try:
                self._serial.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 - 关闭容错
                pass
        # P3 修复：close 若从读线程内调用，读线程仍存活——保留引用而非置 None，
        # 避免紧随的 _ensure_reader 起第二个读线程双读同一句柄
        if not called_from_reader:
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
        wait_urc: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        """发送命令（自动追加结束符）并等待完整响应.

        wait_urc 非空时为异步指令模式：遇 OK 不返回，继续读到匹配 wait_urc 正则的
        URC 立即返回（整段响应文本含 OK+URC）；timeout 内无 URC 则按超时返回（text
        含已收到的 OK 段，status=TIMEOUT）。为空时 OK 即终结（原行为）。
        """
        if not self._connected or self._serial is None:
            return Response(
                text="", status=ResponseStatus.ERROR, error="端口未连接", error_kind=ERROR_KIND_SEND
            )

        to = self.config.response_timeout if timeout is None else timeout
        terminator = self.config.terminator.value.encode("ascii")
        payload = command.encode("utf-8") + terminator

        # 切换到「等待响应」状态，清空缓冲；wait_urc 模式设置 URC 终结正则；
        # 记录回显行（URC 结构化分类用：与命令逐字相等的行是回显，不派发 URC）
        with self._buffer_lock:
            self._reset_buffer_locked()
            self._echo_line = command.strip().encode("utf-8") if command.strip() else None
            if wait_urc is not None:
                self._wait_urc_re = re.compile(wait_urc.encode("utf-8"))
        # 先 set awaiting 再排空队列（B3 修复：消除 set 与 drain 之间读线程恰好检测到断连
        # 却因 awaiting 未 set 而丢弃断连信号的竞态窗口。先 set 后，读线程的断连路径会
        # 把 ERROR 入队，drain 只会清掉这次命令之前入队的陈旧响应；若 drain 恰好清掉了
        # 刚入队的断连信号也无妨——紧接着 write 会失败或断连会再次触发，最终都能被感知）。
        self._awaiting.set()
        self._drain_response_q()

        self._log_tx(payload)
        self._notify_tx_observers(payload)
        try:
            self._serial.write(payload)  # type: ignore[union-attr]
            self._serial.flush()  # type: ignore[union-attr]
        except (SerialException, OSError) as exc:
            self._awaiting.clear()
            self._reset_wait_urc()
            return Response(
                text="",
                status=ResponseStatus.ERROR,
                error=f"发送失败：{exc}",
                error_kind=ERROR_KIND_SEND,
            )

        try:
            return self._await_response(to, cancel)
        finally:
            # 无论正常返回/超时/异常，均复位 wait_urc 状态，避免污染下一条命令
            self._reset_wait_urc()

    def _await_response(self, timeout: float, cancel: CancelToken | None) -> Response:
        """等待响应队列（带超时 + 取消轮询 + 超时快照 + 迟到收割，§7.5）.

        send_command 与数据发送周期（批 2b）共用的等待原语。

        调用前置（调用方负责，参照 send_command 入口）：
            1. 已持锁 ``_reset_buffer_locked()``（清残留缓冲，防污染超时快照文本）；
            2. 已设 ``_echo_line``（等待期回显排除）与 ``_wait_urc_re``（按需）；
            3. 已 ``_awaiting.set()`` 且已 ``_drain_response_q()``。
        调用后置：内部 finally 仅清 ``_awaiting``/清排队列/清缓冲；
        **不复位** ``_wait_urc_re``/``_echo_line``——调用方须在自己 finally 调
        ``_reset_wait_urc()``（send_command :364-366 即此模式）。
        """
        deadline = self._clock() + timeout
        while True:
            if cancel is not None and cancel.cancelled:
                # M1 修复：取消时统一抛 OperationCancelled（与 Fake/vsim 一致），
                # 上层 step_runner catch 后判 INTERRUPTED，而非旧实现的返回 CANCELLED
                # Response（被 _single_attempt 当作普通 ERROR → FAIL，与 Fake 路径分叉）。
                self._awaiting.clear()
                self._drain_response_q()
                raise OperationCancelled("命令等待被取消")
            remaining = deadline - self._clock()
            if remaining <= 0:
                # 末次非阻塞检查：消除「get 超时与 break 之间响应入队」的窗口。
                # 若此刻读线程/断连刚好 put 了响应，取之返回（更准确：设备确实
                # 回了/确实断了，而非笼统 TIMEOUT）；取不到才走超时。
                try:
                    resp = self._response_q.get_nowait()
                    self._awaiting.clear()
                    return resp
                except queue.Empty:
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
            # 快照后清缓冲：若存在未完结半行置孤儿标记（收割窗口内到达的
            # 续行由读线程字节级丢弃）
            keep_re = self._wait_urc_re  # wait_urc 超时：目标行不得被 filter 剥离
            self._reset_buffer_locked()
        text = self._strip_filtered_urcs(partial.decode("utf-8", errors="replace"), keep_re=keep_re)
        err = "响应超时" if keep_re is None else "等待 URC 超时"
        # 迟到响应收割（N58 实测 bug 修复）：超时预算小于设备实际响应时延时
        # （典型：poll 末次 attempt 预算被钳到 0.05s，设备 ~60-90ms 才回），
        # 本命令的响应会在超时返回之后、下一条命令 write 前后的窗口到达——
        # 若不处理，读线程会把已在等待态的下一条命令错认为收件人，其响应
        # 0ms 即回、内容却是本命令的应答（COM5 复现：ATE0 收到 +CEREG: 0,2 OK）。
        # 对策：超时后保持等待态进入收割窗口，静默消费窗口内到达的迟到响应，
        # 通道干净后再返回 TIMEOUT。窗口取 150ms（覆盖 0.05s 钳位预算 + 设备
        # 典型时延）；期间到达的数据按正常分流（URC 派发/响应入队后丢弃）。
        reap_deadline = self._clock() + _STALE_REAP_GRACE_S
        self._awaiting.set()
        try:
            while True:
                if cancel is not None and cancel.cancelled:
                    self._awaiting.clear()
                    self._drain_response_q()
                    raise OperationCancelled("命令等待被取消")
                remain = reap_deadline - self._clock()
                if remain <= 0:
                    break
                try:
                    # 迟到响应：取出即丢弃（其文本已在上方 partial 快照之外，
                    # 设备对同一命令不会二次应答，无需合并）
                    self._response_q.get(timeout=min(remain, 0.05))
                except queue.Empty:
                    continue
        finally:
            self._awaiting.clear()
            self._drain_response_q()
            # 收割窗口内可能又累积了半行数据（迟到响应的尾巴）：清缓冲，
            # 避免泄漏给下一条命令（其入口本也会清，此处提前消除）。
            with self._buffer_lock:
                self._reset_buffer_locked()
        return Response(text=text, status=ResponseStatus.TIMEOUT, error=err)

    def _reset_buffer_locked(self) -> None:
        """清空响应缓冲（调用方须已持 _buffer_lock）.

        孤儿续行标记为**赋值语义**（非只置位）：按当前缓冲状态重算——存在
        未完结半行（不以 \\n 结尾）则 True，否则 False。只置位不清位的旧写法
        有两个 bug：超时后续行 150ms 内未到时 stale 标记穿过收割尾部与下条
        命令入口存活，吞掉下一命令响应的首个 \\n（\\r\\nOK\\r\\n 变 OK\\r\\n）；
        重连路径对死链半行置位后吞掉新会话首行。赋值语义下各调用点天然正确：
        超时快照（半行尚在缓冲 → True，收割期续行可被丢弃）、收割尾部/入口
        （缓冲空 → 自动清 stale）、重连（死链半行 → 由 _maybe_reconnect 显式
        覆写为 False，新会话无续行语义）。
        """
        self._orphan_pending = bool(self._buffer) and not self._buffer.endswith(b"\n")
        self._buffer.clear()
        self._urc_dispatched = 0
        self._buffer_generation += 1

    def _reset_wait_urc(self) -> None:
        """复位 wait_urc 状态（调用前后保持 _buffer_lock 一致性）.

        同时清除回显行——等待窗口结束，后续空闲数据不再需要回显排除。
        """
        with self._buffer_lock:
            self._wait_urc_re = None
            self._echo_line = None

    def _drain_response_q(self) -> None:
        """排空响应队列残留，防止陈旧响应污染下次命令.

        用于 send_command 入口（清掉上次命令在超时/取消/断连窗口内入队但未被取走的
        响应）和 cancel/超时返回前（避免响应遗弃）。安全前提：调用方确保此刻读线程
        不会 put 新响应（入口处 _awaiting 尚未 set；返回前已 clear）。
        """
        while True:
            try:
                self._response_q.get_nowait()
            except queue.Empty:
                break

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
                # 复审回归修复：close() 关句柄会使阻塞 read 抛 OSError——此时
                # stop_event 已置，绝不能走重连（否则端口被重开/双读线程）。
                if self._stop_event.is_set():
                    break
                # 断连：退避后再重试，避免 read 立即抛错导致的忙循环（100% CPU 空转）
                self._handle_disconnect()
                # P1 修复（热插拔自愈）：断连后由读线程限频主动重连（≤1 次/秒）。
                # 旧实现只被动等 send_command 触发 reconnect（引擎路径）——纯监控/
                # 手动调试会话拔插 USB 后读线程永远轮询失效句柄，订阅形同虚设。
                if not self._maybe_reconnect():
                    self._stop_event.wait(0.1)  # 100ms 退避，且响应停止信号
                continue
            except Exception:
                # 其他异常（如 close 期间 overlapped 结构释放引发的 TypeError）：
                # 若已请求停止则安静退出，否则按断连处理并退避
                if self._stop_event.is_set():
                    break
                self._handle_disconnect()
                if not self._maybe_reconnect():
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
        """处理读到的字节：累积、判定完整性、按**结构位置**分流 URC.

        P1 修复（URC 去重）：等待响应期间 buffer 不截断（需保留完整文本交付），
        每个 chunk 都会对全量缓冲重新拆行。用 ``_urc_dispatched`` 记录已完成
        拆行处理的字节偏移——只对**新完成**的行做 URC 派发，历史行不再重复派发。
        buffer 被替换/清空时偏移同步归零。

        URC 分类（零前缀知识，见模块头注释）：
          - 空闲：所有完整非空行 = URC；
          - 等待中、终结行之后：必是主动上报——立即派发，不入响应文本；
          - 等待中、终结行之前：双交付（累积进文本 + 派发事件），结构性排除
            空行/终结行/在途命令回显行。
        """
        with self._buffer_lock:
            # 孤儿续行丢弃：入口清缓冲截断的在途半行，其续行（至下一个 \n 含）
            # 属命令前数据——字节级静默丢弃，不派发、不累积（残缺行内容不可信，
            # 如丢失 $M 前缀的 YGPSPOS:...，行级规则无法识别）。
            if self._orphan_pending and chunk:
                nl = chunk.find(b"\n")
                if nl < 0:
                    return  # 整个 chunk 都是续行内容，继续等行尾
                chunk = chunk[nl + 1 :]
                self._orphan_pending = False
                if not chunk:
                    return  # 续行恰好在本 chunk 结束，其余处理留给下个 chunk
            self._buffer.extend(chunk)
            data = bytes(self._buffer)
            wait_urc_re = self._wait_urc_re
            dispatched_offset = self._urc_dispatched
            generation = self._buffer_generation  # 竞态校验用（见字段注释）
            echo_line = self._echo_line

        # 按行处理
        awaiting = self._awaiting.is_set()
        lines = data.split(b"\n")
        # 最后一行可能不完整
        *complete_lines, tail = lines

        # 预计算每个完整行的字节跨度 [start, end)（end 含换行符），
        # end <= dispatched_offset 的行是历史 chunk 已处理过的，跳过派发。
        spans: list[tuple[int, int]] = []
        _pos = 0
        for _line in complete_lines:
            spans.append((_pos, _pos + len(_line) + 1))
            _pos += len(_line) + 1

        def _urc_candidate(stripped: bytes) -> bool:
            """结构位置排除后的 URC 候选行（无前缀判断）."""
            if not stripped:
                return False
            if _TERMINATOR_RE.match(stripped):
                return False
            # 在途命令的回显行（与刚发送命令逐字相等）不是 URC
            return not (echo_line is not None and stripped == echo_line)

        def _decode(b: bytes) -> str:
            return b.decode("utf-8", errors="replace")

        # --------------------------------------------------------------
        # wait_urc 模式（异步指令）：OK 仅受理不终结，须等匹配 wait_urc 正则的
        # URC 才把整段响应（OK+URC）作为 COMPLETE 入队。
        # --------------------------------------------------------------
        if wait_urc_re is not None and awaiting:
            for mi, (line, (_ls, le)) in enumerate(zip(complete_lines, spans, strict=True)):
                if le <= dispatched_offset:
                    continue  # 历史 chunk 已处理过的行（去重）
                stripped = line.strip()
                if not stripped:
                    continue
                # 目标 URC 匹配：整段响应（含 OK）入队终结。
                # P1 修复：正则作用在 strip 后的行上——split(b"\n") 保留行尾 \r，
                # 旧实现用原始行匹配，含 $ 锚点的合法正则（如 \+X:ok$）永不命中。
                if wait_urc_re.search(stripped):
                    # URC 行也按常规分流给订阅者（§6.4）
                    self._dispatch_urc(_decode(stripped))
                    with self._buffer_lock:
                        resp_bytes = bytes(self._buffer)
                        self._buffer = bytearray(tail)
                        self._urc_dispatched = 0  # buffer 已替换，偏移归零
                        self._buffer_generation += 1
                    # wait_urc 优先级规则：目标行是本命令显式声明的期待响应，
                    # urc_filter 不得剥离（keep_re）——否则「URC 即期待响应」类
                    # 命令（如 AT$MYGPSPOS=0,1 的 $MYGPSPOS 循环上报）在全局
                    # filter 配置下永远无法在响应文本中见到自己的目标行。
                    resp_text = self._strip_filtered_urcs(_decode(resp_bytes), keep_re=wait_urc_re)
                    self._response_q.put(Response(text=resp_text, status=ResponseStatus.COMPLETE))
                    # P3 修复：匹配行之后的完整行不丢弃（buffer 重置为 tail 后它们
                    # 既不在缓冲也未被派发）——按 URC 分流补派发一次。
                    # 结构位置在目标 URC 之后 → 非空即派发（无前缀判断）。
                    for rest in complete_lines[mi + 1 :]:
                        s2 = rest.strip()
                        if s2:
                            self._dispatch_urc(_decode(s2))
                    return
                # OK/ERROR 等终结行：仅受理不终结，继续等 URC（已累积进 buffer）
                if _TERMINATOR_RE.match(stripped):
                    continue
                # 其它行：可能是插队的 URC（如 $ 前缀厂商上报）也可能是载荷——
                # 双交付：派发事件 + 留在文本（结构性排除回显/空行/终结行）
                if _urc_candidate(stripped):
                    self._dispatch_urc(_decode(stripped))
            with self._buffer_lock:
                # 代次校验：锁外派发期间 buffer 若被引擎清/换（命令切换/超时），
                # 陈旧偏移会覆盖归零 → 下一条命令单 chunk 响应被误判历史行（假超时）
                if self._buffer_generation == generation:
                    self._urc_dispatched = spans[-1][1] if spans else dispatched_offset
            return

        # --------------------------------------------------------------
        # 常规模式（wait_urc 未启用）：OK 即终结
        # --------------------------------------------------------------
        found_terminator = False
        for line, (_ls, le) in zip(complete_lines, spans, strict=True):
            if le <= dispatched_offset:
                continue  # 历史 chunk 已处理过的行（去重；终结判定也无需重做）
            stripped = line.strip()
            if not stripped:
                continue
            # 等待响应期间，URC 行同时提取（§6.4）。
            # P1 修复：仅 awaiting 时在此派发——空闲态由下方专门分支统一派发，
            # 旧实现（含重构前）两个循环都会派发 → 空闲态每条 URC 双派发。
            # N58 修订：不再按 + 前缀判断——结构位置排除后（空行/终结行/回显）
            # 均派发，$ 前缀等厂商 URC 不再丢失。
            if awaiting and _urc_candidate(stripped):
                self._dispatch_urc(_decode(stripped))
            if _TERMINATOR_RE.match(stripped) and awaiting:
                # 响应完整：交付。N58 修复（污染）：响应文本**精确切到终结行**
                # （含）为止——与终结行同 chunk 到达的后续行是主动上报，立即
                # 派发（不丢失），不再并入响应文本（不污染严格字节级断言）。
                with self._buffer_lock:
                    # 完整响应 = 从缓冲头到该终结行（含）
                    resp_bytes = bytes(self._buffer[:le])
                    # 保留终结行之后的数据（tail）作为下一轮缓冲
                    self._buffer = bytearray(tail)
                    self._urc_dispatched = 0  # buffer 已替换，偏移归零
                    self._buffer_generation += 1
                resp_text = self._strip_filtered_urcs(_decode(resp_bytes))
                self._response_q.put(Response(text=resp_text, status=ResponseStatus.COMPLETE))
                found_terminator = True
                # 终结行之后的完整行：结构位置 = 命令应答已结束 → 必是主动上报，
                # 立即派发（修复：旧实现把它们并入响应文本，随交付时序污染断言）
                for rest, (_rls, rle) in zip(complete_lines, spans, strict=True):
                    if rle <= le:
                        continue
                    s2 = rest.strip()
                    if s2:
                        self._dispatch_urc(_decode(s2))
                break

        if not found_terminator:
            # 非等待响应状态：空闲收到的数据全部按 URC 处理（§6.4 基本策略）
            if not awaiting:
                for line, (_ls, le) in zip(complete_lines, spans, strict=True):
                    if le <= dispatched_offset:
                        continue
                    stripped = line.strip()
                    if stripped:
                        self._dispatch_urc(_decode(stripped))
                # 已处理的完整行从 buffer 截断，只保留最后一个不完整行（tail）。
                # 否则设备持续发 URC/心跳而无人调用 send_command 时，buffer 会无限累积
                # 所有历史字节，长会话内存缓慢增长甚至 OOM。
                with self._buffer_lock:
                    self._buffer = bytearray(tail)
                    self._urc_dispatched = 0  # buffer 已替换，偏移归零
                    self._buffer_generation += 1
            else:
                # 等待中但未终结：推进已处理偏移（下个 chunk 不再重复派发历史行）。
                # 代次校验防陈旧回写（见 wait_urc 分支同款注释）
                with self._buffer_lock:
                    if self._buffer_generation == generation:
                        self._urc_dispatched = spans[-1][1] if spans else dispatched_offset

    def _strip_filtered_urcs(self, text: str, keep_re: re.Pattern[bytes] | None = None) -> str:
        """从响应文本剥离 urc_filter 匹配的 URC 行（含吸附紧邻空行）.

        设备主动上报的发射单元自带空行包裹（实测 N58：\\r\\n$MYGPSPOS: ...\\r\\n\\r\\n），
        剥离「匹配行 + 前导空行 + 后随空行」可字节级还原该 URC 从未到达时的文本。
        默认 urc_filter 为空 → 原样返回（零开销）。

        使用场景：终结行**之前**插队到达的 URC（结构上无法与载荷区分，只能双
        交付）、wait_urc 整段交付、超时交付的业务码文本——这三处响应文本可能
        含噪声行，由本方法按用户显式配置剥离。

        优先级规则（wait_urc > urc_filter）：keep_re 是当前 wait_urc 正在等待的
        目标正则——匹配它的行是本命令**显式声明的期待响应**（如 AT$MYGPSPOS=0,1
        期待 $MYGPSPOS 循环上报首行），比全局噪声声明更具体，故不被剥离。
        同一端口上「GPS 行对其余 49 个用例是噪声、对 GPS 用例是期待响应」的
        冲突由该规则解决：全局 filter 声明常态，逐命令 wait_urc 声明例外。
        """
        if not self._urc_filter_res or not text:
            return text
        lines = text.split("\n")
        keep: list[str] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            stripped = line.strip()
            # keep_re 优先：wait_urc 目标行是期待响应，不做剥离判定
            kept_by_wait_urc = keep_re is not None and keep_re.search(
                stripped.encode("utf-8", "replace") if stripped else b""
            )
            if (
                stripped
                and not kept_by_wait_urc
                and any(r.search(stripped) for r in self._urc_filter_res)
            ):
                # 悬置半行：超时边界恰好切在噪声行中间（split 尾元素无换行结尾）
                dangling = i == n - 1
                # 吸附前导空行（发射单元自带的前缀 CRLF）。守卫条件（keep[-1]
                # 为空行）天然区分「噪声单元自己的前导 CRLF」与「上一行的行尾
                # CRLF」：只有存在专属空行时才吸附。
                if keep and keep[-1].strip() == "":
                    keep.pop()
                    if dangling:
                        # join 语义下上一行的行尾 \n 由「与被弹元素的分隔符」承载，
                        # 弹掉专属空行后补回空元素以保留该行尾。
                        keep.append("")
                # 吸附后随空行（发射单元的尾随空行）
                if not dangling and i + 1 < n and lines[i + 1].strip() == "":
                    i += 1
                i += 1
                continue
            keep.append(line)
            i += 1
        # 孤儿 CRLF 收敛：send_command 入口清缓冲可能恰好切断在途 URC 发射单元
        # 的行尾 CRLF——LINE 部分被清掉，残留 1-2 个前导空行（无内容、不匹配
        # filter、行级不可识别）。规范 AT 响应文本至多以一个空行开头，把连续
        # 前导空行收敛为一个（COM5 实测：ATE0 响应被污染为 \r\n\r\nOK\r\n）。
        i0 = 0
        while i0 + 1 < len(keep) and keep[i0].strip() == "" and keep[i0 + 1].strip() == "":
            i0 += 1
        if i0:
            keep = keep[i0:]
        return "\n".join(keep)

    def _dispatch_urc(self, text: str) -> None:
        # P3 修复：timestamp 填实际时间（旧实现恒空串）
        from datetime import datetime

        evt = URCEvent(
            port=self.config.name,
            text=text,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        )
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
                Response(
                    text="",
                    status=ResponseStatus.ERROR,
                    error="端口断连",
                    error_kind=ERROR_KIND_DISCONNECT,
                )
            )

    def _maybe_reconnect(self) -> bool:
        """断连后限频主动重连（读线程内调用，热插拔自愈，P1 修复）.

        成功：清掉死句柄期间的残留缓冲（半截字节不作数），返回 True（调用方
        无需额外退避——reconnect 本身耗时）；失败（未到限频间隔/端口仍不可用）
        返回 False，调用方按 100ms 退避。
        复审回归修复：close 进行中（stop_event 已置）绝不重连。
        """
        if self._stop_event.is_set():
            return False
        now = time.monotonic()
        if now - self._last_reconnect_attempt < 1.0:
            return False
        self._last_reconnect_attempt = now
        if self.reconnect():
            with self._buffer_lock:
                # 死句柄期间的残留缓冲（半截字节不作数）：清空。死链半行
                # **不得**置孤儿标记——重开后的首个 chunk 是全新会话数据而非
                # 死链续行，赋值语义下需显式覆写为 False。
                self._reset_buffer_locked()
                self._orphan_pending = False
            return True
        return False

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
        """尝试重新打开端口（不阻塞读线程太久）.

        重开后调 _ensure_reader 保证读线程存活（B2 修复：旧实现重连后不重启读线程，
        导致重连成功的端口无消费线程，send_command 必然超时卡死）。
        复审回归修复：stop 已请求（close 进行中）时直接拒绝——否则读线程的
        断连路径会重开刚被 close 的端口，甚至经 _ensure_reader 的
        _stop_event.clear() 起第二个读线程（同一句柄双读）。
        """
        if self._stop_event.is_set():
            return False
        with self._reconnecting:
            try:
                if self._serial is not None:
                    try:
                        self._serial.close()  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        pass
                if self._try_open_once():
                    # open 期间（可阻塞秒级）stop 可能被请求——复核，置位则放弃
                    if self._stop_event.is_set():
                        try:
                            self._serial.close()  # type: ignore[union-attr,attr-defined]
                        except Exception:  # noqa: BLE001
                            pass
                        self._serial = None  # type: ignore[assignment]
                        self._connected = False
                        return False
                    self._ensure_reader()
                    return True
                return False
            except PortOpenError:
                return False

    def _try_open_once(self) -> bool:
        if not _PYSERIAL_AVAILABLE:  # pragma: no cover
            return False
        try:
            self._serial = self._build_serial()
            self._connected = True
            return True
        except (SerialException, OSError):
            return False
