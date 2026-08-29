"""tests/unit 共享测试替身（批 5 T4：ICommandSender 替身收敛到共享基类）.

与 tests/conftest.py 的分工：conftest 提供 pytest 夹具（fake_port 等）；
本模块提供可继承的替身基类，测试文件直接 import——tests/unit 目录经
pytest prepend 导入模式自动入 sys.path，无需 __init__.py。

与 src/atprobe/infra/serial/fakeserial.py 的 FakePortManager 分工：
FakePortManager 是全功能 PortManager 替身（连接管理 + URC + RX/TX observer
派发），面向引擎级/集成测试；FakeCommandSender 是纯 ICommandSender 最小
替身，面向 execute_step / run_pressure 等纯函数单测——只需发送通道，
无需端口管理（放 tests/ 而非 src/ 的原因：非生产代码，无演示模式需求）。
"""

from __future__ import annotations

from collections.abc import Callable

from atprobe.infra.serial.config import DataStreamSpec
from atprobe.infra.serial.exceptions import OperationCancelled
from atprobe.infra.serial.interfaces import (
    CancelToken,
    ICommandSender,
    Response,
    ResponseStatus,
)


class FakeCommandSender(ICommandSender):
    """ICommandSender 测试替身基类：方法签名逐字对齐协议（含 pre_check）.

    背景：各测试文件曾各自手写替身，历史上出现过形参缺失（expect，后来又有
    pre_check）与协议失配——调用方按协议传参即 TypeError，且缺 send_data 的
    替身连 runtime_checkable 的 isinstance 检查都过不了。继承本类即自动
    保持全形参对齐，子类只需覆写特有行为。

    默认行为（对齐 FakePortManager 的脚本消费惯例，见 fakeserial.py）：
        - 全局 FIFO 脚本队列（构造入参 ``script``）：项为 Response 则返回、
          BaseException 则抛出（异常注入路径）；耗尽返回默认 OK
          （``\\r\\nOK\\r\\n``/COMPLETE——轮询/重试测试耗尽后仍可继续）。
          与 FakePortManager「无脚本返回 ERROR('无预设响应')」的差异是有意
          的：本类面向纯函数单测的轻量脚本，缺省成功更省事；
        - 数据路径与命令路径共用队列：队列无 match 概念（等价全通配），即
          FakePortManager「send_data 仅消费 match=None 脚本」惯例的退化形态
          （match 是命令子串语义，不适用字节流，本类索性不设 match）；
        - cancel 已触发 → 入口即抛 OperationCancelled（先于记录/消费）；
        - pre_check 直调（Fake 无命令锁，同 FakePortManager），抛错透传且
          不记录、不消费；
        - sent / data_sent 分开记录命令与数据（口径分离，同 FakePortManager）；
          calls / data_calls 分别计数（calls 语义沿用既有 FakeSender 惯例：
          仅统计 send_command）。
    """

    def __init__(self, script: list[Response | BaseException] | None = None) -> None:
        self._script: list[Response | BaseException] = list(script) if script else []
        self.sent: list[tuple[str, str]] = []
        self.data_sent: list[tuple[str, bytes]] = []
        self.calls = 0
        self.data_calls = 0

    def _pop_scripted(self) -> Response:
        """消费队首脚本项：异常抛出（注入），耗尽返回默认 OK."""
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)

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
        """发送命令（消费脚本队列）——签名逐字对齐 ICommandSender.send_command.

        timeout/wait_urc/expect 由测试预设的 Response 直接体现（替身不做真实
        读线程/字节级匹配，与 FakePortManager 同款「只接受不消费」惯例）。
        """
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled("FakeCommandSender 被取消")
        if pre_check is not None:
            pre_check()
        self.sent.append((port, command))
        self.calls += 1
        _ = timeout, wait_urc, expect
        return self._pop_scripted()

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
        """发送数据流（消费脚本队列）——签名逐字对齐 ICommandSender.send_data.

        与 send_command 同构；无 pre_check 形参（协议如此：数据路径无 MCP
        直连需求，见 interfaces.py send_data docstring）。
        """
        if cancel is not None and cancel.cancelled:
            raise OperationCancelled("FakeCommandSender 被取消")
        self.data_sent.append((port, spec.data))
        self.data_calls += 1
        _ = timeout, wait_urc, expect
        return self._pop_scripted()
