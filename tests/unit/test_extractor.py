"""extract 与 assert 求值单测（M2 §4/§5.1）."""

from __future__ import annotations

from atprobe.domain.case.assessor import assess, assess_all
from atprobe.domain.case.extractor import extract_all, extract_one
from atprobe.domain.case.models import AssertElement, AssertionOp


class TestExtractor:
    def test_basic_capture_group(self) -> None:
        r = extract_one(r"CEREG:\s*\d,(\d)", "+CEREG: 0,1")
        assert r.matched is True
        assert r.value == "1"

    def test_no_match_empty(self) -> None:
        r = extract_one(r"X(\d+)", "no match")
        assert r.matched is False
        assert r.value == ""

    def test_multiple_extracts(self) -> None:
        values, matched = extract_all(
            {"stat": r"CEREG:\s*\d,(\d)", "rssi": r"CSQ:\s*(\d+)"},
            "+CEREG: 0,5\n+CSQ: 23,0",
        )
        assert values == {"stat": "5", "rssi": "23"}
        assert matched == {"stat": True, "rssi": True}

    def test_partial_match(self) -> None:
        values, matched = extract_all(
            {"a": r"A(\d)", "b": r"B(\d)"}, "A1 only"
        )
        assert values == {"a": "1", "b": ""}
        assert matched == {"a": True, "b": False}

    def test_no_group_uses_full_match(self) -> None:
        r = extract_one(r"OK", "OK\r\n")
        assert r.matched is True
        assert r.value == "OK"


class TestResponseAssertions:
    def test_contains_pass(self) -> None:
        el = AssertElement(contains="OK")
        out = assess(el, "AT\r\nOK\r\n", {})
        assert out.passed is True

    def test_contains_fail(self) -> None:
        el = AssertElement(contains="OK")
        out = assess(el, "ERROR\r\n", {})
        assert out.passed is False

    def test_not_contains(self) -> None:
        el = AssertElement(not_contains="ERROR")
        assert assess(el, "OK\r\n", {}).passed is True
        assert assess(el, "ERROR\r\n", {}).passed is False

    def test_matches(self) -> None:
        el = AssertElement(matches=r"\+CEREG:.*1")
        assert assess(el, "+CEREG: 0,1\r\n", {}).passed is True
        assert assess(el, "+CEREG: 0,2\r\n", {}).passed is False

    def test_equals(self) -> None:
        el = AssertElement(equals="OK\r\n")
        assert assess(el, "OK\r\n", {}).passed is True
        assert assess(el, "OK", {}).passed is False


class TestVariableAssertions:
    def test_eq(self) -> None:
        el = AssertElement(var="stat", op=AssertionOp.EQ, value="1")
        assert assess(el, "", {"stat": "1"}).passed is True
        assert assess(el, "", {"stat": "2"}).passed is False

    def test_ne(self) -> None:
        el = AssertElement(var="stat", op=AssertionOp.NE, value="1")
        assert assess(el, "", {"stat": "2"}).passed is True

    def test_gt_numeric(self) -> None:
        el = AssertElement(var="rssi", op=AssertionOp.GT, value=15)
        assert assess(el, "", {"rssi": 20}).passed is True
        assert assess(el, "", {"rssi": 10}).passed is False

    def test_ge_with_string_value(self) -> None:
        # 字面量是数值则尝试转数值（§4.5）
        el = AssertElement(var="rssi", op=AssertionOp.GE, value="15")
        assert assess(el, "", {"rssi": "15"}).passed is True

    def test_between(self) -> None:
        el = AssertElement(var="rssi", op=AssertionOp.BETWEEN, min=15, max=31)
        assert assess(el, "", {"rssi": 20}).passed is True
        assert assess(el, "", {"rssi": 10}).passed is False
        assert assess(el, "", {"rssi": 31}).passed is True

    def test_in(self) -> None:
        el = AssertElement(var="stat", op=AssertionOp.IN, values=["1", "5"])
        assert assess(el, "", {"stat": "1"}).passed is True
        assert assess(el, "", {"stat": "9"}).passed is False

    def test_contains_str(self) -> None:
        el = AssertElement(var="url", op=AssertionOp.CONTAINS, value="cmnet")
        assert assess(el, "", {"url": "internet.cmnet"}).passed is True

    def test_matches_var(self) -> None:
        el = AssertElement(var="imei", op=AssertionOp.MATCHES, value=r"^\d{4}$")
        assert assess(el, "", {"imei": "1234"}).passed is True
        assert assess(el, "", {"imei": "12"}).passed is False

    def test_undefined_var_fails_gracefully(self) -> None:
        el = AssertElement(var="missing", op=AssertionOp.EQ, value="x")
        out = assess(el, "", {})
        assert out.passed is False
        assert "未定义" in out.reason

    def test_non_numeric_var_fails_gracefully(self) -> None:
        el = AssertElement(var="x", op=AssertionOp.GT, value=5)
        out = assess(el, "", {"x": "abc"})
        assert out.passed is False
        assert "非数值" in out.reason


class TestAssessAll:
    def test_and_semantics(self) -> None:
        els = [
            AssertElement(contains="OK"),
            AssertElement(not_contains="ERROR"),
        ]
        outcomes = assess_all(els, "OK\r\n", {})
        assert all(o.passed for o in outcomes)

    def test_one_fail_fails_all(self) -> None:
        els = [
            AssertElement(contains="OK"),
            AssertElement(contains="MISSING"),
        ]
        outcomes = assess_all(els, "OK\r\n", {})
        assert outcomes[0].passed is True
        assert outcomes[1].passed is False

    def test_name_display(self) -> None:
        el = AssertElement(name="信号合格", contains="+CSQ:")
        out = assess(el, "+CSQ: 23\r\n", {})
        assert out.name == "信号合格"

    def test_auto_name(self) -> None:
        el = AssertElement(contains="OK")
        out = assess(el, "OK", {})
        assert out.name == "contains:OK"
