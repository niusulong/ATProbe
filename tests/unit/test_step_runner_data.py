"""data 步骤引擎接线回归（批 2b Task 6，修 P0-1）.

覆盖：
    1. data.file / inline / inline_hex 全链：字节真正经 send_data 发出（旧实现
       把渲染后的文件路径当命令文本 send_command，从未发过数据——P0-1）；
    2. S-8 数据路径信任边界：渲染后路径须落在「用例目录 ∪ data_allowed_roots」，
       越界/``../`` 逃逸 → DataPathError → 作者错误路径 FAIL（走 on_failure 决策）；
    3. 零字节拒绝（空文件/渲染空十六进制）→ 作者错误 FAIL；
    4. command 步骤 ``{{file_size()}}``（S-8 锚定同 data 路径）；
    5. interval 接线：每次 attempt 发送前固定延迟（ch06「> 后延迟再发数据」）；
    6. expect 透传：step.expect → sender 的 expect 形参（command/data 两形态）；
    7. data×wait_urc（TCP 阶段二形态）与 data×retry（重发即重新走 send_data）；
    8. vsim 端到端：TCPSEND/FSWF 两阶段「expect 提示符 → send_data → URC/OK」
       整链在虚拟模组上闭环（最关键——锁定真实发送字节与会话状态机）。

FakePortManager 驱动（script/脚本消费与 data_sent/expect_calls 记录已就位）；
vsim 段直接用 VsimPortManager（send_command 覆写为 responder 生成，不需脚本）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from atprobe.domain.case.models import (
    AssertElement,
    DataInput,
    FailureStrategy,
    RetryConfig,
    Step,
)
from atprobe.domain.report.models import InputType, StepStatus
from atprobe.engine.step_runner import CaseContext, StepExecResult, execute_step
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import (
    ICommandSender,
    Response,
    ResponseStatus,
)
from atprobe.infra.serial.vsim import VSIM_PORT, VsimPortManager

PORT = "COM9"


def _no_sleep(_seconds: float) -> None:
    """注入用零休眠（interval/retry 间隔不真等）。"""


def _run(
    step: Step,
    ctx: CaseContext,
    sender: ICommandSender,
    *,
    sleep: Callable[[float], None] = _no_sleep,
    port: str = PORT,
) -> StepExecResult:
    return execute_step(
        step,
        index=1,
        phase="steps",
        ctx=ctx,
        sender=sender,
        default_port=port,
        step_timeout_default=5.0,
        clock=time.monotonic,
        sleep=sleep,
    )


def _fake() -> FakePortManager:
    return FakePortManager(sleep=_no_sleep)


# ---------------------------------------------------------------------------
# 1. 三种数据源全链：字节真正发出
# ---------------------------------------------------------------------------
class TestDataSources:
    def test_file_full_chain(self, tmp_path: Path) -> None:
        """data.file：锚集内文件 → 字节发出、request 为摘要、input_type=DATA、断言生效."""
        payload = tmp_path / "payload.bin"
        payload.write_bytes(b"AT+DATA123")
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")  # match=None → 对 data 路径生效
        step = Step(
            data=DataInput(file="payload.bin"),
            assert_=[AssertElement(contains="OK")],
        )
        r = _run(step, CaseContext(case_dir=tmp_path), fake)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"AT+DATA123")]  # P0-1：旧实发的是路径文本
        assert fake.sent == []  # data 不混入命令记录
        assert r.step_result.input_type is InputType.DATA
        assert r.step_result.request == "[data 10字节] AT+DATA123"
        assert r.step_result.command == "[data 10字节] AT+DATA123"

    def test_file_with_variable_path(self, tmp_path: Path) -> None:
        """data.file 路径本身含模板变量：渲染后再做 S-8 锚定与读取."""
        payload = tmp_path / "v.bin"
        payload.write_bytes(b"\x00\x01\x02")
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(data=DataInput(file="{{fname}}"))
        ctx = CaseContext(case_dir=tmp_path)
        ctx.variables["fname"] = "v.bin"
        r = _run(step, ctx, fake)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"\x00\x01\x02")]  # 二进制原样字节

    def test_inline_renders_variables(self) -> None:
        """inline：模板渲染 → UTF-8 字节."""
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(data=DataInput(inline="hello {{name}}"))
        ctx = CaseContext()
        ctx.variables["name"] = "world"
        r = _run(step, ctx, fake)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"hello world")]

    def test_inline_hex_renders_variable(self) -> None:
        """inline_hex：变量渲染后按十六进制解析（"48656C6C6F" → b"Hello"）."""
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(data=DataInput(inline_hex="{{hex_var}}"))
        ctx = CaseContext()
        ctx.variables["hex_var"] = "48656C6C6F"
        r = _run(step, ctx, fake)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"Hello")]

    def test_inline_hex_bad_rendered_hex_is_author_error(self) -> None:
        """渲染注入坏十六进制 → DataPathError → FAIL 走 on_failure 决策."""
        fake = _fake()
        step = Step(
            data=DataInput(inline_hex="{{hex_var}}"),
            on_failure=FailureStrategy.CONTINUE,
        )
        ctx = CaseContext()
        ctx.variables["hex_var"] = "zz-not-hex"
        r = _run(step, ctx, fake)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False
        assert "inline_hex 解析失败" in r.step_result.error_msg
        assert fake.data_sent == []  # 解析失败不发送


# ---------------------------------------------------------------------------
# 2. S-8：数据路径信任边界
# ---------------------------------------------------------------------------
class TestS8Anchoring:
    def test_absolute_path_outside_roots_rejected(self, tmp_path: Path) -> None:
        """锚集外绝对路径 → FAIL，error 含越界信息，on_failure: continue 不中止."""
        outside = tmp_path.parent / "s8_outside_root"
        outside.mkdir(exist_ok=True)
        payload = outside / "outside.bin"
        payload.write_bytes(b"secret")
        fake = _fake()
        step = Step(
            data=DataInput(file=str(payload)),
            on_failure=FailureStrategy.CONTINUE,
        )
        r = _run(step, CaseContext(case_dir=tmp_path), fake)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False  # 作者错误与模板失败同口径，尊重 on_failure
        msg = r.step_result.error_msg
        assert msg is not None and "越界" in msg  # DataPathError 信息（含路径与锚集）
        assert str(payload) in (msg or "")
        assert fake.data_sent == []  # 越界路径未发出任何字节

    def test_dotdot_escape_rejected(self, tmp_path: Path) -> None:
        """相对路径 ../ 逃逸出用例目录 → 同样越界 FAIL."""
        escape = tmp_path.parent / "s8_escape.bin"
        escape.write_bytes(b"escaped")  # resolve 目标存在（更贴近真实场景）
        fake = _fake()
        step = Step(
            data=DataInput(file="../s8_escape.bin"),
            on_failure=FailureStrategy.CONTINUE,
        )
        r = _run(step, CaseContext(case_dir=tmp_path), fake)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False
        assert fake.data_sent == []
        msg = r.step_result.error_msg
        assert msg is not None and "越界" in msg

    def test_extra_root_allows_outside_case_dir(self, tmp_path: Path) -> None:
        """data_allowed_roots 额外根：用例目录外的文件在锚集内 → 放行."""
        shared = tmp_path.parent / "s8_shared_root"
        shared.mkdir(exist_ok=True)
        payload = shared / "shared.bin"
        payload.write_bytes(b"shared-bytes")
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(data=DataInput(file=str(payload)))
        r = _run(step, CaseContext(case_dir=tmp_path, data_allowed_roots=(shared,)), fake)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"shared-bytes")]

    def test_default_abort_when_no_on_failure(self, tmp_path: Path) -> None:
        """未配置 on_failure 的越界 → 默认 ABORT（abort_case=True）."""
        outside = tmp_path.parent / "s8_outside_root"
        outside.mkdir(exist_ok=True)
        payload = outside / "abort.bin"
        payload.write_bytes(b"x")
        fake = _fake()
        step = Step(data=DataInput(file=str(payload)))
        r = _run(step, CaseContext(case_dir=tmp_path), fake)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is True


# ---------------------------------------------------------------------------
# 3. 零字节拒绝
# ---------------------------------------------------------------------------
class TestZeroBytes:
    def test_empty_file_rejected(self, tmp_path: Path) -> None:
        """空文件 → 0 字节 → 作者错误 FAIL（设备会等满声明长度，发空只会拖超时）."""
        (tmp_path / "empty.bin").write_bytes(b"")
        fake = _fake()
        step = Step(
            data=DataInput(file="empty.bin"),
            on_failure=FailureStrategy.CONTINUE,
        )
        r = _run(step, CaseContext(case_dir=tmp_path), fake)
        assert r.status is StepStatus.FAIL
        assert r.abort_case is False
        msg = r.step_result.error_msg
        assert msg is not None and "0 字节" in msg
        assert fake.data_sent == []

    def test_whitespace_rendered_hex_rejected(self) -> None:
        """变量渲染出纯空白十六进制 → b"" → 零字节拦截（模型拦不住渲染产物）."""
        fake = _fake()
        step = Step(data=DataInput(inline_hex="{{pad}}"))
        ctx = CaseContext()
        ctx.variables["pad"] = "   "
        r = _run(step, ctx, fake)
        assert r.status is StepStatus.FAIL
        msg = r.step_result.error_msg
        assert msg is not None and "0 字节" in msg
        assert fake.data_sent == []


# ---------------------------------------------------------------------------
# 4. command 步骤的 {{file_size()}}（S-8 锚定同 data 路径）
# ---------------------------------------------------------------------------
class TestFileSizeInCommand:
    def test_file_size_injected_into_command(self, tmp_path: Path) -> None:
        """AT+FSWF 长度参数取真实文件字节数（锚集内相对路径）."""
        (tmp_path / "p.bin").write_bytes(b"12345")  # 5 字节
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n", match="AT+FSWF")
        step = Step(command='AT+FSWF="t.txt",0,{{file_size("./p.bin")}},10000')
        r = _run(step, CaseContext(case_dir=tmp_path), fake)
        assert r.status is StepStatus.PASS
        assert fake.sent[0][1] == 'AT+FSWF="t.txt",0,5,10000'

    def test_file_size_outside_roots_rejected(self, tmp_path: Path) -> None:
        """锚集外文件 → TemplateRenderError（file_size 内部 S-8）→ 作者错误 FAIL."""
        outside = tmp_path.parent / "s8_outside_root"
        outside.mkdir(exist_ok=True)
        (outside / "q.bin").write_bytes(b"12345678")
        fake = _fake()
        step = Step(command="AT+X={{file_size('" + str(outside / "q.bin") + ")}}")
        r = _run(step, CaseContext(case_dir=tmp_path), fake)
        assert r.status is StepStatus.FAIL
        msg = r.step_result.error_msg
        assert msg is not None and "file_size" in msg


# ---------------------------------------------------------------------------
# 5. interval 接线（每次 attempt 发送前的固定延迟）
# ---------------------------------------------------------------------------
class TestInterval:
    def test_data_interval_sleeps_before_send(self) -> None:
        """data 步骤 interval=80 → 发送前 sleep(0.08)（ch06「> 后延迟再发」）."""
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        sleeps: list[float] = []

        def _rec_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            assert fake.data_sent == []  # 延迟必须发生在发送之前

        step = Step(data=DataInput(inline="hello"), interval=80)
        r = _run(step, CaseContext(), fake, sleep=_rec_sleep)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"hello")]
        assert sleeps == [pytest.approx(0.08)]

    def test_command_interval_sleeps_before_send(self) -> None:
        """command 步骤同样吃 interval（统一语义）."""
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        sleeps: list[float] = []
        step = Step(command="AT", interval=50)
        r = _run(step, CaseContext(), fake, sleep=sleeps.append)
        assert r.status is StepStatus.PASS
        assert sleeps == [pytest.approx(0.05)]


# ---------------------------------------------------------------------------
# 6. expect 透传（step.expect → sender 形参）
# ---------------------------------------------------------------------------
class TestExpectPassthrough:
    def test_command_expect_forwarded(self) -> None:
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(command="AT+TCPSEND=0,5", expect=r"\r\n>")
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.PASS
        assert fake.expect_calls == [(PORT, r"\r\n>")]

    def test_data_expect_forwarded(self) -> None:
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(data=DataInput(inline="hello"), expect=r"\r\nOK")
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.PASS
        assert fake.expect_calls == [(PORT, r"\r\nOK")]


# ---------------------------------------------------------------------------
# 7. data×wait_urc / data×retry
# ---------------------------------------------------------------------------
class TestDataWaitUrcAndRetry:
    def test_data_wait_urc_tcp_phase_two(self) -> None:
        """TCP 阶段二：数据发完等 +TCPSEND URC（响应文本 OK+URC）→ PASS."""
        fake = _fake()
        fake.script_text(PORT, "\r\nOK\r\n\r\n+TCPSEND: 0,5\r\n")
        step = Step(data=DataInput(inline="hello"), wait_urc=r"\+TCPSEND: 0,5")
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"hello")]
        assert fake.wait_urc_calls == [(PORT, r"\+TCPSEND: 0,5")]

    def test_data_retry_resends_bytes(self) -> None:
        """retry：首次失败（ERROR 响应）→ 重发数据 → 第二次成功."""
        fake = _fake()
        fake.script(PORT, Response(text="", status=ResponseStatus.ERROR, error="发送失败"))
        fake.script_text(PORT, "\r\nOK\r\n")
        step = Step(data=DataInput(inline="hello"), retry=RetryConfig(count=2, interval=0))
        r = _run(step, CaseContext(), fake)
        assert r.status is StepStatus.PASS
        assert fake.data_sent == [(PORT, b"hello"), (PORT, b"hello")]  # 尝试次数=2
        assert r.step_result.retry_count == 1


# ---------------------------------------------------------------------------
# 8. vsim 端到端：两阶段「expect 提示符 → send_data」整链
# ---------------------------------------------------------------------------
class TestVsimEndToEnd:
    def test_tcpsend_two_phase_chain(self) -> None:
        """AT+TCPSEND（expect 提示符）→ data（wait_urc +TCPSEND）两步全 PASS."""
        vsim = VsimPortManager(sleep=_no_sleep)
        vsim.open(PortConfig(name=VSIM_PORT))
        ctx = CaseContext()  # case_dir=None 且 inline 无路径 → S-8 不触发
        r1 = _run(Step(command="AT+TCPSEND=0,5", expect=r"\r\n>"), ctx, vsim, port=VSIM_PORT)
        assert r1.status is StepStatus.PASS
        r2 = _run(
            Step(data=DataInput(inline="hello"), wait_urc=r"\+TCPSEND: 0,5"),
            ctx,
            vsim,
            port=VSIM_PORT,
        )
        assert r2.status is StepStatus.PASS
        # 整链锁定：命令走 sent、数据走 data_sent（字节真发出，P0-1 闭环）
        assert vsim.sent == [(VSIM_PORT, "AT+TCPSEND=0,5")]
        assert vsim.data_sent == [(VSIM_PORT, b"hello")]
        assert "+TCPSEND: 0,5" in r2.step_result.response

    def test_fswf_write_then_fsrf_readback(self) -> None:
        """FSWF 写（expect 提示符 → data）→ FSRF 读回断言内容一致."""
        vsim = VsimPortManager(sleep=_no_sleep)
        vsim.open(PortConfig(name=VSIM_PORT))
        ctx = CaseContext()
        r1 = _run(
            Step(command='AT+FSWF="t.txt",0,5,10000', expect=r"\r\n>"),
            ctx,
            vsim,
            port=VSIM_PORT,
        )
        assert r1.status is StepStatus.PASS
        r2 = _run(Step(data=DataInput(inline="hello")), ctx, vsim, port=VSIM_PORT)
        assert r2.status is StepStatus.PASS  # 收满 5 字节 → OK
        assert vsim.data_sent == [(VSIM_PORT, b"hello")]
        r3 = _run(
            Step(
                command='AT+FSRF="t.txt",0,5',
                assert_=[AssertElement(contains="hello")],
            ),
            ctx,
            vsim,
            port=VSIM_PORT,
        )
        assert r3.status is StepStatus.PASS
        assert "+FSRF: 5,hello" in r3.step_result.response
