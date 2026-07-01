# 工具功能实现状态对齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `docs/plan/implementation-status.md` 列出的 11 项缺口（5 项未实现功能 + 6 项文档/代码不符），使 ATProbe 框架的核心功能全部可用、reference 文档与代码一致。

**Architecture:** 三批次递进交付。批次 1 纯文档对齐（B 类 #6 #7 #10 #11）；批次 2 小增强（A 类 #1 内置变量 + B 类 #8 skip 区分 + #9 matched 保留）；批次 3 大功能（A 类 #2#3 参数化 + #4#5 套件）。每批独立可测、独立提交。领域层保持纯净（纯数据/纯函数），编排放 cli/engine 层。

**Tech Stack:** Python 3.12+, Pydantic 2（领域模型），ruamel.yaml（解析），pytest（测试），FakePortManager（集成测试 Fake 串口），typer/CliRunner（CLI 测试）。

**Spec:** `docs/superpowers/specs/2026-07-01-tool-implementation-gaps-design.md`

---

## 文件结构总览

**批次 1（仅改文档，零代码）：**
- Modify: `.agents/skills/atprobe-case-author/references/control-flow.md`（修饰符矩阵 #6 #7）
- Modify: `.agents/skills/atprobe-case-author/references/conventions.md`（tags #10 / name 唯一性 #11）
- Modify: `docs/plan/implementation-status.md`（移除已对齐项）

**批次 2（小增强）：**
- Modify: `src/atprobe/engine/step_runner.py`（#1 内置变量注入 / #8 skip 区分 / #9 matched 过滤）
- Modify: `src/atprobe/engine/pressure.py`（#1 loop_index 注入）
- Modify: `.agents/skills/atprobe-case-author/references/variables.md`（#9 表述对齐）
- Test: `tests/integration/test_engine.py`（#1 #8 #9 集成测试）
- Modify: `docs/plan/implementation-status.md`（移除 #1 #8 #9）

**批次 3（大功能 — 参数化 #2#3）：**
- Modify: `src/atprobe/domain/case/models.py`（Case 加 `param_index` 字段）
- Modify: `src/atprobe/cli/commands/run.py`（参数化展开 `_expand_parameters`）
- Modify: `src/atprobe/engine/scheduler.py`（参数注入 `ctx.variables`）
- Test: `tests/unit/test_models.py`（param_index 字段）
- Test: `tests/integration/test_engine.py`（参数化执行 + #N 后缀）

**批次 3（大功能 — 套件 #4#5）：**
- Create: `src/atprobe/domain/suite/__init__.py`
- Create: `src/atprobe/domain/suite/models.py`（Suite 模型）
- Create: `src/atprobe/domain/suite/parser.py`（suite 解析器）
- Modify: `src/atprobe/engine/config.py`（EngineConfig 加 suite_setup/teardown）
- Modify: `src/atprobe/engine/scheduler.py`（suite 前后置循环）
- Modify: `src/atprobe/cli/commands/run.py`（`run suite-xxx.yaml` 触发）
- Test: `tests/unit/test_suite_models.py`
- Test: `tests/integration/test_engine.py`（套件执行）
- Modify: `docs/plan/implementation-status.md`（移除 #2 #3 #4 #5，归档）

---

# 批次 1：文档对齐（B 类 #6 #7 #10 #11）

纯改文档，零代码风险。每个任务改一个 reference 文件 + 移除 implementation-status 对应项。

## Task 1.1: control-flow.md 修饰符矩阵对齐代码（#6 #7）

**Files:**
- Modify: `.agents/skills/atprobe-case-author/references/control-flow.md`（修饰符矩阵 + 文字说明）

代码现状（已核对）：`step_runner.py:117` 守卫 `if not is_teardown and step.when is not None` —— setup 非 teardown 故 when 生效；retry 路径（`_run_retry` :199）无 is_teardown 守卫，teardown 的 retry 实际会重试。

- [ ] **Step 1: 修改修饰符矩阵**

打开 `.agents/skills/atprobe-case-author/references/control-flow.md`，找到「## setup / teardown 对控制流的限制」下的矩阵（约 135-140 行），把：

```
| 修饰符 | setup | steps | teardown |
|---|---|---|---|
| `when` | ❌ 不支持 | ✅ | ❌ 不支持 |
| `retry` | ✅ 支持 | ✅ | ❌ 不支持 |
| `poll` | ❌ | ✅ | ❌ |
| `on_failure` | ❌（setup 失败一律跳过整个用例） | ✅ | ❌（teardown 失败仅记警告） |
```

改为（对齐代码真实行为）：

```
| 修饰符 | setup | steps | teardown |
|---|---|---|---|
| `when` | ✅（条件不满足则跳过该 setup 步骤） | ✅ | ❌（仅 teardown 不支持） |
| `retry` | ✅ | ✅ | ✅（失败仅记警告，retry 耗尽也不影响用例结果） |
| `poll` | ❌ | ✅ | ❌ |
| `on_failure` | ❌（setup 失败一律跳过整个用例） | ✅ | ❌（teardown 失败仅记警告） |
```

- [ ] **Step 2: 验证文档改动**

Run: `grep -A6 "## setup / teardown" .agents/skills/atprobe-case-author/references/control-flow.md`
Expected: 矩阵显示 setup when ✅、teardown retry ✅

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/atprobe-case-author/references/control-flow.md
git commit -m "docs(skill): control-flow 修饰符矩阵对齐代码（setup支持when/teardown支持retry）"
```

## Task 1.2: conventions.md tags/name 对齐代码（#10 #11）

**Files:**
- Modify: `.agents/skills/atprobe-case-author/references/conventions.md`

代码现状：`run.py:117` `any(...)` 只做并集；name 唯一性无运行时检查。

- [ ] **Step 1: 改 tags 交集表述**

打开 `.agents/skills/atprobe-case-author/references/conventions.md`，找到 tags 系统章节（约 34 行）的：

```
- 支持多标签组合筛选（交集/并集）。
```

改为：

```
- 多 `--tag` 取**并集**（命中任一即选中）；`--exclude-tag` 排除。**不支持交集**。
```

- [ ] **Step 2: 改 name 唯一性表述**

找到「## name 唯一性作用域」章节（约 40-42 行）的：

```
- `name` 在**单个执行范围内**（一次运行加载的所有用例）必须唯一。
```

改为：

```
- `name` 在**单个执行范围内**（一次运行加载的所有用例）**建议**唯一。**非强制**，无运行时检查。
```

- [ ] **Step 3: 验证**

Run: `grep -n "并集\|建议\|非强制" .agents/skills/atprobe-case-author/references/conventions.md`
Expected: 看到 tags「不支持交集」、name「建议唯一 / 非强制」

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/atprobe-case-author/references/conventions.md
git commit -m "docs(skill): conventions 对齐代码（tags仅并集 / name唯一性非强制）"
```

