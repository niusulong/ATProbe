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
interval: int                # 可选，>=0，步骤间间隔(ms)
on_failure: abort|skip|continue  # 可选，用例级失败策略
loop: LoopConfig             # 可选，压测配置（有此字段则该用例为压测用例）
parameters: [dict]           # 可选，参数化矩阵
```

## Step 结构

```yaml
- command: str               # 输入方式一：直接指令（与 data 二选一）
  data: DataInput            # 输入方式二：数据流输入（与 command 二选一）
  retry: RetryConfig         # 可选，与 poll 互斥
  poll: PollConfig           # 可选，与 retry 互斥
  when: str                  # 可选，条件执行
  timeout: float             # 可选，>0，秒；响应终结判定超时
  interval: int              # 可选，>=0，ms
  port: str                  # 可选，覆盖默认端口
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
提取失败（不匹配）时变量为空字符串，`matched=False`。

## 常用修饰符

### retry（重试，与 poll 互斥）

```yaml
retry: { count: 3, interval: 500 }   # 失败后重试，间隔 ms
```

### poll（轮询等待，与 retry 互斥）

```yaml
poll: { timeout: 10000, interval: 500 }  # 在 timeout 内每 interval ms 轮询一次
```

### timeout（响应超时）

```yaml
timeout: 1.2   # 秒。响应终结判定超时；业务码响应（不以 OK/ERROR 结尾）必加此项
```

### on_failure（失败策略）

| 值 | 语义 |
|---|---|
| `abort` | 中止整个用例（默认） |
| `skip` | 跳过**当前步骤**（记 SKIPPED，不算失败），继续执行后续步骤 |
| `continue` | 标记**当前步骤**失败，继续执行后续步骤 |

## 数据流输入（data，与 command 二选一）

```yaml
data:
  file: path/to/file        # 与 inline 二选一
  inline: "raw data"
  chunk_threshold: 4096     # 超过则分块
  chunk_size: 1024
  chunk_interval: 50        # ms
  append_terminator: false  # 是否追加结束符
```

用于需要发送大数据（如 TCPSEND 长 payload）的场景。

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
