"""用例模型解析期校验单测（批 2b Task 1 / 批 3 Task 2）.

覆盖：Step.expect（附加完成条件正则）、DataInput.inline_hex（三选一数据源与
十六进制校验）、data×retry / data×poll 组合的解析期 warning（设计 §2.2，
数据流不可重入——不硬拒，仅告警）；批 3 追加：F-15 变量断言×响应断言混合
解析期拒绝、extract 保留字（timestamp/port）、warmup<count（F-12）、
data×压测 Case 级警告（2b 终审⑨）。
"""

from __future__ import annotations

import logging

import pytest

from atprobe.domain.case.models import (
    AssertElement,
    AssertionOp,
    Case,
    DataInput,
    LoopConfig,
    PollConfig,
    RetryConfig,
    Step,
)


def _case_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """筛出 atprobe.case logger 的 WARNING 级记录."""
    return [r for r in caplog.records if r.name == "atprobe.case" and r.levelno == logging.WARNING]


def _pressure_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """筛出 Case 级压测警告（文案含「压测」；Step 级 data×retry/poll 警告不含，以此区分层级）."""
    return [r for r in _case_warnings(caplog) if "压测" in r.getMessage()]


class TestStepExpect:
    def test_expect_valid(self) -> None:
        """合法 expect 正则正常构造（如 TCPSEND 提示符 \\r\\>）."""
        s = Step(command="AT+CIPSEND=0,10", expect=r"\r\n>")
        assert s.expect == r"\r\n>"

    def test_expect_default_none(self) -> None:
        """expect 缺省 None（向后兼容）."""
        s = Step(command="AT")
        assert s.expect is None

    def test_expect_invalid_regex_rejected(self) -> None:
        """非法 expect 正则在模型校验期拦截（与 wait_urc 同口径）."""
        with pytest.raises(ValueError, match="expect 正则无效"):
            Step(command="AT+X", expect="[")

    def test_expect_and_wait_urc_mutually_exclusive(self) -> None:
        """expect 与 wait_urc 均为自定义完成语义，不可同时指定."""
        with pytest.raises(ValueError, match="互斥"):
            Step(command="AT+X", expect=r"\r\n>", wait_urc=r"\+X:ok")


class TestDataInputInlineHex:
    def test_file_and_inline_hex_rejected(self) -> None:
        """file 与 inline_hex 同传：违反三选一."""
        with pytest.raises(ValueError, match="三选一"):
            DataInput(file="a.bin", inline_hex="41")

    def test_inline_and_inline_hex_rejected(self) -> None:
        """inline 与 inline_hex 同传：违反三选一."""
        with pytest.raises(ValueError, match="三选一"):
            DataInput(inline="txt", inline_hex="41")

    def test_all_sources_empty_rejected(self) -> None:
        """三源全空：违反三选一."""
        with pytest.raises(ValueError, match="三选一"):
            DataInput()

    def test_inline_hex_empty_string_rejected(self) -> None:
        """空串被拒（bytes.fromhex("") 静默得 0 字节，多为笔误）."""
        with pytest.raises(ValueError, match="inline_hex 不可为空字符串"):
            DataInput(inline_hex="")

    def test_inline_hex_invalid_hex_rejected(self) -> None:
        """非法十六进制在模型校验期拦截."""
        with pytest.raises(ValueError, match="inline_hex 不是合法十六进制串"):
            DataInput(inline_hex="GG")

    def test_inline_hex_with_whitespace_ok(self) -> None:
        """含 ASCII 空白的十六进制合法（bytes.fromhex 自带容忍）."""
        d = DataInput(inline_hex="41 42")
        assert d.inline_hex == "41 42"

    def test_inline_hex_alone_ok(self) -> None:
        """纯 inline_hex 单源合法."""
        d = DataInput(inline_hex="00ff10")
        assert d.inline_hex == "00ff10"


