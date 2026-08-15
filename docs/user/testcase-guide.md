# ATProbe 用例设计说明（用户手册）

本手册面向编写 ATProbe 测试用例（YAML）的测试工程师，教程式讲解用例文件的每一个语法点。
所有 YAML 片段均可直接复制修改。行为规范依据 `docs/requirements/REQ-M2-测试用例定义.md`（与代码同步核实）。

---

## 目录

1. [第一个用例](#1-第一个用例)
2. [顶层字段全表](#2-顶层字段全表)
3. [步骤字段全表](#3-步骤字段全表)
4. [断言详解](#4-断言详解)
5. [extract 与变量](#5-extract-与变量)
6. [when 表达式语法](#6-when-表达式语法)
7. [retry / poll / wait_urc 控制流](#7-retry--poll--wait_urc-控制流)
8. [参数化 parameters](#8-参数化-parameters)
9. [套件 suite-\*.yaml](#9-套件-suite-yaml)
10. [压测用例](#10-压测用例)
11. [setup / teardown 语义与双层资源清理](#11-setup--teardown-语义与双层资源清理)
12. [常见错误与陷阱](#12-常见错误与陷阱)
13. [四段式命名规范](#13-四段式命名规范)

---

## 1. 第一个用例

一个 YAML 文件 = 一个测试用例（Case）。最小的用例只需要 `name` 和一个 `steps`：

```yaml
# 文件名：NETWORK-CSQ-RESP-QUERY_FORMAT.yaml
name: CSQ-查询信号质量(严格字节级)     # 用例名，必填、非空白；在同一次执行内保持唯一
description: |                        # 自由文本，建议三段式：场景前提/验证目标/文档依据
  场景前提：任意状态（CSQ 查询不改状态）。
  验证目标：AT+CSQ 查询返回 +CSQ: <rssi>,<ber>，<rssi> ∈ 0..31（99=未知）。
  文档依据：3GPP TS 27.007 §8.5。
tags: [NETWORK, CSQ, RESP, p0]        # 标签，参与 --tag / --exclude-tag 过滤
port: COM5                            # 元数据标注（不影响实际执行端口，见 §2）

setup:                                # 前置步骤：任一失败则整个用例记 SKIPPED
  - command: ATE0                     # 发送的 AT 指令（command 与 data 二选一）
    assert: { matches: '^\r\nOK\r\n$' }   # 断言：完整响应须字节级匹配此正则

steps:                                # 主步骤序列，必填、至少 1 个
  - command: AT+CSQ                   # 被测指令：查询信号质量
    extract:                          # 从响应中提取变量，写入用例变量池
      rssi: '\+CSQ:\s*(\d+)'          # 捕获组 1 → 变量 rssi
      ber: '\+CSQ:\s*\d+,(\d+)'       # 捕获组 1 → 变量 ber
    assert:                           # 断言列表（各元素间 AND，全过才算通过）
      - { name: CSQ严格格式, matches: '^\r\n\+CSQ: \d+,\d+\r\nOK\r\n$' }
      - { name: rssi合法范围, var: rssi, op: in, values: ["0","1","99"] }  # 示意，实际列出全部合法值
      - { name: ber合法范围, var: ber, op: in, values: ["0","7","99"] }

teardown:                             # 后置步骤：无条件执行，用于恢复设备状态
  - command: ATE0
```

逐行要点：

- **YAML 键拼写错误会在解析期直接报错**（模型禁止未知键），不会静默吞掉。
- `command` 与 `data` 必须二选一，都不填或都填都报错。
- 正则写在单引号字符串里，`\r\n` 显式表达回车换行——严格字节级断言是 ATProbe 的核心风格。
- `assert` 里第一个元素是「响应原文断言」（matches），后两个是「变量断言」（var+op），详见 §4。

---

## 2. 顶层字段全表

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | str | 是 | 非空白；唯一性作用域为单次执行（书写约定，非运行时强制），报告以「文件名+name」双标识展示 |
| `description` | str | 否 | 自由文本 |
| `tags` | list[str] | 否 | 参与 `--tag`（并集）/ `--exclude-tag` 过滤 |
| `port` | str | 否 | **解析但不影响执行端口**，仅元数据；执行端口由 `step.port` 或引擎默认端口决定 |
| `parameters` | list[dict] | 否 | 参数化矩阵，每行 `{参数名: str/int/float/bool}`，见 §8 |
| `setup` | list[Step] | 否 | 前置步骤；任一失败/skip → 整个用例 SKIPPED（§11） |
| `steps` | list[Step] | **是**（≥1） | 主步骤序列 |
| `teardown` | list[Step] | 否 | 后置步骤，无条件执行（§11） |
| `on_failure` | str | 否 | 用例级默认失败策略，步骤未配时兜底；取值 `abort`/`skip`/`continue` |
| `loop` | LoopConfig | 否 | 存在即为压测用例（§10） |
| `interval` | int | 否 | **保留字段，引擎当前不消费**，可不填 |
| `source_file` / `param_index` | — | 否 | 引擎内部字段，YAML 不要填写 |

超时原则：**超时只在步骤级配置**（`Step.timeout`），无用例级/全局级继承；未配时用引擎配置默认值（配置文件 `step_timeout`，默认 5s）。

---

## 3. 步骤字段全表

步骤由四组正交字段组成：**输入方式 + 行为修饰符 + 输出处理 + 失败处理**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `command` | str | 直接输入的 AT 指令；发送前模板渲染 `{{var}}`；与 `data` 二选一 |
| `data` | DataInput | 数据流输入（大文件/二进制），见下文 |
| `timeout` | float | 单步超时（秒，>0）；未配用引擎默认值 |
| `port` | str | 本步发送端口；引擎取 `step.port or default_port` |
| `when` | str | 条件表达式，不满足则本步 SKIPPED（不发送指令）；teardown 中被忽略（§6） |
| `retry` | RetryConfig | 重试配置 `{count, interval}`；与 `poll` 互斥（§7） |
| `poll` | PollConfig | 轮询配置 `{until, timeout, interval}`；与 `retry`/`wait_urc` 互斥（§7） |
| `wait_urc` | str | 异步指令：OK 仅受理，等到匹配此正则的 URC 才算终结（§7） |
| `extract` | dict | `{变量名: 正则}`，提取变量入池（§5） |
| `assert` | 单元素或列表 | 断言；支持单键式与列表式两种写法（§4） |
| `on_failure` | str | 本步失败策略 `abort`/`skip`/`continue`，覆盖用例级配置 |

`data` 数据流输入的字段（`file`/`inline` 二选一，校验强制）：

```yaml
steps:
  - data:
      inline: "Hello{{payload_suffix}}"   # 或 file: ./payload.bin；值同样走模板渲染
      chunk_threshold: 4096   # 超过该字节数才分块（默认 4096）
      chunk_size: 1024        # 每块字节数（默认 1024，校验 ≤ threshold）
      chunk_interval: 50      # 块间隔毫秒（默认 50）
      append_terminator: false  # 是否在结尾追加终止符（默认 false）
```

失败策略三值语义：

| 策略 | 步骤状态 | 对用例的影响 |
|---|---|---|
| `abort`（默认） | FAIL | 中止本用例后续步骤，直接跳到 teardown |
| `skip` | **SKIPPED（不算失败）** | 不中止用例，后续步骤继续 |
| `continue` | FAIL | 不中止用例，后续步骤继续 |

决策链：`step.on_failure` → `case.on_failure` → 默认 `abort`。

---

## 4. 断言详解

`assert` 支持两种写法（归一化后等价）：

```yaml
# 单键式：只有一个断言元素时可直接写映射
- command: ATE0
  assert: { matches: '^\r\nOK\r\n$' }

# 列表式：多个元素，之间 AND 关系，全过步骤才算通过
- command: AT+CSQ
  assert:
    - { name: 格式, matches: '^\r\n\+CSQ: \d+,\d+\r\nOK\r\n$' }
    - { name: rssi范围, var: rssi, op: between, min: 0, max: 31 }
```

`name` 可选，用于报告展示；缺省自动生成为 `{op}:{var}`（变量断言）或 `{键}:{期望值}`（原文断言）。

### 4.1 A 类：响应原文断言（4 种）

针对**完整响应文本**（含 `\r\n`）求值；四个键互斥，一个元素**恰好其一**：

| 键 | 语义 | 约束与示例 |
|---|---|---|
| `contains` | 子串包含 | `{ contains: "OK" }` |
| `not_contains` | 不含子串 | 不可为空字符串；`{ not_contains: "+CME ERROR" }` |
| `matches` | `re.search` 正则匹配 | 不可为空字符串，解析期预编译；`{ matches: '^\r\nOK\r\n$' }` |
| `equals` | 与完整响应全等（`==`） | `equals: ''` 合法（断言响应为空）；`{ equals: '\r\nOK\r\n' }` |

### 4.2 B 类：变量断言（var + op，10 种操作符）

针对 `extract` 提取出的变量求值；`var` 与 `op` 必须同时提供。变量断言与原文断言**不可混在同一元素**。

| op | 参数 | 语义 | 示例 |
|---|---|---|---|
| `eq` | `value` | 字符串相等 | `{ var: mode, op: eq, value: "1" }` |
| `ne` | `value` | 字符串不等 | `{ var: stat, op: ne, value: "0" }` |
| `gt` | `value` | 数值大于 | `{ var: rssi, op: gt, value: 10 }` |
| `lt` | `value` | 数值小于 | `{ var: ber, op: lt, value: 7 }` |
| `ge` | `value` | 数值大于等于 | `{ var: rssi, op: ge, value: 5 }` |
| `le` | `value` | 数值小于等于 | `{ var: rssi, op: le, value: 31 }` |
| `between` | `min`+`max` | 闭区间，校验 min ≤ max | `{ var: rssi, op: between, min: 0, max: 31 }` |
| `in` | `values` 列表 | 字符串成员判断 | `{ var: stat, op: in, values: ["1","5"] }` |
| `contains` | `value` | 变量值包含子串 | `{ var: addr, op: contains, value: "." }` |
| `matches` | `value` | 变量值 `re.search` 匹配 | `{ var: ip, op: matches, value: '\d+\.\d+' }` |

补充规则：

- 数值类操作（gt/lt/ge/le/between）对变量值和期望值尝试转数值，任一失败 → 该断言元素判失败（不抛异常）。
- `eq`/`ne` 按字符串比较；bool 转为 `true/false`，整值浮点归一为整数形式。
- 变量未定义（extract 没匹配上、没写入池）→ 该元素失败，原因为「变量 X 未定义」。
- 校验：`between` 需 min/max、`in` 需非空 values、其余需 value，缺失在解析期报错。

---

## 5. extract 与变量

### 5.1 extract 提取

`extract` 为 `{变量名: 正则}` 映射，对响应文本逐个求值：

- **有捕获分组** → 取第一个实际参与匹配的分组（`(...)` 里的内容）；推荐显式写捕获组。
- **无捕获分组** → 整体匹配兜底（不推荐）。
- **无匹配 → 变量不写入池**，等同未定义；后续模板引用报错、`is null` 为真。
- 变量在用例内跨 setup/steps/teardown 共享；同名后写覆盖先写。

```yaml
- command: AT+CEREG?
  extract:
    cereg_stat: '\+CEREG:\s*\d+,(\d)'   # 响应 +CEREG: 0,1 → cereg_stat="1"
```

### 5.2 模板渲染 {{var}}

占位符 `{{var}}`（允许内部空白）只做字符串替换，无表达式求值：

| 占位符 | 查找顺序 |
|---|---|
| `{{var}}`（无点号） | ① 用例变量池 → ② 环境配置默认组 → 仍无则报错 |
| `{{group.param}}`（一级点号） | **仅查环境配置**（如 `{{tcp.host}}`）；点号名不被 extract 覆盖 |

超过两级点号（`a.b.c`）直接报错。服务器地址/端口/平台参数一律用 `{{group.param}}` 引用，禁止硬编码：

```yaml
- command: 'AT+TCPSETUP=0,{{tcp.host}},{{tcp.port}}'
```

### 5.3 内置变量

每步执行开头自动注入：

| 变量 | 值 | 说明 |
|---|---|---|
| `timestamp` | `%Y-%m-%d %H:%M:%S` | 每步刷新为当前时间 |
| `port` | 实际执行端口 | `step.port or default_port` |
| `loop_index` | 当前轮号 | **仅压测场景**注入，从 1 开始 |

---

## 6. when 表达式语法

`when`（步骤条件跳过）与 `poll.until`（轮询终止条件）共用同一文法：

```
表达式   := 或表达式
或表达式 := 与表达式 ( 'or' 与表达式 )*
与表达式 := 比较表达式 ( 'and' 比较表达式 )*
比较表达式 := 操作数 运算符 操作数 | 操作数 'is' ['not'] 'null' | '(' 表达式 ')'
运算符   := == | != | > | < | >= | <=
操作数   := 变量名 | "字符串" | 数值
```

求值规则：

- 变量取**裸名**（如 `cereg_stat`），从作用域解析；**未定义 → null**（不是空串）。
- `==`/`!=` 按字符串比较；`>` `<` `>=` `<=` 按数值比较，任一侧转数值失败 → false。
- 含 null 的比较（`is null` / `is not null` 除外）一律 false——这是判断「提取失败」的惯用法。
- 括号仅作布尔分组；`x == (a == 1)` 这类嵌套比较报语法错误。
- teardown 阶段 `when` 被忽略（不判断、不跳过）。

```yaml
# 提取失败（未注册时 CEREG 无 stat）则跳过本步
- command: 'AT+CGACT?'
  when: 'cereg_stat is not null and (cereg_stat == "1" or cereg_stat == "5")'
  assert: { contains: "OK" }
```

`when` 表达式本身写错（语法错误）按作者错误处理，走 on_failure 决策链。

---

## 7. retry / poll / wait_urc 控制流

### 7.1 retry —— 同步指令的重试

```yaml
retry: { count: 3, interval: 500 }   # 重试 3 次（不含首次）→ 最多执行 4 次；间隔 500ms
```

重试围绕**完整单次执行**（发送→extract→断言）判定：响应 OK 且断言全过才算成功，重试期间重新 extract/assert。

### 7.2 poll —— 轮询直到条件满足

```yaml
- command: AT+CEREG?
  extract:
    cereg_stat: '\+CEREG:\s*\d+,(\d)'
  poll:
    until: 'cereg_stat == "1" or cereg_stat == "5"'  # 终止条件（§6 文法，变量裸名）
    timeout: 60        # 轮询总超时（秒），必填
    interval: 2000     # 轮询间隔（毫秒），默认 1000
  assert:
    - { name: 已注册家用或漫游, var: cereg_stat, op: in, values: ["1", "5"] }
```

语义要点：首轮立即查询；**成功 = until 满足且本次断言通过**，二者缺一不可；until 已满足但断言失败 → 立即失败返回；单次条件不满足不算失败，是正常轮询节奏；超时 → 步骤 FAIL。

### 7.3 wait_urc —— 异步指令等 URC

异步指令的 OK 仅表示「指令受理」，真正结果是随后上报的 URC：

```yaml
- command: AT+CTM2MDEREG
  wait_urc: '\+CTM2M:dereg,0,\d+'   # 等到匹配此正则的 URC 才终结
  timeout: 10                        # OK+URC 总等待上限
  assert:
    - { name: 整段格式, matches: '^\r\nOK\r\n\r\n\+CTM2M:dereg,0,\d+\r\n$' }
```

开启后框架遇 OK **不**终结，继续读到 URC 匹配立即返回（不空等），整段 `Response.text` 含 OK+URC，断言可整体匹配。受理行与 URC 的 `<id>` 一致性可用 `\1` 反向引用校验。`wait_urc` 可与 `retry` 共存；与 `poll` 互斥（解析期校验）。

### 7.4 同步 / 异步 / 业务码的判别

写步骤前先看**指令文档的响应描述**，三类情况三种写法：

| 类型 | 文档特征 | 写法 |
|---|---|---|
| 同步 | 成功直接返回 `OK`（单段响应，无「主动上报」） | 普通 `assert: { matches: '^\r\nOK\r\n$' }`，**绝不能加 wait_urc** |
| 异步 | 先 OK 后跟 URC（文档标「主动上报」） | 加 `wait_urc: '<URC 正则>'` |
| 业务码 | 响应以状态码结尾（如 `+IPSTATUS: 0,DISCONNECT`），**不以 OK/ERROR/+CME ERROR/+CMS ERROR 结尾** | **必须加 `timeout: 1.2`** |

业务码为何要加 timeout：框架的响应终结判定只认 `OK` / `ERROR` / `+CME ERROR:` / `+CMS ERROR:` 四种行。业务码行不被识别为响应结束，会一直等到步骤超时（默认 5s）才返回——而这类响应实际约 100ms 就到了。加个小的兜底超时（如 1.2s）不影响断言正确性（超时但文本完整仍参与 extract/assert），只是避免空等。

---

## 8. 参数化 parameters

同一流程跑多组参数时，用 `parameters` 矩阵，每行展开为独立用例实例：

```yaml
name: TCPSEND-参数化长度
parameters:
  - { len: 64,  expect: "OK" }
  - { len: 512, expect: "OK" }
  - { len: 4096, expect: "+CME ERROR: 53" }

steps:
  - command: 'AT+TCPSEND=0,{{len}}'
    assert: { contains: "{{expect}}" }
```

- 每行 dict 的值可为 str/int/float/bool；每行展开为一个实例，报告名追加 `#1`、`#2`… 后缀。
- 参数在 setup 之前注入用例变量池，**优先级最高**（模板查找先于环境配置默认组）；后续 extract 同名变量可覆盖。
- 空列表（默认）即普通非参数化用例。

---

## 9. 套件 suite-\*.yaml

文件名以 `suite-` 前缀识别（如 `suite-NETWORK.yaml`），字段：

| 字段 | 说明 |
|---|---|
| `name` / `description` | 元数据 |
| `tags` | 套件级标签，仅用于分类展示，**不参与用例筛选**（筛选走各用例自身 tags） |
| `cases` | 用例文件列表，**相对套件文件所在目录**解析 |
| `suite_setup` / `suite_teardown` | 套件级前置/后置，复用 Step 同构 schema |

```yaml
# suite-NETWORK.yaml
name: NETWORK 功能套件
description: 网络注册与信号查询用例集
tags: [NETWORK]
cases:
  - examples/testcases/3gpp/network/NETWORK-CSQ-RESP-QUERY_FORMAT.yaml
  - examples/testcases/3gpp/network/NETWORK-CEREG-FUNC-POLL_REGISTERED.yaml
suite_setup:
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }
suite_teardown:
  - command: AT+CFUN=1
    on_failure: continue
```

执行语义：`suite_setup` 在 cases 循环前执行一次（独立变量池，与用例变量池隔离），失败则跳过全部 cases 但仍执行 `suite_teardown`；`suite_teardown` 在循环后、关闭端口之前无条件执行。

两种运行方式不要混淆：

- `run suite-xxx.yaml`：按套件 `cases` 列表顺序执行，suite_setup/teardown 生效。
- `run <目录>`：执行目录下所有用例文件（目录扫描自动排除 `suite-` 前缀文件），套件文件此时只是索引文档。

---

## 10. 压测用例

顶层加 `loop` 字段即为压测用例（三种场景共用同一 schema）：

```yaml
name: CSQ-压测稳定性
loop:
  count: 100          # 循环次数，必填
  interval: 100       # 上一轮结束→下一轮开始的间隔（毫秒），默认 0
  warmup: 3           # 预热轮数：执行但不计入统计
  abort_on_failure: false   # 遇失败是否中止整个压测，默认 false

setup:
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }

steps:
  - command: AT+CSQ
    assert: { matches: '^\r\n\+CSQ: \d+,\d+\r\nOK\r\n$' }
```

压测语义：

- **只循环 `steps`**：setup 在循环前执行一次，teardown 在循环后执行一次。
- 一轮成功标准：单命令 = 断言通过；序列 = 全步通过。失败默认记一次并继续（步骤未配 `on_failure` 时压测中默认 `continue`）。
- 每轮注入 `loop_index`（从 1 开始，warmup 轮也注入），可用于区分轮次的命令模板。
- 统计口径：每步 min/max/avg/P95/P99 耗时与成功率；超时不计入耗时分布。

---

## 11. setup / teardown 语义与双层资源清理

### 11.1 setup：前提不满足则跳过用例

setup 步骤任一 **FAIL 或 SKIPPED**（含 `on_failure: skip`）都视为前提未满足：终止 setup、**整个用例记 SKIPPED**（不执行 steps），error_msg 带首个失败步骤的原因；teardown 仍执行。这让「无卡设备跑需 SIM 用例」表现为跳过而非失败。

### 11.2 teardown：无条件恢复

teardown 在 finally 块中无条件执行——即使 setup 失败、用例中途 abort、被中断；失败仅记录不影响用例结果。teardown 阶段：`when` 忽略、`poll` 旁路（退化为普通单次/retry 执行）、恒不中止用例。

**状态清洁原则**：多个用例共享同一设备，改过状态的用例必须自己恢复。对会改设备状态的指令，用「setup 查初始值 → steps 测试 → teardown 恢复」配对：

```yaml
setup:
  - command: 'AT+RECVMODE?'               # 查初始值
    extract:
      init_n: '\+RECVMODE:\s*(\d)'
    assert: { contains: "OK" }            # 宽松断言，只为提取

steps:
  - command: 'AT+RECVMODE=0'              # 被测指令
    assert: { matches: '^\r\nOK\r\n$' }

teardown:
  - command: 'AT+RECVMODE={{init_n}}'     # 用变量恢复初始值
  - command: ATE0
```

### 11.3 双层资源清理

带实例/连接语义的协议（HTTP/MQTT/FTP 等）资源分**两层**：连接层（HTTPCLOSE/MQTTDISCONNECT）与实例层（HTTPDESTROY/MQTTDESTROY）。teardown 只关连接不销毁实例 → 实例残留 → 下个用例创建指令复用同实例号时冲突失败（典型现象：5s 无响应），并**连锁污染**后续用例。对策：**先关连接再销毁实例，两条都加 `on_failure: continue`**（连接未建立时关闭指令可能报错，属正常）：

```yaml
teardown:
  - command: AT+HTTPCLOSE=0        # 连接层
    timeout: 3
    on_failure: continue
  - command: AT+HTTPDESTROY=0      # 实例层
    timeout: 6
    on_failure: continue
```

诊断线索：某用例 setup 的创建指令 5s 无响应而前后用例正常，优先排查上一用例 teardown 是否漏销毁实例。

---

## 12. 常见错误与陷阱

### 12.1 同步指令误用 wait_urc → 等满超时必失败

同步指令成功直接返回 OK，没有后续 URC。误加 `wait_urc` 后框架遇 OK 不终结，死等一个不存在的 URC，等满 timeout 判失败。历史教训：`AT+HTTPCON` 文档明确「成功返回 OK」，误当异步加 `wait_urc` → 等满 30s 失败。注意 TCPSETUP 是异步、HTTPCON 是同步，仅差一字，**必须逐条查文档**。

### 12.2 业务码忘加 timeout → 每步空等 5s

响应终结只认 OK/ERROR/+CME ERROR/+CMS ERROR 四种行。业务码响应（如 `+TCPSETUP: ERROR`、`+IPSTATUS: 0,DISCONNECT`）不被识别为结束，等满默认超时。这类步骤一律加 `timeout: 1.2` 兜底（§7.4）。

### 12.3 teardown 残留 → 连锁污染

漏销毁实例/漏断链/漏恢复参数，本用例可能 PASS，但下一个用例莫名失败。按 §11.2/§11.3 的配对与双层清理规范写 teardown。

### 12.4 冒号空格数 —— 严格断言中的字节细节

AT 响应中冒号后有无空格、空格有几个，不同固件不同。严格断言必须按文档「响应格式表」逐字节写（`+CSQ: ` 冒号后一个空格），不要参考其他项目固件的规律；文档未写明时向维护者确认，不要臆测。也注意区分文档的「响应格式表」（断言依据）与「示例」（仅场景设计参考，常省略 `\r\n`）。

### 12.5 其他易错点速查

| 症状/误区 | 原因与对策 |
|---|---|
| extract 没匹配上，后续模板报「未定义」 | 无匹配的变量**不写入池**；检查正则或用 `is null` 判别 |
| `not_contains: ""` 或 `matches: ""` 被拒 | 空串行为反直觉（恒失败），解析期直接报错；空响应断言用 `equals: ''` |
| retry 与 poll 同时写报错 | 二者互斥（wait_urc 与 poll 也互斥），解析期校验 |
| YAML 键拼错报错 | 模型禁止未知键——这是特性，检查拼写（如 `not_contains` 不是 `notcontains`） |
| when 里写 `{{var}}` 行为不同 | 旧写法未定义直接报错；新用例用裸名（未定义→null） |
| 压测中步骤失败却继续跑 | 压测中未配 on_failure 的步骤默认 `continue`；要中止就配 `abort` 或 `abort_on_failure: true` |
| 用例被记 SKIPPED 而非 FAIL | setup 任一步 FAIL/SKIPPED 即整用例 SKIPPED；看 error_msg 里首个失败步骤原因 |

---

## 13. 四段式命名规范

普通用例文件名按 `<功能块>-<指令>-<类型>-<变体>.yaml` 四段组织（**书写约定，代码不强制校验**；唯一被代码识别的文件名规则是套件的 `suite-` 前缀）：

| 段 | 规则 | 示例 |
|---|---|---|
| 1 功能块 | 大写，对应指令文档功能域 | `NETWORK` / `TCP` / `HTTP` |
| 2 指令 | 被测指令去掉 `AT+` 的裸名，大写、单一指令 | `CEREG` / `CSQ` / `TCPSEND` |
| 3 类型 | `RESP` 响应格式 / `PARA` 参数边界 / `FUNC` 功能验证 / `REGRESS` 回归 | `RESP` |
| 4 变体 | 大写下划线分词，描述具体测试点；回归用例放 BUGID | `QUERY_FORMAT` / `POLL_REGISTERED` / `BUG1234567890` |

配套约定：目录按 `<用例根>/<平台>/<功能块>/` 组织（如 `examples/testcases/3gpp/network/`），回归用例独立 `regress/` 顶层；`tags` 前三段 = `[功能块, 指令, 类型]`，可追加 `p0/p1`；`description` 建议三段式（场景前提/验证目标/文档依据）。

**单一职责是第一原则**：一个文件只测一个指令的一个维度，失败时能立即定位是哪个指令的哪类问题；前置依赖指令只进 setup（宽松断言），清理指令只进 teardown。

---

## 附：三分钟速查卡

```yaml
name: 必填唯一              # 顶层
description/tags/port       # 可选元数据（port 不影响执行端口）
parameters: [...]           # 参数化矩阵 → #N 实例
setup/steps/teardown        # 前置/主步骤/后置（setup 败→SKIPPED；teardown 无条件）
loop: {count, interval, warmup, abort_on_failure}   # 有 loop 即压测
on_failure: abort|skip|continue                       # 失败策略链 step→case→abort

steps[]:
  command | data            # 二选一
  timeout: 秒               # 步骤级唯一超时配置
  port / when / on_failure
  retry: {count, interval}          # ⊥ poll
  poll: {until, timeout, interval}  # ⊥ retry ⊥ wait_urc；成功=until 且断言过
  wait_urc: '<URC 正则>'            # 异步指令；同步指令禁用；业务码改加 timeout
  extract: {var: 正则}              # 无匹配不入池
  assert: [单键式 | 列表式 AND]     # A 类 contains/not_contains/matches/equals 四选一
                                    # B 类 var+op: eq/ne/gt/lt/ge/le/between/in/contains/matches
```
