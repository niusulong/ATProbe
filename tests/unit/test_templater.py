"""模板替换器单测（M2 §5.2 / M7 §4）."""

from __future__ import annotations

import pytest

from atprobe.domain.case.templater import (
    UndefinedReferenceError,
    find_references,
    render,
)


class TestRender:
    def test_simple_var(self) -> None:
        assert render("AT+CSQ={{x}}", {"x": 23}) == "AT+CSQ=23"

    def test_multiple_vars(self) -> None:
        assert render("{{a}}{{b}}", {"a": 1, "b": 2}) == "12"

    def test_string_value(self) -> None:
        assert render("ATD{{num}};", {"num": "13800138000"}) == "ATD13800138000;"

    def test_bool_value(self) -> None:
        assert render("{{flag}}", {"flag": True}) == "true"
        assert render("{{flag}}", {"flag": False}) == "false"

    def test_float_value(self) -> None:
        assert render("{{v}}", {"v": 1.5}) == "1.5"
        assert render("{{v}}", {"v": 2.0}) == "2"  # 整数值 float 用整数形式

    def test_no_placeholders(self) -> None:
        assert render("plain text", {}) == "plain text"

    def test_whitespace_around_name(self) -> None:
        assert render("{{  x  }}", {"x": 1}) == "1"

    def test_undefined_raises(self) -> None:
        with pytest.raises(UndefinedReferenceError):
            render("{{missing}}", {})

    def test_allow_partial_keeps_undefined(self) -> None:
        out = render("{{defined}}-{{missing}}", {"defined": "ok"}, allow_partial=True)
        assert out == "ok-{{missing}}"


class TestEnvResolution:
    def test_dot_ref_resolves_env(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{ftp.host}}", {}, env=env) == "192.168.1.100"
        assert render("{{ftp.port}}", {}, env=env) == "21"

    def test_dot_ref_cross_group(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{fota.version_a}}", {}, env=env) == "V1.0.0"

    def test_dot_ref_not_overridable_by_case_var(self, env) -> None:  # type: ignore[no-untyped-def]
        # 点号名边界（M7 §4.4）：点号名只查环境配置，不被用例级变量覆盖
        out = render("{{ftp.host}}", {"ftp.host": "fake"}, env=env)
        assert out == "192.168.1.100"

    def test_simple_name_fallback_to_env_default_group(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{apn}}", {}, env=env) == "cmnet"

    def test_simple_name_case_var_overrides_env(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{apn}}", {"apn": "custom"}, env=env) == "custom"

    def test_dot_ref_undefined_raises(self, env) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(UndefinedReferenceError):
            render("{{fota.missing}}", {}, env=env)

    def test_no_env_dot_ref_raises(self) -> None:
        with pytest.raises(UndefinedReferenceError):
            render("{{ftp.host}}", {}, env=None)

    def test_three_level_ref_rejected(self, env) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(UndefinedReferenceError):
            render("{{a.b.c}}", {}, env=env)


class TestFindReferences:
    def test_finds_all(self) -> None:
        refs = find_references("{{a}} {{b}} {{a}} {{c.d}}")
        assert refs == ["a", "b", "c.d"]

    def test_no_refs(self) -> None:
        assert find_references("plain") == []

    def test_distinguishes_dot_and_simple(self) -> None:
        refs = find_references("{{x}} {{group.param}}")
        assert refs == ["x", "group.param"]
