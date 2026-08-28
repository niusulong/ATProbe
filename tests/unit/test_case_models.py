"""用例模型解析期校验单测（批 2b Task 1）.

覆盖：Step.expect（附加完成条件正则）、DataInput.inline_hex（三选一数据源与
十六进制校验）、data×retry / data×poll 组合的解析期 warning（设计 §2.2，
数据流不可重入——不硬拒，仅告警）。
"""

from __future__ import annotations

import logging

import pytest

from atprobe.domain.case.models import DataInput, PollConfig, RetryConfig, Step


def _case_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """筛出 atprobe.case logger 的 WARNING 级记录."""
    return [r for r in caplog.records if r.name == "atprobe.case" and r.levelno == logging.WARNING]


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
