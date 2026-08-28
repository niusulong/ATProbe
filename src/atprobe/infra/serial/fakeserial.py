"""FakeSerial — 测试用串口模拟器（TSD §8.5）.

实现 ICommandSender / IConnectionManager / IURCSubscriber 接口（鸭子类型 Protocol），
内部维护「响应脚本队列」：测试预设「发 X 返回 Y」，按序消费。
支持注入异常、按次数返回不同响应、时间控制。

放 src/atprobe/infra/serial/ 以便集成测试与（未来）演示模式共用。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from atprobe.infra.serial.config import PortConfig, Terminator
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import (
    CancelToken,
    PortInfo,
    Response,
    ResponseStatus,
    URCEvent,
    URCHandler,
)
from atprobe.infra.serial.rawlog import RawLogger


@dataclass
class _ScriptedResponse:
    """一条预设响应：匹配发送的命令，返回指定响应."""

    response: Response
    match: str | None = None  # None = 匹配任意命令（按序消费）
    consume_after: bool = True  # 消费后是否从队列移除（False = 每次都返回这个，用于 retry/poll）


class FakePortManager:
    """PortManager 的 Fake 实现，供集成测试驱动引擎（无需真实硬件）.

    真实 SerialConnection 有端口级命令锁互斥（P1-3：send_command/write_command
    try-acquire，撞锁抛"端口正忙"），Fake 为单线程测试替身、不加锁。

    用法::

        fake = FakePortManager()
        fake.script("COM3", Response("OK\\r\\n"))           # 任意命令返回 OK
        fake.script("COM3", Response("+CSQ: 23\\r\\nOK\\r\\n"), match="AT+CSQ")
        engine = Engine(sender_factory=lambda: fake)
        result = engine.start(config)
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        raw_logger: RawLogger | None = None,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._raw_logger = raw_logger
        self._configs: dict[str, PortConfig] = {}
        self._connected: set[str] = set()
        # port -> 脚本响应队列
        self._scripts: dict[str, list[_ScriptedResponse]] = {}
        # 记录所有发送过的命令（port, command）
        self.sent: list[tuple[str, str]] = []
        # 记录启用 wait_urc 的调用（port, urc_pattern），供测试断言
        self.wait_urc_calls: list[tuple[str, str]] = []
        self._urc_handlers: dict[str, list[URCHandler]] = {}
        self._rx_observers: dict[str, list[Callable[[bytes], None]]] = {}
        self._tx_observers: dict[str, list[Callable[[bytes], None]]] = {}
        self._fail_open: set[str] = set()
        self._log_files: dict[str, Path | None] = {}

    # ------------------------------------------------------------------
    # 脚本设置
    # ------------------------------------------------------------------
    def script(
        self,
        port: str,
        response: Response,
        *,
        match: str | None = None,
        persistent: bool = False,
    ) -> None:
        """预设响应。persistent=True 时该响应不消费（retry/poll 多次返回同一响应）."""
        self._scripts.setdefault(port, []).append(
            _ScriptedResponse(response=response, match=match, consume_after=not persistent)
        )

    def script_text(
        self, port: str, text: str, *, match: str | None = None, persistent: bool = False
    ) -> None:
        """便捷：预设成功响应文本."""
        self.script(port, Response(text=text), match=match, persistent=persistent)

    def fail_open(self, port: str) -> None:
        """让某端口 open 时失败（模拟端口占用）."""
        self._fail_open.add(port)

    def emit_urc(self, port: str, text: str) -> None:
        """模拟设备主动上报 URC（测试 URC 处理）."""
        evt = URCEvent(port=port, text=text)
        for h in self._urc_handlers.get(port, []):
            h(evt)

    # ------------------------------------------------------------------
    # IConnectionManager
    # ------------------------------------------------------------------
    def open(self, config: PortConfig) -> None:
        if config.name in self._fail_open:
            from atprobe.infra.serial.exceptions import PortOpenError

            raise PortOpenError(config.name, "模拟占用")
        self._configs[config.name] = config
        self._connected.add(config.name)

    def close(self, port: str) -> None:
        self._connected.discard(port)
        # 对齐真实 PortManager.close（L111）：关闭端口即解除用例日志绑定，
        # 避免 close 后再 open 沿用旧用例日志路径（审查 I1）
        self._log_files.pop(port, None)

    def close_all(self) -> None:
        self._connected.clear()

    def is_connected(self, port: str) -> bool:
        return port in self._connected

    def enumerate_ports(self) -> list[PortInfo]:
        return [PortInfo(name=p, description="fake", in_use=False) for p in sorted(self._connected)]

    def config_of(self, port: str) -> PortConfig:
        return self._configs.get(port, PortConfig(name=port))

    def set_case_log(self, port: str, log_file: Path | None) -> None:
        self._log_files[port] = log_file

    def clear_case_log(self, port: str) -> None:
        self._log_files.pop(port, None)

    # ------------------------------------------------------------------
    # 收发双路径派发（与真实 SerialConnection 行为对齐，M8 日志修复支撑）：
    # 1) TX/RX observer 派发（监控语义，M6 §6.2）——真实 send_command 的
    #    _notify_tx_observers / 读线程 RX 派发同构；
    # 2) 用例原始日志（raw_logger + set_case_log 绑定路径，M1 §7）——真实
    #    connection._log_tx/_log_rx 同构。此前 Fake 两者皆缺，共享 PM 模式
    #    （GUI/MCP）的日志链路无法在测试中覆盖。
    # ------------------------------------------------------------------
    def _emit_tx(self, port: str, command: str, *, terminator: Terminator | None = None) -> None:
        """模拟发送帧：派发 TX observer 并按需写用例日志（命令 + 结束符）."""
        cfg = self._configs.get(port, PortConfig(name=port))
        term = terminator if terminator is not None else cfg.terminator
        payload = command.encode("utf-8") + term.value.encode("ascii")
        for obs in list(self._tx_observers.get(port, [])):
            obs(payload)
        lf = self._log_files.get(port)
        if self._raw_logger is not None and lf is not None:
            self._raw_logger.log(lf, "TX", payload)

    def _emit_rx(self, port: str, text: str) -> None:
        """模拟接收帧：派发 RX observer 并按需写用例日志（响应文本 → 字节）."""
        data = text.encode("utf-8")
        for obs in list(self._rx_observers.get(port, [])):
            obs(data)
        lf = self._log_files.get(port)
        if self._raw_logger is not None and lf is not None:
            self._raw_logger.log(lf, "RX", data)

    # ------------------------------------------------------------------
    # ICommandSender
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
        """发送命令（消费预设脚本）.

        Args:
            pre_check: 派发前调用的回调（对齐真实 PortManager 透传/连接层锁内执行的
                契约——Fake 无锁，直调即可）；抛异常则透传、不派发。批 3 MCP 接线用。
        """
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled("FakeSerial 被取消")
        if pre_check is not None:
            pre_check()
        self.sent.append((port, command))
        # wait_urc 由测试预设的 Response.text 直接体现（Fake 不做真实读线程/终结判定），
        # 这里仅记录，便于测试断言调用方确实启用了 URC 等待模式。
        if wait_urc is not None:
            self.wait_urc_calls.append((port, wait_urc))
        self._emit_tx(port, command)  # observer 派发 + 用例日志（对齐真实发送路径）
        scripts = self._scripts.get(port, [])
        # 找匹配的脚本（先 match 精确，再通配）
        idx = None
        for i, sr in enumerate(scripts):
            if sr.match is None or sr.match in command:
                idx = i
                break
        if idx is None:
            return Response(text="", status=ResponseStatus.ERROR, error="无预设响应")
        sr = scripts[idx]
        if sr.consume_after:
            scripts.pop(idx)
        # 模拟发送耗时（让 duration_ms 有意义）
        self._sleep(0.0)
        self._emit_rx(port, sr.response.text)  # 有响应才派发 RX（对齐真实超时语义）
        return sr.response

    # ------------------------------------------------------------------
    # IURCSubscriber
    # ------------------------------------------------------------------
    def subscribe_urc(self, port: str, handler: URCHandler) -> object:
        self._urc_handlers.setdefault(port, []).append(handler)
        return (port, handler)

    def unsubscribe_urc(self, handle: object) -> None:
        if isinstance(handle, tuple) and len(handle) == 2:
            port, handler = handle  # type: ignore[misc]
            hs = self._urc_handlers.get(port, [])  # type: ignore[arg-type]
            if handler in hs:  # type: ignore[operator]
                hs.remove(handler)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # 原始 RX/TX 字节流订阅 + 流式写（手动调试/实时监控用，M6 §6.2）
    # ------------------------------------------------------------------
    def subscribe_rx(self, port: str, observer: Callable[[bytes], None]) -> object:
        self._rx_observers.setdefault(port, []).append(observer)
        return (port, observer)

    def unsubscribe_rx(self, handle: object) -> None:
        if isinstance(handle, tuple) and len(handle) == 2:
            port, observer = handle  # type: ignore[misc]
            obs = self._rx_observers.get(port, [])  # type: ignore[arg-type]
            if observer in obs:  # type: ignore[operator]
                obs.remove(observer)  # type: ignore[arg-type]

    def subscribe_tx(self, port: str, observer: Callable[[bytes], None]) -> object:
        self._tx_observers.setdefault(port, []).append(observer)
        return (port, observer)

    def unsubscribe_tx(self, handle: object) -> None:
        if isinstance(handle, tuple) and len(handle) == 2:
            port, observer = handle  # type: ignore[misc]
            obs = self._tx_observers.get(port, [])  # type: ignore[arg-type]
            if observer in obs:  # type: ignore[operator]
                obs.remove(observer)  # type: ignore[arg-type]

    def write_command(
        self, port: str, command: str, *, terminator: Terminator | None = None
    ) -> None:
        """流式写：记录命令（与 send_command 同口径），供测试断言.

        同时向 TX 观察者派发实际写入的字节（含结束符），模拟真实写线程行为
        （经 _emit_tx 统一收发双路径：observer 派发 + 用例日志）。
        不会自动触发 RX 观察者；测试需用 emit_rx() 主动喂入回包。
        """
        self.sent.append((port, command))
        self._emit_tx(port, command, terminator=terminator)

    def write_bytes(self, port: str, data: bytes) -> None:
        """流式写原始字节（不加结束符）——P2 修复：与 PortManager 接口对齐.

        旧实现缺失本方法，Fake 无法完整替换真实 PortManager（文件发送等
        write_bytes 路径在 Fake 驱动的测试中直接 AttributeError）。
        """
        self.sent.append((port, f"<bytes:{len(data)}>"))
        for obs in self._tx_observers.get(port, []):
            obs(data)
        # 用例日志与 _emit_tx 同构（对齐真实 connection 的 write 路径走 _log_tx，
        # 审查 M1）：绑定中的端口原始字节写同样落用例日志
        lf = self._log_files.get(port)
        if self._raw_logger is not None and lf is not None:
            self._raw_logger.log(lf, "TX", data)

    def emit_rx(self, port: str, data: bytes) -> None:
        """测试辅助：向某端口的 RX 观察者投递字节（模拟模块回包）."""
        for obs in self._rx_observers.get(port, []):
            obs(data)
