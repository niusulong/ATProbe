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
    操作数   := 变量名 | 字符串字面量 | 数值字面量 | '(' 或表达式 ')'
    运算符   := == | != | > | < | >= | <=

求值规则（§6.3）：
    - 变量取值：从作用域解析，未定义 → None。
    - null 比较：除 is null / is not null 外，含 null 的比较一律 false。
    - == / != 按字符串比较；> < >= <= 按数值比较（两侧转数值失败则该比较 false）。
    - 变量值向字面量类型靠拢（字面量是数值则尝试转数值）。
    - 提取失败的变量（若进入变量池为空字符串）按空字符串处理，非 null；
      当前引擎实现是提取失败不写入池（即未定义 → null），详见 step_runner。

兼容旧写法 ``when: '{{var}} == "OK"'``（§6.5）：检测到 {{}} 先文本替换再求值。
"""

from __future__ import annotations

import re as _re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from atprobe.domain.case.templater import render

if TYPE_CHECKING:
    from atprobe.infra.config.envconfig import EnvConfig


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
      | (?P<STR>"(?:[^"\\]|\\.)*")  # 转义契约与 _preprocess 的字符串 DFA 语法等价（收敛方案见批 2+）
      | (?P<NUM>-?\d+(?:\.\d+)?)
      | (?P<LP>\()
      | (?P<RP>\))
      | (?P<NAME>[A-Za-z_][A-Za-z0-9_]*)
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
    def __init__(
        self, left_kind: str, left_val: str, op: str, right_kind: str, right_val: str
    ) -> None:
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
        left = self._parse_operand()
        left_kind, left_val = left
        # 括号子表达式已求值为布尔节点（无运算符跟随时直接透传）。
        # 形如 (a == 1)、((a == 1) and b == 2) 等仅作分组，不参与运算符拼接。
        if left_kind == "__NODE__":
            # 括号路径：left_val 是已求值的 _Node，直接透传
            assert isinstance(left_val, _Node)
            return left_val
        # 此后 left_val 一定是普通操作数的原始字符串（STR/NUM/NAME）
        assert isinstance(left_val, str)
        # 操作数 'is' ['not'] 'null'
        t = self._peek()
        if t is not None and t.kind == "IS":
            self._next()
            t2 = self._next()
            if t2.kind == "NOT":
                t3 = self._next()
                if t3.kind != "NULL":
                    raise ExpressionError("is not 后应为 null")
                return _IsNull(left_kind, left_val, negate=True)
            if t2.kind == "NULL":
                return _IsNull(left_kind, left_val, negate=False)
            raise ExpressionError("is 后应为 null 或 not null")
        if t is not None and t.kind == "OP":
            op_tok = self._next()
            right = self._parse_operand()
            right_kind, right_val = right
            # P1 修复：文法允许括号子表达式作操作数，但比较运算的右操作数不能是
            # 布尔节点（如 `x == (a == 1)`）。旧实现用裸 assert，抛 AssertionError
            # 逃出引擎（step_runner 只捕 ExpressionError），且 python -O 下行为不同。
            if right_kind == "__NODE__":
                raise ExpressionError("比较运算的右操作数不能是括号子表达式")
            assert isinstance(right_val, str)  # noqa: S101 - 到达此处必为 STR/NUM/NAME
            return _Comparison(left_kind, left_val, op_tok.value, right_kind, right_val)
        raise ExpressionError("比较表达式缺少运算符（应为 ==/!=/>/</>=/<= 或 is null）")

    def _parse_operand(self) -> tuple[str, str] | tuple[str, _Node]:
        """解析操作数，返回 (kind, value) 标记对。

        - 普通操作数（STR/NUM/NAME）→ (kind, raw_value)
        - 括号子表达式 → ("__NODE__", node)，由 _parse_comparison 透传为布尔节点
        """
        t = self._next()
        if t.kind in ("STR", "NUM", "NAME"):
            return (t.kind, t.value)
        # 括号分组：'(' 表达式 ')'，递归求值为布尔节点，用 __NODE__ 标记透传给上层。
        if t.kind == "LP":
            node = self._parse_or()
            t2 = self._next()
            if t2.kind != "RP":
                raise ExpressionError("括号未闭合，缺少 ')' ")
            return ("__NODE__", node)
        raise ExpressionError(f"意外的操作数：{t.value!r}")


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------
def _escape_str_value(value: str) -> str:
    """转义替换值中的反斜杠与引号（与 tokenizer 的 STR 字面量转义契约一致）.

    不加外层引号：字符串字面量内的占位符嵌值同样必须转义——否则值内的 ``"`` 会
    逃逸字面量（注入 is not null / or 等语法）、``\\`` 会被 _unquote_str 当转义
    序列吃掉而静默判错（设备提取值正是经变量池进入 when/poll.until 的）。
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _preprocess(expr: str, scope: Mapping[str, object], env: EnvConfig | None) -> str:
    """兼容旧写法（§6.5）：表达式含 {{}} 时先替换占位符再求值.

    替换规则（P1-4）：
    - 字符串字面量外的 ``{{var}}`` / ``{{group.param}}``：以带引号的字面量嵌入，
      避免替换出的裸值被词法层误当变量名（未定义 → null → 比较恒 false）；
      数值比较不受影响（§6.3 规则 3：比较前两侧均转数值）。
    - 字符串字面量内的 ``"{{var}}"``：嵌入转义后的值（保持旧写法兼容，且防值内
      引号/反斜杠逃逸或破坏字面量）。
    - 引用解析复用 templater.render 的口径（点号名仅查环境配置，简单名先查变量池
      再查环境配置默认组），故 env 透传后 {{group.param}} 与命令模板行为一致。

    注意：旧写法用「文本替换」，故变量未定义会抛 UndefinedReferenceError；
    新写法用「裸变量名」，未定义为 null（§6.3 规则 1）。两者语义有别，新用例应用裸名。
    """
    if "{{" not in expr:
        return expr
    out: list[str] = []
    i = 0
    n = len(expr)
    in_str = False
    # 字符串 DFA：与 tokenizer 的 STR 正则（见 _TOKEN_RE 的 STR 行）保持语法等价性
    # 契约——转义序列（\" 与 \\）整体跳过；两处口径若漂移会导致嵌值边界误判
    # （收敛方案见批 2+）。
    while i < n:
        # 占位符检测（字符串字面量内外都可能出现）
        if expr.startswith("{{", i):
            end = expr.find("}}", i + 2)
            name = expr[i + 2 : end].strip() if end != -1 else ""
            if name and "{" not in name and "}" not in name:
                # 严格渲染（未定义即抛 UndefinedReferenceError）
                value = render("{{" + name + "}}", scope, env=env, allow_partial=False)
                escaped = _escape_str_value(value)
                # in-string：嵌在既有字面量内，只转义不加引号；out-of-string：整体加引号
                out.append(escaped if in_str else f'"{escaped}"')
                i = end + 2
                continue
        ch = expr[i]
        out.append(ch)
        if in_str:
            if ch == "\\" and i + 1 < n:  # 转义字符整体照搬
                out.append(expr[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        i += 1
    return "".join(out)


def evaluate(expr: str, scope: Mapping[str, object], *, env: EnvConfig | None = None) -> bool:
    """求值条件表达式，返回布尔结果.

    Args:
        expr: 条件表达式（如 ``'stat == "1" or stat == "5"'``）。
        scope: 变量作用域（变量名 → 值）。未定义的变量解析为 None。
        env: 环境配置（{{group.param}} 点号引用来源），None 时点号名未定义即报错。
    Raises:
        ExpressionError: 表达式语法错误。
        UndefinedReferenceError: 旧写法 {{var}} 中 var 未定义。
    """
    processed = _preprocess(expr, scope, env)
    tokens = _tokenize(processed)
    if not tokens:
        raise ExpressionError("空表达式")
    node = _Parser(tokens).parse()
    return node.eval(scope)