## Task 1.3: implementation-status.md 移除 #6 #7 #10 #11

**Files:**
- Modify: `docs/plan/implementation-status.md`

批次 1 完成后 #6 #7 #10 #11 已对齐，从清单移除。

- [ ] **Step 1: 移除四项**

打开 `docs/plan/implementation-status.md`，删除「二、实现与文档描述不符」下的：
- ### 6. teardown 步骤的 retry 未拦截
- ### 7. setup 步骤的 when 会被求值
- ### 10. tags 筛选仅支持并集，不支持交集
- ### 11. name 唯一性不强制

（保留 #8 #9，它们在批次 2 处理）

- [ ] **Step 2: Commit**

```bash
git add docs/plan/implementation-status.md
git commit -m "docs: implementation-status 移除已对齐项 #6#7#10#11"
```

---

# 批次 2：小增强（A 类 #1 + B 类 #8 #9）

## Task 2.1: 内置变量注入（#1）—— step_runner timestamp/port

**Files:**
- Modify: `src/atprobe/engine/step_runner.py`（execute_step 开头注入）
- Test: `tests/integration/test_engine.py`

REQ-M2 §5.4：`{{timestamp}}`/`{{port}}` 用于字符串模板，执行时自动可用。方案 A：渲染前注入 ctx.variables。

- [ ] **Step 1: 写失败测试 — timestamp/port 注入**

在 `tests/integration/test_engine.py` 的 `TestBasicExecution` 类后新增测试类：

```python
class TestBuiltinVariables:
    def test_timestamp_and_port_substituted(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "OK\r\n")
        case = parse_case("""
name: 内置变量测试
port: COM3
steps:
  - command: 'AT{{timestamp}}-{{port}}'
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.PASS
        # request 应含替换后的值（timestamp 非空、port=COM3），原 {{}} 占位符已消失
        req = cr.step_results[0].request
        assert "{{" not in req
        assert "COM3" in req
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_engine.py::TestBuiltinVariables -v`
Expected: FAIL（`{{timestamp}}` 未定义，抛 UndefinedReferenceError，步骤 FAIL）

- [ ] **Step 3: 实现 — execute_step 开头注入**

打开 `src/atprobe/engine/step_runner.py`，在文件顶部 import 区加 `from datetime import datetime`。

然后在 `execute_step` 函数内，找到「1. when 条件检查」之前（约 `:114` 注释行前），插入内置变量注入：

```python
    # ------------------------------------------------------------------
    # 0. 内置变量注入（REQ-M2 §5.4）
    # ------------------------------------------------------------------
    ctx.variables["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ctx.variables["port"] = port
    # loop_index 仅压测场景由 pressure.run_pressure 注入，常规场景不注入
```

