"""M2 用例数据模型（Pydantic，对应 REQ-M2 §2/§3/§4/§9/§10/§11/§13）.

设计要点：
    - 用例文件 = 一个 Case。三种场景（基础/序列/压测）共用同一 schema，靠是否存在
      ``loop`` 字段区分（REQ-M2 §2.3、M3 §3）。
    - 步骤（Step）由四组正交字段组成（§3.1）：输入方式 + 行为修饰符 + 输出处理 +
      失败处理。
    - retry 与 poll 互斥（§3.1/§9.2/§11.2）。
    - 超时只在步骤级配置（§2.4，无三级继承）。
    - 全部模型 frozen，跨线程传递安全（TSD §5.1）。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    """所有领域模型冻结，禁止额外字段（避免静默吞掉拼写错误的键）."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# §3.4 失败策略
# ---------------------------------------------------------------------------
class FailureStrategy(str, Enum):
    """步骤失败处理策略（REQ-M2 §3.4）."""

    ABORT = "abort"
    SKIP = "skip"
    CONTINUE = "continue"


# ---------------------------------------------------------------------------
# §9 retry 配置
# ---------------------------------------------------------------------------
class RetryConfig(_Frozen):
    """重试配置（REQ-M2 §9）.

    count  重试次数（不含首次），count=3 → 最多执行 4 次（首次+3 次重试）。
    interval 重试间隔（毫秒）。
    """

    count: int = Field(ge=0)
    interval: int = Field(ge=0, default=0)


# ---------------------------------------------------------------------------
# §11 poll 配置
# ---------------------------------------------------------------------------
class PollConfig(_Frozen):
    """轮询配置（REQ-M2 §11）.

    until   条件表达式（用 evaluator 求值，§6）。
    timeout 轮询总超时（秒），必填。
    interval 轮询间隔（毫秒），默认 1000。
    """

    until: str
    timeout: float = Field(gt=0)
    interval: int = Field(gt=0, default=1000)


# ---------------------------------------------------------------------------
# §4 断言
# ---------------------------------------------------------------------------
class AssertionOp(str, Enum):
    """变量断言操作符（REQ-M2 §4.2 B 表）."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    LT = "lt"
    GE = "ge"
    LE = "le"
    BETWEEN = "between"
    IN = "in"
    CONTAINS = "contains"
    MATCHES = "matches"


class AssertElement(_Frozen):
    """单个断言元素（REQ-M2 §4.1 列表式 / §4.2）.

    支持两种形态：
      A. 响应原文断言（§4.2 A 表）：contains / not_contains / matches / equals 之一。
      B. 变量断言（§4.2 B 表）：var + op + (value|min|max|values)。

    name 可选，用于报告展示（§4.4）。缺省由引擎生成。
    """

    name: str | None = None

    # A. 响应原文断言（互斥，至多一个）
    contains: str | None = None
    not_contains: str | None = None
    matches: str | None = None
    equals: str | None = None

    # B. 变量断言
    var: str | None = None
    op: AssertionOp | None = None
    value: str | int | float | None = None
    min: float | None = None  # noqa: A003 (between 下界)
    max: float | None = None  # noqa: A003 (between 上界)
    # M2 修复：改 tuple 防止 frozen 模型的可变字段被就地修改（pydantic v2 frozen 只阻止
    # 重新赋值，不阻止 list.append；tuple 天然不可变，真正满足"跨线程安全"不变量）。
    values: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _validate(self) -> AssertElement:
        # 变量断言：必须同时有 var 与 op
        is_var = self.var is not None or self.op is not None
        if is_var:
            if self.var is None or self.op is None:
                raise ValueError("变量断言需同时提供 var 与 op")
            # between 需 min/max；in 需 values；其余需 value
            if self.op is AssertionOp.BETWEEN and (self.min is None or self.max is None):
                raise ValueError("op=between 需提供 min 与 max")
            # L9：between 下界不应大于上界（否则断言恒失败，用户排查困难）
            if self.op is AssertionOp.BETWEEN and self.min is not None and self.max is not None:
                if self.min > self.max:
                    raise ValueError(f"op=between 的 min({self.min}) 不应大于 max({self.max})")
            if self.op is AssertionOp.IN and not self.values:
                raise ValueError("op=in 需提供 values")
            if self.op not in (AssertionOp.BETWEEN, AssertionOp.IN) and self.value is None:
                raise ValueError(f"op={self.op.value} 需提供 value")
            return self

        # 响应原文断言：恰好一个
        present = [
            k
            for k in ("contains", "not_contains", "matches", "equals")
            if getattr(self, k) is not None
        ]
        if not present:
            raise ValueError("断言元素须指定响应原文断言或变量断言")
        if len(present) > 1:
            raise ValueError(f"响应原文断言互斥，不可同时指定：{present}")
        # L5：not_contains/matches 为空字符串时行为反直觉（'' in anything 恒 True → 永远失败）
        # 给明确错误，而非让用户困惑于"恒失败"结果。equals='' 是合法语义（断言响应为空）。
        for field_name in ("not_contains", "matches"):
            v = getattr(self, field_name)
            if v is not None and v == "":
                raise ValueError(f"{field_name} 不可为空字符串（行为反直觉/无意义）")
        return self


# 兼容「列表式」与「单键式」（§4.1）。单键式归一化为单元素列表。
Assert = list[AssertElement] | AssertElement | None


# ---------------------------------------------------------------------------
# §3.2 / §3.3 输入方式
# ---------------------------------------------------------------------------
class DataInput(_Frozen):
    """数据流输入（REQ-M2 §3.3，对应 M1 §3.2）.

    file / inline 二选一。其余为分块参数。
    """

    file: str | None = None
    inline: str | None = None
    chunk_threshold: int = Field(gt=0, default=4096)
    chunk_size: int = Field(gt=0, default=1024)
    chunk_interval: int = Field(ge=0, default=50)
    append_terminator: bool = False

    @model_validator(mode="after")
    def _exactly_one_source(self) -> DataInput:
        if (self.file is None) == (self.inline is None):
            raise ValueError("data 字段需二选一指定 file 或 inline")
        return self


# 步骤的输入：command（直接输入）或 data（数据流输入），二选一。
# 用 discriminated union 不可行（无 marker），改用「可选字段 + 校验」。
class StepInput(_Frozen):
    """步骤输入的统一表达（§3.1 输入方式二选一）."""

    command: str | None = None
    data: DataInput | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> StepInput:
        if (self.command is None) == (self.data is None):
            raise ValueError("步骤须指定 command 或 data 之一（二选一）")
        return self


# ---------------------------------------------------------------------------
# §3 步骤
# ---------------------------------------------------------------------------
class Step(BaseModel):
    """测试步骤（REQ-M2 §3）.

    由 StepInput（输入方式）+ 行为修饰符（retry/poll/when/timeout/interval/port）
    + 输出处理（extract/assert）+ 失败处理（on_failure）组成。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    # 输入方式（拍平，便于校验）
    command: str | None = None
    data: DataInput | None = None

    # 行为修饰符
    retry: RetryConfig | None = None
    poll: PollConfig | None = None
    when: str | None = None
    timeout: float | None = Field(default=None, gt=0)
    interval: int | None = Field(default=None, ge=0)
    port: str | None = None
    # 异步指令：OK 仅受理，须等待匹配此正则的 URC 上报才算真正终结。
    # 开启后串口层遇 OK 不返回，继续读到 URC 匹配立即返回（整段 text 含 OK+URC）。
    wait_urc: str | None = Field(default=None)

    # 输出处理
    extract: dict[str, str] | None = None
    assert_: Annotated[Assert, Field(alias="assert")] = None

    # 失败处理
    on_failure: FailureStrategy | None = None

    @model_validator(mode="after")
    def _validate(self) -> Step:
        # 输入方式二选一
        if (self.command is None) == (self.data is None):
            raise ValueError("步骤须指定 command 或 data 之一（二选一）")
        # retry 与 poll 互斥（§3.1）
        if self.retry is not None and self.poll is not None:
            raise ValueError("retry 与 poll 互斥，不可同时指定")
        # wait_urc 与 poll 互斥：poll 已可轮询同步查询确认异步状态，语义重叠
        if self.wait_urc is not None and self.poll is not None:
            raise ValueError("wait_urc 与 poll 互斥，不可同时指定")
        # wait_urc 正则合法性预校验（解析期拦截无效正则，优于运行期才发现）
        if self.wait_urc is not None:
            try:
                re.compile(self.wait_urc)
            except re.error as exc:
                raise ValueError(f"wait_urc 正则无效：{exc}") from exc
        return self

    @property
    def input(self) -> StepInput:
        """规范化为 StepInput（供引擎使用）."""
        return StepInput(command=self.command, data=self.data)

    @property
    def assertions(self) -> list[AssertElement]:
        """断言归一化为列表（单键式 → 单元素列表，None → 空列表）."""
        a = self.assert_
        if a is None:
            return []
        if isinstance(a, AssertElement):
            return [a]
        return list(a)


