"""条件表达式求值器单测（M2 §6）."""

from __future__ import annotations

import pytest

from atprobe.domain.case.evaluator import ExpressionError, evaluate


class TestComparisons:
    @pytest.mark.parametrize(
        "expr,scope,expected",
        [
            ('stat == "1"', {"stat": "1"}, True),
            ('stat == "1"', {"stat": "5"}, False),
            ('stat != "1"', {"stat": "5"}, True),
            ("rssi > 15", {"rssi": 20}, True),
            ("rssi > 15", {"rssi": 10}, False),
            ("rssi >= 15", {"rssi": 15}, True),
            ("rssi < 15", {"rssi": 14}, True),
            ("rssi <= 15", {"rssi": 15}, True),
        ],
    )
    def test_basic(self, expr, scope, expected) -> None:  # type: ignore[no-untyped-def]
        assert evaluate(expr, scope) is expected

    def test_string_eq_strict(self) -> None:
        # == 按字符串比较
        assert evaluate('x == "10"', {"x": 10}) is True
        assert evaluate('x == "10"', {"x": "10"}) is True

    def test_numeric_comparison_string_fails(self) -> None:
        # > < 对非数值字符串比较 → false（§6.3 规则 3）
        assert evaluate('x > 5', {"x": "abc"}) is False

    def test_float_comparison(self) -> None:
        assert evaluate("v > 1.5", {"v": 2.0}) is True
        assert evaluate("v <= 1.5", {"v": 1.0}) is True


class TestLogicalOps:
    def test_and(self) -> None:
        assert evaluate('a == "1" and b == "2"', {"a": "1", "b": "2"}) is True
        assert evaluate('a == "1" and b == "2"', {"a": "1", "b": "3"}) is False

    def test_or(self) -> None:
        assert evaluate('a == "1" or b == "2"', {"a": "9", "b": "2"}) is True
        assert evaluate('a == "1" or b == "2"', {"a": "9", "b": "9"}) is False

    def test_mixed(self) -> None:
        assert evaluate('a == "1" and b == "2" or c == "3"',
                        {"a": "1", "b": "9", "c": "3"}) is True


class TestNullHandling:
    def test_undefined_var_is_null(self) -> None:
        assert evaluate("missing is null", {}) is True
        assert evaluate("missing is not null", {}) is False

    def test_defined_var_not_null(self) -> None:
        assert evaluate("x is not null", {"x": "v"}) is True
        assert evaluate("x is null", {"x": "v"}) is False

    def test_null_in_comparison_is_false(self) -> None:
        # null 与任意比较（非 is null）→ false（§6.3 规则 2）
        assert evaluate("missing == \"1\"", {}) is False
        assert evaluate("missing > 5", {}) is False

    def test_empty_string_not_null(self) -> None:
        # 提取失败（空值）按空字符串处理，非 null
        assert evaluate('x == ""', {"x": ""}) is True
        assert evaluate("x is null", {"x": ""}) is False


class TestLegacySyntax:
    def test_mustache_compat_numeric(self) -> None:
        # 旧写法 {{var}} op literal 先文本替换再求值（§6.5，兼容期）。
        # 注意：裸文本替换有歧义（替换后的字符串若不加引号会被当变量名），
        # 数值比较场景可用：{{rssi}} > 15 → "23 > 15"。
        assert evaluate("{{rssi}} > 15", {"rssi": "23"}) is True

    def test_mustache_compat_string_quoted(self) -> None:
        # 字符串比较：旧写法把变量值嵌入引号内 → '"OK" == "OK"'
        # 注意右侧是 {{val}} 而非裸名，避免裸名被当变量解析为 null
        assert evaluate('"{{val}}" == "OK"', {"val": "OK"}) is True


class TestErrors:
    def test_empty_expr(self) -> None:
        with pytest.raises(ExpressionError):
            evaluate("", {})

    def test_missing_operator(self) -> None:
        with pytest.raises(ExpressionError):
            evaluate("x", {"x": "1"})

    def test_unexpected_token(self) -> None:
        with pytest.raises(ExpressionError):
            evaluate("x @ 1", {"x": 1})
