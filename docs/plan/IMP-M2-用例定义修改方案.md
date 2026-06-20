# M2 测试用例定义 — 修改方案（落实审查报告）

> 版本：v1.0
> 日期：2026-06-17
> 状态：草稿
> 依据：`docs/review/REV-M2-审查报告.md`（v1.0）
> 修改对象：`docs/requirements/REQ-M2-测试用例定义.md`、`docs/requirements/REQ-M1-串口通信管理.md`

---

## 0. 方案总览

本文件将审查报告中的问题（🔴×4 / 🟡×5 / 🟢×6）逐项转化为**可落地的设计方案**，每项给出：问题回顾 → 设计目标 → 具体方案（含 schema）→ 影响范围。

**核心设计原则（贯穿全文，先读这一节）：**

1. **步骤字段正交化**：步骤拆为「输入方式 / 行为修饰符 / 输出处理 / 失败处理」四组正交字段，可自由组合（见 §2.1 统一步骤模型）。
2. **表达式模型统一**：`when`、`poll.until` 等条件表达式统一采用「变量名引用」而非 `{{}}` 文本替换；`{{var}}` 仅保留用于 `command` 字符串、`data.inline`、`send_file.path` 等**字符串内容**的模板替换（受控场景）。
3. **最小破坏性**：旧的单键断言 `{ contains: "OK" }`、`when: '{{var}} == ...'` 作为兼容写法保留，引擎内部归一化到新模型。

---

## 1. 严重问题方案（🔴 必做）

### 2.1 统一步骤模型（前置定义，S1/S2/S4 共用）

修订后一个**步骤（step）**由四组正交字段组成：

| 字段组 | 字段 | 说明 |
|--------|------|------|
| **输入方式**（三选一） | `command` / `send_file` / `data` | 发送什么，详见 §1.1（S1） |
| **行为修饰符**（可选） | `retry` / `poll` / `when` / `timeout` / `interval` / `port` | 怎么发、何时发 |
| **输出处理**（可选） | `extract` / `assert` | 提取变量、断言验证 |
| **失败处理**（可选） | `on_failure` | 步骤失败策略 |

> 通用约束：输入方式三选一（缺省时 `command` 必填）；`retry` 与 `poll` 互斥（语义冲突）；`poll` 步骤可叠加 `retry`，但默认 retry 不应用于 poll（避免无限循环）。

这一模型使 setup / teardown / steps 字段共用同一结构，降低学习成本。

---

### 1.1 S1 — 数据输入衔接（M1 + M2 联动）

**设计目标**：让 M1 §3 的三种数据输入（直接输入 / 文件输入 / 长数据输入）在用例步骤中可表达。

**方案**：步骤输入字段扩展为三选一，语义对齐 M1 §3。

```yaml
steps:
  # 方式1：直接输入（短命令）—— 对应 M1 §3.1
  - command: AT
    assert: { contains: "OK" }

  # 方式2：文件输入 —— 对应 M1 §3.2
  - send_file:
      path: firmware.bin            # 必填，支持 {{var}} 模板替换
      mode: chunk                   # whole(默认) / line / chunk
      chunk_size: 1024              # 仅 chunk 模式，默认 1024
      line_separator: "\n"          # 仅 line 模式，默认 \n
      skip_empty: true              # 仅 line 模式，默认 true
      skip_comment: true            # 仅 line 模式（跳过 # 开头），默认 true
      encoding: UTF-8               # 文本编码，默认 UTF-8
    assert: { contains: "OK" }

  # 方式3：长数据输入 —— 对应 M1 §3.3
  - data:
      hex: "0102FF0A"               # HEX 字符串（与 inline 二选一）
      # inline: "{{payload}}"       # 内联/变量引用（与 hex 二选一）
      chunk: true                   # 是否分块，默认 false（超阈值自动启用）
      chunk_threshold: 4096         # 默认 4096
      chunk_size: 1024              # 默认 1024
      chunk_interval: 50            # 块间间隔(ms)，默认 50
      append_terminator: false      # 是否追加结束符，默认 false
    assert: { contains: "OK" }
```

**字段对齐表（M1 ↔ M2）：**