# ---------------------------------------------------------------------------
# §13 压测配置
# ---------------------------------------------------------------------------
class LoopConfig(_Frozen):
    """压测循环配置（REQ-M2 §13）.

    count 循环次数（必填）。
    interval 「上一轮结束→下一轮开始」的间隔（毫秒）。
    warmup 预热轮数（执行但不计入统计）。
    abort_on_failure 遇失败是否中止整个压测。
    """

    count: int = Field(gt=0)
    interval: int = Field(ge=0, default=0)
    warmup: int = Field(ge=0, default=0)
    abort_on_failure: bool = False


# ---------------------------------------------------------------------------
# §2 用例
# ---------------------------------------------------------------------------
class Case(_Frozen):
    """测试用例（REQ-M2 §2）.

    一个用例文件 = 一个 Case。name 在单次执行范围内唯一（§14.3）。
    存在 loop 字段则为压测场景（§2.3）。
    """

    name: str = Field(min_length=1)
    description: str | None = None
    tags: tuple[str, ...] = Field(default_factory=tuple)
    port: str | None = None

    # §10 参数化矩阵（P1，schema 已定义）
    parameters: tuple[dict[str, str | int | float | bool], ...] = Field(default_factory=tuple)

    setup: tuple[Step, ...] = Field(default_factory=tuple)
    teardown: tuple[Step, ...] = Field(default_factory=tuple)

    interval: int | None = Field(default=None, ge=0)
    on_failure: FailureStrategy | None = None

    steps: tuple[Step, ...] = Field(min_length=1)

    loop: LoopConfig | None = None

    # 来源文件路径（由 parser 填充，不来自 YAML）
    source_file: str | None = None

    # 参数化展开实例序号（1-based，非参数化用例为 None）。由 run.py 载入时展开填充，
    # 用于报告 #N 后缀（REQ-M2 §10.2）。
    # 引擎内部字段：YAML 不应填写（填写只会在报告 name 后追加 #N，无其他副作用）。
    param_index: int | None = None

    @property
    def is_pressure(self) -> bool:
        """是否压测用例（§2.3）."""
        return self.loop is not None
