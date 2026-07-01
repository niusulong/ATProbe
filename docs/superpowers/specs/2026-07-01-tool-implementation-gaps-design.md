# 工具功能实现状态对齐设计（implementation-status.md 11 项缺口）

> **本设计的目标**：对照 `docs/plan/implementation-status.md` 列出的 11 项缺口（5 项未实现功能 + 6 项文档/代码不符），
> 在 ATProbe 框架代码（`src/atprobe/`）中补齐实现或对齐文档，使工具从「未完善、未投入使用」推进到
> 「reference 文档描述的核心功能全部可用、文档与代码一致」。
>
> 权威需求来源：`docs/requirements/REQ-M2-测试用例定义.md`（§5.4 内置变量 / §10 参数化 / §12 套件 / §13 压测）。
> 代码现状来源：`src/atprobe/` 实际实现。技能 reference 文档（`.agents/skills/atprobe-case-author/references/`）
> 代表完整目标设计，本设计使其与代码对齐。

## 范围（11 项，已逐项拍板）

### A 类：真功能缺失（5 项，全做）

| 编号 | 缺口 | 拍板 |
|---|---|---|
| #1 | 内置变量 `{{timestamp}}`/`{{port}}`/`{{loop_index}}` 未实现 | 做（方案 A：注入变量池） |
| #2 | 参数化 `parameters` 矩阵展开未实现 | 做（方案 A：Case 带 param_index） |
| #3 | 报告 `#N` 后缀未实现（依赖 #2） | 随 #2 一起做 |
| #4 | 套件 `suite_setup`/`suite_teardown` 未实现 | 做（新建 domain/suite/） |
| #5 | suite cases 列表驱动执行未实现 | 做（显式 `run suite-xxx.yaml` 触发） |

### B 类：文档/代码不符（6 项，逐项）

| 编号 | 缺口 | 拍板 |
|---|---|---|
| #6 | teardown 的 retry 未拦截（代码允许） | 改文档为「允许」 |
| #7 | setup 的 when 会被求值（代码允许） | 改文档为「允许」 |
| #8 | on_failure 的 skip 与 continue 相同 | 收紧代码区分语义 |
| #9 | extract 失败空值无法区分未定义 | 代码保留 matched（方案 A：不写入池） |
| #10 | tags 仅并集不支持交集（文档说支持） | 改文档为「仅并集」 |
| #11 | name 唯一性不强制（文档说必须） | 改文档为「约定非强制」 |

---

## 总体架构

### 设计原则

1. **领域层纯净**（与现有 TSD §2.1/§2.2 一致）：`domain/case/` 和 `domain/report/` 保持纯数据/纯函数，无 I/O。
   新功能的**编排逻辑**放 `cli/` 或 `engine/`，**数据模型**才进 domain。
2. **最小侵入、复用现有扩展点**：所有缺口落在已标注的扩展点上。关键事实——`EngineConfig.cases` 注释
   已写「已展开参数化、应用标签过滤」（`engine/config.py:32`），参数化展开的契约位置早已存在，只是未实现。

### 11 项归属层划分

```
domain/case/models.py      ← #2 Case 加 param_index 字段（数据模型）
domain/case/extractor.py   ← （已返回 matched，无需改）
domain/suite/ (新建)        ← #4#5 Suite 模型 + 解析器（新模块）
domain/report/models.py    ← #3 CaseResult.case_name 装饰（数据模型）
engine/step_runner.py      ← #1 内置变量注入 / #8 skip 区分 / #9 matched 提交
engine/pressure.py         ← #1 loop_index 注入
engine/scheduler.py        ← #4 suite 前后置循环
engine/config.py           ← #4 EngineConfig 加 suite_setup/teardown 字段
cli/commands/run.py        ← #2 参数化展开 / #5 suite 解析与触发
```

### 实施顺序（3 批次，按依赖与风险递增）

每批可独立提交、独立测试。