| M1 §3 参数 | M2 步骤字段 | 默认值 |
|-----------|------------|--------|
| §3.2 文件路径 | `send_file.path` | 必填 |
| §3.2 发送模式 | `send_file.mode` | whole |
| §3.2 分块大小 | `send_file.chunk_size` | 1024 |
| §3.2 行分隔符 | `send_file.line_separator` | `\n` |
| §3.2 跳过空行/注释 | `send_file.skip_empty/skip_comment` | true |
| §3.2 编码 | `send_file.encoding` | UTF-8 |
| §3.3 分块阈值/大小/间隔 | `data.chunk_threshold/size/interval` | 4096/1024/50 |
| §3.3 追加结束符 | `data.append_terminator` | false |
| §3.3 HEX 解析 | `data.hex`（存在即按 HEX 解析） | — |

**影响范围**：
- M2 §3.1 步骤字段表：新增 `send_file`、`data`，标注三选一。
- M1 §3：无需改内容，仅确认参数命名与上表对齐（M1 当前用「分块阈值/分块大小」，M2 沿用，无冲突）。
- PRD：无需改。

---

### 1.2 S2 — 断言升级

**设计目标**：支持数值范围、多条件组合、变量断言、断言命名（提升报告可读性）。

**方案**：`assert` 支持两种写法——**列表式（新，推荐）** 和 **单键式（旧，兼容）**。引擎将单键式归一化为"对响应原文"的单元素列表。

#### 断言元素类型

**A. 响应原文断言**（针对完整响应文本，沿用旧语义）：

| 操作 | 键 | 示例 |
|------|----|------|
| 包含 | `contains` | `{ contains: "OK" }` |
| 不包含 | `not_contains` | `{ not_contains: "ERROR" }` |
| 正则匹配 | `matches` | `{ matches: "\\+CEREG:.*1" }` |
| 完全相等 | `equals` | `{ equals: "OK\r\n" }`（明确含尾部换行） |

**B. 变量断言**（针对 extract 出的变量，新增）：

| 操作符 `op` | 语义 | 示例 |
|------------|------|------|
| `eq` / `ne` | 等于 / 不等于 | `{ var: status, op: eq, value: "READY" }` |
| `gt` / `lt` / `ge` / `le` | 数值比较 | `{ var: rssi, op: ge, value: 15 }` |
| `between` | 数值闭区间 | `{ var: rssi, op: between, min: 15, max: 31 }` |
| `in` | 值在集合中 | `{ var: stat, op: in, values: ["1", "5"] }` |
| `contains` | 字符串包含 | `{ var: apn, op: contains, value: "cmnet" }` |
| `matches` | 正则匹配 | `{ var: imei, op: matches, value: "^\\d{15}$" }` |

#### 完整示例

```yaml
steps:
  - command: AT+CSQ
    extract:
      rssi: '\+CSQ:\s*(\d+)'
      ber:  '\+CSQ:\s*\d+,(\d+)'
    assert:
      - { name: 命令成功, contains: "OK" }
      - { name: 不含错误, not_contains: "ERROR" }
      - { name: 信号强度合格, var: rssi, op: between, min: 15, max: 31 }
      - { name: BER有效, var: ber, op: le, value: 7 }
```

**求值与失败语义**：
- 列表内元素默认 **AND** 关系，全通过 = 步骤断言通过。
- 任一元素失败 → 步骤断言失败，报告展示**每个元素**的 name + 实际值 + 期望（变量断言展示变量实际值）。
- 变量未定义或类型转换失败 → 该元素**判为失败**（不抛异常），记录"变量未定义/类型不符"。
- `name` 可选，缺省时由引擎生成（如 `contains:OK`）。

**兼容性**：`assert: { contains: "OK" }` 等价于 `assert: [ { contains: "OK" } ]`，旧用例零改动。

**影响范围**：M2 §4 断言规则整节重写；M4（报告）需支持展示断言元素明细（M4 未开始，无返工）。

---

### 1.3 S3 — 表达式变量引用模型

**设计目标**：消除 `{{var}}` 文本替换的注入风险与未定义行为，建立明确的类型与求值规则。

