"""模板替换器（REQ-M2 §5.2、REQ-M7 §4）.

纯函数实现（TSD §5.6）。只支持两种占位符的字符串替换：
    {{var}}          简单名 → 先查用例级变量池，未命中查环境配置默认组
    {{group.param}}  点号名 → 仅查环境配置

查找优先级（REQ-M7 §4.1）：
    1. 占位符含点号 → 仅查环境配置（点号名不被 extract 覆盖，§4.4 边界）
       命中则用值；未命中 → UndefinedReferenceError
    2. 占位符不含点号 → 先查用例级变量池
       命中则用值；未命中 → 查环境配置默认组（可选）
       仍未命中 → UndefinedReferenceError

不含任何控制结构/表达式求值（那是 evaluator 的职责，§5.7），无注入风险。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atprobe.infra.config.envconfig import EnvConfig

# 匹配 {{ ... }}，允许内部空白；捕获内部名称
_PLACEHOLDER = re.compile(r"{{\s*([^{}]+?)\s*}}")


class UndefinedReferenceError(KeyError):
    """模板中引用了未定义的变量/环境配置项."""

    def __init__(self, ref: str) -> None:
        self.ref = ref
        super().__init__(ref)


class TemplateRenderError(ValueError):
    """模板渲染错误（如值非字符串无法嵌入、循环引用占位符等）."""


def render(
    template: str,
    variables: Mapping[str, object],
    env: EnvConfig | None = None,
    *,
    allow_partial: bool = False,
) -> str:
    """渲染模板，替换所有 {{...}} 占位符.

    Args:
        template: 含占位符的字符串。
        variables: 用例级变量池（简单名查找源）。
        env: 环境配置（点号名 + 简单名兜底查找源），None 表示无环境配置。
        allow_partial: True 时未定义的占位符原样保留（不抛错），用于「先替换能替换的」
            场景（如命令含 `{{loop_index}}` 在第一遍渲染时尚未注入）。默认 False，未定义即报错。
    Returns:
        渲染后的字符串。
    Raises:
        UndefinedReferenceError: 占位符未定义且 allow_partial=False。
    """
    def _resolve(name: str) -> str:
        # 拒绝嵌套点号路径（仅允许两级 group.param）
        parts = name.split(".")
        if len(parts) > 2:
            raise UndefinedReferenceError(name)
        if len(parts) == 2:
            # 点号名：仅查环境配置（§4.4 边界）
            if env is None:
                raise UndefinedReferenceError(name)
            return env.resolve_str(name)
        # 简单名：先查用例变量池，再查环境配置默认组
        if name in variables:
            return _to_str(variables[name], name)
        if env is not None and env.has(name):
            return env.resolve_str(name)
        raise UndefinedReferenceError(name)

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            return _resolve(name)
        except UndefinedReferenceError:
            if allow_partial:
                return match.group(0)  # 原样保留
            raise

    return _PLACEHOLDER.sub(_replace, template)


def _to_str(value: object, ref: str) -> str:
    """将变量值转为可嵌入字符串的形式."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # 整数值的 float 用整数形式（与 assessor/evaluator 保持一致，避免 2.0 vs 2）
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, str):
        return value
    if value is None:
        raise UndefinedReferenceError(ref)
    # dict/list 等：JSON-ish 表示（罕见，主要防误用）
    return str(value)


def find_references(template: str) -> list[str]:
    """提取模板中所有占位符名称（去重，保持首次出现顺序）.

    供 UI「校验引用」（M7 §7.2）与 dry-run（M5 §3.6）使用。
    """
    seen: dict[str, None] = {}
    for m in _PLACEHOLDER.finditer(template):
        seen.setdefault(m.group(1), None)
    return list(seen)