- **批次 1**：低风险文档对齐（B 类 #6 #7 #10 #11，纯文档无代码风险）
- **批次 2**：小而独立的代码增强（A 类 #1 + B 类 #8 #9，改动局部）
- **批次 3**：大功能（A 类 #2#3 参数化 + #4#5 套件，跨多模块）

### 测试策略

- 每个缺口都有可注入的 FakeSender 测试路径（`Engine(sender_factory=...)` 已支持）。
- 批次 3 的参数化/套件用 `--vsim` 虚拟模组做端到端冒烟（run.py 已内置 vsim，无需真实硬件）。
- 遵循现有测试布局：`tests/unit/` 放领域层单测（models/parser/extractor），`tests/integration/` 放引擎/CLI 集成测试。

---

## 批次 1：文档对齐（B 类 #6 #7 #10 #11）

纯改文档，零代码风险。目标：reference 文档与代码真实行为一致。

### #6 #7：setup 允许 when / teardown 允许 retry

**现状**：`control-flow.md` 的修饰符支持矩阵（setup ❌ when / teardown ❌ retry）与代码不符。
代码实际：`step_runner.py:117` 守卫只拦 teardown 的 when（`not is_teardown and step.when is not None`），
故 setup 的 when 生效；retry 路径（`:151` `_run_retry`）无 is_teardown 守卫，teardown 的 retry 实际会重试。

**修法**：`references/control-flow.md` 修饰符矩阵改为代码真实行为：

| 修饰符 | setup | steps | teardown |
|---|---|---|---|
| `when` | ✅ | ✅ | ❌（仅 teardown 不支持） |
| `retry` | ✅ | ✅ | ✅ |
| `poll` | ❌ | ✅ | ❌ |
| `on_failure` | ❌（setup 失败一律跳过整个用例） | ✅ | ❌（teardown 失败仅记警告） |

配套修正矩阵下方文字说明：
- 「setup 不支持 when」→「setup 支持 when（条件不满足则跳过该 setup 步骤）」
- teardown 的 retry 补注：「teardown 失败仅记警告，retry 耗尽也不影响用例结果」

### #10：tags 仅并集

**现状**：`conventions.md:34` 写「支持多标签组合筛选（交集/并集）」，代码 `run.py:117` 只做并集（`any(...)`）。

**修法**：`references/conventions.md` 改为「多 `--tag` 取**并集**（命中任一即选中）；`--exclude-tag` 排除。
不支持交集。」删掉「交集」表述。

### #11：name 唯一性约定非强制

**现状**：`conventions.md:40-42` 写 name「必须唯一」，代码无运行时检查（仅 models.py:260 docstring 提及）。

**修法**：`references/conventions.md` 改为「name 在执行范围内**建议**唯一（报告以"文件名+name"双标识，
重名不报错但报告可能混淆）。**非强制**，无运行时检查。」

### implementation-status.md 同步

批次 1 完成后，`docs/plan/implementation-status.md` 移除 #6 #7 #10 #11 四项（已对齐）。

---

## 批次 2：小增强（A 类 #1 + B 类 #8 #9）

### #1 内置变量注入（`{{timestamp}}` / `{{port}}` / `{{loop_index}}`）

**目标语义**（REQ-M2 §5.4）：三个内置变量用于字符串模板，执行时自动可用。

**实现方案 A（推荐）：在步骤渲染前注入到 ctx.variables**

- `step_runner.execute_step` 在模板替换（`_render_input`，约 `:128`）**之前**，把内置变量写进 `ctx.variables`：
  - `{{timestamp}}` → `datetime.now().strftime("%Y-%m-%d %H:%M:%S")`（每次步骤调用时刷新）
  - `{{port}}` → 当前步骤的 `port`（`:110` 已算出）
  - `{{loop_index}}` → 仅压测场景有值；常规场景不注入（引用会报 `UndefinedReferenceError`，符合「压测场景专用」语义）
- 压测的 `loop_index`：`pressure.py:77` 循环开头 `ctx.variables["loop_index"] = rnd`
- 复用现有模板替换链路，不改 templater.py；变量池语义统一。

