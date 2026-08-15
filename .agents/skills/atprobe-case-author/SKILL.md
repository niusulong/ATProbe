---
name: atprobe-case-author
description: |
  从 AT 指令集文档（通常 docs/at-ref/*.md，或用户指定的文档目录）生成 ATProbe 工具可直接运行的
  端到端测试用例（YAML）。当用户提到「基于指令集/命令手册写测试用例」「把 chXX 文档转成测试用例」
  「生成 AT 指令的 YAML 测试」「补 XX 指令的测试」「为 ATProbe 写端到端用例」，或给出一个指令文档
  路径要求生成测试时，使用本 skill。纯文档驱动：直接依据指令集文档生成严格字节级断言（回车换行、
  空格、错误码），不与实际设备交互。测试的核心目的是验证设备实际运行与文档一致——一切以文档为标准。
  文档信息不完整或存疑时逐步与用户确认。
---

# ATProbe 测试用例生成

把指令集文档（`docs/at-ref/chXX-*.md` 或用户指定的文档目录）转成测试用例 YAML
（约定输出到 `examples/testcases/<功能块>/*.yaml`，或用户指定的用例目录），可直接用
`uv run python -m atprobe run <路径> --config <配置>` 运行。本 skill 不假设特定工作区——
文档目录、用例输出目录、env 配置路径均由用户的工作区决定。

## 命名与结构规范（写任何用例前必读）

> **单一职责是第一原则**：一个用例文件只测**一个指令**的一个维度。失败时能立即定位是哪个指令的哪类问题。
> 不要把多个指令的测试塞进一个文件——历史教训：曾有一个文件含 7 个指令的业务码测试，任一失败都无法定位。

### 文件命名（4 段，全大写）

```
<用例目录>/<平台>/<功能块>/<功能块>-<指令>-<类型>-<变体>.yaml       ← 功能用例
<用例目录>/regress/<平台>/<功能块>/<功能块>-<指令>-REGRESS-<BUGID>.yaml  ← 回归用例
```

| 段 | 规则 | 示例 |
|---|---|---|
| `<功能块>` | 大写，对应指令文档章节功能名；**运行时从文档提取，不硬编码** | TCP / NTP / FTP |
| `<指令>` | 被测指令名，**去掉 AT+ 前缀的裸名**，大写，单一指令 | TCPSEND / UPDATETIME |
| `<类型>` | FUNC / RESP / PARA（功能用例）或 REGRESS（回归用例） | FUNC |
| `<变体>` | 大写、下划线分词，描述本用例的具体测试点；回归用例放 BUGID | NORMAL_SEND / BUG1234567890 |

**目录层级**（按平台隔离，不同平台指令实现可能不同）：

```
testcases/
  EC626/                    ← 平台目录（模组型号/芯片平台名，大写）
    tcp/                    ← 功能块目录（与文件名功能块段一致）
      TCP-TCPSEND-FUNC-NORMAL_SEND.yaml
    ntp/
  regress/                  ← 回归用例顶层（与平台平级，不混进平台功能结构）
    EC626/                  ← 平台目录
      http/                 ← 按功能块归类
        HTTP-HTTPCON-REGRESS-BUG1234567890.yaml
```

> **为什么按平台分**：不同平台（如 EC616/N58/EC626）的 HTTP/MQTT 等指令实现可能完全不同
> （指令名、响应格式、参数都不同），混在一个目录会冲突。`cases_dir` 递归扫描所有子目录，
> 加平台层框架自动识别，无需改框架代码。
> **回归用例为什么单独 `regress/`**：回归用例的归属是 bug 而非功能，与功能用例性质不同，
> 目录层面分开便于回归集独立运行/筛选（`run regress/`）。

示例：
```
EC626/tcp/TCP-TCPSEND-FUNC-NORMAL_SEND.yaml              # 平台功能用例
EC626/tcp/TCP-XIIC-PARA-OVER_N.yaml                      # XIIC 链路号越界 → CME 53
regress/EC626/http/HTTP-HTTPCON-REGRESS-BUG1234567890.yaml  # IPv6 HTTPS 回归
```

### 测试类型

指令中心用例分三类（权威定义见 `references/testcase-matrix.md`）：

- **RESP**（响应格式）——查询/测试指令的响应字节格式，断言用 `matches: '^...$'`
- **FUNC**（功能验证）——正常业务路径 + 该指令自身的业务失败路径（如未建链）
- **PARA**（参数与边界）——合法参数→OK、越界/错误参数→CME；变体名区分（`VALID_*`/`OVER_*`/`WRONG_FORMAT_*`）

另有第四类，独立于指令矩阵：

- **REGRESS**（缺陷回归）——验证某个已修复 bug 不再复现，**变体段放 BUGID**（如 `BUG1234567890`），不走 RESP/FUNC/PARA 矩阵。设计流程见 `references/regression-design.md`。

### 单一职责落地

- **steps 只含被测指令**。前置依赖指令（如 TCPSEND 需先 TCPSETUP 建链）只进 `setup`，且断言宽松（`contains: OK`），不作为断言重点。清理指令进 `teardown`。
- **tags 强制三段**：`[<功能块>, <指令>, <类型>]`，可追加 `p0/p1` 等。例：`tags: [TCP, TCPSEND, FUNC, p0]`。
- **description 强制三段**：场景前提（设备状态/前置依赖/是否需注网）+ 验证目标 + 文档依据（断言依据文档哪段描述/响应格式）。

### 设备状态清洁（setup/teardown 完整生命周期）

> **每条用例执行前后，设备状态都必须是干净的。** 多个用例共享同一设备，若 A 用例的设置指令改变了
> 某参数，B 用例的查询断言就会基于被污染的状态而误判。用例必须自己负责"不留痕迹"。

针对**会改设备状态的指令**（主要是 PARA 设置类、FUNC 动作类），用 setup/teardown 配对保证状态可逆：

- **setup 查初始值**：测试前先查询被改参数的当前值，用 `extract` 存入变量池。
- **steps 测试**：执行被测指令（设置新值/触发动作）。
- **teardown 恢复**：用 `{{var}}` 引用 setup 提取的初始值，把参数设回原值。框架支持 command 里
  `{{var}}` 模板替换（见 step_runner「解析输入，模板替换 {{var}}」）。

```yaml
# 示例：测试 AT+RECVMODE= 设置指令，setup 记录初始值，teardown 恢复
setup:
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }
  - command: 'AT+RECVMODE?'                 # 查初始值
    extract:
      init_n: '\+RECVMODE:\s*(\d)'           # 存入变量 init_n
      init_mode: '\+RECVMODE:\s*\d+,(\d)'    # 存入变量 init_mode
    assert: { contains: "OK" }               # 宽松断言，只为提取

steps:
  - command: 'AT+RECVMODE=0'                 # 被测指令：设置新值
    assert: { matches: '^\r\nOK\r\n$' }

teardown:
  - command: 'AT+RECVMODE={{init_n}},{{init_mode}}'   # 恢复初始值（{{var}} 替换）
  - command: ATE0
```

变体处理：
- 指令**不改设备状态**（如 RESP 查询类、CMDPARSE 指令名拼错）——无需状态恢复，setup/teardown 只放 ATE0 等基础规整。
- 指令改状态但**文档定义了明确的默认值/安全值**——teardown 可直接写死默认值，不必 extract 初始值。
- 动作类指令（如 TCPSEND）建链后的链路——teardown 用 `AT+TCPCLOSE` 主动断开，恢复到未建链状态。

### 功能块名从哪来（通用，不硬编码）

**绝不维护指令集特定的映射表。** 功能块目录名在读文档阶段运行时提取：
1. 读指令文档第 1 行标题（格式 `# 第 X 章 <功能名>`），取"第 X 章"之后的功能名。
2. 功能名是干净英文/ASCII 则规范化大写使用（如 `TCP/UDP...` → 用 `TCP` 或文档约定的短名）。
3. **功能名无法干净提取（如纯中文"网络时间同步"）→ 停下来问用户**，不自动降级、不臆测。

### 功能块级通用用例

测模组指令识别机制（指令名拼错 → CME 58）这类不专属某指令的用例，用特殊指令段 `CMDPARSE`，每功能块最多一个文件：`<功能块>-CMDPARSE-FUNC-INVALID_NAME.yaml`。

### 测试参数 env 化（服务器地址/端口/域名禁止硬编码）

> **凡是用例里要连的服务器地址、端口、域名、平台参数——一律用 env 变量引用，禁止写死。**
> 这些值在不同测试环境间会变（换服务器、换平台、换网络），写死就得改每个用例；用变量则只改一处。

框架支持**环境配置点号引用**（`{{group.param}}`，如 `{{tcp.host}}`、`{{ctwing.product_id}}`），
承载跨用例共享、可修改的固化参数。机制详解见 `references/variables.md`「环境配置」节。

**规则**：用例 command 里凡出现服务器 IP / 域名 / 端口 / 平台参数（ProductID 等），**必须**写成
对应的 env 变量，不得硬编码字面值。

```yaml
# ✅ 正确：服务器地址/端口用 env 变量，换环境只改 env.yaml
steps:
  - command: 'AT+TCPSETUP=0,{{tcp.host}},{{tcp.port}}'
    wait_urc: '\+TCPSETUP: \d+,(OK|FAIL)'
    assert: { contains: "OK" }
  - command: 'AT+CTM2MREG={{ctwing.product_id}},{{ctwing.device_name}}'
    assert: { contains: "OK" }
```

```yaml
# ❌ 错误：硬编码地址端口，换环境就要改用例
steps:
  - command: 'AT+TCPSETUP=0,192.168.1.100,8080'
```

**例外——故意非法的边界测试值保留硬编码**：参数越界 / 格式错误 / 未建链等用例里，故意用非法值
触发错误（如 `AT+TCPSETUP=0,1.2.3.4,80` 触发业务码、`AT+TCPSETUP=6,...` 链路号越界）——这类值
**不是真实服务器地址**，是测试构造的非法输入，必须硬编码（用 env 反而错，env 存的是合法地址）。

**全指令集 env 参数清单见 `references/env-params.md`**：按业务分组列出每个功能块需要的 env 字段、
语义、占位值，并含 env.yaml 模板与「参数对齐工作流」。生成用例前先查它。

## 核心理念：文档是唯一标准，纯文档生成严格断言

**测试的根本目的是验证设备实际运行是否与文档一致**——所以断言的依据必须是**文档**，而非设备实测。

不要把设备实测当成断言依据：设备返回可能与文档不符（那正是测试要发现的 bug），如果拿设备实测
回填断言，就等于"用被测对象的输出定义它自己的正确性"，失去验证意义。因此本 skill **不与设备
交互、不"跑一次拿真实响应"**——所有断言（含回车换行、空格数、错误码数值等字节级细节）**直接从
指令集文档提取**。

文档是断言的唯一标准来源。具体做法：读文档逐指令提取响应格式描述，**直接写成严格字节级断言**
（`matches: '^\r\n...\r\nOK\r\n$'` 等，空格用字面空格、`\r\n` 显式）。

> **区分文档内的「格式规格」与「示例」。** 指令文档通常有两部分：
> - **「命令格式」/「响应格式」表**（含 `<CR><LF>` 等占位符的格式定义）——这是**字节级断言的依据**。
> - **「示例」代码块**（纯文本的输入/输出演示，如 `AT+CMD=...` 回车 `OK`）——这只是**用例设计方案的参考**
>   （告诉你该测哪些场景、参数怎么填），**不是字节级格式依据**。示例常省略 `<CR><LF>`、合并多行、用占位值，
>   直接照抄会得到错误的断言。
>
> 写断言时：**用例设计参考「示例」，字节格式依据「响应格式表」。** 两者冲突时以响应格式表为准。

> **绝不参考其他项目/固件的回码规律。** 不同项目、不同固件下，相同指令的回码格式（空格数、错误码数值、
> 业务码 vs CME）可能完全不同。任何"经验规律"都可能误导。断言的依据只能是**当前项目的指令集文档**。

**文档不完整或存疑时怎么办？** 不要臆测，也不要去跑设备"探测"——**停下来与用户逐步确认**
（见工作流第 1 步「标注待澄清项」）。宁可问清楚再写严格断言，也不要凭猜测写一个可能错误的断言。

## 工作流程（按顺序执行）

> **先判断输入类型，走对应分支**：
> - 目标是**全新平台/芯片**（`response-patterns.md` 无该平台小节、`testcases/<平台>/` 不存在） → **先读 `references/new-platform-onboarding.md`** 完成响应勘测 + 建 env + 定平台目录，再走下方主流程。新平台勿照搬其他固件规律。
> - 用户提供 **bug 报告 / 缺陷现象日志**（含 BUGID、实测结果） → 这是回归用例，**跳到步骤 3'**（按缺陷生成回归用例），深度流程见 `references/regression-design.md`。
> - 用户提供 **指令集文档**（要"生成某指令/某章节的用例"） → 走步骤 1→2→3→4（指令中心主流程）。
> 三条分支共享步骤 2（env 对齐）与步骤 4（自查）。

### 1. 读指令集文档 + 确定功能块名 + 标注待澄清项

读指令集文档（`docs/at-ref/chXX-*.md` 或用户指定的文档目录），做三件事：

**(a) 确定功能块名**（用于目录名和文件名第一段）：
- 读文档第 1 行标题 `# 第 X 章 <功能名>`，取"第 X 章"之后的功能名。
- 功能名是干净英文/ASCII → 规范化大写使用（如文档标题含 `TCP`）。
- **功能名无法干净提取（纯中文、含歧义）→ 问用户**该功能块叫什么，不臆测、不硬编码。

**(b) 逐指令提取**：指令名、参数定义、参数取值范围、支持的形态（`?`/`=?`/`=`/执行）、响应格式描述。
注意区分——**「响应格式表」是断言依据**（含 `<CR><LF>`、空格、字段结构等字节级细节），**「示例」块只是
用例设计参考**（测哪些场景、参数怎么填），不能当字节格式依据。两者冲突以响应格式表为准。

**(c) 标注待澄清项**：遇到以下无法从文档明确判定的情况，**停下来问用户**，不臆测、不跑设备探测：

| 情况 | 处理 |
|---|---|
| 参数语义/取值范围文档未明 | 问用户 |
| 业务逻辑有歧义（如不确定某指令是否需先注网/建链） | 问用户场景前提 |
| 错误码归类有歧义（不确定 CME 53 还是业务码） | 问用户 |
| 前置依赖关系不明 | 问用户 |
| 响应字节格式文档描述不全（如空格数/换行未写明） | 问用户（不同固件回码可能不同，勿参考其他项目） |

**不该问的场景**（文档已明确）：文档明确写出的取值范围/参数格式/响应格式、文档明确标注的指令形态支持情况——这些直接用。

### 2. env 参数对齐（生成用例前必做）

生成用例前，先对齐环境参数，确保用例里的服务器地址/端口/鉴权等用 `{{group.param}}` 引用而非硬编码。
**详细流程见 `references/env-params.md`「参数对齐工作流」节**，核心是：

1. 读 `references/env-params.md` 查本次功能块需要哪些 env 参数；服务器地址/端口的默认值来源是
   **本地文件 `references/server-cluster.local.md`**（不入库的项目测试集群清单，存在时
   需要服务器信息**直接用其中默认值**，不必询问用户；不存在则用 env-params.md 占位值并把
   服务器项列入待补充清单）。读项目 env.yaml 掌握已有真实值。
2. 用例用 `{{group.param}}` 引用；缺失项按清单命名规则记入「待补充 env 项清单」。
3. 生成结束时输出清单（只列缺失项——主要是鉴权/设备类，不含真实值），供用户补到项目 env.yaml。

> skill **不直接改写项目 env.yaml 的真实值**。env-params.md（占位清单）、server-cluster.local.md
> （本地集群默认值）与项目 env.yaml（真实值）三层分离，后两者均不入库。

### 3. 按矩阵逐指令生成用例（严格断言 + 单一职责）

**先读 `references/testcase-matrix.md`**，按"形态 × 必备模板"矩阵为**每个指令**逐个生成用例文件。关键改变：

- **一个指令 = 多个文件**（不再是多指令一个文件）。矩阵保证不漏：每条指令支持的形态都套模板。
- **每个文件只测一个指令的一个类型维度**。前置依赖指令（如 TCPSEND 需先建链）只进 `setup`，断言宽松。
- 文件命名严格按「命名与结构规范」：`<功能块>-<指令>-<类型>-<变体>.yaml`，四段全大写。

断言直接依据文档写成严格字节级（不再分"宽松初版→收紧"两步）：
- 查询/响应类（RESP）按文档响应格式写 `matches: '^\r\n<格式>\r\nOK\r\n$'`（空格用字面空格，`\r\n` 显式）
- 设置/参数类（PARA）成功路径写 `assert: { matches: '^\r\nOK\r\n$' }`；边界路径按文档错误码写 `matches: '^\r\n\+CME ERROR: <码>\r\n$'`
- 功能类（FUNC）按文档描述的业务结果/业务码写 `matches`，业务码响应加 `timeout: 1.2`（见下文"业务码超时陷阱"）
- **异步指令**（文档标「主动上报」，或响应先 OK 后跟 URC）用 `wait_urc` 等 URC 终结（见下文"异步指令陷阱"）
- 每个步骤前加 YAML 注释（`# x.x 指令名`）便于对照（注意：Step 不支持 `name` 字段）
- 文档未写明字节细节时——问用户（原则见「核心理念」，不参考其他项目规律）

每个文件按单一职责模板填充：
- `tags: [<功能块>, <指令>, <类型>, p0/p1]`（强制前三段）
- `description` 三段：场景前提 + 验证目标 + 文档依据（写明断言依据文档哪段描述/响应格式）
- 需注网的 FUNC 用例，description 写明"需注网"

完整 YAML schema、字段语义见 `references/yaml-schema.md`。涉及变量引用、条件执行、参数化、压测、套件时，按需读对应机制 reference（见文末「何时读 references」）。

### 3'. 按缺陷生成回归用例（bug 报告输入走此分支）

用户给出 bug 报告（含 BUGID、缺陷现象日志、实测结果）时，按以下流程生成回归用例。
**完整流程、专项陷阱、问题报告模板见 `references/regression-design.md`（必读）**，此处为精炼版：

1. **解构 bug 报告**：提取 BUGID、所属项目/功能块、缺陷现象日志（关键：触发指令 + 错误码）、发现版本、前置条件。
2. **定位验证点**：区分这是"指令参数/格式问题"还是"业务功能问题"。后者（如 IPv6 连接缺陷）需完整业务前置链（注网/拨号/建链），复杂度高。
3. **查文档定响应格式**：**从指令文档确认触发指令是同步（成功直接 OK）还是异步（OK+URC）**——这是断言依据，不可臆测，不可照搬其他项目规律。历史教训：误把同步指令当异步用 `wait_urc` → 等满 timeout 必然失败。
4. **设计 setup（业务前置链）**：注网判断用 `AT+CEREG?`（`<stat>=1/5` 才算成功，`CGATT=1` 的 OK 仅受理）；地址查询（`CGPADDR`）宽松断言（地址格式由网络决定，可能是十进制点分字节，不严格校验）；setup 首步 `ATE0` 加 `retry` 兜底串口抖动。
5. **设计断言（bug 反向断言）**：steps 只含触发指令，断言"修复后正确响应"+"bug 错误码不再出现"（`not_contains`）。缺陷报告里的复现步骤/参数**不能照搬**（如 PDP 类型 IPV4V6 vs IPV6 要按实测卡调整）。
6. **命名 + teardown + 问题报告**：文件名 `<功能块>-<指令>-REGRESS-<BUGID>.yaml`（如 `HTTP-HTTPCON-REGRESS-BUG1234567890.yaml`）；teardown 必须双层资源清理（连接层 + 实例层，见陷阱节）；同步输出问题报告字段填充（前置条件/执行步骤/预期/实测）。

> 回归用例的 env 引用同样走步骤 2（服务器地址等用 `{{group.param}}`，默认值来源 `references/server-cluster.local.md`）。

### 4. 自查用例完整性（交付前）

生成完所有用例后，做两件事：

**① 跑验证脚本**（一键校验全部生成的用例，复用框架校验逻辑）：
```bash
uv run python <skill目录>/scripts/validate-cases.py <生成的用例目录> --env <env.yaml路径>
```
（`<skill目录>` 是本 skill 所在路径，如 `.agents/skills/atprobe-case-author`；`<env.yaml路径>`
是目标工作区的 env 配置。若工作区尚无 env.yaml，从 `assets/env.yaml.example` 复制初始化。）
脚本校验：YAML 解析/schema、extract/assert/wait_urc 正则编译、env 引用存在性、文件名四段规范。
atprobe 未安装时自动降级为基础校验（YAML 语法 + 正则 + 文件名）并提示安装。全部通过才交付。

**② 对照 `references/testcase-matrix.md` 末尾「自查清单」逐项核对**，确保：
- 每个指令支持的形态都有对应类型用例，无遗漏
- 每个数值参数都有越界用例（若文档给了范围）
- 动作指令有 FUNC-NORMAL（成功）和 FUNC-NOLINK/PRECONDITION_FAIL（前提失败）
- 业务码响应步骤都加了 `timeout`
- 断言的正则与文档描述的响应格式严格对应（空格数、换行、错误码数值）
- **改设备状态的用例，setup 查了初始值且 teardown 用 `{{var}}` 恢复**（见「设备状态清洁」原则）

> 本 skill 只负责**生成**用例，不负责运行。用例的运行与设备验证由用户后续用
> `uv run python -m atprobe run <目录> --config <配置>` 执行。

### 5. 上设备实测（文档为标准，实测偏差是测试发现）

本 skill 只负责**生成**用例。用例上设备运行由用户用
`uv run python -m atprobe run <用例/目录> --config <配置>` 执行。

**核心原则：文档是唯一事实源，实测不符时不急着改用例。** 严格断言（`matches`）按文档写，
设备实测若不符，**这恰恰是测试的价值——捕获了设备实现的偏差**，不要反过来用设备改断言。

实测不符时的正确处理（按顺序）：
1. **先确认断言写对了**：重读文档该指令的响应格式描述，确认断言与文档严格对应（空格数/换行/错误码数值）。
2. **断言没错、设备不符 = 测试发现**：保留断言不动。这正是测试要捕获的——可能是：
   - 设备固件 bug（实现与文档不一致）；
   - 固件版本与文档版本不匹配；
   - 设备状态/前置条件未真正满足（如以为无 PDP 实则有）。
3. **记录为缺陷**：把实测偏差（实测响应原文 + 与文档的差异）记录为 bug 报告，后续可走步骤 3' 生成 REGRESS 回归用例。
4. **不急着改断言迎合设备**：除非经厂商确认是文档勘误（文档本身写错），才据勘误修正断言。

> 工具支持：框架在步骤**非 PASS 时自动打印原始响应**（`resp: <CR><LF>...`，`\r\n` 转义可见），
> 无需开 debug 级，便于直接对照文档看偏差在哪。PASS 步骤的响应只在 debug 级（`--log-level debug`）显示。

**何时用宽松断言（`contains`/`not_contains`）vs 严格断言（`matches`）**：
- 文档明确给出确切码值/格式 → 严格 `matches`（最大化捕获设备偏差）。
- 文档只写「ERROR」/「失败」未给具体码值 → 宽松 `contains: "ERROR"`（文档本身未精确到码值，不强求）。
- 测试前提未满足的路径（如无卡设备跑需 SIM 的用例）属预期不符，不算缺陷。

## 关键陷阱（已踩过，务必避免）

### 业务码超时陷阱

框架的响应终结判定只认 `OK` / `ERROR` / `+CME ERROR:.*` / `+CMS ERROR:.*` 四种行。
Neoway 业务码（如 `+TCPSETUP: ERROR`、`+IPSTATUS: 0,DISCONNECT`、`+PDPSTATUS: DISCONNECT`）
**不被识别为响应结束**，会等满步骤超时（默认 5s）。这些指令响应实际 100ms 内返回。

**对策**：这类步骤加 `timeout: 1.2`（兜底即可，不影响断言正确性，只是避免空等）。
怎么判断某步是业务码？看文档响应描述——若该指令的正常响应不以 `OK`/`ERROR`/`+CME ERROR`/`+CMS ERROR`
结尾（如返回 `+IPSTATUS: 0,DISCONNECT` 这类状态码），即为业务码，需加 timeout。

### 异步指令陷阱（OK 仅受理 ≠ 成功；用 wait_urc）

异步指令（如 `AT+CTM2MREG`、`AT+CTM2MDEREG`、`AT+CTM2MSEND`、`AT+CTM2MUPDATE`）的响应
分两段：先返回 `OK`（仅表示**指令被受理**），随后异步上报 URC 才是真正结果（如
`+CTM2M:reg,0`、`+CTM2M:dereg,0,<id>`、`+CTM2M:send,0,<id>`）。

**陷阱**：框架默认遇 `OK` 即终结该步（`connection.py` 的 OK 终结判定）。若不显式声明，
`OK` 之后的 URC 不会进入 `Response.text`，用例**无法对 URC 的字节格式**（冒号无空格、
成功码 `=0`、`<id>` 一致性等）**做断言**——而那正是异步指令测试的核心价值。

**对策**：在这类指令的步骤上加 `wait_urc: '<URC 正则>'`。开启后框架行为变为——遇 `OK` 不终结，
继续读到**匹配该正则的 URC 立即返回**（不空等 timeout），整段 `Response.text` 含 `OK\r\n\r\n+URC...`，
断言正则可整体匹配 OK+URC。`wait_urc` 是正则字符串，精准指定预期 URC，避免被无关 URC 干扰。

```yaml
# 异步指令典型写法：AT+CTM2MDEREG
steps:
  - command: AT+CTM2MDEREG
    wait_urc: '\+CTM2M:dereg,0,\d+'        # 等待这条 URC 才算终结
    timeout: 10                            # OK+URC 总等待上限（秒）
    assert:
      # 整段响应（OK+URC）字节级断言——这才是异步指令测试的价值
      - { name: 整段格式, matches: '^\r\nOK\r\n\r\n\+CTM2M:dereg,0,\d+\r\n$' }
      - { name: 成功码为0, contains: "dereg,0," }
```

受理行含 `<id>`、URC 也含 `<id>` 时，用 `\1` 反向引用校验 MsgID 一致性：

```yaml
  - command: AT+CTM2MSEND=...
    wait_urc: '\+CTM2M:send,0,\d+'
    timeout: 10
    assert:
      # 受理行 id 与 URC id 必须一致（\1 反向引用）
      - { matches: '^\r\n\+CTM2MSEND:(\d+)\r\nOK\r\n\r\n\+CTM2M:send,0,\1\r\n$' }
```

**约束**：
- `wait_urc` 与 `poll` **互斥**（poll 轮询同步查询也能确认异步末态，语义重叠，二选一）。
- `wait_urc` 可与 `retry` 共存（retry 包裹「发→等 URC→断言」的完整单次尝试）。
- 框架行为细节：OK 后 `_process_incoming` 继续累积，URC 正则**匹配即立即入队返回**
  （不空等）；timeout 内无 URC → status=TIMEOUT（text 含已收到的 OK 段，断言照常跑）。
- **纯被动 URC**（无指令前导，如平台主动下行的 `+CTM2MRECV`）本机制不直接支持——它依赖
  「前面发了指令并收到 OK」的前提。测纯被动 URC 需另设计 URC 监听用例类型。

### 同步指令陷阱（误用 wait_urc 必然超时）

与异步指令陷阱相反——**同步指令成功直接返回 OK，没有后续 URC**。若误加 `wait_urc`，框架遇 OK 不终结，
死等一个永远不存在的 URC，等满 timeout 后步骤判失败。

**判据**：看文档该指令的响应描述——若成功响应就是 `OK`（或带结果码的单段响应），无「主动上报」/
「OK 后跟 URC」描述，即为同步指令。**同步指令绝不能加 `wait_urc`**，用普通 `assert: { matches: '^\r\nOK\r\n$' }` 即可。

历史教训：`AT+HTTPCON` 文档明确「成功返回 OK」，误当异步加 `wait_urc: '\+HTTPCON: \d+'` → 等满 30s 超时失败。
同类风险指令：HTTP 系列、TCPSETUP（注意 TCPSETUP 是异步，HTTPCON 是同步，仅差一字，必须逐条查文档）。

### 双层资源清理陷阱（teardown 残留会连锁污染后续用例）

带实例/连接语义的协议（HTTP/MQTT/FTP 等）资源分**两层**：连接层（HTTPCLOSE/MQTTDISCONNECT）和实例层
（HTTPDESTROY/MQTTDESTROY）。teardown **只关连接不销毁实例** → 实例对象残留 → 下个用例 `HTTPCREATE`
复用同实例号时冲突失败（现象：5s 无响应）。多用例共享同一设备时，一个用例清理不完整会**连锁污染**后续用例。

**对策**：这类用例 teardown 一律**先关连接再销毁实例**，两条都加 `on_failure: continue`（连接未建立时关闭指令可能报错，属正常，跳过继续清理）：

```yaml
teardown:
  - command: AT+HTTPCLOSE=0        # 连接层
    timeout: 3
    on_failure: continue
  - command: AT+HTTPDESTROY=0      # 实例层
    timeout: 6
    on_failure: continue
  # ...其余清理
```

诊断线索：若某用例 setup 的创建指令（HTTPCREATE/MQTTOPEN 等）5s 无响应而前后用例正常，优先排查上一用例
teardown 是否漏销毁实例。

### suite 文件的两种运行方式

`suite-<功能块>.yaml` 有两种运行方式，不要混淆：

- **`run suite-xxx.yaml`**：按套件 `cases` 列表顺序执行用例，`suite_setup`/`suite_teardown` 生效。
- **`run <目录>`**：执行目录下**所有用例**（按文件名排序），自动跳过 `suite-` 前缀文件——
  此模式下套件文件只是索引文档，其 `cases` 列表**不**被读取。

> 注意：不能把套件文件当普通用例直接解析（套件 schema 无 `steps`，会报 `steps: Field required`），
> 但 `run suite-xxx.yaml` 会走套件路径正确处理。

## YAML 最小骨架

```yaml
# 文件名示例：<功能块>-<指令>-<类型>-<变体>.yaml
name: <功能块>-<指令概述>-<变体>(严格字节级)
description: |
  场景前提：<设备状态/有无SIM/是否注网/前置依赖，据实填写>。
  验证目标：<本用例验证什么>。
  文档依据：<断言依据文档哪节响应格式描述，如"据文档6.x节，响应为 \r\n+CMD: <value>\r\nOK\r\n">
tags: [TCP, RECVMODE, RESP, p0]
port: COM5    # 可选，仅日志标注；实际发送端口由配置文件 ports[0] 决定（按工作区实际端口填）

setup:
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }

steps:
  - command: 'AT+<CMD>?'
    extract:
      val: '\+CMD:\s*(\d+)'            # 按文档实际响应格式调整正则
    assert:
      - { name: 严格格式, matches: '^\r\n\+CMD: <文档格式>\r\nOK\r\n$' }  # 据文档响应格式表
      - { name: 值在范围, var: val, op: in, values: ["0", "1"] }            # 据文档取值范围

teardown:
  - command: ATE0
```

更多字段（retry/poll/when/on_failure/data 输入等）和完整断言语法读 `references/yaml-schema.md`；这些机制的深入用法见 `control-flow.md`（retry/poll/when/on_failure）、`variables.md`（变量引用）、`parameters.md`/`pressure.md`/`suite.md`。

## 何时读 references（渐进式按需加载）

写用例时按当前需要读对应机制说明，不必一次全读：

- `references/new-platform-onboarding.md` —— **新平台/芯片从零起步必读**（全新模组先勘测响应规律、建 env、定目录、走主流程的 5 步；勘测产物清单）
- `references/testcase-matrix.md` —— **第 1、3 步必读**（每指令必备用例清单矩阵 + 三类型定义 + 自查清单）
- `references/regression-design.md` —— **步骤 3'（bug 回归）必读**（回归用例 7 步设计流程 + 专项陷阱 + 问题报告模板）
- `references/response-patterns.md` —— **写严格断言时查**（通用响应骨架 + 各平台实测速查：数据行空格/业务码/CME码/同步异步；新平台勘测结果沉淀处）
- `references/env-params.md` —— **第 2 步必读**（全指令集 env 参数清单 + env.yaml 模板，env 参数对齐用）
- `references/yaml-schema.md` —— **字段速查**（顶层 Case/Step 字段 + 断言操作符表 + extract/data 规则 + 严格字节级示例）
- `references/variables.md` —— 用到**变量**时读（`{{var}}` 引用 / extract 提取 / 作用域 / 内置变量 / 跨端口共享 / env 点号引用）
- `references/control-flow.md` —— 用到**条件或重试**时读（`when` 条件跳过 / if-else 模拟 / `on_failure` / `retry` / `poll` / `wait_urc`）
- `references/parameters.md` —— 写**参数化**用例时读（`parameters` 矩阵展开多次执行）
- `references/pressure.md` —— 写**压测**用例时读（`loop` 循环 / 压测语义 / 统计维度）
- `references/suite.md` —— 组织**套件**时读（`suite` 定义 / 执行顺序 / 目录结构）
- `references/conventions.md` —— 随时查**书写规范**（正则单引号规范 / tags 系统 / name 唯一性 / 超时仅步骤级）
