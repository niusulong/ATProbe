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

import logging
import re
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atprobe.domain.case.redos import check_pattern

# 模型层解析期告警通道（data×retry/poll 慎用提示等，不硬拒）
_log = logging.getLogger("atprobe.case")


def _validate_regex(pattern: str, what: str) -> None:
    """正则解析期校验：语法编译 + ReDoS 静态分级（S-2，设计 §5）.

    四处用户正则（wait_urc/expect/extract/assert.matches）统一口径：
    语法错误抛 ``{what} 正则无效``；嵌套量词等灾难性回溯形态硬拒
    （30-40 字符输入即可卡死引擎线程）；重叠交替类告警经模块 logger。
    """
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{what} 正则无效：{exc}") from exc
    hard, warnings = check_pattern(pattern)
    if hard is not None:
        raise ValueError(f"{what} 正则存在灾难性回溯风险（{hard}）——请改写为非嵌套量词形式")
    for w in warnings:
        _log.warning("%s 正则 %r 存在回溯风险：%s", what, pattern, w)


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
            # F-15 修复：变量断言不可混入响应断言字段。求值器按 is_var 分派只执行
            # 变量断言，混入的 contains/matches 等会静默丢失——校验器与求值器口径
            # 对齐，解析期拦截优于运行期静默吞掉用户意图。
            present = [
                k
                for k in ("contains", "not_contains", "matches", "equals")
                if getattr(self, k) is not None
            ]
            if present:
                raise ValueError(f"变量断言不可同时指定响应断言字段：{present}")
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
        # L5：contains/not_contains/matches 为空字符串时行为反直觉——contains:'' 恒真
        # （'' in anything 恒 True，断言静默通过且无意义）、not_contains:'' 恒失败、
        # matches:'' 恒命中；均给带字段定位的明确错误，而非让用户困惑于恒定结果。
        # equals='' 是合法语义（断言响应为空）。
        for field_name in ("contains", "not_contains", "matches"):
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

    file / inline / inline_hex 三选一：
      - file 读原始字节；
      - inline 渲染后按 UTF-8 编码发送；
      - inline_hex 渲染后按十六进制解析发送。
    渲染发生在引擎层（批 2b Task 6），模型只管声明。其余为分块参数。
    """

    file: str | None = None
    inline: str | None = None
    # 十六进制数据源（如 "00FF10"、"41 42"）：适合携带不可打印字节（二进制协议头等）
    inline_hex: str | None = None
    chunk_threshold: int = Field(gt=0, default=4096)
    chunk_size: int = Field(gt=0, default=1024)
    chunk_interval: int = Field(ge=0, default=50)
    append_terminator: bool = False

    @model_validator(mode="after")
    def _exactly_one_source(self) -> DataInput:
        # 三选一：file / inline / inline_hex 恰好一个非 None
        sources = [k for k in ("file", "inline", "inline_hex") if getattr(self, k) is not None]
        if len(sources) != 1:
            raise ValueError("data 字段需三选一指定 file、inline 或 inline_hex")
        # 空串拒绝：bytes.fromhex("") 会静默得到 0 字节数据，多为笔误
        if self.inline_hex == "":
            raise ValueError("inline_hex 不可为空字符串")
        # 十六进制合法性解析期预校验（bytes.fromhex 自带容忍 ASCII 空白，如 "41 42"）。
        # 含模板占位符（{{var}}，渲染在引擎层）时跳过——字面量含 "{" 必非合法
        # 十六进制，但渲染产物无法在解析期判定；渲染后的合法性由 step_runner 的
        # bytes.fromhex 复核（坏十六进制 → DataPathError 走 on_failure 决策），
        # 渲染出空串则被引擎零字节拒绝拦截。
        if self.inline_hex is not None and "{{" not in self.inline_hex:
            try:
                bytes.fromhex(self.inline_hex)
            except ValueError as exc:
                raise ValueError(f"inline_hex 不是合法十六进制串：{exc}") from exc
        # P3 修复：分块语义关系校验——chunk_size 大于 chunk_threshold 时
        # 「阈值内不分块、阈值上按 chunk_size 分块」的关系倒挂，多为笔误
        if self.chunk_size > self.chunk_threshold:
            raise ValueError(
                f"chunk_size（{self.chunk_size}）不能大于 chunk_threshold（{self.chunk_threshold}）"
            )
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

    内置变量 ``timestamp``（当前时间）/``port``（执行端口）每步注入步骤上下文，
    不可作 extract 变量名（提取结果会被每步注入覆盖，解析期拒绝）。
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
    # 本步骤每次发送前的固定延迟（ms）。引擎接线在批 2b Task 6（此前为死字段的修复）；
    # 场景见 ch06：AT+CIPSEND 收到 \r\n> 提示符后，延迟 50-100ms 再发数据。
    interval: int | None = Field(default=None, ge=0)
    port: str | None = None
    # 异步指令：OK 仅受理，须等待匹配此正则的 URC 上报才算真正终结。
    # 开启后串口层遇 OK 不返回，继续读到 URC 匹配立即返回（整段 text 含 OK+URC）。
    wait_urc: str | None = Field(default=None)
    # 附加完成条件正则（批 2b Task 1 新增）：如 TCPSEND 提示符 \r\n>——命中即视为本
    # 步骤完成。与 wait_urc 同属「自定义完成语义」，二者互斥；引擎接线在批 2b Task 6。
    expect: str | None = Field(default=None)

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
            _validate_regex(self.wait_urc, "wait_urc")
        # expect 与 wait_urc 互斥：均为「自定义完成语义」，叠加则完成判定歧义
        if self.expect is not None and self.wait_urc is not None:
            raise ValueError("expect 与 wait_urc 互斥，不可同时指定")
        # expect 正则合法性预校验（与 wait_urc 同款口径）
        if self.expect is not None:
            _validate_regex(self.expect, "expect")
        # P1 修复：extract 与 assert.matches 正则同样在解析期预校验（与 wait_urc
        # 口径一致）。旧实现这两个正则编译失败在执行期抛裸 re.error，逃出引擎
        # 线程（无 CaseParseError 包装、无文件行号，用户直面 traceback）。
        if self.extract is not None:
            for var_name, pattern in self.extract.items():
                # P3：内置变量每步注入（step_runner），extract 同名提取会被覆盖——解析期拒绝
                if var_name in ("timestamp", "port"):
                    raise ValueError(
                        f"extract 变量名 {var_name!r} 与内置保留字冲突（每步注入，会被覆盖）"
                    )
                _validate_regex(pattern, f"extract 变量 {var_name!r}")
        for a in self.assertions:
            if a.matches is not None:
                _validate_regex(a.matches, f"断言 {a.name or '(未命名)'} 的 matches")
        # data×retry / data×poll 组合不硬拒但告警：数据流不可重入（设计 §2.2）——
        # 设备收满声明长度后，重试/轮询重发的字节会被设备当 AT 命令解析、污染后续命令。
        # Step 无 name 字段，%s 以数据源声明值（file/inline/inline_hex）定位步骤。
        if self.data is not None and (self.retry is not None or self.poll is not None):
            src = self.data.file or self.data.inline or self.data.inline_hex or "?"
            _log.warning(
                "步骤 %s 含 data 输入与 retry/poll：数据流不可重入——设备收满声明长度后，"
                "重试/轮询重发的字节会被设备当 AT 命令解析、污染后续命令(设计 §2.2)",
                src,
            )
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
    # 注：port 当前为「解析但不影响执行端口」的字段（执行端口由 step.port 或
    # 引擎 default_port 决定）——保留用于用例元数据标注。
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

    @model_validator(mode="after")
    def _validate(self) -> Case:
        # P3 修复：纯空白字符串通过 min_length=1（"   "），与 quickcmd 侧口径统一
        if not self.name.strip():
            raise ValueError("name 不能为空白字符串")
        # F-12 修复：warmup>=count 时统计轮数为 0（全部轮次只预热不计入），
        # 压测报告必判 FAIL——这类配置只可能是笔误，解析期硬拒
        if self.loop is not None and self.loop.warmup >= self.loop.count:
            raise ValueError(
                f"压测 warmup（{self.loop.warmup}）须小于 count（{self.loop.count}）："
                f"否则统计轮数为 0，全 warmup 压测必判 FAIL"
            )
        # 批 3 终审⑧：case 级 parameters 键名与内置保留字（timestamp/port）冲突。
        # 两个保留字由 step_runner 每步注入步骤上下文（§0），parameters 注入的
        # 同名参数会被每步覆盖、静默失效——与 extract 保留字同款错误风格，
        # 解析期拒绝（extract 侧已有校验，此处补齐 case 级对称性）。
        for row in self.parameters:
            for key in row:
                if key in ("timestamp", "port"):
                    raise ValueError(
                        f"parameters 键名 {key!r} 与内置保留字冲突（每步注入，会被覆盖）"
                    )
        # 2b 终审⑨：data 步骤×压测不硬拒但按用例粒度告警（与 Step 级 data×retry/poll
        # 同族）——数据流不可重入，压测每轮重发的字节会被设备当 AT 命令解析、污染后续命令。
        if self.loop is not None and any(s.data is not None for s in self.steps):
            _log.warning(
                "用例 %s 含 data 步骤且配置压测：数据流不可重入——压测每轮重发的字节"
                "会被设备当 AT 命令解析、污染后续命令",
                self.name,
            )
        return self

    @property
    def is_pressure(self) -> bool:
        """是否压测用例（§2.3）."""
        return self.loop is not None
