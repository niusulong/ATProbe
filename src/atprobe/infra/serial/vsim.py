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

# 复用库级应答状态机（同一份事实源，src/ 自包含，不依赖 tools/）
from atprobe.infra.serial.atresponder import AtResponder
from atprobe.infra.serial.config import DataStreamSpec, PortConfig
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import (
    CancelToken,
    PortInfo,
    Response,
    ResponseStatus,
)
from atprobe.infra.serial.rawlog import RawLogger

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
        raw_logger: RawLogger | None = None,
        fs_timeout_s: float | None = None,
    ) -> None:
        super().__init__(clock=clock, sleep=sleep, raw_logger=raw_logger)
        self._responder = AtResponder(rssi=rssi, cereg=cereg, fs_timeout_s=fs_timeout_s)
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
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
        pre_check: Callable[[], None] | None = None,
    ) -> Response:
        # pre_check：派发前调用（对齐真实 PortManager 透传/连接层锁内执行契约，
        # Vsim 无锁直调；批 3 MCP 接线用，防传参 TypeError）
        if cancel is not None and cancel.cancelled:
            from atprobe.infra.serial.exceptions import OperationCancelled

            raise OperationCancelled("Vsim 被取消")
        if pre_check is not None:
            pre_check()
        self.sent.append((port, command))
        # wait_urc/expect 由 AtResponder 生成的响应文本体现，此处仅接受以保持接口一致
        _ = wait_urc
        _ = expect
        self._emit_tx(port, command)  # observer 派发 + 用例日志（对齐真实发送路径）
        frame = self._responder.respond(command)
        if not frame:
            return Response(text="", status=ResponseStatus.ERROR, error="空指令")
        text = frame.decode("utf-8", errors="replace")
        self._emit_rx(port, text)  # 有响应才派发 RX（对齐真实超时语义）
        # 注：ERROR 也是完整响应（由断言判定失败），无需单独状态——旧实现此处
        # 有一行无意义的死赋值（status = COMPLETE），已清理
        status = ResponseStatus.COMPLETE
        if self._echo:
            sys.stderr.write(f"[vsim] > {command}\n")
            for line in text.split("\r\n"):
                if line:
                    sys.stderr.write(f"[vsim] < {line}\n")
            sys.stderr.flush()
        return Response(text=text, status=status)

    # ------------------------------------------------------------------
    # §3.2 数据流发送（委托 AtResponder 两阶段状态机，设计 §2.3）
    # ------------------------------------------------------------------
    def send_data(
        self,
        port: str,
        spec: DataStreamSpec,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        """发送数据流（委托 AtResponder 数据会话状态机）.

        会话收满 → 完整帧 COMPLETE；未收满且 fs_timeout_s 已配置 → 模拟设备
        侧等数据超时（sleep 后 expire_pending 强制出帧）；未收满且未配置 →
        TIMEOUT（设备静默等数据，引擎步骤超时路径接管）。wait_urc/expect
        继承 Fake 行为仅记录（由响应文本直接体现）。数据走 data_sent 记录，
        不混入 sent（命令/数据口径分离）。
        """
        if cancel is not None and cancel.cancelled:
            from atprobe.infra.serial.exceptions import OperationCancelled

            raise OperationCancelled("Vsim 被取消")
        self.data_sent.append((port, spec.data))
        if wait_urc is not None:
            self.wait_urc_calls.append((port, wait_urc))
        if expect is not None:
            self.expect_calls.append((port, expect))
        self._emit_tx_bytes(port, spec.data)
        frame = self._responder.receive_data(spec.data)
        if frame:
            text = frame.decode("utf-8", errors="replace")
            self._emit_rx(port, text)  # 有响应才派发 RX（对齐真实超时语义）
            return Response(text=text, status=ResponseStatus.COMPLETE)
        # 会话未收满：设备侧等数据超时出帧，或静默交引擎超时路径
        if self._responder.fs_timeout_s is not None:
            self._sleep(self._responder.fs_timeout_s)
            frame = self._responder.expire_pending()
            text = frame.decode("utf-8", errors="replace")
            self._emit_rx(port, text)
            return Response(text=text, status=ResponseStatus.COMPLETE)
        return Response(text="", status=ResponseStatus.TIMEOUT, error="等待数据超时")

    # URC 订阅/用例日志绑定（subscribe_urc/set_case_log）继承 FakePortManager：
    # 演示模式默认不主动上报，如需可由调用方调用继承的 emit_urc。
