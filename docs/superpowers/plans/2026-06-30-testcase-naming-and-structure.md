# ATProbe 测试用例命名与结构规范 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将"测试用例命名与结构规范"（spec: `docs/superpowers/specs/2026-06-30-testcase-naming-and-structure-design.md`）落地为对 `atprobe-case-author` skill 文件的改造，不动框架源码。

**Architecture:** 纯文档改造。在 SKILL.md 新增"命名与结构规范"前置章节 + 改造工作流步骤；新增 `references/testcase-matrix.md` 承载"每指令必备用例清单矩阵"；微调 `references/yaml-schema.md` 补充 tags/description 约束。所有改动是约束规则的文字描述，不涉及代码编译/运行。

**Tech Stack:** Markdown（skill 定义文件）。无代码、无测试框架。

**关键约束（来自 spec）：**
- skill 必须保持指令集无关，**不得**硬编码任何 `chXX→功能块` 映射。
- 保留 skill 既有的核心闭环（宽松断言→运行→收紧断言→验证反证），只在其外层包一层命名/结构规范。
- 老用例迁移不在本计划范围。

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `.agents/skills/atprobe-case-author/SKILL.md` | 改造 | 主流程 + 核心理念 + 命名/结构规范前置章节 + 工作流改造 |
| `.agents/skills/atprobe-case-author/references/testcase-matrix.md` | 新建 | 每指令必备用例清单矩阵（形态×模板） |
| `.agents/skills/atprobe-case-author/references/yaml-schema.md` | 微调 | 补充 tags 强制三段、description 强制三段约束 |
| `.agents/skills/atprobe-case-author/references/response-patterns.md` | 不动 | 与命名规范正交 |

---

## Task 1: 新建 references/testcase-matrix.md（矩阵 reference）

**Files:**
- Create: `.agents/skills/atprobe-case-author/references/testcase-matrix.md`

- [ ] **Step 1: 写入矩阵 reference 文件**

创建文件，完整内容如下。这份文件承载 spec §5 的"每指令必备用例清单矩阵"，供 SKILL.md 第 2 步按需引用。

````markdown
# 每指令必备用例清单矩阵

按指令形态套模板，照做即不漏。读指令文档，看该指令支持哪些形态，每个形态套下表模板，汇总即该指令全部必备用例。

## 形态 × 必备模板

| 指令支持的形态 | 必备用例（类型-变体） | 数量 |
|---|---|---|
| `=?` 测试命令 | `RESP-TEST_RANGE` | ×1 |
| `?` 查询命令 | `RESP-QUERY_FORMAT` | ×1 |
| `=<参数>` 设置命令 | `PARA-VALID_<场景>`（覆盖默认/典型/边界合法值） | ≥1 |
| | `PARA-OVER_<参数名>`（每个数值参数越上限） | 每参数 ×1 |
| | `PARA-UNDER_<参数名>`（每个数值参数越下限） | 每参数 ×1 |
| | `PARA-WRONG_FORMAT_<场景>`（缺引号/缺参/类型错） | 每场景 ×1 |
| 执行命令（无参动作） | `FUNC-NORMAL`（需注网则 description 注明） | ×1 |
| | `FUNC-PRECONDITION_FAIL`（前置不满足，如未建链） | ×1 |
| 带参数的动作指令（如 TCPSEND） | 上述 PARA 全套 **+** `FUNC-NORMAL_<动作>` **+** `FUNC-NOLINK` | PARA 数 + 2 |

## 三个测试类型的精确定义

| 类型 | 名称 | 定义 | 断言重点 |
|---|---|---|---|
| **RESP** | 响应格式 | 校验查询（`?`）/测试（`=?`）指令的**响应字节格式**：空格数、换行、字段结构。不关心值对错 | `matches: '^...$'` 严格字节级 |
| **FUNC** | 功能验证 | 在**正常/真实业务路径**下指令是否做了该做的事。含成功路径 + 该指令**自身**的业务失败路径（如未建链） | 业务结果码 / 业务码 |
| **PARA** | 参数与边界 | 指令**合法参数**是否被接受（→ OK）**以及**非法/越界参数是否被拒绝（→ CME）。变体名区分 success/fail | `OK` 或 `+CME ERROR: <code>` |

