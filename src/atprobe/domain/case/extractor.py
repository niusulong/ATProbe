"""extract 提取器（REQ-M2 §5.1）.

纯函数。从响应文本中按正则提取变量，取**第一个捕获分组**作为值。
提取失败（无匹配）时返回空字符串且 matched=False。

注意：本层只负责「提取并返回 (value, matched)」。是否把失败变量写入变量池由
引擎层（step_runner）决定——当前实现是**不写入**（等同未定义，`is null` 为 True），
故 matched 标志是引擎过滤的依据，而非领域层的状态。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionResult:
    """单条 extract 的结果."""

    name: str
    value: str
    matched: bool  # False 表示正则无匹配（空值）


def extract_one(pattern: str, response: str) -> ExtractionResult:
    """按正则提取，返回结果.

    - 正则无捕获分组 → 用整体匹配作为值（友好兜底，但仍推荐显式分组）。
    - 有捕获分组 → 取第一个捕获分组。
    - 无匹配 → matched=False，value="" 。
    - 正则编译失败 → 抛 re.error。
    """
    m = re.search(pattern, response)
    if m is None:
        return ExtractionResult(name="", value="", matched=False)
    if m.groups():
        value = m.group(1) if m.lastindex and m.lastindex >= 1 else ""
    else:
        value = m.group(0)
    return ExtractionResult(name="", value=value, matched=True)


def extract_all(
    spec: dict[str, str], response: str
) -> tuple[dict[str, str], dict[str, bool]]:
    """对一组 extract 规则提取，返回 (变量值字典, 是否匹配字典).

    Args:
        spec: {变量名: 正则}。
        response: M1 交付的完整响应文本。
    Returns:
        values: {变量名: 值}（无匹配的变量值为空字符串 ""）。
        matched: {变量名: 是否匹配到}。
    Raises:
        re.error: 正则编译失败。
    """
    values: dict[str, str] = {}
    matched: dict[str, bool] = {}
    for name, pattern in spec.items():
        r = extract_one(pattern, response)
        values[name] = r.value
        matched[name] = r.matched
    return values, matched
