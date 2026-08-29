"""模板替换器（REQ-M2 §5.2、REQ-M7 §4）.

纯函数实现（TSD §5.6）。支持三种占位符的字符串替换：
    {{var}}          简单名 → 先查用例级变量池，未命中查环境配置默认组
    {{group.param}}  点号名 → 仅查环境配置
    {{fn("arg")}}    内置函数 → 仅白名单分发（如 file_size），路径经 S-8 锚定

查找优先级（REQ-M7 §4.1）：
    1. 占位符含点号 → 仅查环境配置（点号名不被 extract 覆盖，§4.4 边界）
       命中则用值；未命中 → UndefinedReferenceError
    2. 占位符不含点号 → 先查用例级变量池
       命中则用值；未命中 → 查环境配置默认组（可选）
       仍未命中 → UndefinedReferenceError

不含任何控制结构/表达式求值（那是 evaluator 的职责，§5.7），无注入风险。
内置函数仅字面量字符串参数、白名单分发（§5 S-8：路径函数一律锚定校验）。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from atprobe.domain.case.datasource import (
    DataPathError,
    data_roots,
    ensure_within,
    resolve_case_path,
)
from atprobe.domain.case.errors import UndefinedReferenceError

# 匹配 {{ ... }}，允许内部空白；捕获内部名称
_PLACEHOLDER = re.compile(r"{{\s*([^{}]+?)\s*}}")

# 函数形态占位符：name(args)，name 为标识符（点号名/简单名不含括号，不会误命中）
_FUNC_FORM = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\((.*)\)")


class EnvLookup(Protocol):
    """render 对环境配置的最小调用面（结构化协议，D-2：domain 不反向依赖 infra）.

    infra 的 EnvConfig 已有同名同签名方法（resolve_str/has），结构匹配即满足
    （Protocol 按 duck-typing 结构子类型，无需显式继承）。方法集以 render 的
    实际调用面为准——只声明用到的那两个，不多不少。
    """

    def resolve_str(self, ref: str) -> str:
        """解析 ``group.param`` 或简单名引用，返回字符串形式；未定义抛 UndefinedReferenceError."""
        ...

    def has(self, name: str) -> bool:
        """简单名是否在环境配置中定义（默认组查找）."""
        ...


class TemplateRenderError(ValueError):
    """模板渲染错误（如值非字符串无法嵌入、循环引用占位符等）."""


def _fn_file_size(arg: str, case_dir: Path | None, roots: Sequence[Path]) -> str:
    """{{file_size("path")}} → 文件字节数（S-8：路径须在锚集内）."""
    try:
        anchored = ensure_within(resolve_case_path(arg, case_dir), roots)
        return str(anchored.stat().st_size)
    except (OSError, DataPathError) as exc:
        raise TemplateRenderError(f"file_size: 无法访问文件 {arg}（{exc}）") from exc


# 内置函数白名单：新增函数须先过 S-8 锚定/参数形态审视（§5）
_BUILTINS: dict[str, Callable[[str, Path | None, Sequence[Path]], str]] = {
    "file_size": _fn_file_size,
}


def render(
    template: str,
    variables: Mapping[str, object],
    env: EnvLookup | None = None,
    *,
    case_dir: Path | None = None,
    data_allowed_roots: tuple[Path, ...] = (),
    allow_partial: bool = False,
) -> str:
    """渲染模板，替换所有 {{...}} 占位符.

    Args:
        template: 含占位符的字符串。
        variables: 用例级变量池（简单名查找源）。
        env: 环境配置查找接口（EnvLookup 协议，EnvConfig 结构匹配；点号名 +
            简单名兜底查找源），None 表示无环境配置。
        case_dir: 用例文件所在目录——内置路径函数的默认锚根与相对路径基准
            （S-8，§5）。None 时相对路径按 CWD 解析、锚集仅 data_allowed_roots。
        data_allowed_roots: 额外数据根（EngineConfig.data_allowed_roots），
            与 case_dir 并集构成路径锚集。
        allow_partial: True 时未定义的占位符原样保留（不抛错），用于「先替换能替换的」
            场景（如命令含 `{{loop_index}}` 在第一遍渲染时尚未注入）。默认 False，未定义即报错。
            注意：内置函数求值失败不属于「未定义变量」，allow_partial 下照抛
            TemplateRenderError。
    Returns:
        渲染后的字符串。
    Raises:
        UndefinedReferenceError: 占位符未定义且 allow_partial=False。
        TemplateRenderError: 内置函数未知/参数形态错误/文件不可访问或越界（S-8）。
    """

    def _resolve(name: str) -> str:
        # 函数形态 {{fn("arg")}}：白名单分发，参数须为引号字面量
        func = _FUNC_FORM.fullmatch(name)
        if func is not None:
            fn, raw_arg = func.group(1), func.group(2)
            arg = raw_arg.strip()
            if len(arg) < 2 or arg[0] not in ("'", '"') or arg[-1] != arg[0]:
                raise TemplateRenderError(f"内置模板函数 {fn} 的参数须为引号字符串")
            handler = _BUILTINS.get(fn)
            if handler is None:
                raise TemplateRenderError(f"未知内置模板函数：{fn}")
            return handler(arg[1:-1], case_dir, data_roots(case_dir, data_allowed_roots))
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
    函数形态（如 {{file_size("x")}}）不是变量引用，跳过——UI 校验不应报未定义。
    """
    seen: dict[str, None] = {}
    for m in _PLACEHOLDER.finditer(template):
        if _FUNC_FORM.fullmatch(m.group(1)):
            continue
        seen.setdefault(m.group(1), None)
    return list(seen)