**方案**：区分两种变量使用场景，规则不同。

| 场景 | 语法 | 求值方式 | 示例 |
|------|------|---------|------|
| **字符串内容模板**（command / data.inline / send_file.path） | `{{var}}` | 文本替换（受控，值原样嵌入） | `command: 'AT+CIPSTART="TCP","{{ip}}",8080'` |
| **条件表达式**（when / poll.until） | 裸变量名 | 引擎按作用域取值，类型安全比较 | `when: 'stat == "1" and rssi > 15'` |

#### 条件表达式语法与求值规则

```
表达式  := 或表达式
或表达式 := 与表达式 ( 'or' 与表达式 )*
与表达式 := 比较表达式 ( 'and' 比较表达式 )*
比较表达式 := 操作数 运算符 操作数  |  操作数 'is' 'null'  |  操作数 'is' 'not' 'null'
操作数   := 变量名 | 字符串字面量 | 数值字面量
运算符   := == | != | > | < | >= | <=
```

**求值规则（必须明文写入 M2）：**

1. **变量取值**：按作用域解析（用例级 → 跨端口级）。未定义 → null。
2. **null 比较**：除 `is null` / `is not null` 外，含 null 的比较一律为 **false**。
3. **类型规则**：
   - 字符串字面量：用双引号包裹，如 `"READY"`。
   - 数值字面量：纯数字，如 `15`。
   - 比较时：运算符 `==`/`!=` 按字符串比较；`>`/`<`/`>=`/`<=` 按数值比较（两侧自动尝试转数值，失败则该比较为 false）。
4. **变量值与字面量比较**：变量侧自动尝试向字面量类型靠拢（字面量是数值则尝试转数值，是字符串则按字符串）。

**示例：**

```yaml
steps:
  - command: AT+CEREG?
    extract: { stat: 'CEREG:\s*\d,(\d)' }
    when: 'stat == "1" or stat == "5"'      # 字符串比较
  - command: AT+CSQ
    extract: { rssi: '\+CSQ:\s*(\d+)' }
    when: 'rssi > 15'                        # 数值比较
  - command: AT+CIPSEND=...
    when: 'peer_ip is not null'              # null 判断
```

**向后兼容**：旧写法 `when: '{{var}} == "OK"'` 仍可用——引擎检测到 `{{}}` 时，先做文本替换再求值（兼容期），并在文档标注"不推荐，新用例请用变量名引用"。

**影响范围**：M2 §6（条件跳过）整节重写为"表达式"小节，统一覆盖 when/poll.until；§5 变量系统补充求值规则。

---

### 1.4 S4 — 步骤级重试

**设计目标**：应对 AT 命令偶发抖动，稳定测试结果。

**方案**：步骤增加 `retry` 修饰符，setup/teardown/steps 通用。

```yaml
steps:
  - command: AT+CEREG?
    assert: { var: stat, op: in, values: ["1", "5"] }
    extract: { stat: 'CEREG:\s*\d,(\d)' }
    retry:
      count: 3            # 最大重试次数（不含首次），默认 0（不重试）
      interval: 2000      # 重试间隔(ms)，默认 0
```

**执行语义（必须明文）：**

1. 首次执行失败（断言失败、响应超时）→ 按 `retry.interval` 等待 → 重试。
2. 重试上限：首次 + `count` 次重试。例如 `count: 3` 共执行最多 4 次。
3. 任一次成功 → 步骤成功，停止重试。
4. 全部失败 → 步骤失败，按 `on_failure` 处理。
5. **重试粒度**：每次重试是"重新发送命令 + 重新断言 + 重新 extract"的完整步骤执行（extract 在每次执行中重算，保留最后一次成功的变量值）。
6. 重试期间若触发串口重连（M1 §4.2），重连成功后计入重试次数。

**setup 重试**：setup 步骤同样支持 `retry`（修正审查 M5 关联点：当前 setup 一律失败即跳过用例过于严格）。setup retry 耗尽仍失败 → 用例跳过（保持"跳过而非失败"语义）。

**影响范围**：M2 §3.1 步骤字段表新增 `retry`；§3.2 失败处理补充 retry 与 on_failure 的交互顺序；§7 前置条件补充 setup 可配 retry。

