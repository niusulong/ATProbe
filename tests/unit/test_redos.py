"""S-2 用户正则 ReDoS 解析期分级检测测试（设计 §5）.

三层覆盖：
    - 纯检测（check_pattern）：硬拒族（嵌套量词/(a|a)*）、合法零误拒族（存量
      N58/示例模式）、警告族（重叠交替）、空/坏 pattern 容错；
    - 接线：models（Step 四处正则校验点）、appconfig（urc_filter）、
      urcbuffer（subscribe）——硬拒抛各自口径错误、警告走 logger 不硬拒。
"""

from __future__ import annotations

import logging

import pytest

from atprobe.domain.case.models import Step
from atprobe.domain.case.redos import check_pattern
from atprobe.infra.config.appconfig import AppConfigError, load_app_config
from atprobe.mcp.errors import McpError
from atprobe.mcp.urcbuffer import UrcRegistry

# ---------------------------------------------------------------------------
# 纯检测：硬拒族
# ---------------------------------------------------------------------------
HARD_PATTERNS = [
    pytest.param(r"(a+)+$", id="nested-plus-anchored"),
    pytest.param(r"(\w+)+", id="nested-word-class"),
    pytest.param(r"(a|a)*", id="star-over-overlap"),
    pytest.param(r"((a+)*)+", id="triple-nested"),
    pytest.param(r"(?:a+)+", id="noncapture-nested"),
    pytest.param(r"(a{1,2})+", id="nested-variable-bounds"),
    pytest.param(r"(a*)*b", id="star-nested-star"),
]


@pytest.mark.parametrize("pattern", HARD_PATTERNS)
def test_hard_family_rejected(pattern: str) -> None:
    """灾难性回溯典型形态 → 硬拒（非 None 理由）."""
    hard, _warnings = check_pattern(pattern)
    assert hard is not None


# ---------------------------------------------------------------------------
# 纯检测：合法零误拒族（存量 N58 / 示例用例模式全通过）
# ---------------------------------------------------------------------------
SAFE_PATTERNS = [
    pytest.param(r"\+CEREG: \d,(\d)", id="cereg"),
    pytest.param(r"(\r\n>|\+TCPSEND: SOCKET ID OPEN FAILED)", id="alt-diff-first-char"),
    pytest.param(r"\+FSRF: 10,([^\r\n]+)", id="negated-class-plus"),
    pytest.param(r"OK", id="plain-literal"),
    pytest.param(r"^\$MYGPSPOS", id="anchored-literal"),
    pytest.param(r"^\$MYGPSPOS:", id="n58-stock-urc-filter"),
    pytest.param(r"a{2}", id="fixed-repeat"),
    pytest.param(r"(a{2})+", id="fixed-inner-skipped"),
    pytest.param(r"(A|B)+", id="alt-engine-merged"),
]


@pytest.mark.parametrize("pattern", SAFE_PATTERNS)
def test_safe_family_zero_false_positive(pattern: str) -> None:
    """合法模式零误拒、零误警（含 N58 存量 urc_filter 与示例 expect/extract）."""
    assert check_pattern(pattern) == (None, [])


def test_overlap_alternation_warns_not_hard() -> None:
    """(a|a)+ 重叠交替 → 警告不硬拒（静态误报率高，仅告警）."""
    hard, warnings = check_pattern(r"(a|a)+")
    assert hard is None
    assert len(warnings) == 1
    assert "交替" in warnings[0]


def test_empty_and_invalid_pattern_tolerated() -> None:
    """空 pattern / 解析失败容错返回空结果（语法错误由调用方 re.compile 口径报）."""
    assert check_pattern("") == (None, [])
    assert check_pattern("[unclosed") == (None, [])


# ---------------------------------------------------------------------------
# 接线：models.Step 四处正则校验点
# ---------------------------------------------------------------------------
class TestStepWiring:
    def test_wait_urc_hard_rejected(self) -> None:
        with pytest.raises(ValueError, match="wait_urc 正则存在灾难性回溯风险"):
            Step(command="AT+X", wait_urc=r"(a+)+$")

    def test_expect_hard_rejected(self) -> None:
        with pytest.raises(ValueError, match="expect 正则存在灾难性回溯风险"):
            Step(command="AT+X", expect=r"(\w+)+")

    def test_extract_hard_rejected(self) -> None:
        with pytest.raises(ValueError, match="回溯"):
            Step(command="AT+X", extract={"csq": r"(?:a+)+"})

    def test_assert_matches_hard_rejected(self) -> None:
        with pytest.raises(ValueError, match="回溯"):
            Step(command="AT+X", assert_={"matches": r"(a{1,2})+"})

    def test_valid_regex_still_accepted(self) -> None:
        """合法正则照常构造（接线未破坏既有口径）."""
        s = Step(command="AT+X", expect=r"\r\n>", wait_urc=None)
        assert s.expect == r"\r\n>"

    def test_overlap_alternation_warns_via_logger(self, caplog: pytest.LogCaptureFixture) -> None:
        """重叠交替类不硬拒，经 atprobe.case logger 告警."""
        with caplog.at_level(logging.WARNING, logger="atprobe.case"):
            Step(command="AT+X", expect=r"(a|a)+")
        assert any(
            r.name == "atprobe.case" and "回溯风险" in r.getMessage() for r in caplog.records
        )


# ---------------------------------------------------------------------------
# 接线：appconfig urc_filter
# ---------------------------------------------------------------------------
class TestAppconfigWiring:
    def test_urc_filter_hard_rejected(self) -> None:
        yaml_text = "urc_filter:\n  - '(a+)+'\n"
        with pytest.raises(AppConfigError, match="灾难性回溯风险"):
            load_app_config(yaml_text, source="test.yaml")

    def test_urc_filter_stock_patterns_pass(self) -> None:
        """存量 N58 模式（examples/atprobe-com5.yaml 实配）零误拒."""
        yaml_text = "urc_filter:\n  - '^\\$MYGPSPOS:'\n"
        cfg = load_app_config(yaml_text, source="test.yaml")
        assert cfg.urc_filter == (r"^\$MYGPSPOS:",)

    def test_urc_filter_invalid_regex_unchanged(self) -> None:
        """语法错误仍由 SerialConnection 编译期口径处理（appconfig 层不重复报）."""
        cfg = load_app_config("urc_filter:\n  - '[unclosed'\n", source="test.yaml")
        assert cfg.urc_filter == ("[unclosed",)


# ---------------------------------------------------------------------------
# 接线：urcbuffer subscribe
# ---------------------------------------------------------------------------
class TestUrcbufferWiring:
    def test_subscribe_hard_rejected_invalid_input(self) -> None:
        reg = UrcRegistry()
        with pytest.raises(McpError) as ei:
            reg.subscribe("COM5", pattern=r"(a+)+$")
        assert ei.value.kind == "INVALID_INPUT"
        assert "灾难性回溯风险" in str(ei.value)

    def test_subscribe_overlap_warns_not_rejected(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = UrcRegistry()
        with caplog.at_level(logging.WARNING, logger="atprobe.mcp"):
            sub_id = reg.subscribe("COM5", pattern=r"(a|a)+")
        assert sub_id in reg._subs  # 未被硬拒
        assert any(r.name == "atprobe.mcp" and "回溯风险" in r.getMessage() for r in caplog.records)

    def test_subscribe_valid_pattern_unchanged(self) -> None:
        reg = UrcRegistry()
        sub_id = reg.subscribe("COM5", pattern=r"^\$MYGPSPOS")
        assert sub_id in reg._subs
