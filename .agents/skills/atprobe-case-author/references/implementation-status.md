# 当前实现状态（未实现 / 与文档描述不符的功能）

> **写用例前必读。** 本文件列出 reference 文档描述了但**当前代码尚未实现**、或**实现与文档描述有差异**的功能。
> reference 文档（variables/parameters/suite 等）代表完整的目标设计（源自 REQ-M2 需求），是后续完善的蓝图；
> 本文件反映**当前代码的真实状态**。生成用例时，**不要使用本文件标注为"未实现"的功能**，否则用例会运行失败。

下方按"未实现功能"和"实现与文档不符"两类列出，每项附代码证据（file:line）。

## 一、未实现功能（reference 有描述，代码尚未实现）

### 1. 内置变量 `{{timestamp}}` / `{{port}}` / `{{loop_index}}` —— 未实现

- **状态**：未实现。代码不注入任何内置变量，引用它们会抛 `UndefinedReferenceError`。
- **代码证据**：`templater.py:56` 仅为 docstring 示例；引擎唯一写变量池处是 `step_runner.py:164`（只写 extract 结果），无内置变量注入；`pressure.py` 循环时 `rnd` 局部变量从不写入 `ctx.variables`。
- **生成用例时**：不要使用 `{{timestamp}}`/`{{port}}`/`{{loop_index}}`。压测场景如需引用当前轮次，暂不可用。
- **详见**：`variables.md`「内置变量」描述的目标设计。

### 2. 参数化 `parameters` 矩阵展开 —— 未实现（P1）

- **状态**：未实现。`parameters` 字段能被 schema 接受（不会报错），但**执行时完全被忽略**——不会展开成 N 次执行，参数不注入变量池。
- **代码证据**：`models.py:269-270` 字段已定义；`scheduler.py:186` 有过时注释"由上层展开"，但 `run.py`/`scheduler.py` 均无展开代码；`CaseContext.variables` 初始为空，参数从不写入。
- **生成用例时**：不要依赖 `parameters` 矩阵。需要测多组参数时，**为每组参数写独立的用例文件**（用命名变体区分，如 `PARA-VALID_APN_CMNET` / `PARA-VALID_APN_CMIOT`）。
- **详见**：`parameters.md` 描述的目标设计。

### 3. 报告 `#1`/`#2` 后缀 —— 未实现（依赖参数化）

- **状态**：未实现（因参数化未实现，无多次实例可加后缀）。
- **代码证据**：`CaseResult.case_name`（`report/models.py:117`）直接取 `case.name`，无 `#N` 装饰。
- **详见**：`parameters.md`「行为规则」。

### 4. 套件 `suite_setup` / `suite_teardown` —— 未实现（P1）

- **状态**：未实现。代码中无 `Suite` 类，无任何代码读取或执行 `suite_setup`/`suite_teardown`。
- **代码证据**：全代码库 grep `suite_setup`/`suite_teardown`/`class Suite` 零命中；`list.py:84-109` 的 `_parse_suite_meta` 用裸 YAML 加载，只读 `name`/`description`/`cases`，忽略 setup/teardown。
- **生成用例时**：不要在 suite 文件里写 `suite_setup`/`suite_teardown`。套件级前后置需求改为在每个用例的 setup/teardown 里各自处理。
- **详见**：`suite.md` 描述的目标设计。

### 5. suite 文件作为索引、`run <目录>` 按 cases 列表执行 —— 未实现

- **状态**：部分未实现。`run <目录>` 时框架**跳过** `suite-` 前缀文件，直接跑目录下所有非 suite 的 yaml，**不读取 suite 文件里的 `cases:` 列表**。
- **代码证据**：`run.py:241` 目录扫描时 `if f.name.startswith("suite-"): continue` 跳过；suite 文件的 `cases:` 列表从不被解析展开。
- **实际行为**：`run <目录>` = 跑目录下所有用例文件（按文件名排序），suite 文件仅作人类阅读的索引文档。
- **生成用例时**：用例文件放进功能块目录即可被 `run <目录>` 执行，无需依赖 suite 文件的 cases 列表来注册。

## 二、实现与文档描述不符（功能已实现，但行为与 reference 描述有差异）

### 6. teardown 步骤的 retry 未被拦截 —— 与文档不符

- **状态**：`control-flow.md` 表格称 teardown 不支持 retry，但**代码未拦截**——teardown 步骤若带 `retry` 块，实际会重试。
- **代码证据**：`step_runner.py:145` 对 poll 有 `and not is_teardown` 守卫，但 retry 路径（`:151` else 分支）无此守卫。
- **生成用例时**：teardown 步骤避免写 retry（虽然能跑，但与文档语义不符，后续可能被修正为拦截）。

### 7. setup 步骤的 when 会被求值 —— 与文档不符

- **状态**：`control-flow.md` 表格称 setup 不支持 when，但**代码允许**——setup 步骤的 when 会被求值。
- **代码证据**：`step_runner.py:117` 守卫是 `if not is_teardown and step.when is not None`，setup 非 teardown，故 when 生效。
- **生成用例时**：setup 步骤避免写 when（虽然能跑，但与文档语义不符）。

### 8. on_failure 的 skip 与 continue 行为相同 —— 与文档不符

- **状态**：`control-flow.md` 区分 skip（跳过当前步骤）和 continue（标记失败继续），但**代码不区分**——两者都 `abort_case=False`，行为完全相同（继续后续步骤）。
- **代码证据**：`step_runner.py:189` 仅判断 `strategy is FailureStrategy.ABORT`，非 ABORT 一律继续。
- **生成用例时**：skip 和 continue 现可互换使用，但建议按文档语义写（后续代码完善后语义会区分）。

### 9. extract 失败的"已提取但空值"在实际变量池中无法区分 —— 与文档不符

- **状态**：`variables.md` 称 extract 失败"标记为已提取但空值，区别于未定义"，但**引擎丢弃了 matched 标志**——非匹配直接写 `""`，与未定义在实际变量池中无法区分。
- **代码证据**：`extractor.py:31-32` 返回 `ExtractionResult(value="", matched=False)`；`step_runner.py:307` `values, _matched = extract_all(...)` 丢弃 `_matched`，只把 `""` 写入池。
- **生成用例时**：不要依赖"提取失败 vs 未定义"的区分。用 `is null` 判断变量是否存在时，注意提取失败的变量是空字符串而非 null。

### 10. tags 筛选仅支持并集，不支持交集 —— 与文档不符

- **状态**：`conventions.md` 称"支持多标签组合筛选（交集/并集）"，但**代码只支持并集**（`--tag` 多值取并集）和排除（`--exclude-tag`），不支持交集。
- **代码证据**：`run.py:117` 用 `any(...)` 判断 `--tag` 命中（并集语义）。
- **生成用例时**：tags 按并集筛选设计即可。

### 11. name 唯一性不强制 —— 与文档不符

- **状态**：`conventions.md` 称 name"必须唯一"，但**代码不强制**——重名不会报错，仅在文档约定。
- **代码证据**：仅 `models.py:260` docstring 提及，无运行时检查。
- **生成用例时**：仍应保持 name 唯一（报告会用"文件名+name"双标识，重名虽不报错但报告会混淆）。