---

## 2. 重要问题方案（🟡 强烈建议）

### 2.1 M1 — teardown 与套件级 setup/teardown

**方案**：用例增加 `teardown`；套件增加 `suite_setup` / `suite_teardown`。

```yaml
# 用例文件
setup:
  - command: AT+CGACT=1,1
    assert: { contains: "OK" }
steps:
  - command: AT+CIPSTART="TCP","{{ip}}",8080
    assert: { contains: "CONNECT" }
teardown:                          # 无论用例成功/失败/跳过都执行
  - command: AT+CIPCLOSE
  - command: AT+CGACT=0,1
```

**语义：**
- `teardown` 在用例**结束后无条件执行**（成功/失败/被 setup 跳过均执行；进程异常崩溃除外）。
- teardown 步骤的失败**不影响用例结果**（用例结果已定），仅记录警告日志。
- teardown 不支持 `when`/`retry`（保持简单，避免清理逻辑复杂化）。

**套件级（可选增强，先入文档后实现）：**
```yaml
# suite-network.yaml
name: 网络注册测试套件
suite_setup:                       # 套件开头执行一次
  - command: AT+CFUN=1
suite_teardown:                    # 套件结尾执行一次
  - command: AT+CFUN=0
cases:
  - network-basic_register.yaml
```
执行顺序：`suite_setup → [用例setup → 用例steps → 用例teardown]×N → suite_teardown`。

**影响范围**：M2 §2.2 文件结构新增 teardown；新增 §7.x 套件级前后置小节（或在 §8 套件内补充）。

---

### 2.2 M2 — 条件循环/轮询（poll）

**设计目标**：等待异步事件（注网、连接建立等）。

**方案**：步骤增加 `poll` 修饰符（与 §2.1 统一步骤模型一致，poll 是行为修饰符）。

```yaml
steps:
  - command: AT+CEREG?
    extract: { stat: 'CEREG:\s*\d,(\d)' }
    poll:
      until: 'stat == "1" or stat == "5"'   # 条件表达式（用 S3 模型）
      timeout: 60                            # 总超时(秒)，必填
      interval: 3000                         # 轮询间隔(ms)，默认 1000
    on_failure: continue                      # 超时未满足→按此策略
```

**执行语义：**
1. 执行命令 → extract 变量 → 求 `until` 表达式。
2. 满足 → 步骤成功，停止。
3. 不满足 → 等 `interval` → 再次执行命令（重新 extract）。
4. 累计达 `timeout` 仍未满足 → 步骤失败，按 `on_failure`。
5. poll 期间每次执行的响应**都记录**到原始日志；报告中展示轮询次数和总耗时。
6. poll 与 retry 互斥（语义重叠，避免双重循环）。

**影响范围**：M2 §3.1 新增 `poll` 修饰符；新增 §6.x 轮询小节（或并入条件表达式节）。

---

### 2.3 M3 — 参数化（先预留 schema，实现可后置）

**设计目标**：同流程不同参数，避免复制用例。

**方案**：用例增加 `parameters` 字段（参数矩阵），用例按行展开为多次执行。

```yaml
name: PDP激活-多APN
parameters:
  - { apn: cmnet,  type: IP }
  - { apn: cmiot,  type: IP }
  - { apn: '',      type: IPV6 }
steps:
  - command: 'AT+CGDCONT=1,"{{type}}","{{apn}}"'
    assert: { contains: "OK" }
```

**语义：**
- `parameters` 是列表，每个元素是一个参数字典。
- 用例执行时按列表展开为 N 次独立执行，每次参数注入到**用例级变量作用域**（最高优先级）。
- `{{param}}` 在 command/data/path 中做模板替换。
- 报告中每次执行作为独立用例实例展示（name 加后缀 `#1`/`#2`）。
- 参数化用例的 extract 变量与参数变量同作用域，提取值会覆盖同名参数（extract 优先级在参数之后，符合"后赋值覆盖"）。

**落地策略**：本次仅在 M2 写入 schema 定义，标记为"P1 增强功能，实现可后置"，避免阻塞主流程。

