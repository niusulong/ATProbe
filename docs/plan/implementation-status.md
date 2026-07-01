# 工具功能实现状态（需求 vs 当前代码的差距清单）

> **本文档面向后续工具（ATProbe 框架）功能开发者。** 当前工具尚未完善、未正式投入使用，配套的
> atprobe-case-author 技能也同样未投入使用。本文件对照 `docs/requirements/REQ-M2-测试用例定义.md`
> 权威需求与 `src/atprobe/` 实际代码，列出**需求已设计但代码尚未实现**、以及**代码实现与需求描述有差异**
> 的功能点，作为后续开发的参考清单（即待补全/待对齐的工作项）。

需求文档（REQ-M2）与技能 reference 文档（`.agents/skills/atprobe-case-author/references/`）代表完整的
目标设计；本文件反映当前代码的真实状态。下方按"未实现功能"和"实现与文档不符"两类列出，每项附代码证据（file:line）。

## 一、未实现功能（reference 有描述，代码尚未实现）

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

