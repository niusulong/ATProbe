"""用户正则 ReDoS 静态分级检测（S-2，设计 §5）.

用户正则来源五处——Step 的 wait_urc/expect/extract/assert.matches、atprobe.yaml 的
urc_filter、MCP URC 订阅的 pattern——均在解析/注册期先行 ``re.compile`` 校验语法。
本模块在其后对 ``re`` 引擎的解析树（``re._parser``，即 sre_parse 的 3.11+ 官方
内位，避免 ``import sre_parse`` 的 DeprecationWarning）做灾难性回溯的静态启发式
分级，不引入 regex 库、不实际执行匹配：

    - 硬拒①嵌套量词：可变次数量词（``min != max``，含 ``*`` / ``+`` / ``{m,n}``）
      作用的子模式自身含可变次数量词——``(a+)+`` / ``(\\w+)+`` / ``((a+)*)+`` /
      ``(a{1,2})+`` 族，灾难性回溯的典型形态（实测 30-40 字符输入即可让引擎线程
      卡死）。固定次数 ``{n,n}`` 无逐次回溯展开，不计入（``(a{2})+`` 放行）。
    - 硬拒②可空量词×全重叠交替：可匹配 0 次的量词（``*``）内含完全重叠的交替
      ——两分支可匹配相同内容，CPython 公共前缀外提后表现为双空分支 ``(a|)``，
      即 ``(a|a)*`` 族的解析形态（实测 26 字符即达 10 秒级）。
    - 警告类重叠交替：量词内分支首字符相同的文字交替（``(a|a)+`` / ``(x|a|a)+``）
      ——静态误报率高，仅告警不硬拒。
    - 其余放行（运行期边界：响应文本超 64KB 时 extract 性能退化，属输入规模
      问题，建议控制单步等待的响应规模而非改写正则）。

近似与容错：反向引用（``\\1``）按消耗字符的原子处理（不做组内容展开分析）；
空 pattern / 解析失败容错返回 ``(None, [])``——语法错误由调用方的 ``re.compile``
口径先行报告。

**已知漏拒族**（启发式边界，静态检测不可能完备——列出供共享用例场景自查）：

- ``(a|aa)+`` 同首字符且分支间有前缀包含关系的交替套量词：不构成硬拒①②的
  解析形态，但对 ``aaa...b`` 型输入存在指数回溯（仅当输入不匹配时触发）；
- ``(cat|car)+`` 同首字符、等长或近长分支的交替套量词：同上族的文字版；
- 缓解因素：本工具的用户正则全部作用于**有限的设备响应文本**（单步响应通常
  <1KB，超 64KB 才显著退化），上述形态在正常响应规模下不构成实际 DoS；
  若把正则用于不可信的大文本（当前无此场景），须另行评估。
"""

from __future__ import annotations

from collections.abc import Iterable

# Python 3.11+：re._parser 为 sre_parse 的官方内位（运行期静默；import sre_parse
# 会触发 DeprecationWarning）。mypy 无其存根，忽略 attr-defined（_sre_parse 视为 Any）。
from re import _parser as _sre_parse  # type: ignore[attr-defined]
from typing import Any

# 节点（op, av）形态：
#   量词族  av = (min, max, subpattern)，unbounded 的 max 为 MAXREPEAT 哨兵；
#   SUBPATTERN av = (group, add_flags, del_flags, subpattern)；
#   BRANCH   av = (None, [branch, ...])，branch 为节点序列；
#   ATOMIC_GROUP（(?>...)）av 为节点序列；其余（LITERAL/IN/AT/GROUPREF 等）为叶子。
_REPEAT_OPS = frozenset(
    {_sre_parse.MAX_REPEAT, _sre_parse.MIN_REPEAT, _sre_parse.POSSESSIVE_REPEAT}
)
_SUBPATTERN = _sre_parse.SUBPATTERN
_BRANCH = _sre_parse.BRANCH
_LITERAL = _sre_parse.LITERAL
_ATOMIC_GROUP = getattr(_sre_parse, "ATOMIC_GROUP", None)  # 3.11+ 恒存在，容错取用


def check_pattern(pattern: str) -> tuple[str | None, list[str]]:
    """静态检测用户正则的灾难性回溯风险（S-2）.

    返回 ``(hard_error, warnings)``：hard_error 非 None 表示硬拒（嵌套量词等
    典型形态，理由见返回文本）；warnings 为建议性告警（重叠交替类）。空
    pattern / 解析失败容错返回 ``(None, [])``。
    """
    if not pattern:
        return (None, [])
    warnings: list[str] = []
    try:
        tree = _sre_parse.parse(pattern, 0)
        hard = _scan(tree, warnings)
    except Exception:
        # 调用方已先 re.compile 校验语法；此处的解析/递归异常（如超深嵌套）
        # 不重复报错，交由编译口径统一处理。
        return (None, [])
    return (hard, list(dict.fromkeys(warnings)))  # 去重且保序


def _is_variable(av: Any) -> bool:
    """量词是否可变次数（min != max；unbounded 的 max 为哨兵，恒不等于 int min）."""
    return bool(av[0] != av[1])