**影响范围**：M2 §2.2 新增 `parameters` 字段；新增 §x 参数化小节。

---

### 2.4 M4 — 压测语义补全

**方案**：在 M2 §10 压测配置补充以下明文定义。

| 待定义项 | 决策（建议默认） |
|---------|----------------|
| 一轮成功的标准 | 命令序列压测：**一轮内所有步骤断言全通过** = 该轮成功；单命令压测：该命令断言通过 = 成功 |
| 压测中失败的处置 | **记一次失败继续**（不中止整个压测），最终统计失败率。可在 `loop` 配置 `abort_on_failure: true` 改为遇失败即止 |
| `interval` 语义 | **"上一轮结束→下一轮开始"的间隔**（非固定节拍）。需固定节拍场景后续再议 |
| 预热 warmup | 支持 `warmup: 5`，前 5 轮**执行但不计入响应时间统计**，避免冷启动污染数据 |

**完整压测配置示例：**

```yaml
loop:
  count: 100                  # 与 duration 二选一
  interval: 100               # 轮间间隔(ms)
  warmup: 5                   # 预热轮数，默认 0
  abort_on_failure: false     # 遇失败是否中止，默认 false
```

**统计维度明文（回应审查）：**
- 单命令压测：响应时间分布（min/max/avg/P95/P99）、成功/失败次数、成功率。
- 命令序列压测：**每步**响应时间分布与成功率 + **整体序列**成功率（一轮全步骤成功才算）。

**影响范围**：M2 §10 整节扩充。

---

### 2.5 M5 — 条件分支

**方案**：采用"标准写法约定" + 可选 `else`，优先级低。

**if-else 标准写法（用 when 互斥模拟）：**

```yaml
steps:
  - command: AT+CIPSEND=10
    when: 'mode == "online"'
    assert: { contains: "OK" }
  - command: AT+CIPSEND=0
    when: 'mode != "online"'      # 与上一步互斥
    assert: { contains: "OK" }
```

**可选增强（写入文档，实现后置）：** 支持 `else` 字段串联：

```yaml
- if:
    when: 'stat == "1"'
    command: AT+CGACT=1,1
  else:
    command: AT+COPS=0
```

**落地策略**：本次仅写入"标准写法约定"，`else` 标记为 P2 增强。

**影响范围**：M2 §6 条件跳过补充"模拟 if-else"说明。

---

## 3. 细节方案（🟢 一并修订）

| 编号 | 方案 |
|------|------|
| **G1** | §5.1 措辞改为"提取正则的**第一个捕获分组**作为变量值"。若正则有多个捕获分组，**仅取第一个**；需多值提取请写多条 extract（不同正则或不同分组）。命名分组 `(?P<x>...)` 不单独支持（统一取第一个分组） |
| **G2** | 新增"正则书写规范"小节：YAML 中推荐用**单引号字符串**（`'...'`），正则内反斜杠**单写一次**（如 `'\+CEREG:\s*\d'`），避免双反斜杠。给出正确/错误对比示例 |
| **G3** | 明确 `name` 唯一性作用域：**单个执行范围内（一次运行加载的所有用例）name 必须唯一**。报告中以"文件名 + name"双标识展示用例，避免重名混淆 |
| **G4** | 新增"响应完整性契约"小节：**M1 负责判定响应完整**（收到 OK/ERROR/URC 终结标志或超时），将完整响应文本交给 M2；M2 的 extract/assert **针对完整响应**操作。这是 M1↔M2 的关键接口 |
| **G5** | 补充编码说明：extract/assert 针对 M1 **解码后的文本**操作；中文短信、USSD、UCS2 等编码转换由 M1 处理，M2 层面只面对文本 |
| **G6** | 明确 `command` 字段内容**不含结束符**，结束符由 M1 按 §2.1 配置自动追加。`send_file`/`data` 是否追加结束符由各自字段控制 |

---

## 4. 文档改动清单

修订时按本清单逐文件、逐章节落实。

### 4.1 `REQ-M2-测试用例定义.md`（主改动）