**为何不选方案 B（templater 内置解析层）**：templater 现为纯字符串替换无 I/O，注入 timestamp 需传入 clock，
破坏纯函数性（TSD §5.6）。

**改动点**：
- `engine/step_runner.py`：`execute_step` 开头注入 timestamp/port（loop_index 由 pressure 注入）；import datetime
- `engine/pressure.py`：循环开头（`:77` `for rnd in range(...)`）注入 `ctx.variables["loop_index"] = rnd`

**边界**：内置变量会被 extract 同名覆盖（罕见，可接受；REQ-M2 §5.3「同名后赋值覆盖」本就适用所有变量）。

**测试点**：
- FakeSender 用例，command 含 `{{timestamp}}`/`{{port}}`，断言 `StepResult.request` 含替换后的值
- 压测用例含 `{{loop_index}}`，断言不同轮 request 不同（用 vsim 或 FakeSender）

### #8 skip vs continue 区分语义

**目标语义**（REQ-M2 §3.4 + control-flow.md）：
- `abort`：中止整个用例
- `skip`：跳过**当前步骤**（不标记失败），继续后续
- `continue`：标记当前步骤**失败**，继续后续

**现状**：`step_runner.py:188-189` 只判断 `strategy is ABORT`，非 ABORT 一律 `abort_case=False`（继续），
skip 和 continue 行为完全相同（都继续，都记 FAIL）。

**实现**：区分的关键在**步骤状态标记**，不在是否继续。当前 `step_runner.py` 流程：
`:166` 算出 `status`（PASS/FAIL）→ `:175` 用该 status 构建 `StepResult` → `:186-189` 才算 `abort_case`。
要在 skip 时让 StepResult 记 SKIPPED，**status 的计算必须前移到构建 StepResult（`:175`）之前**，
且与 abort_case 一起判定。改为（替换 `:166` 一行 + `:186-189` 整块）：

```python
# 替换 :166 原行，status 与 abort_case 在此一并算出（在构建 sr 之前）
strategy: FailureStrategy | None = None
if not attempt.step_passed:
    strategy = step.on_failure or case_on_failure or FailureStrategy.ABORT

if not attempt.step_passed and strategy is FailureStrategy.SKIP:
    status = StepStatus.SKIPPED          # skip：步骤记 SKIPPED（不算失败）
else:
    status = StepStatus.PASS if attempt.step_passed else StepStatus.FAIL

# sr 构建用上面的 status（:175 处不变，status 变量已是最终值）
sr = StepResult(... status=status, ...)

# on_failure（替换 :186-189）
abort_case = (
    not is_teardown
    and status is StepStatus.FAIL
    and strategy is FailureStrategy.ABORT
)
```

效果：
- skip：status=SKIPPED，abort_case=False（继续后续，且该步不进 FAIL 统计）
- continue：status=FAIL，abort_case=False（继续后续，该步记失败）
- abort：status=FAIL，abort_case=True（中止用例）

**影响面**：`scheduler.py:286` `any_fail = any(s.status is StepStatus.FAIL ...)` —— skip 步骤不进 FAIL 统计，
用例可能 PASS（符合 skip 语义：被跳过的步骤失败不算数）。这是期望行为。

**改动点**：仅 `engine/step_runner.py` 一处分支逻辑。

**测试点**：3 个用例分别用 skip/continue/abort（步骤故意失败），断言：
- skip：失败步骤状态 SKIPPED，后续步骤执行，用例可 PASS
- continue：失败步骤状态 FAIL，后续步骤执行，用例 FAIL
- abort：失败步骤状态 FAIL，后续步骤不执行，用例 FAIL

### #9 保留 matched 标志（`is null` 可区分空值 vs 未定义）

**目标语义**（REQ-M2 §5.1 + variables.md）：extract 失败的变量「已提取但空值，区别于未定义」，
使 `is null` 能区分。

