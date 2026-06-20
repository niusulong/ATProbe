"""FakeSerial — 测试用串口模拟器（TSD §8.5）.

实现 ICommandSender / IConnectionManager / IURCSubscriber 接口（鸭子类型 Protocol），
内部维护「响应脚本队列」：测试预设「发 X 返回 Y」，按序消费。
支持注入异常、按次数返回不同响应、时间控制。

放 src/atprobe/infra/serial/ 以便集成测试与（未来）演示模式共用。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import (
    CancelToken,
    PortInfo,
    Response,
    ResponseStatus,
    URCEvent,
    URCHandler,
)


@dataclass
class _ScriptedResponse:
    """一条预设响应：匹配发送的命令，返回指定响应."""

    response: Response
    match: str | None = None  # None = 匹配任意命令（按序消费）
    consume_after: bool = True  # 消费后是否从队列移除（False = 每次都返回这个，用于 retry/poll）


class FakePortManager:
    """PortManager 的 Fake 实现，供集成测试驱动引擎（无需真实硬件）.

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
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._configs: dict[str, PortConfig] = {}
        self._connected: set[str] = set()
        # port -> 脚本响应队列
        self._scripts: dict[str, list[_ScriptedResponse]] = {}
        # 记录所有发送过的命令（port, command）
        self.sent: list[tuple[str, str]] = []
        self._urc_handlers: dict[str, list[URCHandler]] = field(default_factory=dict)  # type: ignore[assignment]
        self._urc_handlers = {}
        self._rx_observers: dict[str, list[Callable[[bytes], None]]] = {}
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

    def script_text(self, port: str, text: str, *, match: str | None = None, persistent: bool = False) -> None:
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
    # ICommandSender
    # ------------------------------------------------------------------
    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled("FakeSerial 被取消")
        self.sent.append((port, command))
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
    # 原始 RX 字节流订阅 + 流式写（手动调试/实时监控用，§6.2）
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

    def write_command(self, port: str, command: str) -> None:
        """流式写：记录命令（与 send_command 同口径），供测试断言.

        不会自动触发 RX 观察者；测试需用 emit_rx() 主动喂入回包。
        """
        self.sent.append((port, command))

    def emit_rx(self, port: str, data: bytes) -> None:
        """测试辅助：向某端口的 RX 观察者投递字节（模拟模块回包）."""
        for obs in self._rx_observers.get(port, []):
            obs(data)
