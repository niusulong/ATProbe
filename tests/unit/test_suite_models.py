"""套件模型与解析器单测（REQ-M2 §12）."""

from __future__ import annotations

import pytest

from atprobe.domain.suite.models import Suite
from atprobe.domain.suite.parser import SuiteParseError, parse_suite


class TestSuiteModel:
    def test_minimal_suite(self) -> None:
        s = Suite(name="测试套件", cases=("a.yaml", "b.yaml"))
        assert s.name == "测试套件"
        assert s.cases == ("a.yaml", "b.yaml")
        assert s.suite_setup == ()
        assert s.suite_teardown == ()

    def test_suite_with_setup_teardown(self) -> None:
        from atprobe.domain.case.models import Step
        s = Suite(
            name="x",
            suite_setup=(Step(command="AT+CFUN=1"),),
            suite_teardown=(Step(command="AT+CFUN=0"),),
            cases=("a.yaml",),
        )
        assert len(s.suite_setup) == 1
        assert len(s.suite_teardown) == 1


class TestSuiteParser:
    def test_parse_basic(self) -> None:
        s = parse_suite("""
name: 网络测试套件
description: 网络相关
cases:
  - a.yaml
  - b.yaml
""")
        assert s.name == "网络测试套件"
        assert s.description == "网络相关"
        assert s.cases == ("a.yaml", "b.yaml")

    def test_parse_with_setup(self) -> None:
        s = parse_suite("""
name: x
suite_setup:
  - command: AT+CFUN=1
cases:
  - a.yaml
""")
        assert len(s.suite_setup) == 1

    def test_parse_invalid_step_in_setup(self) -> None:
        # setup 步骤既无 command 又无 data → 校验失败
        with pytest.raises(SuiteParseError):
            parse_suite("""
name: x
suite_setup:
  - foo: bar
cases: []
""")

    def test_parse_non_dict_root(self) -> None:
        with pytest.raises(SuiteParseError):
            parse_suite("- not a dict")