| 章节 | 改动 | 对应问题 |
|------|------|---------|
| §2.2 文件结构 | 新增 `teardown`、`parameters`、`suite_setup/teardown`（套件） | M1, M3 |
| §3.1 步骤字段表 | 重写为四组正交字段（输入/修饰/输出/失败）；新增 `send_file`、`data`、`retry`、`poll` | S1, S4, M2 |
| §3.2 失败处理 | 补充 retry → on_failure 交互顺序 | S4 |
| §4 断言规则 | 整节重写：列表式 + 变量断言 + name | S2 |
| §5 变量系统 | 补充求值规则、null/类型规则、作用域优先级 | S3 |
| §5.1 变量提取 | 修正措辞（第一个捕获分组） | G1 |
| §6 条件跳过→表达式 | 重写为"表达式"节（when/poll.until 共用）；补充 if-else 写法 | S3, M5 |
| §7 前置条件 | 补充 setup 可配 retry | S4 |
| 新增 §x teardown | teardown 语义小节 | M1 |
| 新增 §x 轮询 | poll 语义小节 | M2 |
| 新增 §x 参数化 | parameters 语义小节（标记 P1 后置） | M3 |
| §10 压测配置 | 补充轮次成功定义/失败处置/interval 语义/warmup | M4 |
| 新增 §x 正则规范 | 正则书写规范 | G2 |
| 新增 §x 响应契约 | M1↔M2 响应完整性契约 | G4 |
| §8.3/§9 | name 唯一性作用域 | G3 |
| 全文 | command 不含结束符、编码说明 | G5, G6 |

### 4.2 `REQ-M1-串口通信管理.md`（联动小改）

| 章节 | 改动 | 对应问题 |
|------|------|---------|
| §3 数据输入 | 确认参数命名与 M2 §1.1 对齐表一致（无实质改动，仅校对） | S1 |
| §7 原始日志 | 确认"响应完整性判定"责任表述（回应 G4 契约） | G4 |

### 4.3 其他文档

- `PRD-总体需求.md`：**无需改动**（PRD 是业务层，不涉及 schema 细节）。
- `SESSION-*-需求细化进度.md`：M2 修订完成后更新状态记录。

---

## 5. 验收标准

M2 修订稿需满足以下标准方可标记"已确认"：

**功能覆盖（每条用一个示例用例验证可表达性）：**

- [ ] S1：能写出固件升级（send_file chunk）、批量命令脚本（send_file line）、HEX 长报文（data hex）三类用例
- [ ] S2：能写出 `AT+CSQ` 信号强度 between 断言 + 多条件组合用例
- [ ] S3：能写出含 null 判断、数值比较、字符串比较混合的 when 表达式
- [ ] S4：能写出带 retry 的步骤和带 retry 的 setup
- [ ] M1：能写出含 teardown 的用例和含 suite_setup 的套件
- [ ] M2：能写出等待注网的 poll 用例
- [ ] M4：压测配置含 warmup + abort_on_failure，统计维度明文

**一致性校验：**

- [ ] M1↔M2 数据输入参数命名完全对齐（§1.1 对齐表）
- [ ] 表达式语法在 when / poll.until 中完全一致（同一套规则）
- [ ] 旧写法（单键 assert、`{{}}` when）均被文档标注为兼容，引擎需支持

**文档质量：**

- [ ] 每个新字段有：字段名、类型、默认值、必填性、语义说明
- [ ] 每个新机制有：YAML 示例 + 执行语义明文
- [ ] 无"未定义行为"遗留（求值规则、失败语义、作用域全部明文）

---

## 6. 落地节奏建议

| 阶段 | 内容 | 产出 |
|------|------|------|
| **第1步** | 确认本方案（用户审阅） | 方案定稿 |
| **第2步** | 改 M2 主文档（按 §4.1 清单，S 级优先） | M2 v1.1 草稿 |
| **第3步** | 联动校对 M1（§4.2 清单） | M1 v1.2 |
| **第4步** | 用示例用例走查验收标准 §5 | 验收记录 |
| **第5步** | 用户确认 → 更新 SESSION 进度 | M2 状态→已确认 |

> 参数化（M3）、条件分支 else（M5）、套件级前后置的增强部分可标记为后续迭代，不阻塞 M2 主流程定稿。