def _contains_variable_repeat(nodes: Iterable[tuple[Any, Any]]) -> bool:
    """节点序列（递归穿透组/交替/量词体）是否含可变次数量词（嵌套判定内层）.

    固定次数 ``{n,n}`` 本身不计入量词，但其体仍穿透——如 ``(a{2}b+)+`` 中
    ``b+`` 藏在固定量词之后，依旧构成嵌套。
    """
    for op, av in nodes:
        if op in _REPEAT_OPS:
            if _is_variable(av):
                return True
            if _contains_variable_repeat(av[2]):
                return True
        elif op is _SUBPATTERN:
            if _contains_variable_repeat(av[3]):
                return True
        elif op is _BRANCH:
            if any(_contains_variable_repeat(b) for b in av[1]):
                return True
        elif _ATOMIC_GROUP is not None and op is _ATOMIC_GROUP:
            if _contains_variable_repeat(av):
                return True
    return False


def _can_match_empty(nodes: Iterable[tuple[Any, Any]]) -> bool:
    """节点序列是否可整体匹配空串（识别前缀外提残迹 ``(a|)`` 中的空分支）.

    零宽断言（AT）与 ``{0,..}`` 量词可空；反向引用按消耗字符处理（从宽，
    宁可漏报重叠，不凭空误报）。
    """
    for op, av in nodes:
        if op is _sre_parse.AT:
            continue
        if op in _REPEAT_OPS:
            if av[0] == 0 or _can_match_empty(av[2]):
                continue
            return False
        if op is _SUBPATTERN:
            if _can_match_empty(av[3]):
                continue
            return False
        if op is _BRANCH:
            if any(_can_match_empty(b) for b in av[1]):
                continue
            return False
        if _ATOMIC_GROUP is not None and op is _ATOMIC_GROUP:
            if _can_match_empty(av):
                continue
            return False
        return False
    return True


def _collect_branches(nodes: Iterable[tuple[Any, Any]], out: list[list[Any]]) -> None:
    """收集节点序列内全部 BRANCH 的分支列表（穿透组/固定量词体/嵌套分支）.

    不进入可变次数量词体——调用方（_scan）已先做嵌套量词硬拒判定，可变量词
    体要么已触发硬拒返回，要么必不含再一层量词。
    """
    for op, av in nodes:
        if op is _BRANCH:
            out.append(av[1])
            for b in av[1]:
                _collect_branches(b, out)
        elif op is _SUBPATTERN:
            _collect_branches(av[3], out)
        elif op in _REPEAT_OPS and not _is_variable(av):
            _collect_branches(av[2], out)
        elif _ATOMIC_GROUP is not None and op is _ATOMIC_GROUP:
            _collect_branches(av, out)


def _check_overlap(bs: list[Any], mn: int, warnings: list[str]) -> str | None:
    """量词体内单个交替的重叠判定：返回硬拒理由或追加告警（mn 为量词下限）."""
    empty_n = sum(1 for b in bs if _can_match_empty(b))
    if empty_n >= 2:
        # 全重叠交替（外提残迹双空分支）：量词可匹配 0 次时零宽歧义无界 → 硬拒；
        # 至少匹配 1 次时歧义受字符数约束但静态误报率高 → 仅告警。
        if mn == 0:
            return "可空量词×全重叠交替（(a|a)* 族：* 内两分支可匹配相同内容）"
        warnings.append("量词内全重叠交替（如 (a|a)+）：分支可匹配相同内容，建议改写为字符类")
        return None
    # 首字符相同的文字分支（外提未合并的残存形态，如 (x|a|a)+）
    first_literal: dict[Any, int] = {}
    for b in bs:
        if b:
            op, av = b[0]
            if op is _LITERAL:
                first_literal[av] = first_literal.get(av, 0) + 1
    if any(c >= 2 for c in first_literal.values()):
        warnings.append("量词内分支首字符相同的文字交替（如 (x|a|a)+）：建议合并为字符类")
    return None


def _scan(nodes: Iterable[tuple[Any, Any]], warnings: list[str]) -> str | None:
    """遍历节点序列，返回首个硬拒理由（无则 None），告警追加至 warnings."""
    for op, av in nodes:
        if op in _REPEAT_OPS:
            body = av[2]
            if _is_variable(av):
                if _contains_variable_repeat(body):
                    return "嵌套量词（量词作用域内再含可变次数量词，(a+)+/(\\w+)+ 族）"
                branches: list[list[Any]] = []
                _collect_branches(body, branches)
                for bs in branches:
                    hard = _check_overlap(bs, av[0], warnings)
                    if hard is not None:
                        return hard
            hard = _scan(body, warnings)
            if hard is not None:
                return hard
        elif op is _SUBPATTERN:
            hard = _scan(av[3], warnings)
            if hard is not None:
                return hard
        elif op is _BRANCH:
            for b in av[1]:
                hard = _scan(b, warnings)
                if hard is not None:
                    return hard
        elif _ATOMIC_GROUP is not None and op is _ATOMIC_GROUP:
            hard = _scan(av, warnings)
            if hard is not None:
                return hard
    return None
