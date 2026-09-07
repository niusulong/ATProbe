# ATProbe 用例 YAML Schema

从 `src/atprobe/domain/case/models.py` 精确提取。字段语义、断言操作符、验证规则全部来自源码。

## 顶层结构（Case）

```yaml
name: str                    # 必填，min_length=1，执行范围内唯一
description: str             # 可选，多行用 | 块；规范要求强制三段：场景前提 + 验证目标 + 文档依据
tags: [str]                  # 可选，分类标签；规范要求强制前三段为 [功能块, 指令, 类型]，如 [TCP, TCPSEND, FUNC]
port: str                    # 可选，仅日志标注；实际发送端口由配置文件 ports[0] 决定
setup: [Step]                # 可选，前置步骤
teardown: [Step]             # 可选，清理步骤
steps: [Step]                # 必填，min_length=1，主测试步骤
interval: int                # 可选，>=0，**保留字段，引擎当前不消费**（发送延迟请配 Step.interval）
on_failure: abort|skip|continue  # 可选，用例级失败策略
loop: LoopConfig             # 可选，压测配置（有此字段则该用例为压测用例）
parameters: [dict]           # 可选，参数化矩阵
```

## Step 结构

```yaml
- command: str               # 输入方式一：直接指令（与 data 二选一），发送前模板渲染 {{var}}/{{file_size()}}
  data: DataInput            # 输入方式二：数据流输入（与 command 二选一），发送的是**内容字节流**
  retry: RetryConfig         # 可选，与 poll 互斥
  poll: PollConfig           # 可选，与 retry/wait_urc 互斥
  when: str                  # 可选，条件执行（teardown 中被忽略）
  timeout: float             # 可选，>0，秒；响应终结判定超时
  interval: int              # 可选，>=0，ms；本步**每次发送前的固定延迟**（如 CIPSEND 出 > 提示符后延迟 50-100ms 再发数据）
  port: str                  # 可选，覆盖默认端口
  wait_urc: str              # 可选，正则；异步指令 OK 后等匹配此 URC 才终结（与 poll/expect 互斥）
  expect: str                # 可选，正则；附加完成条件——响应命中即视为本步完成（与 wait_urc 互斥），两阶段发送的 \r\n> 提示符形态
  extract: {name: regex}     # 可选，变量提取
  assert: Assert             # 可选，断言（列表式或单键式）
  on_failure: abort|skip|continue  # 可选，步骤级失败策略
```

> Step 用 `extra="forbid"`，**不支持 `name` 字段**。给步骤加说明用 YAML 注释 `#`，不要写 `name:`
> （会被拒绝）。断言元素才支持 `name`（见下）。

## 断言（Assert）

两种形态，**互斥**（一个断言元素只能是其中一种）。

### A. 响应原文断言（针对完整响应文本）

四选一，对 `response.text` 操作：

| 字段 | 语义 | 底层 |
|---|---|---|
| `contains: str` | 响应包含子串 | `sub in response` |
| `not_contains: str` | 响应不包含子串 | `sub not in response` |
| `matches: regex` | 响应匹配正则 | `re.search(pat, response)` |
| `equals: str` | 响应完全相等 | `response == value` |

**空串拒绝（解析期）**：`contains` / `not_contains` / `matches` 不可为空字符串——
`contains:''` 恒真、`not_contains:''` 恒失败、`matches:''` 恒命中，行为反直觉，
解析期直接报错。断言「响应为空」用 `equals: ''`（合法语义）。

### B. 变量断言（针对 extract 提取的变量）

需同时提供 `var` + `op`，加对应值字段：

```yaml
- { var: myvar, op: eq, value: "0" }
- { var: myvar, op: in, values: ["0", "1"] }
- { var: myvar, op: between, min: 0, max: 100 }
```

| op | 语义 | 需要的字段 |
|---|---|---|
| `eq` | 等于 | value |
| `ne` | 不等于 | value |
| `gt` / `lt` / `ge` / `le` | 数值大于/小于/大于等于/小于等于 | value（数值） |
| `between` | 数值在闭区间 | min, max |
| `in` | 在枚举集合内 | values: [str] |
| `contains` | 变量值包含子串 | value |
| `matches` | 变量值匹配正则 | value（正则） |

补充规则：

- `eq` / `ne` 按**字符串**比较，整值浮点归一为整数形式（提取到 `3.0` 视作 `"3"`），
  bool 转 `true/false`——期望值按提取形态写。
