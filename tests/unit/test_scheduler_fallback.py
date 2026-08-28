"""Scheduler 兜底与压测结果完整性测试（本轮 P1 修复配套）.

覆盖：
    - 主循环异常兜底：sender 抛非预期异常 → start() 正常返回 error 结果、
      状态机终结（不卡 RUNNING）、handler 收到 EngineFinishedEvent
    - KeyboardInterrupt → 状态 FINISHED（非 ERROR）、error 注明中断
    - 压测用例 teardown 进 CaseResult（旧实现 return 早于 finally）

Engine 构造沿用 test_engine.py 模式：FakePortManager 既是 sender 也是
port_manager（引擎从 sender 上发现连接管理能力）。
"""

from __future__ import annotations

from atprobe.domain.case.models import Case, LoopConfig, Step
from atprobe.engine.config import EngineConfig, EngineState
from atprobe.engine.interfaces import EngineFinishedEvent
from atprobe.engine.scheduler import Engine
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import (
    CancelToken,
    Response,
    ResponseStatus,
)


class _ExplodingFake(FakePortManager):
    """第 N 次发送抛指定异常的 Fake（模拟引擎内部意外错误）."""

    def __init__(self, exc: BaseException, explode_on_call: int = 1) -> None:
        super().__init__(sleep=lambda s: None)
        self._exc = exc
        self._explode_on = explode_on_call
        self.calls = 0

    def send_command(
        self,
        port: str,
        command: str,
        *,
        timeout: float | None = None,
        wait_urc: str | None = None,
        expect: str | None = None,
        cancel: CancelToken | None = None,
    ) -> Response:
        # expect：step_runner 无条件透传（批 2b Task 6），替身只接受不消费
        _ = expect
        self.calls += 1
        if self.calls >= self._explode_on:
            raise self._exc
        return Response(text="\r\nOK\r\n", status=ResponseStatus.COMPLETE)


def _case(
    steps: list[Step], teardown: list[Step] | None = None, loop: LoopConfig | None = None
) -> Case:
    return Case(name="兜底测试", steps=tuple(steps), teardown=tuple(teardown or ()), loop=loop)


def _cfg(cases: list[Case]) -> EngineConfig:
    # F-9：EngineConfig.ports 不可为空——错误路径测试也带一个（虚拟）端口；
    # sender 由 FakePortManager 替身提供，open 走 Fake 无真实副作用
    return EngineConfig(ports=(PortConfig(name="V0"),), cases=tuple(cases))


class TestEngineFallback:
    def test_unexpected_exception_returns_error_result(self) -> None:
        """sender 抛 RuntimeError → start 返回 error 结果、状态 ERROR、finished 事件发出."""
        events: list[object] = []
        fake = _ExplodingFake(RuntimeError("boom"))
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        result = engine.start(_cfg([_case([Step(command="AT")])]), handler=events.append)
        assert result.error is not None and "boom" in result.error
        assert engine.state() is EngineState.ERROR  # 不再卡 RUNNING
        assert any(isinstance(e, EngineFinishedEvent) for e in events)

    def test_keyboard_interrupt_finishes_not_error(self) -> None:
        """KeyboardInterrupt → 状态 FINISHED、error 注明中断（BaseException 兜底）."""
        fake = _ExplodingFake(KeyboardInterrupt())
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        result = engine.start(_cfg([_case([Step(command="AT")])]))
        assert "中断" in (result.error or "")
        assert engine.state() is EngineState.FINISHED


class TestPressureTeardownInResult:
    def test_pressure_case_result_contains_teardown(self) -> None:
        """压测用例的 teardown 步骤结果进 CaseResult（旧实现 return 早于 finally）."""
        fake = FakePortManager(sleep=lambda s: None)
        fake.open(PortConfig(name="V0"))
        engine = Engine(sender_factory=lambda: fake, sleep=lambda s: None)
        cfg = EngineConfig(
            ports=(PortConfig(name="V0"),),
            cases=(
                _case(
                    [Step(command="AT")],
                    teardown=[Step(command="AT+Z")],
                    loop=LoopConfig(count=3, warmup=0),
                ),
            ),
        )
        result = engine.start(cfg)
        assert len(result.case_results) == 1
        cr = result.case_results[0]
        teardown_cmds = [sr.command for sr in cr.teardown_results]
        assert teardown_cmds == ["AT+Z"], "压测 teardown 结果应进 CaseResult"


class TestExplodingFakeSanity:
    """_ExplodingFake 行为自检（保证上面两个测试的前提成立）."""

    def test_explodes_as_expected(self) -> None:
        fake = _ExplodingFake(RuntimeError("x"), explode_on_call=2)
        assert fake.send_command("V0", "AT").status is ResponseStatus.COMPLETE
        try:
            fake.send_command("V0", "AT")
        except RuntimeError:
            pass
        else:
            raise AssertionError("应在第 2 次抛出") from None


class TestSenderParseFailureEmitsFinished:
    """P1-7：sender 解析失败路径也发 EngineFinishedEvent（GUI 面板以该事件收尾）."""

    def test_factory_exception_emits_finished_event(self) -> None:
        def _boom() -> object:
            raise ValueError("factory broken")

        events: list[object] = []
        eng = Engine(sender_factory=_boom)
        result = eng.start(_cfg([]), handler=events.append)
        assert result.error is not None
        assert result.error.startswith("sender 解析失败")
        assert any(isinstance(e, EngineFinishedEvent) for e in events), (
            "sender 解析失败必须补发 EngineFinishedEvent——否则 GUI 进度面板永久悬挂"
        )