**现状**：`extractor.py` 已返回 `matched` 标志（`ExtractionResult.matched`，`:31-32`），
但 `step_runner.py:307` `values, _matched = extract_all(...)` 丢弃了它，只把 `""` 写入池。
evaluator 的 `is null` 检查 `v is None`（evaluator.py:153）：
- 未定义变量 → `scope.get(raw, None)` → None → `is null` 为 True
- 提取失败变量 → `""` → 非 None → `is null` 为 False

**问题**：提取失败的变量是 `""`，无法用 `is null` 判定为「没提到」，语义模糊。

**实现方案 A（推荐）：提取失败的变量不写入池（保持未定义）**

`step_runner.py` 两处需同步（`_single_attempt` 保留 matched，提交处只写 matched=True 的）：

1. `_single_attempt`（`:283`）增加 `matched: dict[str, bool]` 字段，从 `extract_all` 取第二个返回值
2. 提交到变量池处（`:162-164`），只提交 matched=True 的：

```python
for k, v in attempt.extracted.items():
    if attempt.matched.get(k, True):   # 仅提交匹配成功的变量
        ctx.variables[k] = v
```

**效果**：提取失败 = 未定义 = `is null` 为 True。evaluator/assessor 零改动（未定义变量本就走 None 路径，
assessor 对未定义变量报「变量未定义」，evaluator `is null` 返回 True）。

**为何不选方案 B（写哨兵值 None）/ 方案 C（CaseContext 加 matched 字典）**：
- 方案 B：None 与「未定义」在 `scope.get(raw, None)` 下无法区分，且需改 assessor 对 None 的处理
- 方案 C：改动面大（assessor/evaluator 签名都要带 matched），破坏纯函数

方案 A 最干净，满足文档承诺的 `is null` 区分能力（提取失败可用 `is null` 判定为 True）。

**语义说明**：方案 A 实际是「提取失败 = 未定义」，比文档原文「已提取但空值，区别于未定义」略简化。
但文档承诺的核心能力（`is null` 能识别「没提到」）被完整满足，且实现最简洁。reference 文档
`variables.md` 相应表述改为：「提取失败（正则无匹配）→ 变量**不写入变量池**（等同于未定义），
`is null` 判定为 True。」

**改动点**：
- `engine/step_runner.py`：`_SingleAttempt` 加 `matched` 字段；`_single_attempt` 填充；提交处按 matched 过滤
- `.agents/skills/atprobe-case-author/references/variables.md`：「提取失败」表述对齐
- `docs/plan/implementation-status.md`：移除 #9 项

**测试点**：
- extract 正则不匹配 → 变量未定义 → `when: 'x is null'` 求值为 True（步骤执行）
- extract 正则不匹配 → 断言 `var: x, op: eq, value: "0"` → 报「变量 x 未定义」（assessor 现有行为）
- extract 正则匹配 → 变量有值 → `is null` 为 False

---

## 批次 3：大功能（A 类 #2#3 参数化 + #4#5 套件）

### 功能块一：参数化展开（#2）+ 报告 #N 后缀（#3）

#### 数据模型

`Case.parameters` 字段已存在（`models.py:270`）。**新增**一个可选字段标记展开实例序号：

`domain/case/models.py` 的 `Case` 加：
```python
param_index: int | None = None   # 参数化展开实例序号（1-based），非参数化用例为 None
```

不新增模型——参数化是「载入时展开」的编排逻辑，属 CLI 层。

#### 展开逻辑（cli/commands/run.py）

在 `run.py:105-111` 载入 cases 后、tag 过滤（`:114`）前，加展开步骤：

```python
cases: list[Case] = []
for cp in case_paths:
    case = parse_case_file(cp)
    if case.parameters:
        cases.extend(_expand_parameters(case))
    else:
        cases.append(case)
```

新增 `_expand_parameters(case: Case) -> list[Case]`：
- 对 `case.parameters` 每一行（参数字典），生成一个 Case 实例：
  `case.model_copy(update={"parameters": (row,), "param_index": idx})`