- 数值类操作符（gt/lt/ge/le/between）转数值失败 → 该元素判失败（不抛异常）。
- 变量未定义（extract 没匹配上、没入池）→ 该元素失败，原因为「变量 X 未定义」。

### 断言写法形态

```yaml
# 列表式（推荐，可多条 + 每条带 name）
assert:
  - { name: 格式校验, matches: '^\r\n\+CMD: \d+\r\nOK\r\n$' }
  - { name: 值校验, var: val, op: in, values: ["0", "1"] }

# 单键式（仅一条）
assert: { contains: "OK" }
```

`name` 可选，用于报告展示，缺省引擎自动生成。

## 变量提取（extract）

```yaml
extract:
  varname: 'regex'     # 有捕获组取 group(1)，无捕获组取 group(0)
```

底层 `re.search`。提取的变量可在后续步骤的 `var` 断言中使用，也可在 `when` 条件中引用。

- **无匹配 → 变量不写入池**（等同未定义）：后续模板引用报「未定义」、`when` 里按 null
  处理（`is null` 判真）、`var` 断言失败——**不是**空字符串。
- **键名保留字**：`timestamp` / `port` 每步无条件内置注入，extract 键与之同名解析期报错。
- **单行业务码的提取正则用排除字符类 `([^\r\n]+)`，不要贪婪 `.+`**：响应文本逐行保留
  `\r`（框架不做行尾剥除），`(.+)` 会连同行尾 `\r` 吞入变量——后续拼 AT 命令或做
  `equals` 断言时出现不可见的尾随回车，极难排查：

```yaml
- command: AT+FSFL=...
  extract:
    fs_name: '\+FSFL:\s*\d+,"([^\r\n]+)"'   # [^\r\n]+ 保证不吃行尾 \r
```

## 常用修饰符

### retry（重试，与 poll 互斥）

```yaml
retry: { count: 3, interval: 500 }   # 失败后重试，间隔 ms
```

### poll（轮询等待，与 retry/wait_urc 互斥）

```yaml
poll:
  until: 'stat == "1" or stat == "5"'  # 终止条件表达式（**必填**），变量裸名
  timeout: 60                          # 总超时（秒），必填
  interval: 2000                       # 轮询间隔 ms，默认 1000
```

成功 = `until` 满足**且**本次断言通过，二者缺一不可；超时仍未满足 → 步骤 FAIL。

### timeout（响应超时）

```yaml
timeout: 1.2   # 秒。响应终结判定超时；业务码响应（不以 OK/ERROR 结尾）必加此项
```

### wait_urc（异步指令：OK 后等 URC 终结）

```yaml
wait_urc: '\+CTM2M:dereg,0,\d+'   # 正则。异步指令遇 OK 不终结，等匹配此 URC 才返回
timeout: 10                       # OK+URC 总等待上限（秒）
```

异步指令（OK 仅受理、URC 才是结果）专用。开启后 `Response.text` 含整段 `OK\r\n\r\n+URC...`，
断言可整体匹配（含 MsgID 一致性 `\1` 反向引用）。URC 匹配即立即返回，不空等 timeout；
timeout 内无 URC → status=TIMEOUT（断言照常跑）。与 `poll` 互斥，可与 `retry` 共存。
**等待期收到 ERROR / +CME ERROR / +CMS ERROR 立即终结**（设备已明确拒绝，继续等目标
URC 只会烧完超时预算），不再等到超时。**必配严格断言**——无断言的 wait_urc 不是闸门
（见 SKILL.md「两阶段发送三陷阱」第 2 条）。详见 SKILL.md「异步指令陷阱」。

### expect（附加完成正则：提示符等非终结形态）

```yaml
- command: 'AT+FSWF="test.txt",0,{{file_size("./fs_payload.bin")}},10000'
  expect: '\r\n> '                  # 命中提示符即本步完成（不等 OK/ERROR 终结行）
  assert: { matches: '\r\n> $' }    # 尾锚断言（勿用首锚 ^：设备可能回显命令行）
- data: { file: ./fs_payload.bin }  # expect 命中后必须紧跟 data 步骤
```

两阶段发送（FSWF/TCPSEND/CIPSEND 类：阶段一声明长度出 `>` 提示符，阶段二发数据）的
阶段一步骤用 `expect` 声明完成形态；与 `wait_urc` 互斥（均为自定义完成语义，二选一）。
超时回退业务码路径（TIMEOUT 三态：文本完整以 \r\n 结尾 → 走正常断言）。三个真机实证
陷阱（expect 后必跟 data / 必配断言否则假 PASS / 断言文本止于命中点）见
SKILL.md「两阶段发送三陷阱」。