class TestDataRetryPollWarning:
    def test_data_with_retry_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """data+retry 组合发 warning：数据流不可重入（不硬拒）."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Step(data=DataInput(inline="payload"), retry=RetryConfig(count=2, interval=100))
        warns = _case_warnings(caplog)
        assert any("不可重入" in w.getMessage() for w in warns), (
            f"应发出 data×retry 不可重入 warning，实际：{[w.getMessage() for w in warns]}"
        )

    def test_data_with_poll_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """data+poll 组合同样发 warning."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Step(
                data=DataInput(inline_hex="41"),
                poll=PollConfig(until='x == "1"', timeout=5),
            )
        warns = _case_warnings(caplog)
        assert any("不可重入" in w.getMessage() for w in warns), (
            f"应发出 data×poll 不可重入 warning，实际：{[w.getMessage() for w in warns]}"
        )

    def test_data_without_retry_poll_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """data 无 retry/poll：正常，无 warning."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Step(data=DataInput(file="a.bin"))
        assert _case_warnings(caplog) == []

    def test_command_with_retry_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """command+retry 是常规组合：无 warning."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Step(command="AT", retry=RetryConfig(count=2))
        assert _case_warnings(caplog) == []


class TestAssertVarResponseExclusive:
    """F-15：变量断言与响应原文断言不可混用（解析期拒绝）.

    求值器按 is_var 分派只执行变量断言，混入的响应断言会静默丢失——
    校验器与求值器口径对齐，解析期拦截优于运行期静默。
    """

    @pytest.mark.parametrize(
        "field",
        [
            pytest.param({"contains": "OK"}, id="contains"),
            pytest.param({"not_contains": "ERR"}, id="not_contains"),
            pytest.param({"matches": r"OK$"}, id="matches"),
            pytest.param({"equals": "OK"}, id="equals"),
        ],
    )
    def test_mixed_rejected(self, field: dict[str, str]) -> None:
        """任一响应断言字段与 var/op 同现 → ValueError."""
        with pytest.raises(ValueError, match="不可同时指定"):
            AssertElement(var="x", op=AssertionOp.EQ, value="1", **field)

    def test_var_only_ok(self) -> None:
        """纯变量断言照常通过（既有口径零回归）."""
        a = AssertElement(var="x", op=AssertionOp.EQ, value="1")
        assert a.var == "x"
        assert a.contains is None

    def test_response_only_ok(self) -> None:
        """纯响应断言照常通过（既有口径零回归）."""
        a = AssertElement(contains="OK")
        assert a.contains == "OK"
        assert a.var is None


class TestAssertEmptyString:
    """L5 对称性补齐（批 5 T6-1）：contains 空串恒真——解析期拒绝.

    ``contains: ""`` 时 ``'' in anything`` 恒 True，断言静默通过且无意义；
    not_contains/matches 已拦（既有口径），此处补齐 contains，错误带字段定位。
    显式空串才拦：None（未设置该字段）是合法缺省。
    """

    @pytest.mark.parametrize(
        "field",
        [
            pytest.param({"contains": ""}, id="contains"),
            pytest.param({"not_contains": ""}, id="not_contains"),
            pytest.param({"matches": ""}, id="matches"),
        ],
    )
    def test_empty_string_rejected(self, field: dict[str, str]) -> None:
        name = next(iter(field))
        with pytest.raises(ValueError, match=f"{name} 不可为空字符串"):
            AssertElement(**field)

    def test_equals_empty_string_still_legal(self) -> None:
        """equals='' 是合法语义（断言响应为空），不受影响."""
        a = AssertElement(equals="")
        assert a.equals == ""

    def test_unset_fields_not_blocked(self) -> None:
        """None（未设置）不拦——只拦显式空串."""
        a = AssertElement(contains="OK")
        assert a.not_contains is None and a.matches is None


class TestExtractReservedWords:
    """extract 变量名不可与内置保留字冲突（timestamp/port 每步注入，会被覆盖）."""

    @pytest.mark.parametrize("name", ["timestamp", "port"])
    def test_reserved_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match="保留字"):
            Step(command="AT", extract={name: r"\d+"})

    def test_near_name_ok(self) -> None:
        """近似名（ported/timestamps）不冲突，正常通过."""
        s = Step(command="AT", extract={"ported": r"\d+", "timestamps": r"\d+"})
        assert set(s.extract) == {"ported", "timestamps"}


