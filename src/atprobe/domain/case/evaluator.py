"""条件表达式求值器（REQ-M2 §6）.

纯函数实现（TSD §5.7）。用于 ``when``（步骤条件跳过）与 ``poll.until``（轮询终止条件），
两者共用同一套语法和求值规则（§6.1）。

文法（§6.2）::

    表达式   := 或表达式
    或表达式 := 与表达式 ( 'or' 与表达式 )*
    与表达式 := 比较表达式 ( 'and' 比较表达式 )*
    比较表达式 := 操作数 运算符 操作数
                | 操作数 'is' 'null'
                | 操作数 'is' 'not' 'null'
    操作数   := 变量名 | 字符串字面量 | 数值字面量
    运算符   := == | != | > | < | >= | <=

求值规则（§6.3）：
    - 变量取值：从作用域解析，未定义 → None。
    - null 比较：除 is null / is not null 外，含 null 的比较一律 false。
    - == / != 按字符串比较；> < >= <= 按数值比较（两侧转数值失败则该比较 false）。
    - 变量值向字面量类型靠拢（字面量是数值则尝试转数值）。
    - 提取失败（空值）按空字符串处理，非 null。

兼容旧写法 ``when: '{{var}} == "OK"'``（§6.5）：检测到 {{}} 先文本替换再求值。
"""

from __future__ import annotations

import re as _re
from collections.abc import Mapping

from atprobe.domain.case.templater import render


class ExpressionError(ValueError):
    """表达式语法或求值错误."""


# ---------------------------------------------------------------------------
# 词法
# ---------------------------------------------------------------------------

_TOKEN_RE = _re.compile(
    r"""
      (?P<AND>and\b)
      | (?P<OR>or\b)
      | (?P<IS>is\b)
      | (?P<NOT>not\b)
      | (?P<NULL>null\b)
      | (?P<OP>>=|<=|==|!=|>|<)
      | (?P<STR>"(?:[^"\\]|\\.)*")
      | (?P<NUM>-?\d+(?:\.\d+)?)
      | (?P<LP>\()
      | (?P<RP>\))
      | (?P<NAME>[A-Za-z_][A-Za-z0-9_\.]*)
    """,
    _re.VERBOSE,
)


class _Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"Token({self.kind}, {self.value!r})"