## 类型设计依据

- **PARAM 与 BND 合并为 PARA**：参数校验与边界针对同一组设置类指令，只是断言期望不同（OK vs CME）。合并后集中在同一类型下便于整体查漏，变体名（`VALID_*` / `OVER_*` / `WRONG_FORMAT_*`）已显式标注 success/fail。
- **业务失败路径归 FUNC**：指令自身前提不满足（如 TCPSEND 未建链）属该指令正常行为范畴，不另设错误类。业务码（`+TCPSEND: ERROR`）与 CME 错误码（参数越界）走不同类型，语义清晰。

## 跨类型说明：带参数的动作指令

带参数的动作指令（如 TCPSEND）有两条独立验证线，各自独立成文件：
- **PARA 类**测"参数是否被接受"（断 OK/CME）——不实际触发业务
- **FUNC 类**测"动作是否真的发生"（断业务结果）——需真实环境

两条线不冲突。

## 完整示例：TCPSEND 指令的文件集

TCPSEND 支持设置形态 `=<linkid>,<length>` 且是动作指令，套矩阵：

```
TCP-TCPSEND-PARA-VALID_LENGTH.yaml      # 合法长度 → OK
TCP-TCPSEND-PARA-OVER_LENGTH.yaml       # 4097 → CME 53
TCP-TCPSEND-FUNC-NORMAL_SEND.yaml       # 实际发送成功（description 注明需注网）
TCP-TCPSEND-FUNC-NOLINK.yaml            # 未建链 → +TCPSEND: SOCKET ID OPEN FAILED
```

## 功能块级通用用例

测模组指令识别机制（如指令名拼错 → CME 58）这类不专属某指令的用例，用特殊指令段 `CMDPARSE`，每功能块最多一个文件：`<功能块>-CMDPARSE-FUNC-INVALID_NAME.yaml`。

## 自查清单

为一条新指令写完用例后，按此自查防遗漏：

- [ ] 该指令支持的每个形态（`?`/`=?`/`=`/执行）是否都有对应类型用例
- [ ] 每个数值参数是否都有 OVER 和 UNDER 边界用例（若文档给了范围）
- [ ] 动作指令是否有 FUNC-NORMAL（成功）和 FUNC-NOLINK/PRECONDITION_FAIL（前提失败）
- [ ] 用例文件名是否符合 `<功能块>-<指令>-<类型>-<变体>.yaml` 四段格式
- [ ] 每个文件是否只测一个指令
````

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/atprobe-case-author/references/testcase-matrix.md
git commit -m "docs(skill): 新增 testcase-matrix.md（每指令必备用例清单矩阵）

承载命名与结构规范 spec §5 的形态×模板矩阵 + 三类型定义 +
TCPSEND 完整示例 + 自查清单，供 SKILL.md 工作流第 2 步引用。"
```

---

## Task 2: 微调 references/yaml-schema.md（tags/description 约束）

**Files:**
- Modify: `.agents/skills/atprobe-case-author/references/yaml-schema.md:8-19`（顶层结构段）

- [ ] **Step 1: 在顶层结构段补充 tags/description 约束**

找到 yaml-schema.md 第 8-19 行的"顶层结构（Case）"代码块。在 `tags: [str]` 行和 `description: str` 行追加约束注释。将：

```yaml
name: str                    # 必填，min_length=1，执行范围内唯一
description: str             # 可选，多行用 | 块
tags: [str]                  # 可选，分类标签
```

替换为：

```yaml
name: str                    # 必填，min_length=1，执行范围内唯一
description: str             # 可选，多行用 | 块；规范要求强制三段：场景前提 + 验证目标 + 探测依据
tags: [str]                  # 可选，分类标签；规范要求强制前三段为 [功能块, 指令, 类型]，如 [TCP, TCPSEND, FUNC]
```

- [ ] **Step 2: 在文件末尾追加约束说明小节**

在 yaml-schema.md 末尾（第 166 行 `## 示例：完整的严格字节级用例片段` 那段代码块之后）追加新小节：

