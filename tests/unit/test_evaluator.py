"""条件表达式求值器单测（M2 §6）."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

import atprobe.domain.case.evaluator as evaluator
from atprobe.domain.case.errors import UndefinedReferenceError
from atprobe.domain.case.evaluator import ExpressionError, evaluate
from atprobe.infra.config.envconfig import EnvConfig


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
        assert evaluate("x > 5", {"x": "abc"}) is False

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
        assert evaluate('a == "1" and b == "2" or c == "3"', {"a": "1", "b": "9", "c": "3"}) is True


class TestParentheses:
    """括号分组（与 and/or 优先级配合，用于复杂条件如注册状态多分支判断）."""

    def test_simple_paren(self) -> None:
        assert evaluate('(a == "1")', {"a": "1"}) is True
        assert evaluate('(a == "1")', {"a": "2"}) is False

    def test_paren_overrides_precedence(self) -> None:
        # 无括号：and 优先于 or → (a==1 and b==2) or c==3
        # 有括号：a==1 and (b==2 or c==3) —— 语义不同
        scope = {"a": "1", "b": "9", "c": "3"}
        assert evaluate('a == "1" and (b == "2" or c == "3")', scope) is True
        assert evaluate('a == "1" and b == "2" or c == "3"', scope) is True  # 同结果但不同路径
        # 关键区分用例：a!=1 时，括号版应 false（因 and 左假），无括号版看 c==3
        scope2 = {"a": "9", "b": "9", "c": "3"}
        assert evaluate('a == "1" and (b == "2" or c == "3")', scope2) is False
        assert evaluate('a == "1" and b == "2" or c == "3"', scope2) is True

    def test_nested_paren(self) -> None:
        assert evaluate('((a == "1"))', {"a": "1"}) is True
        assert (
            evaluate('(a == "1" or (b == "2" and c == "3"))', {"a": "9", "b": "2", "c": "3"})
            is True
        )

    def test_paren_with_null_check(self) -> None:
        assert (
            evaluate('(a == "1" or b == "5") and c is not null', {"a": "1", "b": "5", "c": "x"})
            is True
        )
        assert (
            evaluate('(a == "1" or b == "5") and c is not null', {"a": "1", "b": "5"}) is False
        )  # c 未定义 → null

    def test_unbalanced_paren_error(self) -> None:
        with pytest.raises(ExpressionError):
            evaluate('(a == "1"', {"a": "1"})
        with pytest.raises(ExpressionError):
            evaluate('a == "1")', {"a": "1"})


class TestNullHandling:
    def test_undefined_var_is_null(self) -> None:
        assert evaluate("missing is null", {}) is True
        assert evaluate("missing is not null", {}) is False

    def test_defined_var_not_null(self) -> None:
        assert evaluate("x is not null", {"x": "v"}) is True
        assert evaluate("x is null", {"x": "v"}) is False

    def test_null_in_comparison_is_false(self) -> None:
        # null 与任意比较（非 is null）→ false（§6.3 规则 2）
        assert evaluate('missing == "1"', {}) is False
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

    def test_mustache_compat_string_bare_placeholder(self) -> None:
        # 裸占位符（不在引号内）替换后以带引号字面量嵌入，裸值不再被误当
        # 变量名解析为 null——模块 docstring 宣告的旧写法 {{var}} == "OK"（P1-4）
        assert evaluate('{{val}} == "OK"', {"val": "OK"}) is True
        assert evaluate('{{val}} == "NO"', {"val": "OK"}) is False


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


class TestEvaluateWithEnv:
    """P1-4：条件表达式可引用环境配置变量（与命令模板口径一致）."""

    @staticmethod
    def _env() -> EnvConfig:
        return EnvConfig(_groups={"apn": {"name": "cmnet"}})

    def test_dotted_ref_with_env(self) -> None:
        assert evaluate('{{apn.name}} == "cmnet"', {}, env=self._env()) is True

    def test_dotted_ref_mismatch(self) -> None:
        assert evaluate('{{apn.name}} == "ctnet"', {}, env=self._env()) is False

    def test_dotted_ref_without_env_still_raises(self) -> None:
        with pytest.raises(UndefinedReferenceError):
            evaluate('{{apn.name}} == "cmnet"', {})

    def test_dotted_ref_quoted_form_still_works(self) -> None:
        # 字符串字面量内的占位符嵌入原始值（替换规则对两种写法都成立）
        assert evaluate('"{{apn.name}}" == "cmnet"', {}, env=self._env()) is True


class TestAdversarialValues:
    """P1-4 复核：替换值含特殊字符时的嵌入安全性（in-string 同样转义）."""

    def test_out_of_string_value_with_quotes(self) -> None:
        # 值内含引号：out-of-string 嵌入经转义仍是完整字面量，不会逃逸注入语法
        v = 'A" is not null or "B'
        assert evaluate('{{v}} == "OK"', {"v": v}) is False
        assert evaluate('{{v}} == "A\\" is not null or \\"B"', {"v": v}) is True

    def test_in_string_value_with_quotes_no_injection(self) -> None:
        # 修复前红：裸嵌值逃逸字面量 → "A" is not null or "B" == "OK" → True（注入）
        v = 'A" is not null or "B'
        assert evaluate('"{{v}}" == "OK"', {"v": v}) is False
        assert evaluate('"{{v}}" == "A\\" is not null or \\"B"', {"v": v}) is True

    def test_value_with_backslash_not_mangled(self) -> None:
        # 修复前红（in-string 形态）：\U、\a 被 _unquote_str 当转义吃掉 → 判错
        v = "C:\\Users\\at"  # 值为 C:\Users\at
        assert evaluate('{{v}} == "C:\\\\Users\\\\at"', {"v": v}) is True
        assert evaluate('"{{v}}" == "C:\\\\Users\\\\at"', {"v": v}) is True
        assert evaluate('{{v}} != "C:Usersat"', {"v": v}) is True

    def test_value_with_newline_and_escape_sequence(self) -> None:
        # 真实换行：STR 字面量可跨行（[^"\] 含 \n），两种形态都等值
        v = "line1\nline2"
        assert evaluate('{{v}} == "line1\nline2"', {"v": v}) is True
        assert evaluate('"{{v}}" == "line1\nline2"', {"v": v}) is True
        # 修复前红（in-string 形态）：值含两字符 \n 序列，裸嵌后被转义成真实换行 → 判错
        v2 = "a\\nb"  # 值为 a\nb（反斜杠 + 字母 n 两个字符）
        assert evaluate('"{{v}}" == "a\\\\nb"', {"v": v2}) is True
        assert evaluate('{{v}} == "a\\\\nb"', {"v": v2}) is True

    def test_numeric_coercion_unaffected(self) -> None:
        # 数值强转：{{v}} > 4（v="23"）→ "23" > 4 → True；非数值 → False
        assert evaluate("{{v}} > 4", {"v": "23"}) is True
        assert evaluate("{{v}} > 4", {"v": "3"}) is False
        assert evaluate("{{v}} > 4", {"v": "abc"}) is False

    def test_adjacent_placeholders(self) -> None:
        # 相邻占位符：in-string 内拼接为一个值；out-of-string 相邻产生两个相邻
        # 字面量 → 语法错误（响亮报错，不静默当变量名 → null）
        assert evaluate('"{{a}}{{b}}" == "XY"', {"a": "X", "b": "Y"}) is True
        with pytest.raises(ExpressionError):
            evaluate('{{a}}{{b}} == "XY"', {"a": "X", "b": "Y"})


class TestParseCache:
    """Pf-5（设计 §4.3）：AST 缓存——poll/压测高频路径免重复 tokenize+parse."""

    @pytest.fixture(autouse=True)
    def _clear_parse_cache(self) -> Iterator[None]:
        # 冷缓存起点：防止先前测试（本文件或引擎/step_runner 测试）已缓存同名
        # 表达式导致计数断言失真；结束后清理，避免污染后续测试
        evaluator._parse_cached.cache_clear()
        yield
        evaluator._parse_cached.cache_clear()

    @staticmethod
    def _counting_tokenize(monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """包装 evaluator._tokenize，记录每次调用的输入串（lru_cache 未命中才到达）."""
        calls: list[str] = []
        original = evaluator._tokenize

        def wrapper(expr: str) -> object:
            calls.append(expr)
            return original(expr)

        monkeypatch.setattr(evaluator, "_tokenize", wrapper)
        return calls

    def test_plain_expr_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 无 {{}}：processed == 原表达式（scope 无关），第二次求值全命中
        calls = self._counting_tokenize(monkeypatch)
        expr = 'cache_a == "1" or cache_b > 7'
        assert evaluate(expr, {"cache_a": "1", "cache_b": "9"}) is True
        assert evaluate(expr, {"cache_a": "2", "cache_b": "1"}) is False  # 同 AST 不同 scope
        assert calls == [expr]  # 只 tokenize 一次

    def test_mustache_same_value_hits_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # {{}}：同 scope 同值 → 处理串相同 → 第二次命中
        calls = self._counting_tokenize(monkeypatch)
        expr = '{{cache_v}} == "OK"'
        assert evaluate(expr, {"cache_v": "OK"}) is True
        assert evaluate(expr, {"cache_v": "OK"}) is True
        assert calls == ['"OK" == "OK"']  # 只 tokenize 一次

    def test_mustache_different_values_no_cross_talk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # scope 值不同 → 处理串不同 → 各自解析求值，不串台；值复现的轮次命中
        calls = self._counting_tokenize(monkeypatch)
        expr = "{{cache_w}} > 3"
        assert evaluate(expr, {"cache_w": "23"}) is True
        assert evaluate(expr, {"cache_w": "2"}) is False
        assert evaluate(expr, {"cache_w": "23"}) is True  # 处理串复现 → 命中
        assert calls == ['"23" > 3', '"2" > 3']

    def test_empty_expression_raises_every_time(self) -> None:
        # lru_cache 不缓存异常调用：空表达式每次都重抛（语义与无缓存一致）
        for _ in range(2):
            with pytest.raises(ExpressionError):
                evaluate("", {})

    def test_concurrent_evaluate_smoke(self) -> None:
        # 冒烟：多线程共享缓存节点（eval 纯函数）求值无异常、无串台
        expr = 'cc_a == "1" and cc_b is not null'
        scopes = [{"cc_a": "1", "cc_b": "z"}, {"cc_a": "2", "cc_b": "z"}] * 40
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda s: evaluate(expr, s), scopes))
        assert results == [s["cc_a"] == "1" for s in scopes]
