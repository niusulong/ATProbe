# ATProbe 测试用例命名与结构规范

- **状态**：设计已确认，待实现
- **日期**：2026-06-30
- **范围**：仅定义命名/目录/结构新规范；老用例迁移另起独立 plan，不在本 spec 范围内
- **影响产物**：`atprobe-case-author` skill（`.agents/skills/atprobe-case-author/`）的 SKILL.md 及 references；不动框架源码

## 1. 背景与问题

当前 `atprobe-case-author` skill 对用例的命名与目录结构**几乎无规范**，导致：

1. **命名不规范**：目录/文件名小写（`tcp/`、`tcp-param_boundary.yaml`），看不到被测指令，测试类型混在功能词里。
2. **职责混杂**：单个文件塞多个指令。最严重的是 `tcp-link_ops_nolink.yaml` 一个文件含 7 个指令（TCPSETUP/TCPSEND/TCPCLOSE/IPSTATUS/TCPACK/UDPSETUP/UDPCLOSE）的业务码测试——任一失败无法定位是哪个指令。
3. **无遗漏防护**：没有"每条指令该有哪些用例"的清单机制，凭经验写，容易漏掉边界或响应格式。
4. **通用性顾虑**：skill 必须保持指令集无关，不能为某一指令集（如 Neoway N58）硬编码映射表。

## 2. 设计目标

- **单一职责**：一个用例文件只测一个指令的一个维度，失败可立即定位。
- **命名直观**：文件名一眼看出"哪个功能块 / 哪个指令 / 什么测试类型 / 什么变体"。
- **防遗漏**：提供"按指令形态套模板"的必备用例清单，照做即不漏。
- **通用性**：规范不依赖任何具体指令集，功能块名等动态信息从指令文档运行时提取，模糊则问用户。

## 3. 命名规范

### 3.1 文件名结构（4 段，全大写）

```
examples/testcases/<功能块>/<功能块>-<指令>-<类型>-<变体>.yaml
```

| 段 | 规则 | 示例 |
|---|---|---|
| `<功能块>` | 大写，对应指令文档章节功能名；运行时从文档提取，不硬编码 | `TCP` / `NTP` / `FTP` |
| `<指令>` | 被测 AT 指令名，**去掉 `AT+` 前缀的裸名**，大写，单一指令 | `TCPSEND` / `UPDATETIME` |
| `<类型>` | 4 字母代码，三选一：`FUNC` / `RESP` / `PARA` | `FUNC` |
| `<变体>` | 大写、下划线分词，描述本用例的具体测试点 | `NORMAL_SEND` / `OVER_LENGTH` |

**全大写规则**：四段全部大写，包括变体段。下划线仅用于段内多词分隔。

**真实示例：**

```
TCP-TCPSEND-FUNC-NORMAL_SEND.yaml       # 数据发送的正常业务路径
TCP-TCPSEND-FUNC-NOLINK.yaml            # 未建链的业务失败路径
TCP-TCPSEND-PARA-VALID_LENGTH.yaml      # 合法长度参数 → OK
TCP-TCPSEND-PARA-OVER_LENGTH.yaml       # 长度越界 → CME 53
TCP-RECVMODE-RESP-QUERY_FORMAT.yaml     # 查询响应字节格式
NTP-UPDATETIME-RESP-TEST_RANGE.yaml     # 测试命令取值范围格式
TCP-CMDPARSE-FUNC-INVALID_NAME.yaml     # 功能块级：指令名拼错
```

### 3.2 硬性规则

1. **一个文件 = 一个指令**：`steps` 内所有断言都针对同一被测指令的不同变体/参数。前置依赖指令只进 setup/teardown。
2. **指令段用裸名**：`TCPSEND` 而非 `ATTCPSEND` / `+TCPSEND`，功能块段已隐含分类。
3. **功能块级通用用例**：测模组指令识别机制（如指令名拼错 → CME 58）这类不专属某指令的用例，用特殊指令段 `CMDPARSE`，每功能块最多一个文件。

## 4. 测试类型体系（3 类）