```markdown

## 命名与结构规范约束（详见 SKILL.md「命名与结构规范」章节）

- **tags 强制三段**：前三个元素必须是 `[<功能块>, <指令>, <类型>]`，类型为 FUNC/RESP/PARA 之一。可继续追加优先级等标签（如 `p0`）。例：`tags: [TCP, TCPSEND, FUNC, p0]`。
- **description 强制三段**：用 `|` 块，内容包含：
  1. **场景前提**：设备状态（有无 SIM/注网/PDP）、前置依赖、是否需注网。
  2. **验证目标**：本用例要验证什么。
  3. **探测依据**：第 3 步运行后回填的真实响应格式（作为断言来源的可追溯记录）。
- **文件命名**：`<功能块>-<指令>-<类型>-<变体>.yaml`，四段全大写。详见 SKILL.md。
- **单一职责**：`steps` 内所有断言只针对同一被测指令；前置依赖指令进 setup/teardown 且断言宽松。
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/atprobe-case-author/references/yaml-schema.md
git commit -m "docs(skill): yaml-schema 补充 tags/description 强制三段约束

配合命名与结构规范，明确 tags 前三段=[功能块,指令,类型]，
description 三段=场景前提+验证目标+探测依据。"
```

---

## Task 3: 在 SKILL.md 插入「命名与结构规范」前置章节

**Files:**
- Modify: `.agents/skills/atprobe-case-author/SKILL.md:10-27`（在「核心概念」之前插入新章节）

- [ ] **Step 1: 在「## 核心理念」之前插入命名规范章节**

SKILL.md 当前第 10 行是 `# ATProbe 测试用例生成`，第 14 行附近是 `## 核心理念：先跑出真实响应，再收紧断言`。在这两个标题之间（`## 核心理念` 之前）插入完整新章节。

定位锚点：找到这一段：

