"""断言求值（REQ-M2 §4）.

纯函数。对完整响应文本与提取出的变量求值断言元素，返回每个元素的通过情况。

两类断言（§4.2）：
    A. 响应原文断言：contains / not_contains / matches / equals（针对完整响应）。
    B. 变量断言：var + op + 参数（针对 extract 出的变量）。

求值异常处理（§4.5）：
    - 变量未定义或类型转换失败 → 该断言元素判为失败（不抛异常），记录原因。
    - 数值类操作对变量值尝试转数值，失败则元素失败。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from atprobe.domain.case.models import AssertElement, AssertionOp


@dataclass(frozen=True)
class AssertionOutcome:
    """单个断言元素的求值结果（对应 M3 §8.5 AssertionResult）."""

    name: str
    op_kind: str  # "response.contains" / "var.eq" 等，便于报告展示
    expected: str
    actual: str
    passed: bool
    reason: str = ""  # 失败原因（通过时为空）


def _display_name(el: AssertElement) -> str:
    if el.name:
        return el.name
    # 自动生成（§4.4）
    if el.var is not None and el.op is not None:
        return f"{el.op.value}:{el.var}"
    if el.contains is not None:
        return f"contains:{el.contains}"
    if el.not_contains is not None:
        return f"not_contains:{el.not_contains}"
    if el.matches is not None:
        return f"matches:{el.matches}"
    if el.equals is not None:
        return f"equals:{el.equals}"
    return "assertion"


def _try_float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def assess(el: AssertElement, response: str, variables: Mapping[str, object]) -> AssertionOutcome:
    """评估单个断言元素.

    eq/ne 的比较口径（本函数不改行为，仅钉语义）：
      - **始终按字符串比较**，比较前两侧都经 ``_to_str`` 归一：bool → ``true``/``false``，
        **整数值的 float 归一为整数形式**（``3.0`` → ``"3"``），None → 空串。
      - 因此 ``value: 3.0``（YAML 数字字面量）与提取出的字符串 ``"3.0"`` **不相等**：
        字面量侧归一为 ``"3"``，提取侧保持原文本 ``"3.0"``。用例侧应对齐设备的
        实际文本形态（写 ``value: "3.0"`` 或提取后补零），而非依赖数值等价。
      - 浮点精度：eq/ne **无任何 epsilon 容差**（纯字符串等值）；数值大小比较
        （gt/lt/ge/le/between）才走 ``float()`` 转换，受 IEEE-754 二进制浮点
        表示限制（如 0.1+0.2 != 0.3），无特殊处理。

    数值类操作（gt/lt/ge/le/between）对变量值与期望值各尝试 ``float()`` 转换，
    任一失败 → 该断言元素判失败（记录原因，不抛异常，§4.5）。
    """
    name = _display_name(el)

    # ---- A. 响应原文断言 ----
    if el.contains is not None:
        passed = el.contains in response
        return AssertionOutcome(
            name,
            "response.contains",
            f"包含 {el.contains!r}",
            response,
            passed,
            "" if passed else f"响应不包含 {el.contains!r}",
        )
    if el.not_contains is not None:
        passed = el.not_contains not in response
        return AssertionOutcome(
            name,
            "response.not_contains",
            f"不包含 {el.not_contains!r}",
            response,
            passed,
            "" if passed else f"响应含禁止内容 {el.not_contains!r}",
        )
    if el.matches is not None:
        try:
            ok = re.search(el.matches, response) is not None
        except re.error as exc:
            return AssertionOutcome(
                name, "response.matches", el.matches, response, False, f"正则错误：{exc}"
            )
        return AssertionOutcome(
            name,
            "response.matches",
            f"匹配 {el.matches!r}",
            response,
            ok,
            "" if ok else f"响应不匹配 {el.matches!r}",
        )
    if el.equals is not None:
        ok = response == el.equals
        return AssertionOutcome(
            name,
            "response.equals",
            repr(el.equals),
            repr(response),
            ok,
            "" if ok else "响应不完全相等",
        )

    # ---- B. 变量断言 ----
    # 类型收窄（var/op 由模型校验保证成对出现）——显式抛错而非裸 assert：
    # python -O 下 assert 被剥除，破坏时会以 AttributeError 形式逃逸（设计 §7）
    if el.var is None or el.op is None:
        raise ValueError(f"变量断言缺少 var/op（模型校验缺口）：{el.var!r}/{el.op!r}")
    var_name = el.var
    op = el.op
    present = var_name in variables
    raw_val: object = variables.get(var_name)
    val_str = _to_str(raw_val)

    expected_disp = _expected_display(el)

    if not present:
        return AssertionOutcome(
            name,
            f"var.{op.value}",
            expected_disp,
            "<未定义>",
            False,
            f"变量 {var_name} 未定义",
        )

    # is-null 类已排除（op 枚举不含 null）
    reason = ""

    if op is AssertionOp.EQ:
        passed = val_str == _to_str(el.value)
        if not passed:
            reason = f"{var_name}={val_str!r} 不等于 {_to_str(el.value)!r}"
    elif op is AssertionOp.NE:
        passed = val_str != _to_str(el.value)
        if not passed:
            reason = f"{var_name}={val_str!r} 等于 {_to_str(el.value)!r}"
    elif op in (
        AssertionOp.GT,
        AssertionOp.LT,
        AssertionOp.GE,
        AssertionOp.LE,
        AssertionOp.BETWEEN,
    ):
        num = _try_float(val_str)
        if num is None:
            return AssertionOutcome(
                name,
                f"var.{op.value}",
                expected_disp,
                val_str,
                False,
                f"变量 {var_name}={val_str!r} 非数值，无法比较",
            )
        if op is AssertionOp.BETWEEN:
            lo, hi = el.min, el.max  # type: ignore[assignment]
            passed = lo is not None and hi is not None and lo <= num <= hi
            if not passed:
                reason = f"{var_name}={num} 不在 [{lo}, {hi}] 内"
        else:
            operand = _try_float(_to_str(el.value))
            if operand is None:
                return AssertionOutcome(
                    name,
                    f"var.{op.value}",
                    expected_disp,
                    val_str,
                    False,
                    f"期望值 {el.value!r} 非数值",
                )
            if op is AssertionOp.GT:
                passed, reason = (num > operand, f"{var_name}={num} 不大于 {operand}")
            elif op is AssertionOp.LT:
                passed, reason = (num < operand, f"{var_name}={num} 不小于 {operand}")
            elif op is AssertionOp.GE:
                passed, reason = (num >= operand, f"{var_name}={num} 小于 {operand}")
            else:  # LE
                passed, reason = (num <= operand, f"{var_name}={num} 大于 {operand}")
    elif op is AssertionOp.IN:
        vals: tuple[str, ...] | list[str] = el.values or []
        passed = val_str in vals
        if not passed:
            reason = f"{var_name}={val_str!r} 不在 {vals} 内"
    elif op is AssertionOp.CONTAINS:
        sub = _to_str(el.value)
        passed = sub in val_str
        if not passed:
            reason = f"{var_name}={val_str!r} 不包含 {sub!r}"
    elif op is AssertionOp.MATCHES:
        pat = _to_str(el.value)
        try:
            passed = re.search(pat, val_str) is not None
        except re.error as exc:
            return AssertionOutcome(
                name, f"var.{op.value}", pat, val_str, False, f"正则错误：{exc}"
            )
        if not passed:
            reason = f"{var_name}={val_str!r} 不匹配 {pat!r}"
    else:  # pragma: no cover
        return AssertionOutcome(
            name, f"var.{op.value}", expected_disp, val_str, False, "未知操作符"
        )

    actual_disp = val_str
    return AssertionOutcome(name, f"var.{op.value}", expected_disp, actual_disp, passed, reason)


def assess_all(
    elements: list[AssertElement], response: str, variables: Mapping[str, object]
) -> list[AssertionOutcome]:
    """评估断言元素列表（元素间 AND 关系，§4.3）."""
    return [assess(el, response, variables) for el in elements]


def _expected_display(el: AssertElement) -> str:
    op = el.op
    if op is None:
        return ""
    if op is AssertionOp.BETWEEN:
        return f"between [{el.min}, {el.max}]"
    if op is AssertionOp.IN:
        return f"in {el.values}"
    return _to_str(el.value)


def _to_str(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    if v is None:
        return ""
    return str(v)