| 类型代码 | 名称 | 定义 | 断言重点 |
|---|---|---|---|
| **RESP** | 响应格式 | 校验查询（`?`）和测试（`=?`）指令的**响应字节格式**：空格数、换行、字段结构。不关心值对错，只关心格式骨架 | `matches: '^...$'` 严格字节级 |
| **FUNC** | 功能验证 | 在**正常/真实业务路径**下指令是否做了该做的事。含成功路径 + 该指令**自身**的业务失败路径（如未建链） | 业务结果码 / 业务码 |
| **PARA** | 参数与边界 | 指令**合法参数**是否被接受（→ OK）**以及**非法/越界参数是否被拒绝（→ CME）。变体名区分 success/fail | `OK` 或 `+CME ERROR: <code>` |

### 4.1 PARAM 与 BND 合并的依据

合并为单一 `PARA` 类，用变体名区分：
- `PARA-VALID_*` → 合法参数，断言 OK
- `PARA-OVER_*` / `PARA-UNDER_*` → 越上下限，断言 CME
- `PARA-WRONG_FORMAT_*` / `PARA-NO_QUOTE` 等 → 格式错，断言 CME

理由：参数校验与边界测试针对的是同一组指令（设置类），只是断言期望不同（OK vs CME）。合并后一个指令的参数维度集中在同一类型下，便于整体查漏，且变体名已显式标注 success/fail。

### 4.2 业务失败路径归 FUNC 的依据

指令**自身前提不满足**（如 TCPSEND 未建链）属于该指令的正常行为范畴，归 FUNC，不另设错误类。保持"单一指令"原则不破。业务码（`+TCPSEND: ERROR`）与 CME 错误码（参数越界）走不同类型，语义清晰。

## 5. 每指令必备用例清单矩阵（防遗漏核心）

AT 指令按 3GPP 有 4 种形态。**读文档看该指令支持哪些形态，每个形态套下表模板，汇总即该指令全部必备用例**。按形态查漏，不凭经验。

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

**跨类型说明**：带参数的动作指令（如 TCPSEND）有两条独立验证线：
- **PARA 类**测"参数是否被接受"（断 OK/CME）——不实际触发业务
- **FUNC 类**测"动作是否真的发生"（断业务结果）——需真实环境

两条线不冲突，各自独立成文件。

### 5.1 完整示例：TCPSEND 指令的文件集

```
TCP-TCPSEND-PARA-VALID_LENGTH.yaml      # 合法长度 → OK
TCP-TCPSEND-PARA-OVER_LENGTH.yaml       # 4097 → CME 53
TCP-TCPSEND-FUNC-NORMAL_SEND.yaml       # 实际发送成功（description 注明需注网）
TCP-TCPSEND-FUNC-NOLINK.yaml            # 未建链 → +TCPSEND: SOCKET ID OPEN FAILED
```

## 6. 目录结构与 suite 索引

### 6.1 目录结构

```
examples/testcases/
├── TCP/                                  # 功能块目录，大写
│   ├── TCP-NETAPN-RESP-QUERY_FORMAT.yaml
│   ├── TCP-XIIC-RESP-QUERY_FORMAT.yaml
│   ├── TCP-RECVMODE-RESP-QUERY_FORMAT.yaml
│   ├── TCP-RECVMODE-RESP-TEST_RANGE.yaml
│   ├── TCP-NETAPN-PARA-VALID.yaml
│   ├── TCP-NETAPN-PARA-NO_QUOTE.yaml
│   ├── TCP-XIIC-PARA-OVER_N.yaml
│   ├── TCP-TCPSEND-PARA-VALID_LENGTH.yaml
│   ├── TCP-TCPSEND-PARA-OVER_LENGTH.yaml
│   ├── TCP-TCPSEND-FUNC-NORMAL_SEND.yaml
│   ├── TCP-TCPSEND-FUNC-NOLINK.yaml
│   ├── TCP-TCPSETUP-FUNC-NOLINK.yaml
│   ├── TCP-TCPCLOSE-FUNC-NOLINK.yaml
│   ├── TCP-IPSTATUS-FUNC-QUERY.yaml
│   ├── TCP-CMDPARSE-FUNC-INVALID_NAME.yaml
│   └── suite-TCP.yaml
├── NTP/
│   ├── NTP-UPDATETIME-RESP-QUERY_FORMAT.yaml
│   ├── NTP-UPDATETIME-RESP-TEST_RANGE.yaml
│   ├── NTP-UPDATETIME-FUNC-NORMAL.yaml
│   └── suite-NTP.yaml
└── ...
```

