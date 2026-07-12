"""用例模型与解析器单测（M2 §2/§3/§4）."""

from __future__ import annotations

import pytest

from atprobe.domain.case.models import (
    AssertionOp,
    DataInput,
    FailureStrategy,
    LoopConfig,
    PollConfig,
    RetryConfig,
    Step,
)
from atprobe.domain.case.parser import CaseParseError, parse_case


class TestStepValidation:
    def test_command_required_or_data(self) -> None:
        with pytest.raises(Exception):
            Step()  # 既无 command 也无 data

    def test_command_and_data_mutually_exclusive(self) -> None:
        with pytest.raises(Exception):
            Step(command="AT", data=DataInput(inline="x"))

    def test_retry_poll_mutually_exclusive(self) -> None:
        with pytest.raises(Exception):
            Step(
                command="AT",
                retry=RetryConfig(count=1),
                poll=PollConfig(until='x == "y"', timeout=5),
            )

    def test_wait_urc_defaults_none(self) -> None:
        """wait_urc 缺省 None（向后兼容，OK 即终结）."""
        s = Step(command="AT")
        assert s.wait_urc is None

    def test_wait_urc_parsed(self) -> None:
        """wait_urc 正则字符串正常解析."""
        s = Step(command="AT+CTM2MDEREG", wait_urc=r"\+CTM2M:dereg,0,\d+")
        assert s.wait_urc == r"\+CTM2M:dereg,0,\d+"

    def test_wait_urc_with_retry_allowed(self) -> None:
        """wait_urc 与 retry 可共存（retry 包裹「发→等URC→断言」单次尝试）."""
        s = Step(
            command="AT+X",
            wait_urc=r"\+X:ok",
            retry=RetryConfig(count=2, interval=500),
        )
        assert s.wait_urc is not None
        assert s.retry is not None

    def test_wait_urc_and_poll_mutually_exclusive(self) -> None:
        """wait_urc 与 poll 互斥（语义重叠）."""
        with pytest.raises(Exception):
            Step(
                command="AT+X",
                wait_urc=r"\+X:ok",
                poll=PollConfig(until='x == "y"', timeout=5),
            )

    def test_wait_urc_invalid_regex_rejected(self) -> None:
        """wait_urc 无效正则在模型校验期拦截（而非运行期）."""
        with pytest.raises(Exception):
            Step(command="AT+X", wait_urc="[")

    def test_data_file_or_inline_exclusive(self) -> None:
        with pytest.raises(Exception):
            DataInput(file="a.bin", inline="b")
        with pytest.raises(Exception):
            DataInput()  # 都没有


class TestAssertValidation:
    def test_response_assert_one_of(self) -> None:
        with pytest.raises(Exception):
            # 同时 contains 和 equals
            parse_case("""
name: x
steps:
  - command: AT
    assert: { contains: "OK", equals: "OK" }
""")

    def test_var_assert_needs_var_and_op(self) -> None:
        with pytest.raises(Exception):
            parse_case("""
name: x
steps:
  - command: AT
    assert: [{ var: rssi }]
""")

    def test_between_needs_min_max(self) -> None:
        with pytest.raises(Exception):
            parse_case("""
name: x
steps:
  - command: AT
    assert: [{ var: rssi, op: between, min: 1 }]
""")


class TestCaseParsing:
    def test_minimal_case(self) -> None:
        c = parse_case("""
name: 最小用例
steps:
  - command: AT
""")
        assert c.name == "最小用例"
        assert len(c.steps) == 1
        assert c.is_pressure is False
        assert c.tags == ()

    def test_full_case(self) -> None:
        c = parse_case("""
name: 完整用例
tags: [network, p0]
port: COM3
on_failure: continue
interval: 100
setup:
  - command: AT
    assert: { contains: "OK" }
steps:
  - command: AT+CSQ
    extract:
      rssi: 'rssi:(\\d+)'
    when: 'rssi > 5'
    retry: { count: 3, interval: 2000 }
    assert:
      - { contains: "+CSQ:" }
teardown:
  - command: AT+CGACT=0,1
loop:
  count: 100
  interval: 100
  warmup: 5
""")
        assert c.tags == ("network", "p0")
        assert c.port == "COM3"
        assert c.on_failure is FailureStrategy.CONTINUE
        assert c.interval == 100
        assert len(c.setup) == 1
        assert c.steps[0].retry == RetryConfig(count=3, interval=2000)
        assert c.steps[0].when == "rssi > 5"
        assert c.loop == LoopConfig(count=100, interval=100, warmup=5)
        assert c.is_pressure is True

    def test_assert_single_key_normalized_to_list(self) -> None:
        c = parse_case("""
name: x
steps:
  - command: AT
    assert: { contains: "OK" }
""")
        # 单键式归一化为单元素列表
        assert len(c.steps[0].assertions) == 1

    def test_assert_list_multiple(self) -> None:
        c = parse_case("""
name: x
steps:
  - command: AT
    assert:
      - { contains: "OK" }
      - { not_contains: "ERROR" }
""")
        assert len(c.steps[0].assertions) == 2

    def test_var_assert_ops(self) -> None:
        c = parse_case("""
name: x
steps:
  - command: AT
    assert: [{ var: rssi, op: ge, value: 15 }]
""")
        assert c.steps[0].assertions[0].op is AssertionOp.GE

    def test_data_input_file(self) -> None:
        c = parse_case("""
name: x
steps:
  - data:
      file: firmware.bin
      chunk_size: 2048
      append_terminator: true
""")
        assert c.steps[0].data.file == "firmware.bin"
        assert c.steps[0].data.chunk_size == 2048
        assert c.steps[0].data.append_terminator is True

    def test_data_input_inline(self) -> None:
        c = parse_case("""
name: x
steps:
  - data:
      inline: "hello"
""")
        assert c.steps[0].data.inline == "hello"

    def test_yaml_syntax_error_reports_line(self) -> None:
        with pytest.raises(CaseParseError) as exc_info:
            parse_case("""
name: x
steps:
  - command: AT
   bad: indent
""")
        assert (
            "行" in str(exc_info.value)
            or "syntax" in str(exc_info.value).lower()
            or "用例" in str(exc_info.value)
        )

    def test_steps_required(self) -> None:
        with pytest.raises(CaseParseError):
            parse_case("name: nosteps\n")

    def test_extra_field_rejected(self) -> None:
        # extra=forbid
        with pytest.raises(CaseParseError):
            parse_case("""
name: x
unknown_field: bad
steps:
  - command: AT
""")

    def test_source_file_recorded(self) -> None:
        c = parse_case("name: x\nsteps:\n  - command: AT\n", source="foo.yaml")
        assert c.source_file == "foo.yaml"


class TestCaseParamIndex:
    def test_default_param_index_none(self) -> None:
        from atprobe.domain.case.models import Case

        c = Case(name="x", steps=[Step(command="AT")])
        assert c.param_index is None

    def test_param_index_settable(self) -> None:
        from atprobe.domain.case.models import Case

        c = Case(name="x", steps=[Step(command="AT")], param_index=2)
        assert c.param_index == 2