### on_failure（失败策略）

| 值 | 语义 |
|---|---|
| `abort` | 中止整个用例（默认） |
| `skip` | 跳过**当前步骤**（记 SKIPPED，不算失败），继续执行后续步骤 |
| `continue` | 标记**当前步骤**失败，继续执行后续步骤 |

## 数据流输入（data，与 command 二选一）

```yaml
data:
  file: ./payload.bin       # file / inline / inline_hex 三选一（校验强制）
  inline: "raw data"        #   值同样走模板渲染 {{var}}
  inline_hex: "48656c6c6f"  #   十六进制串：渲染后按 hex 解析为字节流发送
  chunk_threshold: 4096     # 超过该字节数才分块（默认 4096）
  chunk_size: 1024          # 每块字节数（默认 1024，校验 ≤ threshold）
  chunk_interval: 50        # 块间隔 ms（默认 50）
  append_terminator: false  # 是否在结尾追加终止符（默认 false）
```

**语义（v0.10 起明确）**：`data` 发送的是**内容字节流**，不是路径字符串——`file` 读取
文件内容分块发送。主要场景是两阶段发送的第二阶段（`expect` 命中提示符后**紧跟** data
步骤）与大数据流（如 TCPSEND 长 payload）。

**inline_hex 延迟校验**：值含 `{{` 占位符时解析期无法静态验证十六进制合法性，引擎层
渲染后复核——非法 hex 串或零字节数据在**执行期**报错（字面量仍在解析期校验）。

**路径信任边界（S-8）**：`data.file` 与 `{{file_size()}}` 的渲染后路径必须落在
「用例文件所在目录 ∪ cases_dir ∪ mcp.allowed_roots」内，越界报错——共享/不可信
用例不能借 data 步骤读取任意路径文件，数据文件放进用例目录。

**配套模板函数 `{{file_size("路径")}}`**（v0.10+）：渲染为指定文件的**字节数**，用于
「指令声明长度 = 数据长度」场景（如 FSWF/TCPSEND）。参数须为**引号包裹的字面量路径**
（不支持变量引用），`./` 相对用例文件所在目录——用法见上方 expect 小节示例。

## 示例：完整的严格字节级用例片段

```yaml
steps:
  # 查询 + 严格格式 + 变量范围校验
  - command: 'AT+RECVMODE?'
    extract:
      recv_n: '\+RECVMODE:\s*(\d)'
      recv_mode: '\+RECVMODE:\s*\d+,(\d)'
    assert:
      - { name: RECVMODE严格格式, matches: '^\r\n\+RECVMODE: \d+,\d+\r\nOK\r\n$' }
      - { name: n在0-1, var: recv_n, op: in, values: ["0", "1"] }
      - { name: mode在0-1, var: recv_mode, op: in, values: ["0", "1"] }

  # 业务码响应（不加 timeout 会空等 5s）
  - command: 'AT+TCPSETUP=0,1.2.3.4,80'
    timeout: 1.2
    assert:
      - { name: TCPSETUP业务ERROR, matches: '^\r\n\+TCPSETUP: ERROR\r\n$' }
      - { name: 非CME错误, not_contains: "+CME ERROR" }

  # 参数越界 → CME 53
  - command: 'AT+XIIC=9'
    assert:
      - { name: XIIC越界CME53, matches: '^\r\n\+CME ERROR: 53\r\n$' }
```

## 深入机制：按需读 sibling references

本文件是**字段速查**（字段名 + 断言操作符 + 基本规则）。具体机制的设计用法见按功能域拆分的兄弟文件，按需加载：

- `variables.md` —— 变量系统（提取 / `{{var}}` 引用 / 作用域 / 内置变量 / 环境配置）
- `control-flow.md` —— 控制流（`when` 条件 / if-else 模拟 / `on_failure` / `retry` / `poll`）
- `parameters.md` —— 参数化矩阵（`parameters` 展开多次执行）
- `pressure.md` —— 压测配置（`loop` 循环 / 压测语义 / 统计维度）
- `suite.md` —— 套件组织（`suite` 定义 / 执行顺序 / 目录结构）
- `conventions.md` —— 书写规范（正则书写 / tags 系统 / name 唯一性 / 超时）