```markdown
# ATProbe 测试用例生成

把 `docs/at-ref/chXX-*.md` 指令集文档转成 `examples/testcases/<dir>/*.yaml`，可直接用
`uv run python -m atprobe run <路径> --config <配置>` 运行。

## 核心理念：先跑出真实响应，再收紧断言
```

替换为：

```markdown
# ATProbe 测试用例生成

把 `docs/at-ref/chXX-*.md` 指令集文档转成 `examples/testcases/<功能块>/*.yaml`，可直接用
`uv run python -m atprobe run <路径> --config <配置>` 运行。

## 命名与结构规范（写任何用例前必读）

> **单一职责是第一原则**：一个用例文件只测**一个指令**的一个维度。失败时能立即定位是哪个指令的哪类问题。
> 不要把多个指令的测试塞进一个文件——历史教训：曾有一个文件含 7 个指令的业务码测试，任一失败都无法定位。

### 文件命名（4 段，全大写）

```
examples/testcases/<功能块>/<功能块>-<指令>-<类型>-<变体>.yaml
```

| 段 | 规则 | 示例 |
|---|---|---|
| `<功能块>` | 大写，对应指令文档章节功能名；**运行时从文档提取，不硬编码** | TCP / NTP / FTP |
| `<指令>` | 被测指令名，**去掉 AT+ 前缀的裸名**，大写，单一指令 | TCPSEND / UPDATETIME |
| `<类型>` | 4 字母代码，三选一：FUNC / RESP / PARA | FUNC |
| `<变体>` | 大写、下划线分词，描述本用例的具体测试点 | NORMAL_SEND / OVER_LENGTH |

示例：
```
TCP-TCPSEND-FUNC-NORMAL_SEND.yaml       # 数据发送的正常业务路径
TCP-TCPSEND-PARA-OVER_LENGTH.yaml       # 长度越界 → CME 53
TCP-RECVMODE-RESP-QUERY_FORMAT.yaml     # 查询响应字节格式
TCP-CMDPARSE-FUNC-INVALID_NAME.yaml     # 功能块级：指令名拼错（CME 58）
```

### 三个测试类型

| 类型 | 名称 | 测什么 | 断言重点 |
|---|---|---|---|
| **RESP** | 响应格式 | 查询（`?`）/测试（`=?`）指令的**响应字节格式**（空格数、换行、字段结构），不关心值对错 | `matches: '^...$'` |
| **FUNC** | 功能验证 | 正常/真实业务路径下指令是否做了该做的事；含该指令**自身**的业务失败路径（如未建链） | 业务结果/业务码 |
| **PARA** | 参数与边界 | 合法参数是否被接受（→ OK）**以及**越界/错误参数是否被拒绝（→ CME）。变体名区分 success/fail | OK 或 CME |

> PARA 类合并了传统的"参数测试"和"边界测试"——它们针对同一组设置类指令，只是断言期望不同。变体名（`VALID_*` / `OVER_*` / `WRONG_FORMAT_*`）已显式标注。

### 单一职责落地

- **steps 只含被测指令**。前置依赖指令（如 TCPSEND 需先 TCPSETUP 建链）只进 `setup`，且断言宽松（`contains: OK`），不作为断言重点。清理指令进 `teardown`。
- **tags 强制三段**：`[<功能块>, <指令>, <类型>]`，可追加 `p0/p1` 等。例：`tags: [TCP, TCPSEND, FUNC, p0]`。
- **description 强制三段**：场景前提（设备状态/前置依赖/是否需注网）+ 验证目标 + 探测依据（第 3 步运行后回填）。

### 功能块名从哪来（通用，不硬编码）

**绝不维护指令集特定的映射表。** 功能块目录名在读文档阶段运行时提取：
1. 读指令文档第 1 行标题（格式 `# 第 X 章 <功能名>`），取"第 X 章"之后的功能名。
2. 功能名是干净英文/ASCII 则规范化大写使用（如 `TCP/UDP...` → 用 `TCP` 或文档约定的短名）。
3. **功能名无法干净提取（如纯中文"网络时间同步"）→ 停下来问用户**，不自动降级、不臆测。

### 功能块级通用用例

测模组指令识别机制（指令名拼错 → CME 58）这类不专属某指令的用例，用特殊指令段 `CMDPARSE`，每功能块最多一个文件：`<功能块>-CMDPARSE-FUNC-INVALID_NAME.yaml`。

## 核心理念：先跑出真实响应，再收紧断言
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/atprobe-case-author/SKILL.md
git commit -m "docs(skill): SKILL.md 新增「命名与结构规范」前置章节

插入 4 段全大写命名规则、三类型定义、单一职责落地、
功能块名运行时提取（不硬编码）、功能块级 CMDPARSE 用例。"
```

---

## Task 4: 改造 SKILL.md 工作流第 1 步（功能块名提取 + 模糊即提问）

**Files:**
- Modify: `.agents/skills/atprobe-case-author/SKILL.md`（工作流「### 1. 读指令集文档」小节）

- [ ] **Step 1: 重写工作流第 1 步**

找到当前工作流第 1 步整段（在 Task 3 插入新章节后，行号会下移；用内容定位）：

```markdown
### 1. 读指令集文档

读 `docs/at-ref/chXX-*.md`，提取每个指令小节的：指令名、参数定义、参数取值范围、响应格式描述。
注意文档的响应格式描述只是"参考"，实际以第 3 步运行结果为准。
```

替换为：

```markdown
### 1. 读指令集文档 + 确定功能块名 + 标注待澄清项

读 `docs/at-ref/chXX-*.md`，做三件事：

**(a) 确定功能块名**（用于目录名和文件名第一段）：
- 读文档第 1 行标题 `# 第 X 章 <功能名>`，取"第 X 章"之后的功能名。
- 功能名是干净英文/ASCII → 规范化大写使用（如文档标题含 `TCP`）。
- **功能名无法干净提取（纯中文、含歧义）→ 问用户**该功能块叫什么，不臆测、不硬编码。

**(b) 逐指令提取**：指令名、参数定义、参数取值范围、支持的形态（`?`/`=?`/`=`/执行）、响应格式描述。
注意文档的响应格式描述只是"参考"，实际以第 3 步运行结果为准。

**(c) 标注待澄清项**：遇到以下无法从文档明确判定的情况，**停下来问用户**，不臆测：

| 情况 | 处理 |
|---|---|
| 参数语义/取值范围文档未明 | 问用户，或标注"待第 3 步运行探测" |
| 业务逻辑有歧义（如不确定某指令是否需先注网/建链） | 问用户场景前提 |
| 错误码归类有歧义（不确定 CME 53 还是业务码） | 标注待第 3 步运行确认 |
| 前置依赖关系不明 | 问用户 |

**不该问的场景**（有唯一确定来源，走既有闭环）：能从文档明确读出的取值范围/参数格式、能从运行拿到的真实响应字节格式、文档明确标注的指令形态支持情况。

> 参考头脑风暴 skill 的交互式澄清哲学：信息有唯一确定来源（文档或运行）时不问；存在多种合理解释或信息缺失时问。
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/atprobe-case-author/SKILL.md
git commit -m "docs(skill): 工作流第1步改造——功能块名提取 + 模糊即提问

(a) 确定功能块名：从文档第1行提取，无法干净提取则问用户，不硬编码。
(b) 逐指令提取形态/参数/响应。
(c) 标注待澄清项：参数语义/业务逻辑/错误码归类/前置依赖不明时问用户。
注入 brainstorming 的「模糊即提问」哲学。"
```

---

## Task 5: 改造 SKILL.md 工作流第 2 步（按矩阵逐指令生成 + 单一职责）

**Files:**
- Modify: `.agents/skills/atprobe-case-author/SKILL.md`（工作流「### 2. 写初版用例（宽松断言）」小节）

- [ ] **Step 1: 重写工作流第 2 步**

找到当前工作流第 2 步整段：

```markdown
### 2. 写初版用例（宽松断言）

按文档先写一版用例文件，放到 `examples/testcases/<dir>/`。这版**故意用宽松断言**：
- 查询类先写 `assert: { contains: "OK" }`
- 每个步骤前加 YAML 注释（`# 6.x 指令名`）便于对照（注意：Step 不支持 `name` 文档里的所有指令变体：查询（`?`）、测试（`=?`）、设置成功、参数越界、链路操作、指令名错误

目的不是这版断言要准，而是**让指令真实发出去并拿到响应**。完整 YAML schema、字段语义见
`references/yaml-schema.md`。
```

替换为：

```markdown
### 2. 按矩阵逐指令生成初版用例（宽松断言 + 单一职责）

**先读 `references/testcase-matrix.md`**，按"形态 × 必备模板"矩阵为**每个指令**逐个生成用例文件。关键改变：

- **一个指令 = 多个文件**（不再是多指令一个文件）。矩阵保证不漏：每条指令支持的形态都套模板。
- **每个文件只测一个指令的一个类型维度**。前置依赖指令（如 TCPSEND 需先建链）只进 `setup`，断言宽松。
- 文件命名严格按「命名与结构规范」：`<功能块>-<指令>-<类型>-<变体>.yaml`，四段全大写。

这版**故意用宽松断言**（目的不是断言准，而是让指令真实发出去拿响应）：
- 查询/响应类（RESP）先写 `assert: { contains: "OK" }`
- 设置/参数类（PARA）成功路径先写 `assert: { matches: '^\r\nOK\r\n$' }`，边界路径先写 `contains: "ERROR"`
- 功能类（FUNC）先写 `assert: { contains: "OK" }` 或 `contains: "ERROR"` 兜底
- 每个步骤前加 YAML 注释（`# x.x 指令名`）便于对照（注意：Step 不支持 `name` 字段）
- 业务码响应（不以 OK/ERROR 结尾）的步骤先加 `timeout: 1.2` 兜底（见下文"业务码超时陷阱"）

每个文件按单一职责模板填充：
- `tags: [<功能块>, <指令>, <类型>, p0/p1]`（强制前三段）
- `description` 三段：场景前提 + 验证目标 + 探测依据（探测依据第 3 步后回填）
- 需注网的 FUNC 用例，description 写明"需注网"

完整 YAML schema、字段语义见 `references/yaml-schema.md`。
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/atprobe-case-author/SKILL.md
git commit -m "docs(skill): 工作流第2步改造——按矩阵逐指令生成 + 单一职责

从「多指令一个文件」改为「按矩阵为每指令逐个生成文件」。
引用 testcase-matrix.md；强调一文件一指令、前置进 setup、
文件名四段全大写、tags/description 强制三段。"
```

---

## Task 6: 更新 SKILL.md「何时读 references」小节 + YAML 骨架修正

**Files:**
- Modify: `.agents/skills/atprobe-case-author/SKILL.md`（末尾「## 何时读 references」小节 + 「## YAML 最小骨架」小节）

- [ ] **Step 1: 在「何时读 references」追加 testcase-matrix.md 条目**

找到文件末尾的小节：

```markdown
## 何时读 references

- `references/response-patterns.md` —— 第 4 步收紧断言时读取（Neoway 固件回码规律 + 严格正则速查）
- `references/yaml-schema.md` —— 第 2、4 步写用例时读取（完整 schema + 断言操作符表）
```

替换为：

```markdown
## 何时读 references

- `references/testcase-matrix.md` —— **第 1、2 步必读**（每指令必备用例清单矩阵 + 三类型定义 + 自查清单）
- `references/yaml-schema.md` —— 第 2、4 步写用例时读取（完整 schema + 断言操作符表 + tags/description 强制三段约束）
- `references/response-patterns.md` —— 第 4 步收紧断言时读取（Neoway 固件回码规律 + 严格正则速查）
```

- [ ] **Step 2: 修正「YAML 最小骨架」示例使其符合新命名/结构规范**

找到文件中的「## YAML 最小骨架」小节的代码块。当前示例还是单指令但命名/结构需对齐新规范。找到：

```yaml
name: <用例名>
description: |
  <场景前提 + 验证目标 + 探测依据（真实响应格式，第3步后回填）>
tags: [<分类>, p0]
port: COM5    # 可选，仅日志标注；实际发送端口由配置文件 ports[0] 决定

setup:
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }

steps:
  - command: 'AT+CMD?'
    extract:
      val: '\+CMD:\s*(\d+)'
    assert:
      - { name: 严格格式, matches: '^\r\n\+CMD: \d+\r\nOK\r\n$' }
      - { name: 值在范围, var: val, op: in, values: ["0", "1"] }

teardown:
  - command: ATE0
```

替换为（对齐命名规范：tags 三段、description 三段、注释点明文件名）：

```yaml
# 文件名示例：TCP-RECVMODE-RESP-QUERY_FORMAT.yaml
name: TCP-接收模式-查询响应格式(严格字节级)
description: |
  场景前提：N58 COM5，无卡无网场景，无需前置依赖。
  验证目标：AT+RECVMODE? 响应的字节格式（冒号后空格数、字段结构）。
  探测依据：（第3步运行后回填，如 \r\n+RECVMODE: 1,1\r\nOK\r\n）
tags: [TCP, RECVMODE, RESP, p0]
port: COM5    # 可选，仅日志标注；实际发送端口由配置文件 ports[0] 决定

setup:
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }

steps:
  - command: 'AT+RECVMODE?'
    extract:
      val: '\+RECVMODE:\s*(\d+)'
    assert:
      - { name: 严格格式, matches: '^\r\n\+RECVMODE: \d+,\d+\r\nOK\r\n$' }
      - { name: 值在范围, var: val, op: in, values: ["0", "1"] }

teardown:
  - testcase
  - command: ATE0
```

- [ ] **Step 3: 修正骨架里的笔误**

上一步骨架的 teardown 里我留了个笔误 `- testcase`，需删掉。最终 teardown 段应为：

```yaml
teardown:
  - command: ATE0
```

（即在 Step 2 的骨架里把 `  - testcase\n` 那一行删掉。）

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/atprobe-case-author/SKILL.md
git commit -m "docs(skill): 更新 references 引用顺序 + YAML 骨架对齐命名规范

- 「何时读 references」新增 testcase-matrix.md 为第1/2步必读，置顶。
- YAML 最小骨架示例对齐新规范：文件名注释、tags 三段、description 三段。"
```

---

## Task 7: 全文一致性自检

**Files:**
- Read: `.agents/skills/atprobe-case-author/SKILL.md`（全文通读）
- Read: `.agents/skills/atprobe-case-author/references/testcase-matrix.md`
- Read: `.agents/skills/atprobe-case-author/references/yaml-schema.md`

- [ ] **Step 1: 通读三个文件，检查一致性**

逐项核对：

1. **类型代码一致性**：SKILL.md、testcase-matrix.md、yaml-schema.md 三处对 FUNC/RESP/PARA 的定义是否完全一致（无 FUNC/RESP/PARA vs FUNC/RESP/BND 之类的漂移）。
2. **命名段数一致性**：四处提到命名格式（SKILL.md 规范章节、Task 5 改造的第2步、testcase-matrix.md 示例、yaml-schema.md 约束小节）是否都是"4 段全大写"。
3. **交叉引用有效**：SKILL.md 引用 `references/testcase-matrix.md` 的文件名是否与 Task 1 实际创建的文件名完全一致。
4. **无残留旧约定**：SKILL.md 全文搜索是否还有 `<dir>` 小写占位、`suite-<dir>` 之外的多指令文件示例。

- [ ] **Step 2: 修正发现的任何不一致**

就地修正（用 Edit 工具）。常见可能问题：
- 某处写 `suite-<dir>` 而非 `suite-<功能块>` → 统一为后者
- 某处示例还用小写文件名 → 改全大写
- 三类型定义某处漏了 PARA 的"合并 PARAM+BND"说明

- [ ] **Step 3: Commit（如有修正）**

```bash
git add .agents/skills/atprobe-case-author/
git commit -m "docs(skill): 命名规范落地后全文一致性修正

统一类型代码 FUNC/RESP/PARA、命名四段全大写、
suite 文件命名、消除旧约定残留。"
```

（若 Step 1 自检无问题则跳过此 commit。）

---

## Self-Review（计划作者自检）

**1. Spec 覆盖核对**（对照 spec 各节）：

| Spec 节 | 落地任务 |
|---|---|
| §3 命名规范（4段全大写） | Task 3（SKILL 规范章节）+ Task 6（YAML 骨架） |
| §4 三类型体系（FUNC/RESP/PARA） | Task 3（规范章节）+ Task 1（testcase-matrix 定义） |
| §5 必备清单矩阵 | Task 1（testcase-matrix.md 完整承载）+ Task 5（第2步引用） |
| §6 目录结构 + 功能块名来源 | Task 3（规范章节「功能块名从哪来」）+ Task 4（第1步提取流程） |
| §6.3 suite 索引 | 现有 SKILL.md 已有 suite 约定，Task 7 自检确认一致性 |
| §7 用例内部结构（tags/desc 三段） | Task 2（yaml-schema）+ Task 3（规范章节）+ Task 5（第2步）+ Task 6（骨架） |
| §8 模糊即提问 | Task 4（第1步 c 项 + 表格） |
| §9 skill 改造点 | 9.1→Task 3/4/5/6；9.2→Task 1；9.3→Task 2；9.4 不动 |

✅ 全部 spec 节有对应任务，无遗漏。

**2. Placeholder 扫描**：无 TBD/TODO/"适当处理"等。Task 6 Step 3 是修复一个已知的笔误（`- testcase`），已显式说明。

**3. 类型一致性**：三类型代码 FUNC/RESP/PARA 在所有任务中一致。命名格式"4 段全大写"在所有任务中一致。文件名 `testcase-matrix.md` 在 Task 1 创建与 Task 5/6 引用中一致。