- 即每个实例的 `parameters` 缩为单行，并带 `param_index` 序号（1-based）
- 返回实例列表

#### 参数注入（engine/scheduler.py）

`scheduler._run_case`（`:186` 附近，现注释「由上层展开」）改为实际注入：

```python
# 参数化注入（M2 §10.2）：参数行注入用例级变量作用域（最高优先级）
if case.parameters:
    for k, v in case.parameters[0].items():
        ctx.variables[k] = v
```

注入在 `_run_case` 最开头（setup 前），保证 setup/steps/teardown 全程可见（REQ-M2 §10.2）。
extract 同名覆盖天然支持（后赋值覆盖，§5.3）。

#### 报告 #N 后缀（#3）

`domain/report/models.py:117` `CaseResult.case_name` 现直接取 `case.name`。
`scheduler._build_case_result`（`:392`）构造 CaseResult 时，按 `param_index` 装饰 name：

```python
display_name = case.name
if case.param_index is not None:
    display_name = f"{case.name}#{case.param_index}"
return CaseResult(case_name=display_name, ...)
```

报告/日志自然区分 `PDP激活-多APN#1` / `#2` / `#3`（REQ-M2 §10.2「name 加后缀 #1/#2」）。

#### 向后兼容

- 无 `parameters` 的用例：行为完全不变（`param_index=None`，name 不装饰）
- 有 `parameters` 的用例：从「被忽略」变为「展开执行」（这正是修复目标）

#### 测试点

- 单测 `_expand_parameters`：3 行参数 → 3 个 Case 实例，各带正确 param_index 和单行 parameters
- 集成测试：参数化用例经 run.py 载入 → scheduler 执行 → 报告含 `#1/#2/#3` 三个实例
- vsim 端到端：参数化用例（如多 APN）实际跑通

### 功能块二：套件（#4 suite_setup/teardown + #5 cases 列表驱动）

#### 新建模块 domain/suite/

```
src/atprobe/domain/suite/
├── __init__.py
├── models.py      # Suite 数据模型
└── parser.py      # suite YAML 解析器
```

**Suite 模型**（`domain/suite/models.py`）：

```python
from atprobe.domain.case.models import _Frozen, Step

class Suite(_Frozen):
    """用例套件（REQ-M2 §12）。用例集合的索引文件，通过路径引用用例。"""
    name: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    suite_setup: tuple[Step, ...] = ()
    suite_teardown: tuple[Step, ...] = ()
    cases: tuple[str, ...] = ()        # 用例文件相对路径（相对 suite 文件所在目录）
    source_file: str | None = None     # 由 parser 填充
```

复用 `case.Step`（setup/teardown 步骤结构一致），保持模型不重复定义。`extra="forbid"`（继承 `_Frozen`）。

**Suite 解析器**（`domain/suite/parser.py`）：仿 `case/parser.py`，
用 ruamel safe load + pydantic 校验，失败抛 `SuiteParseError`（携带 source 与原因）。

#### 套件触发方式（cli/commands/run.py）

**方案 A（推荐）：新增显式 `run suite-xxx.yaml` 触发 + 保留目录扫描**

- `run suite-TCP.yaml`（显式套件文件）→ 解析 suite，按 cases 列表执行 + suite_setup/teardown
- `run <目录>`（目录）→ 维持现状（跑目录所有用例，跳过 suite 文件）
- `run <普通用例.yaml>`（单用例文件）→ 维持现状

**为何不选方案 B（目录扫描时隐式读 suite cases 列表）**：会改变现有 `run <目录>` 语义
（从「跑全部」变「按 suite 列表跑」），破坏向后兼容。方案 A 让 suite 成为可选的显式组织手段。

**run.py 改动**：
- `_resolve_case_paths`（`:231`）：识别 path 是 `suite-*.yaml` 文件时，不走目录扫描，标记为套件
- 新增套件执行编排：解析 suite → 按 cases 相对路径载入用例 → 构造 EngineConfig（带 suite_setup/teardown）→ engine.start
- suite 的 cases 相对路径相对 **suite 文件所在目录**解析