### 6.2 功能块目录名来源（通用，不硬编码）

**不维护指令集特定的映射表**。功能块目录名由 skill 在读文档阶段**运行时提取**：

1. 读指令文档第 1 行标题（格式 `# 第 X 章 <功能名>`）。
2. 提取"第 X 章"之后的功能名部分。
3. 若功能名是干净的英文/ASCII（如 `TCP/UDP客户端指令` 含 `TCP`），规范化为大写去特殊字符（→ `TCPUDP`，或文档已约定短名则取短名）。
4. **若功能名无法干净提取（如纯中文"网络时间同步"），停下来问用户**该章节的功能块名，不自动降级、不硬编码。

提取规则同样适用于文档文件名（`chXX-<功能名>.md`）作为备选来源。

### 6.3 suite 索引文件

保持现有 `suite-<功能块>.yaml` 约定，明确其定位与 schema：

- **定位**：文档索引，**不可执行**（`run suite-xxx.yaml` 会报错）。运行方式是 `run <目录>`。
- **schema**：只列文件名清单，不含可执行 step。框架目录扫描时自动跳过 `suite-` 前缀文件避免重复。
- **用例顶层 name**：语义化中文短语（如"TCP-数据发送-正常发送(严格字节级)"），报告展示用顶层 `name` 而非文件名。

```yaml
# suite-TCP.yaml 示例
name: TCP/UDP客户端指令测试套件
description: |
  ch06 TCP/UDP 客户端指令端到端测试集合。
tags: [TCP, regression]
cases:
  - TCP-NETAPN-RESP-QUERY_FORMAT.yaml
  - TCP-XIIC-RESP-QUERY_FORMAT.yaml
  # ... 按文件名列出
```

## 7. 单一职责的用例内部结构

```yaml
name: TCP-数据发送-正常发送(严格字节级)       # 语义化中文，报告展示用
description: |
  验证 AT+TCPSEND 在已建链状态下发送数据的业务成功路径。
  场景前提：需注网 + 已用 AT+TCPSETUP 建链（本用例 setup 携带）。
  验证目标：发送后返回成功业务码。
  探测依据：（第3步运行后回填真实响应格式）
tags: [TCP, TCPSEND, FUNC, p0]                # 强制含功能块+指令+类型
port: COM5

setup:                                         # 前置依赖只进 setup，宽松断言
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }
  - command: AT+TCPSETUP=0,<ip>,<port>
    assert: { contains: OK }                   # 仅宽松确认建链，不喧宾夺主

steps:                                         # steps 只含被测指令本身
  - command: AT+TCPSEND=0,<length>
    assert:
      - { name: 发送成功业务码, matches: '^\r\n\+TCPSEND: <真实格式>\r\n$' }

teardown:
  - command: AT+TCPCLOSE=0
  - command: ATE0
```

**3 条硬规则：**

1. **steps 只含被测指令**。前置/清理指令进 setup/teardown，其断言保持宽松（`contains: OK`），不作为断言重点。
2. **tags 强制三段** `[<功能块>, <指令>, <类型>]`，便于按维度筛选遗漏。可附加优先级（`p0/p1`）等。
3. **description 强制三段**：`场景前提`（设备状态/前置依赖/是否需注网）+ `验证目标` + `探测依据`（第3步运行后回填真实响应格式）。

## 8. 模糊即提问（通用行为准则）

参考 brainstorming skill 的交互式澄清哲学，`atprobe-case-author` skill 在工作流第 1 步（读文档）及全程，遇到**无法从文档明确判定**的情况**停下来问用户**，不臆测。

### 8.1 应当提问的场景

