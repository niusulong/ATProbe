"""进程内虚拟模组端口管理器（零驱动依赖的演示/联调模式）.

当没有开发板、也没装虚拟串口对（com0com/socat）时，用本类作为引擎的 sender：
直接在进程内把 ATProbe 发出的 AT 指令交给 ``atprobe.infra.serial.atresponder.AtResponder``
生成响应，不经过任何真实串口/驱动。引擎、提取器、断言、压测、报告全链路照常工作。
（注：``tools/vsim/at_responder.py`` 仅是同一应答状态机的 CLI 包装，库级事实源在 src/。）

用法（CLI 通过 ``--vsim`` 自动注入）::

    from atprobe.infra.serial.vsim import VsimPortManager
    engine = Engine(sender_factory=lambda: VsimPortManager(rssi=23, cereg=1))
    result = engine.start(cfg)

与 ``FakePortManager`` 的区别：Fake 需要测试逐条预设响应脚本；VsimPortManager
按指令动态生成真实模组风格的响应，适合「整条用例跑一遍看结果」的演示场景。
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

# 复用库级应答状态机（同一份事实源，src/ 自包含，不依赖 tools/）
from atprobe.infra.serial.atresponder import AtResponder
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import (
    CancelToken,
    PortInfo,
    Response,
    ResponseStatus,
    URCHandler,
)

# 演示用的虚拟端口名（对用户可见，但不会真正打开硬件）
VSIM_PORT = "VSIM0"


class VsimPortManager(FakePortManager):
    """按指令动态生成响应的虚拟模组端口管理器."""

    def __init__(
        self,
        *,
        rssi: int = 23,
        cereg: int = 1,
        echo: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(clock=clock, sleep=sleep)
        self._responder = AtResponder(rssi=rssi, cereg=cereg)
        self._echo = echo  # 是否在控制台打印每条收发（演示用）

    # ------------------------------------------------------------------
    # 连接管理：任意端口都视作可连，演示模式下不真正打开硬件
    # ------------------------------------------------------------------
    def open(self, config: PortConfig) -> None:
        # 不调用父类的 fail_open 检查；演示模式一律放行
        self._configs[config.name] = config
        self._connected.add(config.name)

    def enumerate_ports(self) -> list[PortInfo]:
        # 暴露一个虚拟端口，让 GUI/CLI 端口列表非空
        return [PortInfo(name=VSIM_PORT, description="虚拟模组（进程内）", in_use=False)]

    # ------------------------------------------------------------------
    # 命令发送：委托给 AtResponder 动态生成响应
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
            from atprobe.infra.serial.exceptions import OperationCancelled

            raise OperationCancelled("Vsim 被取消")
        self.sent.append((port, command))
        frame = self._responder.respond(command)
        if not frame:
            return Response(text="", status=ResponseStatus.ERROR, error="空指令")
        text = frame.decode("utf-8", errors="replace")
        status = ResponseStatus.COMPLETE
        if text.rstrip().endswith("ERROR"):
            status = ResponseStatus.COMPLETE  # ERROR 也是完整响应，由断言判定失败
        if self._echo:
            sys.stderr.write(f"[vsim] > {command}\n")
            for line in text.split("\r\n"):
                if line:
                    sys.stderr.write(f"[vsim] < {line}\n")
            sys.stderr.flush()
        return Response(text=text, status=status)

    # ------------------------------------------------------------------
    # URC：演示模式默认不主动上报（如需可由调用方调用继承的 emit_urc）
    # ------------------------------------------------------------------
    def subscribe_urc(self, port: str, handler: URCHandler) -> object:
        return super().subscribe_urc(port, handler)

    def set_case_log(self, port: str, log_file: Path | None) -> None:
        self._log_files[port] = log_file