#### 引擎层套件支持（engine/config.py + engine/scheduler.py）

**方式 1（推荐）：EngineConfig 加 suite_setup/teardown 字段，scheduler.start 在 cases 循环前后执行**

`engine/config.py` 的 `EngineConfig` 加：
```python
suite_setup: tuple[Step, ...] = ()       # 套件级前置（cases 循环前执行一次）
suite_teardown: tuple[Step, ...] = ()    # 套件级后置（cases 循环后执行一次）
```

`scheduler.start`（`:126` cases 循环前）执行 suite_setup（phase="suite_setup"，
复用 `execute_step`，`is_teardown=False`）；cases 循环后（`:154` finally 前）执行 suite_teardown
（phase="suite_teardown"，`is_teardown=True` 即不响应取消、失败仅记警告）。

执行顺序（REQ-M2 §12.2）：
```
suite_setup → [用例setup → 用例steps → 用例teardown]×N → suite_teardown
```

**为何不选方式 2（scheduler 内部识别 suite 完整套件循环）**：引擎职责膨胀。
方式 1 让引擎保持「执行用例列表 + 可选前后置」的单一职责，套件编排在 CLI。

#### 套件内标签筛选

REQ-M2 §12.2「支持按标签筛选执行套件中的部分用例」。run.py 载入 suite cases 后，
应用现有 `--tag`/`--exclude-tag` 过滤（复用 `:114-119` 逻辑），过滤后传给 EngineConfig。

#### 向后兼容

- `run <目录>` 行为不变（目录扫描，跳过 suite 文件）
- `run suite-TCP.yaml` 新行为（按 cases 列表 + 前后置）
- 现有 `list suites` 子命令（`list.py:64`）已能列出 suite 元信息，无需改

#### 测试点

- 单测 `Suite` 模型校验 + `parse_suite` 解析（合法/非法 YAML）
- 单测 `parse_suite_file`：suite_setup/teardown 用 Step 校验
- 集成测试：`run suite-xxx.yaml` → suite_setup 执行 → 各 case 执行 → suite_teardown 执行
- 集成测试：suite cases 列表 + `--tag` 筛选只跑部分
- vsim 端到端：套件实际跑通

---

## implementation-status.md 最终状态

全部 11 项完成后，`docs/plan/implementation-status.md` 内容清空（或改为「全部已对齐」说明）。
该文档定位为「工具开发参考」，随实现进度逐步缩减，最终可归档或删除。

---

## 不在本设计范围（明确排除）

- **技能文档（atprobe-case-author）的 5 个 gap**（混合标题提取规则 / 端到端范例 / 提问范式 / 未实现功能护栏 / 旧用例迁移）：
  这些是技能层面，待工具功能补齐后再做（依赖本设计的成果）。
- **框架其他未涉及 REQ-M2 章节**（如 M4 报告增强、M7 环境配置扩展）：不在 implementation-status.md 11 项内。
- **旧用例迁移**（`examples/testcases/{tcp,ntp}/*.yaml` 改新命名）：列为后续工作，不在本设计。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| #2 参数化展开改变 cases 列表长度，可能影响 GUI 进度条 total_cases | scheduler 的 CaseStartEvent.total_cases 用 len(config.cases)（已含展开后），自然正确 |
| #8 skip 改步骤状态为 SKIPPED，可能影响现有用例的 any_fail 判定 | 现有用例极少用 skip（grep 确认）；改动是修正语义，符合文档 |
| #9 提取失败不写入池，可能影响依赖「空字符串」的现有用例 | 现有用例 extract 正则都匹配成功（有响应才有意义）；不匹配的边界本就是异常 |
| #4#5 套件新建模块，增加代码量 | 模块小（Suite 模型 + parser < 100 行），复用 Step，独立可测 |
| 批次 3 跨多模块，回归风险 | 分两个功能块独立提交（参数化先，套件后），每块独立测试 + vsim 冒烟 |