| 场景 | 示例 | 处理 |
|---|---|---|
| 功能块名无法干净提取 | 纯中文标题、含歧义字符 | 问用户功能块名 |
| 参数语义/取值范围文档未明 | 文档只写"参数为数字"无范围 | 问用户，或标注"待第3步运行探测" |
| 业务逻辑有歧义 | 不清楚某指令是否需先注网/建链 | 问用户场景前提 |
| 错误码归类有歧义 | 不确定返回 CME 53 还是业务码 | 标注待第3步运行确认 |
| 前置依赖关系不明 | 不清楚某动作指令的前置条件链 | 问用户 |

### 8.2 不应提问的场景（走既有闭环）

- 能从文档明确读出的取值范围、参数格式 → 直接用
- 能从一次运行拿到真实响应的字节格式 → 走"宽松断言→运行→收紧"闭环（第2-5步）
- 文档明确标注的指令形态支持情况（`?`/`=?`/`=`/执行） → 直接套矩阵

**判定准则**：信息有唯一确定来源（文档或运行）时不问；存在多种合理解释或信息缺失时问。

## 9. skill 改造点（实现指引）

本 spec 落地为对 `.agents/skills/atprobe-case-author/` 的改造，不动框架源码。

### 9.1 SKILL.md 改造

1. **新增"命名与结构规范"章节**（本 spec §3-7 的精简版），置于工作流之前作为前置约束。
2. **工作流第 1 步新增"功能块名提取"子步骤**：读文档第 1 行提取功能名，抽不出则问用户（§6.2、§8）。
3. **工作流第 2 步改造**：从"写一个多指令初版文件"改为"按矩阵为每个指令逐个生成文件"（§5）。
4. **工作流第 2 步强调单一职责**：每个文件只一个指令，前置依赖进 setup（§7）。
5. **强化"模糊即提问"**：在工作流描述里明确哪些情况问用户（§8）。
6. **保留既有核心闭环**：宽松断言→运行→收紧断言→验证反证（skill 现有第2-5步不动）。

### 9.2 新增 references/testcase-matrix.md

把 §5 的"每指令必备用例清单矩阵"独立成 reference 文件，供 skill 第 2 步按需读取。内容：形态×模板表、跨类型说明、TCPSEND 完整示例。

### 9.3 references/yaml-schema.md 微调

补充 `tags` 强制三段约束、`description` 强制三段结构的说明（§7）。

### 9.4 references/response-patterns.md 不动

该文件是 Neoway 固件回码规律，属于"探测后回填断言"阶段的事实参考，与命名/结构规范正交。

## 10. 老用例迁移（附录，不在本 spec 实施范围）

现有 `examples/testcases/` 下 5 个文件可按本规范重组，作为新规范的首批示范。迁移原则：保留原有断言内容，只重组文件边界，不重新探测、不改变覆盖度。具体迁移将另起独立 plan。

| 现有文件 | 拆分方向 |
|---|---|
| `tcp-setup_query_format.yaml`（8 指令） | 按指令拆 `RESP-QUERY_FORMAT` / `RESP-TEST_RANGE` |
| `tcp-param_boundary.yaml`（多指令） | 按指令拆 `PARA-VALID` / `PARA-OVER_*` / `PARA-NO_QUOTE` |
| `tcp-link_ops_nolink.yaml`（7 指令） | 按指令拆 `FUNC-NOLINK` / `FUNC-QUERY` |
| `tcp-invalid_command.yaml` | `TCP-CMDPARSE-FUNC-INVALID_NAME.yaml` |
| `ntp/ntp-updatetime_query.yaml` | `NTP-UPDATETIME-RESP-*` + `NTP-UPDATETIME-FUNC-*` |

## 11. 验收标准

规范落地后，对任意一条新指令（以 TCPSEND 为例）应满足：

- [ ] 文件名符合 `<功能块>-<指令>-<类型>-<变体>.yaml` 四段全大写格式
- [ ] 每个文件 `steps` 只含同一被测指令
- [ ] 按矩阵自查，该指令所有支持的形态都有对应用例，无遗漏
- [ ] 依赖前置的 FUNC 用例，前置指令在 setup，断言宽松
- [ ] 需注网的 FUNC 用例 description 写明场景前提
- [ ] tags 含三段，description 含三段
- [ ] 功能块名从文档提取，未硬编码任何指令集映射