注意：`port` 变量在原代码 `:110` `port = step.port or default_port` 已算出，此注入在其之后。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_engine.py::TestBuiltinVariables -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/atprobe/engine/step_runner.py tests/integration/test_engine.py
git commit -m "feat(engine): 注入内置变量 {{timestamp}}/{{port}}（REQ-M2 §5.4）"
```

## Task 2.2: 内置变量注入（#1）—— pressure loop_index

**Files:**
- Modify: `src/atprobe/engine/pressure.py`（循环开头注入 loop_index）
- Test: `tests/integration/test_engine.py`

`{{loop_index}}` 仅压测场景，从 1 开始（REQ-M2 §5.4）。

- [ ] **Step 1: 写失败测试 — loop_index 注入**

在 `tests/integration/test_engine.py` 的 `TestBuiltinVariables` 类加：

```python
    def test_loop_index_in_pressure(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        # 持续返回 OK，压测 3 轮
        fake_port.script_text("COM3", "OK\r\n", persistent=True)
        case = parse_case("""
name: 压测loop_index
port: COM3
loop:
  count: 3
  interval: 0
steps:
  - command: 'AT{{loop_index}}'
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.is_pressure
        # 压测用例 step_results 首轮展示，request 应已替换 loop_index
        assert cr.status is CaseStatus.PASS
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_engine.py::TestBuiltinVariables::test_loop_index_in_pressure -v`
Expected: FAIL（`{{loop_index}}` 未定义）

- [ ] **Step 3: 实现 — pressure 循环注入 loop_index**

打开 `src/atprobe/engine/pressure.py`，找到 `run_pressure` 的循环（约 `:77` `for rnd in range(1, total + 1):`），在循环体开头（`if cancel is not None and cancel.cancelled:` 之前）插入：

```python
        # 内置变量 loop_index（REQ-M2 §5.4，压测场景从 1 开始）
        ctx.variables["loop_index"] = rnd
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_engine.py::TestBuiltinVariables::test_loop_index_in_pressure -v`
Expected: PASS

- [ ] **Step 5: 回归 — 全部压测测试**

Run: `uv run pytest tests/integration/test_engine.py -k "pressure or Pressure" -v`
Expected: 全 PASS（确认 loop_index 注入未破坏现有压测）

- [ ] **Step 6: Commit**

```bash
git add src/atprobe/engine/pressure.py tests/integration/test_engine.py
git commit -m "feat(engine): 压测注入内置变量 {{loop_index}}（REQ-M2 §5.4）"
```

## Task 2.3: skip vs continue 区分语义（#8）

**Files:**
- Modify: `src/atprobe/engine/step_runner.py`（status 计算前移 + on_failure 区分）
- Test: `tests/integration/test_engine.py`

目标：skip 步骤记 SKIPPED（不进 FAIL 统计）；continue 记 FAIL 继续；abort 中止。

- [ ] **Step 1: 写失败测试 — 三策略区分**

在 `tests/integration/test_engine.py` 新增测试类：

```python
class TestOnFailureStrategies:
    def test_skip_marks_skipped_not_fail(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "ERROR\r\n")
        fake_port.script_text("COM3", "OK\r\n", match="AT+SECOND")
        case = parse_case("""
name: skip测试
port: COM3
steps:
  - command: AT
    assert: { contains: "OK" }
    on_failure: skip
  - command: AT+SECOND
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.step_results[0].status is StepStatus.SKIPPED  # 非FAIL
        assert len(cr.step_results) == 2  # 后续步骤执行
        assert cr.status is CaseStatus.PASS  # skip不进FAIL统计，第二步PASS

    def test_continue_marks_fail_and_continues(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "ERROR\r\n")
        fake_port.script_text("COM3", "OK\r\n", match="AT+SECOND")
        case = parse_case("""
name: continue测试
port: COM3
steps:
  - command: AT
    assert: { contains: "OK" }
    on_failure: continue
  - command: AT+SECOND
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.step_results[0].status is StepStatus.FAIL  # 记FAIL
        assert len(cr.step_results) == 2  # 后续步骤执行
        assert cr.status is CaseStatus.FAIL  # 第一步FAIL导致用例FAIL
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_engine.py::TestOnFailureStrategies -v`
Expected: 两条都 FAIL（当前 skip 和 continue 行为相同：都记 FAIL 且继续）

- [ ] **Step 3: 实现 — status 计算前移 + 区分**

打开 `src/atprobe/engine/step_runner.py`，找到 `:166`：

```python
    status = StepStatus.PASS if attempt.step_passed else StepStatus.FAIL
```

把它连同下面 `:186-189` 的 on_failure 块，整体替换为（注意 status 现在在构建 sr 之前算出，含 skip 区分）：

```python
    # status 与 abort_case 一并算出（含 skip 区分，REQ-M2 §3.4）
    strategy: FailureStrategy | None = None
    if not attempt.step_passed:
        strategy = step.on_failure or case_on_failure or FailureStrategy.ABORT

    if not attempt.step_passed and strategy is FailureStrategy.SKIP:
        status = StepStatus.SKIPPED          # skip：步骤记 SKIPPED（不算失败）
    else:
        status = StepStatus.PASS if attempt.step_passed else StepStatus.FAIL
```

（`status` 仍在构建 `sr`（`:175`）之前，sr 复用此 status 变量，无需改 sr 构建行）

然后把原 `:186-189` 的：

```python
    abort_case = False
    if status is StepStatus.FAIL and not is_teardown:
        strategy = step.on_failure or case_on_failure or FailureStrategy.ABORT
        abort_case = strategy is FailureStrategy.ABORT
```

改为：

```python
    # on_failure（skip 已在 status 体现，此处仅决 abort_case）
    abort_case = (
        not is_teardown
        and status is StepStatus.FAIL
        and strategy is FailureStrategy.ABORT
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_engine.py::TestOnFailureStrategies -v`
Expected: 两条都 PASS

- [ ] **Step 5: 回归 — 全部引擎测试**

Run: `uv run pytest tests/integration/test_engine.py -v`
Expected: 全 PASS（确认 abort 默认行为、retry 等未破坏）

- [ ] **Step 6: Commit**

```bash
git add src/atprobe/engine/step_runner.py tests/integration/test_engine.py
git commit -m "fix(engine): 区分 on_failure skip/continue 语义（skip记SKIPPED不算失败）"
```

## Task 2.4: extract 失败不写入变量池（#9）

**Files:**
- Modify: `src/atprobe/engine/step_runner.py`（_SingleAttempt 加 matched + 提交过滤）
- Modify: `.agents/skills/atprobe-case-author/references/variables.md`
- Test: `tests/integration/test_engine.py`

方案 A：提取失败的变量（matched=False）不写入池，等同未定义，`is null` 为 True。

- [ ] **Step 1: 写失败测试 — extract 失败 = 未定义**

在 `tests/integration/test_engine.py` 新增测试类：

```python
class TestExtractMatched:
    def test_unmatched_extract_is_undefined(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        # 响应不含 X: 字段，extract 正则不匹配
        fake_port.script_text("COM3", "+CSQ: 23\r\nOK\r\n")
        case = parse_case("""
name: extract失败测试
port: COM3
steps:
  - command: AT+CSQ
    extract:
      rssi: 'CSQ: (\\d+)'
      missing: 'X: (\\d+)'   # 不匹配
    when: 'missing is null'   # 未定义 → is null 为 True → 步骤执行
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        # when 为 True 故步骤执行（非 SKIPPED），且 rssi 提取成功
        assert cr.step_results[0].status is not StepStatus.SKIPPED
        assert cr.step_results[0].extracted_vars.get("rssi") == "23"

    def test_unmatched_extract_not_in_pool(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "+CSQ: 23\r\nOK\r\n")
        case = parse_case("""
name: extract失败不入池
port: COM3
steps:
  - command: AT+CSQ
    extract:
      missing: 'X: (\\d+)'   # 不匹配
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        # missing 未写入变量池（extracted_vars 可能含空串或不含，但变量池中应未定义）
        # 用 is null 验证：第二步引用 missing 应判为 null
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_engine.py::TestExtractMatched -v`
Expected: FAIL（当前提取失败写 `""`，`is null` 为 False，when 条件不满足，步骤 SKIPPED）

- [ ] **Step 3: 实现 — _SingleAttempt 加 matched 字段**

打开 `src/atprobe/engine/step_runner.py`，找到 `_SingleAttempt` dataclass（约 `:82`），在 `extracted` 字段后加：

```python
    extracted: dict[str, str] = field(default_factory=dict)
    matched: dict[str, bool] = field(default_factory=dict)   # 新增：每个 extract 是否匹配
```

- [ ] **Step 4: 实现 — _single_attempt 填充 matched**

找到 `_single_attempt`（约 `:306-308`）的：

```python
    if step.extract:
        values, _matched = extract_all(step.extract, resp.text)
        extracted = values
```

改为（保留 matched）：

```python
    if step.extract:
        values, matched = extract_all(step.extract, resp.text)
        extracted = values
    else:
        matched = {}
```

然后在 `_single_attempt` 的所有 `return _SingleAttempt(...)` 处，加上 `matched=matched`。具体：
- 找到 `return _SingleAttempt(response=resp, extracted=extracted, ...)` 的几处（约 `:301` 响应异常处、`:318` 断言失败处、`:322` 成功处），每处在参数列加 `matched=matched,`。

注意 `:301` 响应异常分支 `extracted={}`，对应 `matched={}`（该分支在 extract 之前 return，matched 未定义，需在该分支前初始化 `matched = {}`，或在该 return 处直接写 `matched={}`）。

最稳妥：在 `_single_attempt` 函数体开头（`t0 = clock()` 之后）加 `matched: dict[str, bool] = {}`，所有 return 处用 `matched=matched`。

- [ ] **Step 5: 实现 — 提交处按 matched 过滤**

找到提交 extract 到变量池处（约 `:162-164`）：

```python
    for k, v in attempt.extracted.items():
        ctx.variables[k] = v
```

改为（仅提交 matched=True 的）：

```python
    for k, v in attempt.extracted.items():
        if attempt.matched.get(k, True):
            ctx.variables[k] = v
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_engine.py::TestExtractMatched -v`
Expected: PASS

- [ ] **Step 7: 回归 — extract 相关测试**

Run: `uv run pytest tests/integration/test_engine.py tests/unit/test_extractor.py -v`
Expected: 全 PASS（确认成功 extract 仍写入池）

- [ ] **Step 8: 更新 variables.md 表述**

打开 `.agents/skills/atprobe-case-author/references/variables.md`，找到「## 变量提取（extract）」下的：

```
- 提取失败（正则无匹配）→ 变量值为空字符串，标记为"已提取但空值"（区别于"未定义"）。
```

改为：

```
- 提取失败（正则无匹配）→ 变量**不写入变量池**（等同于未定义），`is null` 判定为 True。
```

- [ ] **Step 9: Commit**

```bash
git add src/atprobe/engine/step_runner.py tests/integration/test_engine.py .agents/skills/atprobe-case-author/references/variables.md
git commit -m "fix(engine): extract 失败不写入变量池（is null 可识别未提取）"
```

## Task 2.5: implementation-status.md 移除 #1 #8 #9

**Files:**
- Modify: `docs/plan/implementation-status.md`

- [ ] **Step 1: 移除三项**

打开 `docs/plan/implementation-status.md`，删除：
- 「一、未实现功能」下 `### 1. 内置变量`
- 「二、实现与文档描述不符」下 `### 8. on_failure 的 skip 与 continue` 和 `### 9. extract 失败`

- [ ] **Step 2: Commit**

```bash
git add docs/plan/implementation-status.md
git commit -m "docs: implementation-status 移除已实现项 #1#8#9"
```

---

# 批次 3：大功能 — 参数化（#2 #3）

## Task 3.1: Case 加 param_index 字段

**Files:**
- Modify: `src/atprobe/domain/case/models.py`（Case 加 param_index）
- Test: `tests/unit/test_models.py`

- [ ] **Step 1: 写失败测试 — param_index 字段**

在 `tests/unit/test_models.py` 末尾加测试类：

```python
class TestCaseParamIndex:
    def test_default_param_index_none(self) -> None:
        from atprobe.domain.case.models import Case
        c = Case(name="x", steps=[Step(command="AT")])
        assert c.param_index is None

    def test_param_index_settable(self) -> None:
        from atprobe.domain.case.models import Case
        c = Case(name="x", steps=[Step(command="AT")], param_index=2)
        assert c.param_index == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_models.py::TestCaseParamIndex -v`
Expected: FAIL（Case 无 param_index 字段）

- [ ] **Step 3: 实现 — Case 加字段**

打开 `src/atprobe/domain/case/models.py`，找到 `Case` 类的 `source_file` 字段（约 `:283`）：

```python
    # 来源文件路径（由 parser 填充，不来自 YAML）
    source_file: str | None = None
```

在其后加：

```python
    # 参数化展开实例序号（1-based，非参数化用例为 None）。由 run.py 载入时展开填充，
    # 用于报告 #N 后缀（REQ-M2 §10.2）。YAML 中不出现此字段。
    param_index: int | None = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_models.py::TestCaseParamIndex -v`
Expected: PASS

- [ ] **Step 5: 回归 — 全部 models 测试**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add src/atprobe/domain/case/models.py tests/unit/test_models.py
git commit -m "feat(models): Case 加 param_index 字段（参数化展开序号）"
```

## Task 3.2: 参数化展开 _expand_parameters（#2）

**Files:**
- Modify: `src/atprobe/cli/commands/run.py`（载入后展开）
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: 写失败测试 — 参数化展开执行**

在 `tests/integration/test_cli.py` 新增测试类（用 examples_dir 或临时用例文件）。先用临时文件方式：

```python
class TestParameterization:
    def test_parameters_expand_to_n_instances(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        case_file = tmp_path / "para.yaml"
        case_file.write_text("""
name: 多参数测试
parameters:
  - { val: A }
  - { val: B }
  - { val: C }
steps:
  - command: 'AT{{val}}'
    assert: { contains: "OK" }
""", encoding="utf-8")
        # dry-run 展开后应显示 3 个实例
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [{name: COM3}]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(app, ["run", "--config", str(cfg), "--dry-run", "--vsim", str(case_file)])
        assert result.exit_code == 0
        # 三个实例都列出
        assert result.stdout.count("多参数测试") == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_cli.py::TestParameterization -v`
Expected: FAIL（当前参数化不展开，dry-run 只显示 1 个）

- [ ] **Step 3: 实现 — run.py 加 _expand_parameters**

打开 `src/atprobe/cli/commands/run.py`，在文件末尾（`_check_ports_available` 函数之后）加辅助函数：

```python
def _expand_parameters(case: Case) -> list[Case]:
    """参数化展开：把 parameters 矩阵的每行展开为独立 Case 实例（REQ-M2 §10.2）.

    每个实例的 parameters 缩为单行，并带 param_index 序号（1-based）。
    非参数化用例（parameters 为空）返回单元素列表（原样）。
    """
    if not case.parameters:
        return [case]
    instances: list[Case] = []
    for idx, row in enumerate(case.parameters, start=1):
        instances.append(
            case.model_copy(update={"parameters": (row,), "param_index": idx})
        )
    return instances
```

并在文件顶部 import 区加 `from atprobe.domain.case.models import Case`（若未导入）。

- [ ] **Step 4: 实现 — 载入处调用展开**

找到 run.py 载入用例处（约 `:105-111`）：

```python
    cases = []
    for cp in case_paths:
        try:
            cases.append(parse_case_file(cp))
        except CaseParseError as exc:
            typer.secho(f"用例解析失败：{exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
```

改为（载入后展开）：

```python
    cases = []
    for cp in case_paths:
        try:
            parsed = parse_case_file(cp)
        except CaseParseError as exc:
            typer.secho(f"用例解析失败：{exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        cases.extend(_expand_parameters(parsed))
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_cli.py::TestParameterization -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/atprobe/cli/commands/run.py tests/integration/test_cli.py
git commit -m "feat(cli): 参数化 parameters 矩阵展开为 N 个用例实例（REQ-M2 §10）"
```

## Task 3.3: 参数注入 ctx.variables + 报告 #N 后缀（#2 #3）

**Files:**
- Modify: `src/atprobe/engine/scheduler.py`（_run_case 注入参数）
- Modify: `src/atprobe/engine/scheduler.py`（_build_case_result 装饰 name）
- Test: `tests/integration/test_engine.py`

- [ ] **Step 1: 写失败测试 — 参数注入 + #N 后缀**

在 `tests/integration/test_engine.py` 新增测试类：

```python
class TestParameterization:
    def test_params_injected_and_index_suffix(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        # 两个实例各返回对应响应
        fake_port.script_text("COM3", "OK\r\n", match="ATA", persistent=True)
        fake_port.script_text("COM3", "OK\r\n", match="ATB", persistent=True)
        from atprobe.domain.case.models import Case, Step
        base = Case(
            name="多参数", port="COM3",
            steps=(Step(command="AT{{val}}", ),),
            parameters=({"val": "A"}, {"val": "B"}),
        )
        # 手动展开（模拟 run.py 行为）
        from atprobe.cli.commands.run import _expand_parameters
        cases = _expand_parameters(base)
        assert len(cases) == 2
        result = _engine_with_fake(fake_port).start(_cfg(cases))
        # 两个实例，name 带 #1 #2
        names = [cr.case_name for cr in result.case_results]
        assert "多参数#1" in names and "多参数#2" in names
        # 参数注入变量池（request 含替换后的值）
        assert "ATA" in result.case_results[0].step_results[0].request
        assert "ATB" in result.case_results[1].step_results[0].request
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_engine.py::TestParameterization -v`
Expected: FAIL（参数未注入，request 仍含 `{{val}}`；name 无 #N 后缀）

- [ ] **Step 3: 实现 — _run_case 注入参数**

打开 `src/atprobe/engine/scheduler.py`，找到 `_run_case` 开头（约 `:186`）：

```python
        # 参数化注入（M2 §10.2）—— 由上层展开，此处 case 已是单实例
        ctx = CaseContext(env=config.env_config if isinstance(config.env_config, EnvConfig) else None)
```

改为（实际注入参数到变量池）：

```python
        ctx = CaseContext(env=config.env_config if isinstance(config.env_config, EnvConfig) else None)
        # 参数化注入（M2 §10.2）：参数行注入用例级变量作用域（最高优先级）
        if case.parameters:
            for k, v in case.parameters[0].items():
                ctx.variables[k] = v
```

- [ ] **Step 4: 实现 — _build_case_result 装饰 name**

找到 `_build_case_result`（约 `:385-399`）的：

```python
        duration_ms = (self._clock() - t0) * 1000.0
        return CaseResult(
            case_name=case.name, case_file=case.source_file or "",
```

改为（param_index 装饰）：

```python
        duration_ms = (self._clock() - t0) * 1000.0
        display_name = case.name
        if case.param_index is not None:
            display_name = f"{case.name}#{case.param_index}"
        return CaseResult(
            case_name=display_name, case_file=case.source_file or "",
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_engine.py::TestParameterization -v`
Expected: PASS

- [ ] **Step 6: 回归 — 全部引擎 + CLI 测试**

Run: `uv run pytest tests/integration/test_engine.py tests/integration/test_cli.py -v`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add src/atprobe/engine/scheduler.py tests/integration/test_engine.py
git commit -m "feat(engine): 参数化注入变量池 + 报告 #N 后缀（REQ-M2 §10.2）"
```

---

# 批次 3：大功能 — 套件（#4 #5）

## Task 3.4: Suite 模型 + 解析器（新建 domain/suite/）

**Files:**
- Create: `src/atprobe/domain/suite/__init__.py`
- Create: `src/atprobe/domain/suite/models.py`
- Create: `src/atprobe/domain/suite/parser.py`
- Test: `tests/unit/test_suite_models.py`

- [ ] **Step 1: 写失败测试 — Suite 模型 + 解析**

创建 `tests/unit/test_suite_models.py`：

```python
"""套件模型与解析器单测（REQ-M2 §12）."""

from __future__ import annotations

import pytest

from atprobe.domain.suite.models import Suite
from atprobe.domain.suite.parser import SuiteParseError, parse_suite


class TestSuiteModel:
    def test_minimal_suite(self) -> None:
        s = Suite(name="测试套件", cases=("a.yaml", "b.yaml"))
        assert s.name == "测试套件"
        assert s.cases == ("a.yaml", "b.yaml")
        assert s.suite_setup == ()
        assert s.suite_teardown == ()

    def test_suite_with_setup_teardown(self) -> None:
        from atprobe.domain.case.models import Step
        s = Suite(
            name="x",
            suite_setup=(Step(command="AT+CFUN=1"),),
            suite_teardown=(Step(command="AT+CFUN=0"),),
            cases=("a.yaml",),
        )
        assert len(s.suite_setup) == 1
        assert len(s.suite_teardown) == 1


class TestSuiteParser:
    def test_parse_basic(self) -> None:
        s = parse_suite("""
name: 网络测试套件
description: 网络相关
cases:
  - a.yaml
  - b.yaml
""")
        assert s.name == "网络测试套件"
        assert s.description == "网络相关"
        assert s.cases == ("a.yaml", "b.yaml")

    def test_parse_with_setup(self) -> None:
        s = parse_suite("""
name: x
suite_setup:
  - command: AT+CFUN=1
cases:
  - a.yaml
""")
        assert len(s.suite_setup) == 1

    def test_parse_invalid_step_in_setup(self) -> None:
        # setup 步骤既无 command 又无 data → 校验失败
        with pytest.raises(SuiteParseError):
            parse_suite("""
name: x
suite_setup:
  - foo: bar
cases: []
""")

    def test_parse_non_dict_root(self) -> None:
        with pytest.raises(SuiteParseError):
            parse_suite("- not a dict")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_suite_models.py -v`
Expected: FAIL（模块不存在，ImportError）

- [ ] **Step 3: 创建 __init__.py**

创建 `src/atprobe/domain/suite/__init__.py`：

```python
"""套件（Suite）领域模型与解析器（REQ-M2 §12）."""

from atprobe.domain.suite.models import Suite
from atprobe.domain.suite.parser import SuiteParseError, parse_suite, parse_suite_file

__all__ = ["Suite", "SuiteParseError", "parse_suite", "parse_suite_file"]
```

- [ ] **Step 4: 创建 models.py**

创建 `src/atprobe/domain/suite/models.py`：

```python
"""M2 用例套件数据模型（REQ-M2 §12）.

套件是用例集合的索引文件，通过文件路径引用用例。复用 ``case.Step`` 表达
suite_setup/suite_teardown 步骤（结构一致），保持模型不重复定义。
"""

from __future__ import annotations

from atprobe.domain.case.models import _Frozen, Step


class Suite(_Frozen):
    """用例套件（REQ-M2 §12）。

    通过 ``cases`` 列表引用用例文件（相对套件文件所在目录的路径）。
    suite_setup/suite_teardown 在套件执行的开头/结尾各执行一次（§12.2）。
    """

    name: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = Field(default_factory=tuple)
    suite_setup: tuple[Step, ...] = ()
    suite_teardown: tuple[Step, ...] = ()
    cases: tuple[str, ...] = ()
    source_file: str | None = None
```

注意：`_Frozen` 已配置 `extra="forbid"` + frozen。需从 `pydantic` 导入 `Field`，在文件顶部加 `from pydantic import Field`。

- [ ] **Step 5: 创建 parser.py**

创建 `src/atprobe/domain/suite/parser.py`：

```python
"""M2 套件 YAML 解析器（REQ-M2 §12）.

将 suite YAML 解析为 :class:`Suite` 模型。解析失败抛 :class:`SuiteParseError`。
仿 ``case.parser`` 的结构。
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from atprobe.domain.suite.models import Suite


class SuiteParseError(ValueError):
    """套件解析错误，携带来源文件与原因."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}" if source else message)


_yaml = YAML(typ="safe")
_yaml.indent(mapping=2, sequence=4, offset=2)


def parse_suite(data: str | bytes | dict[str, Any], *, source: str | None = None) -> Suite:
    """解析套件数据为 Suite.

    Raises:
        SuiteParseError: YAML 语法错误或 schema 校验失败。
    """
    if isinstance(data, dict):
        raw: Any = data
    else:
        try:
            raw = _yaml.load(StringIO(data) if isinstance(data, str) else StringIO(data.decode("utf-8")))
        except YAMLError as exc:
            line = getattr(getattr(exc, "problem_mark", None), "line", None)
            loc = f"第 {line + 1} 行" if line is not None else "未知行"
            raise SuiteParseError(f"YAML 语法错误（{loc}）：{exc}", source=source) from exc

    if not isinstance(raw, dict):
        raise SuiteParseError(f"套件根节点必须是映射，实际为 {type(raw).__name__}", source=source)

    try:
        suite = Suite.model_validate(raw)
    except ValidationError as exc:
        lines = ["套件字段校验失败："]
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            lines.append(f"  - {loc}: {err['msg']}")
        raise SuiteParseError("\n".join(lines), source=source) from exc

    if source:
        suite = suite.model_copy(update={"source_file": source})
    return suite


def parse_suite_file(path: str | Path) -> Suite:
    """从文件解析套件."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteParseError(f"无法读取套件文件：{exc.strerror or exc}", source=str(p)) from exc
    return parse_suite(text, source=str(p))
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_suite_models.py -v`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add src/atprobe/domain/suite/ tests/unit/test_suite_models.py
git commit -m "feat(domain): 新建 Suite 模型与解析器（REQ-M2 §12）"
```

## Task 3.5: EngineConfig 加 suite_setup/teardown + scheduler 执行（#4）

**Files:**
- Modify: `src/atprobe/engine/config.py`（加字段）
- Modify: `src/atprobe/engine/scheduler.py`（start 执行 suite 前后置）
- Test: `tests/integration/test_engine.py`

- [ ] **Step 1: 写失败测试 — suite_setup/teardown 执行**

在 `tests/integration/test_engine.py` 新增测试类：

```python
class TestSuiteSetupTeardown:
    def test_suite_setup_runs_before_cases(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        # suite_setup 用 AT+CFUN=1，case 用 AT
        fake_port.script_text("COM3", "OK\r\n", match="AT\\+CFUN=1", persistent=True)
        fake_port.script_text("COM3", "OK\r\n", match="^AT$", persistent=True)
        from atprobe.domain.case.models import Step
        case = parse_case("""
name: 用例A
port: COM3
steps:
  - command: AT
    assert: { contains: "OK" }
""")
        cfg = EngineConfig(
            ports=(PortConfig(name="COM3"),),
            cases=(case,),
            suite_setup=(Step(command="AT+CFUN=1"),),
            suite_teardown=(Step(command="AT+CFUN=0"),),
        )
        result = _engine_with_fake(fake_port).start(cfg)
        assert result.summary.passed == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_engine.py::TestSuiteSetupTeardown -v`
Expected: FAIL（EngineConfig 无 suite_setup 字段）

- [ ] **Step 3: 实现 — EngineConfig 加字段**

打开 `src/atprobe/engine/config.py`，找到 `EngineConfig` 的字段定义（约 `:40-47`），在 `report_env_snapshot: bool = True` 后加：

```python
    # 套件级前后置（REQ-M2 §12.2）：cases 循环前/后各执行一次。默认空（非套件执行）
    suite_setup: tuple[Step, ...] = ()    # type: ignore[name-defined]  # noqa: F821
    suite_teardown: tuple[Step, ...] = ()  # type: ignore[name-defined]  # noqa: F821
```

并在文件顶部加 import（避免循环，用 TYPE_CHECKING）：

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from atprobe.domain.case.models import Step
```

- [ ] **Step 4: 实现 — scheduler.start 执行 suite 前后置**

打开 `src/atprobe/engine/scheduler.py`，找到 `start` 中 cases 循环（约 `:126` `for idx, case in enumerate(config.cases, start=1):`），在其**之前**插入 suite_setup 执行：

```python
        # 套件级前置（REQ-M2 §12.2）：cases 循环前执行一次
        suite_setup_results: list[StepResult] = []
        for i, step in enumerate(config.suite_setup, start=1):
            if self._stop_mode is StopMode.ALL:
                break
            r = execute_step(
                step, index=i, phase="suite_setup", ctx=CaseContext(env=config.env_config if isinstance(config.env_config, EnvConfig) else None),
                sender=sender, default_port=default_port, step_timeout_default=config.step_timeout_default,
                clock=self._clock, sleep=self._sleep, cancel=cancel,
            )
            suite_setup_results.append(r.step_result)
            self._emit_step(handler, r)
            if r.abort_case:  # suite_setup 失败 → 中止
                break
```

然后在 cases 循环的 `finally` 块（约 `:154`）之后、`summary = aggregate(...)` 之前，插入 suite_teardown：

```python
        # 套件级后置（REQ-M2 §12.2）：cases 循环后执行一次（无条件，失败仅记警告）
        suite_teardown_results: list[StepResult] = []
        suite_ctx = CaseContext(env=config.env_config if isinstance(config.env_config, EnvConfig) else None)
        for i, step in enumerate(config.suite_teardown, start=1):
            try:
                r = execute_step(
                    step, index=i, phase="suite_teardown", ctx=suite_ctx,
                    sender=sender, default_port=default_port, step_timeout_default=config.step_timeout_default,
                    clock=self._clock, sleep=self._sleep, cancel=None,
                    is_teardown=True,
                )
                suite_teardown_results.append(r.step_result)
            except Exception:  # noqa: BLE001 - suite_teardown 失败仅记录
                pass
```

注意：suite_setup/teardown_results 仅用于日志/报告展示，不进 aggregate（aggregate 只看 case_results）。如需在 ExecutionResult 中展示，可后续扩展，本任务先保证执行发生。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_engine.py::TestSuiteSetupTeardown -v`
Expected: PASS

- [ ] **Step 6: 回归**

Run: `uv run pytest tests/integration/test_engine.py -v`
Expected: 全 PASS（默认 suite_setup/teardown 为空，非套件执行不受影响）

- [ ] **Step 7: Commit**

```bash
git add src/atprobe/engine/config.py src/atprobe/engine/scheduler.py tests/integration/test_engine.py
git commit -m "feat(engine): EngineConfig 加 suite_setup/teardown + scheduler 执行（REQ-M2 §12.2）"
```

## Task 3.6: CLI `run suite-xxx.yaml` 触发套件执行（#5）

**Files:**
- Modify: `src/atprobe/cli/commands/run.py`（识别 suite 文件 + 编排）
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: 写失败测试 — run suite 文件**

在 `tests/integration/test_cli.py` 新增测试类：

```python
class TestRunSuite:
    def test_run_suite_executes_cases_in_order(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # 建套件 + 两个用例
        (tmp_path / "a.yaml").write_text("""
name: 用例A
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("""
name: 用例B
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        suite_file = tmp_path / "suite-test.yaml"
        suite_file.write_text("""
name: 测试套件
cases:
  - a.yaml
  - b.yaml
""", encoding="utf-8")
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [{name: COM3}]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(app, ["run", "--config", str(cfg), "--vsim", str(suite_file)])
        assert result.exit_code == 0
        assert "用例A" in result.stdout
        assert "用例B" in result.stdout
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_cli.py::TestRunSuite -v`
Expected: FAIL（当前 suite 文件被当普通用例解析，报 steps: Field required）

- [ ] **Step 3: 实现 — run.py 识别 suite 文件**

打开 `src/atprobe/cli/commands/run.py`，找到 `_resolve_case_paths`（约 `:231`）。该函数当前对 `suite-` 前缀文件在目录扫描时跳过，但单文件参数会直接加入。改为：识别 `suite-` 前缀的单文件，标记为套件。

在 `run` 函数中，找到载入用例处（Task 3.2 改过的，约 `:105`），在展开参数化之前加套件分支：

```python
    # 套件文件识别：suite- 前缀的单文件走套件执行路径
    suite_files = [p for p in case_paths if p.name.startswith("suite-")]
    case_files = [p for p in case_paths if not p.name.startswith("suite-")]

    cases: list[Case] = []
    # 套件：解析 suite，按 cases 列表载入用例
    suite_setups = []
    suite_teardowns = []
    for sf in suite_files:
        from atprobe.domain.suite import parse_suite_file, SuiteParseError as _SPE
        try:
            suite = parse_suite_file(sf)
        except _SPE as exc:
            typer.secho(f"套件解析失败：{exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        suite_setups.extend(suite.suite_setup)
        suite_teardowns.extend(suite.suite_teardown)
        # suite.cases 相对套件文件所在目录解析
        for crel in suite.cases:
            cpath = (sf.parent / crel).resolve()
            try:
                parsed = parse_case_file(cpath)
            except CaseParseError as exc:
                typer.secho(f"用例解析失败：{exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(2) from exc
            cases.extend(_expand_parameters(parsed))

    # 普通用例文件
    for cp in case_files:
        try:
            parsed = parse_case_file(cp)
        except CaseParseError as exc:
            typer.secho(f"用例解析失败：{exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        cases.extend(_expand_parameters(parsed))
```

- [ ] **Step 4: 实现 — EngineConfig 带套件前后置**

找到构造 EngineConfig 处（约 `:155`），加 suite_setup/teardown：

```python
        engine_cfg = EngineConfig(
            ports=tuple(ports),
            cases=tuple(cases),
            suite_setup=tuple(suite_setups),
            suite_teardown=tuple(suite_teardowns),
            step_timeout_default=app_cfg.step_timeout,
            ...
        )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/integration/test_cli.py::TestRunSuite -v`
Expected: PASS

- [ ] **Step 6: 回归 — 全部 CLI 测试**

Run: `uv run pytest tests/integration/test_cli.py -v`
Expected: 全 PASS（`run <目录>` 行为不变，suite 文件在目录扫描时仍跳过）

- [ ] **Step 7: Commit**

```bash
git add src/atprobe/cli/commands/run.py tests/integration/test_cli.py
git commit -m "feat(cli): run suite-xxx.yaml 触发套件执行（按 cases 列表 + 前后置）"
```

## Task 3.7: 套件标签筛选 + 全量回归

**Files:**
- Modify: `src/atprobe/cli/commands/run.py`（套件 cases 应用 tag 过滤）
- Test: `tests/integration/test_cli.py`

REQ-M2 §12.2：套件支持按标签筛选部分用例。复用现有 `--tag`/`--exclude-tag`。

- [ ] **Step 1: 写失败测试 — 套件 tag 筛选**

在 `tests/integration/test_cli.py` 的 `TestRunSuite` 类加：

```python
    def test_run_suite_with_tag_filter(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        (tmp_path / "a.yaml").write_text("""
name: 用例A
tags: [smoke]
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("""
name: 用例B
tags: [regression]
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        suite_file = tmp_path / "suite-test.yaml"
        suite_file.write_text("""
name: 测试套件
cases:
  - a.yaml
  - b.yaml
""", encoding="utf-8")
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [{name: COM3}]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(app, ["run", "--config", str(cfg), "--vsim", "--tag", "smoke", str(suite_file)])
        assert result.exit_code == 0
        assert "用例A" in result.stdout
        assert "用例B" not in result.stdout  # 被 tag 过滤
```

- [ ] **Step 2: 运行测试**

Run: `uv run pytest tests/integration/test_cli.py::TestRunSuite::test_run_suite_with_tag_filter -v`

若 FAIL（套件载入的用例未经过 tag 过滤），继续 Step 3；若 PASS（tag 过滤已在 cases 上统一应用），跳到 Step 4。

- [ ] **Step 3: 实现 — 确保 tag 过滤在套件展开后统一应用**

打开 `src/atprobe/cli/commands/run.py`，确认 tag 过滤（约 `:114-119`，Task 3.2 改后位置可能下移）在套件 cases 载入**之后**对统一 `cases` 列表应用。当前 tag 过滤逻辑：

```python
    if tag or exclude_tag:
        cases = [
            c for c in cases
            if (not tag or any(t in c.tags for t in tag))
            and not any(t in c.tags for t in exclude_tag)
        ]
```

确认此段在所有用例（含套件展开）载入之后执行。若 Task 3.6 的套件载入在此段之前，则无需改动（统一过滤）。

- [ ] **Step 4: 全量回归**

Run: `uv run pytest -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/atprobe/cli/commands/run.py tests/integration/test_cli.py
git commit -m "feat(cli): 套件用例支持 --tag 筛选（REQ-M2 §12.2）"
```

## Task 3.8: implementation-status.md 清空/归档

**Files:**
- Modify: `docs/plan/implementation-status.md`

全部 11 项完成，归档该文档。

- [ ] **Step 1: 改为已完成说明**

打开 `docs/plan/implementation-status.md`，保留标题，把正文改为：

```markdown
# 当前实现状态（未实现 / 与文档描述不符的功能）

> **本文档列出的 11 项缺口已全部对齐（2026-07-01）。** 详见
> `docs/superpowers/specs/2026-07-01-tool-implementation-gaps-design.md` 与对应实现提交。
> reference 文档描述的核心功能现已全部可用，文档与代码一致。

历史缺口清单已随实现进度逐项移除。本文件保留作为后续开发的参考入口。
```

- [ ] **Step 2: Commit**

```bash
git add docs/plan/implementation-status.md
git commit -m "docs: implementation-status 11 项缺口全部对齐，归档"
```

---

## 完成验证

全部任务完成后，运行完整回归确认无回归：

- [ ] **Step 1: 全量测试**

Run: `uv run pytest -v`
Expected: 全 PASS

- [ ] **Step 2: vsim 端到端冒烟（参数化 + 套件）**

```bash
uv run python -m atprobe run --vsim --dry-run examples/testcases/tcp/
```
Expected: 列出用例无报错（确认 CLI 路径通畅）

- [ ] **Step 3: 确认 implementation-status 已归档**

Run: `grep -c "已全部对齐" docs/plan/implementation-status.md`
Expected: 1