class TestCaseParametersReservedWords:
    """批 3 终审⑧ / 批 5 T6-5：case 级 parameters 键名保留字拒绝.

    timestamp/port 由 step_runner 每步注入，parameters 同名参数会被覆盖、
    静默失效——与 extract 保留字同款错误风格（解析期拒绝，带键定位）。
    """

    @pytest.mark.parametrize("key", ["timestamp", "port"])
    def test_reserved_key_rejected(self, key: str) -> None:
        with pytest.raises(ValueError, match=f"parameters 键名 {key!r}"):
            Case(name="p", parameters=({key: "x"},), steps=(Step(command="AT"),))

    def test_mixed_row_reports_the_reserved_one(self) -> None:
        """多键参数行：只报保留字键（错误信息带定位）."""
        with pytest.raises(ValueError, match="parameters 键名 'port'"):
            Case(
                name="p",
                parameters=({"apn": "cmnet", "port": "COM5"},),
                steps=(Step(command="AT"),),
            )

    def test_normal_keys_ok(self) -> None:
        """常规键名不受影响（含近似名 ported/timestamps）."""
        c = Case(
            name="p",
            parameters=({"apn": "cmnet", "ported": "1", "timestamps": "2"},),
            steps=(Step(command="AT"),),
        )
        assert c.parameters[0]["apn"] == "cmnet"


class TestCaseParametersIsolation:
    """批 5 T6-8：parameters 行 dict 不与构造入参共享（跨实例不传染）.

    pydantic v2 校验时会重建内层 dict——本测试钉住该不变量：外部改动传入
    dict（或改 model.parameters[0]）不得影响已构造的 Case 实例。
    """

    def test_external_dict_mutation_isolated(self) -> None:
        row = {"apn": "cmnet"}
        c = Case(name="p", parameters=(row,), steps=(Step(command="AT"),))
        row["apn"] = "changed"
        assert c.parameters[0]["apn"] == "cmnet", "构造后外部改动不得传染进模型"

    def test_list_input_mutation_isolated(self) -> None:
        row = {"k": "v"}
        c = Case(name="p", parameters=[row], steps=(Step(command="AT"),))
        row["k"] = "zzz"
        assert c.parameters[0]["k"] == "v"

    def test_two_cases_do_not_share_row(self) -> None:
        row = {"k": "v"}
        a = Case(name="a", parameters=(row,), steps=(Step(command="AT"),))
        b = Case(name="b", parameters=(row,), steps=(Step(command="AT"),))
        a.parameters[0]["k"] = "mutated-via-a"
        assert b.parameters[0]["k"] == "v", "两个 Case 实例不得共享同一 row dict"


class TestLoopWarmupLessThanCount:
    """F-12：warmup>=count 时统计轮数为 0，全 warmup 压测必判 FAIL——解析期拒绝."""

    @pytest.mark.parametrize(
        ("count", "warmup"),
        [(3, 3), (2, 5)],
        ids=["equal", "greater"],
    )
    def test_warmup_ge_count_rejected(self, count: int, warmup: int) -> None:
        with pytest.raises(ValueError, match="warmup"):
            Case(name="p", steps=(Step(command="AT"),), loop=LoopConfig(count=count, warmup=warmup))

    def test_warmup_lt_count_ok(self) -> None:
        c = Case(name="p", steps=(Step(command="AT"),), loop=LoopConfig(count=3, warmup=2))
        assert c.loop is not None and c.loop.warmup == 2

    def test_no_loop_not_affected(self) -> None:
        """非压测用例不触发 warmup 校验."""
        c = Case(name="basic", steps=(Step(command="AT"),))
        assert c.loop is None


class TestCaseLoopDataWarning:
    """2b 终审⑨：data 步骤×压测组合的 Case 级解析期 warning（不硬拒）.

    与 Step 级 data×retry/poll 警告同族（数据流不可重入），但按用例粒度
    提示压测每轮重发的字节会被设备当 AT 命令解析。
    """

    def test_loop_with_data_step_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """loop+data 步骤 → Case 级 warning 含「不可重入」."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Case(
                name="p",
                steps=(Step(data=DataInput(inline="payload")),),
                loop=LoopConfig(count=3, warmup=1),
            )
        pw = _pressure_warnings(caplog)
        assert any("不可重入" in w.getMessage() for w in pw), (
            f"应发出 Case 级 data×压测 warning，实际：{[w.getMessage() for w in _case_warnings(caplog)]}"
        )

    def test_loop_without_data_step_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """loop 无 data 步骤：无 Case 级压测 warning."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Case(name="p", steps=(Step(command="AT"),), loop=LoopConfig(count=3, warmup=1))
        assert _pressure_warnings(caplog) == []

    def test_data_without_loop_no_case_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """data 无 loop：Step 级 data×retry 警告仍发，但 Case 级压测警告不重复发出."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Case(
                name="d",
                steps=(Step(data=DataInput(inline="payload"), retry=RetryConfig(count=1)),),
            )
        assert _pressure_warnings(caplog) == []
        assert _case_warnings(caplog), "Step 级 data×retry 警告应照常发出"