def _tokenize(expr: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    n = len(expr)
    while pos < n:
        # 跳过空白
        while pos < n and expr[pos].isspace():
            pos += 1
        if pos >= n:
            break
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ExpressionError(f"表达式词法错误，无法识别：{expr[pos:]!r}")
        pos = m.end()
        kind = m.lastgroup
        assert kind is not None
        tokens.append(_Token(kind, m.group()))
    return tokens


# ---------------------------------------------------------------------------
# AST 节点
# ---------------------------------------------------------------------------
class _Node:  # pragma: no cover - abstract
    def eval(self, scope: Mapping[str, object]) -> bool:  # noqa: A003
        raise NotImplementedError


class _BoolLit(_Node):
    def __init__(self, value: bool) -> None:
        self.value = value

    def eval(self, scope: Mapping[str, object]) -> bool:  # noqa: A003
        return self.value


class _Comparison(_Node):
    def __init__(self, left_kind: str, left_val: str, op: str, right_kind: str, right_val: str) -> None:
        self.left_kind = left_kind
        self.left_val = left_val
        self.op = op
        self.right_kind = right_kind
        self.right_val = right_val

    def eval(self, scope: Mapping[str, object]) -> bool:  # noqa: A003
        lv = _resolve_operand(self.left_kind, self.left_val, scope)
        rv = _resolve_operand(self.right_kind, self.right_val, scope)

        # null 语义（§6.3 规则 2）：含 null 的比较（非 is null）一律 false
        if lv is None or rv is None:
            return False

        op = self.op
        if op == "==":
            return _as_str(lv) == _as_str(rv)
        if op == "!=":
            return _as_str(lv) != _as_str(rv)
        # 数值比较
        ln, lok = _try_num(lv)
        rn, rok = _try_num(rv)
        if not (lok and rok):
            return False
        if op == ">":
            return ln > rn
        if op == "<":
            return ln < rn
        if op == ">=":
            return ln >= rn
        if op == "<=":
            return ln <= rn
        raise ExpressionError(f"未知运算符 {op}")  # pragma: no cover


class _IsNull(_Node):
    def __init__(self, operand_kind: str, operand_val: str, negate: bool) -> None:
        self.kind = operand_kind
        self.val = operand_val
        self.negate = negate

    def eval(self, scope: Mapping[str, object]) -> bool:  # noqa: A003
        v = _resolve_operand(self.kind, self.val, scope)
        is_null = v is None
        return (not is_null) if self.negate else is_null


class _And(_Node):
    def __init__(self, left: _Node, right: _Node) -> None:
        self.left = left
        self.right = right

    def eval(self, scope: Mapping[str, object]) -> bool:  # noqa: A003
        return self.left.eval(scope) and self.right.eval(scope)


class _Or(_Node):
    def __init__(self, left: _Node, right: _Node) -> None:
        self.left = left
        self.right = right

    def eval(self, scope: Mapping[str, object]) -> bool:  # noqa: A003
        return self.left.eval(scope) or self.right.eval(scope)


# ---------------------------------------------------------------------------
# 操作数解析
# ---------------------------------------------------------------------------
def _resolve_operand(kind: str, raw: str, scope: Mapping[str, object]) -> object:
    if kind == "STR":
        return _unquote_str(raw)
    if kind == "NUM":
        return _parse_num(raw)
    if kind == "NAME":
        if raw == "null":
            return None
        return scope.get(raw, None)
    raise ExpressionError(f"未知操作数 {kind}")  # pragma: no cover


def _unquote_str(raw: str) -> str:
    # 去掉首尾引号，处理简单转义
    inner = raw[1:-1]
    out: list[str] = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
            out.append(mapping.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_num(raw: str) -> int | float:
    return float(raw) if "." in raw else int(raw)


def _try_num(v: object) -> tuple[float, bool]:
    if isinstance(v, bool):
        return float(v), True
    if isinstance(v, (int, float)):
        return float(v), True
    if isinstance(v, str):
        try:
            return float(v), True
        except ValueError:
            return 0.0, False
    return 0.0, False


def _as_str(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        # 整数值的 float 用整数形式比较（避免 1.0 != 1）
        return str(int(v)) if v.is_integer() else str(v)
    return str(v)


# ---------------------------------------------------------------------------
# 递归下降解析
# ---------------------------------------------------------------------------
class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> _Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self) -> _Token:
        if self.pos >= len(self.tokens):
            raise ExpressionError("表达式不完整，意外的结尾")
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self) -> _Node:
        node = self._parse_or()
        if self.pos != len(self.tokens):
            raise ExpressionError(f"表达式多余内容：{self.tokens[self.pos].value!r}")
        return node

    def _parse_or(self) -> _Node:
        node = self._parse_and()
        while True:
            t = self._peek()
            if t is not None and t.kind == "OR":
                self._next()
                rhs = self._parse_and()
                node = _Or(node, rhs)
            else:
                break
        return node

    def _parse_and(self) -> _Node:
        node = self._parse_comparison()
        while True:
            t = self._peek()
            if t is not None and t.kind == "AND":
                self._next()
                rhs = self._parse_comparison()
                node = _And(node, rhs)
            else:
                break
        return node

    def _parse_comparison(self) -> _Node:
        # 操作数 'is' ['not'] 'null'
        left = self._parse_operand()
        t = self._peek()
        if t is not None and t.kind == "IS":
            self._next()
            t2 = self._next()
            if t2.kind == "NOT":
                t3 = self._next()
                if t3.kind != "NULL":
                    raise ExpressionError("is not 后应为 null")
                return _IsNull(left[0], left[1], negate=True)
            if t2.kind == "NULL":
                return _IsNull(left[0], left[1], negate=False)
            raise ExpressionError("is 后应为 null 或 not null")
        if t is not None and t.kind == "OP":
            op_tok = self._next()
            right = self._parse_operand()
            return _Comparison(left[0], left[1], op_tok.value, right[0], right[1])
        raise ExpressionError("比较表达式缺少运算符（应为 ==/!=/>/</>=/<= 或 is null）")

    def _parse_operand(self) -> tuple[str, str]:
        t = self._next()
        if t.kind in ("STR", "NUM", "NAME"):
            return (t.kind, t.value)
        raise ExpressionError(f"意外的操作数：{t.value!r}")


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------
def _preprocess(expr: str, scope: Mapping[str, object]) -> str:
    """兼容旧写法（§6.5）：表达式含 {{}} 时先文本替换再求值.

    注意：旧写法用「文本替换」，故变量未定义会抛 UndefinedReferenceError；
    新写法用「裸变量名」，未定义为 null（§6.3 规则 1）。两者语义有别，新用例应用裸名。
    """
    if "{{" not in expr:
        return expr
    # 旧写法：渲染（未定义报错），allow_partial=False 保持兼容严格性
    return render(expr, scope, env=None, allow_partial=False)


def evaluate(expr: str, scope: Mapping[str, object]) -> bool:
    """求值条件表达式，返回布尔结果.

    Args:
        expr: 条件表达式（如 ``'stat == "1" or stat == "5"'``）。
        scope: 变量作用域（变量名 → 值）。未定义的变量解析为 None。
    Raises:
        ExpressionError: 表达式语法错误。
        UndefinedReferenceError: 旧写法 {{var}} 中 var 未定义。
    """
    processed = _preprocess(expr, scope)
    tokens = _tokenize(processed)
    if not tokens:
        raise ExpressionError("空表达式")
    node = _Parser(tokens).parse()
    return node.eval(scope)
