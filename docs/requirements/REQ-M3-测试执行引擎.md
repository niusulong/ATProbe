# M3 测试执行引擎 — 需求文档

> 版本：v0.2（草稿）
> 日期：2026-06-19
> 状态：草稿
> 修订说明：v0.2 配合 M5 议题成果——§7.2 stop 接口增加 mode 参数（current/all），§9 待细化项全部落地（指向 M5）
> 依赖：M1 串口通信管理（v1.5）、M2 测试用例定义（v1.4）

---

## 1. 模块概述

测试执行引擎是工具的"大脑"，负责把 M2 定义的用例（或套件）跑起来，产出结构化的执行结果供 M4 报告消费。

本模块依赖 M1（串口通信能力）和 M2（用例定义），向上为 M4（报告）和 M5（CLI）提供服务。

**核心设计原则（贯穿全文）：**

- **串行执行**：单次运行内用例串行执行，用例内步骤也串行（含跨端口步骤）。无并发、无线程安全、无资源竞争。
- **用例驱动**：执行单元是用例，不是端口。端口是步骤执行时使用的通信资源。
- **极简控制**：引擎对外仅暴露 start/stop 两个控制接口。
- **并行外部化**：需要并行测试多端口时，启动多个工具实例，每个绑定自己的端口。

---

## 2. 执行调度模型

### 2.1 三层执行编排

执行单元分三层，自底向上：

```
套件（Suite）→ 用例（Case）→ 步骤（Step）
```

**执行顺序（串行）：**

```
suite_setup
└─ 用例1: setup → steps → teardown
└─ 用例2: setup → steps → teardown
└─ ...
suite_teardown
```

### 2.2 串行调度器

引擎内有一个单线程串行调度器：

1. 解析输入（用例/套件 + 执行参数：端口列表、标签过滤等）。
2. **加载环境配置（M7）**：若提供了 env 配置路径，解析 env.yaml，注入用例模板替换上下文（作为点号引用 `{{group.param}}` 的数据源）。加载失败 → ERROR。
3. 打开执行参数指定的端口（可能多个，供跨端口用例使用）。
4. suite_setup（若有）。
5. **按顺序串行执行每个用例**：setup → steps → teardown。
6. suite_teardown（若有）。
7. 关闭所有端口。
8. 聚合结果。

**关键点：**

- 同一时刻只有一个步骤在执行，端口间无并发竞争。
- 跨端口用例（双模块测试）：步骤按 `port` 字段在对应端口串行切换。
- 多端口仅用于单用例的跨端口步骤，不是为了多用例并行。

### 2.3 多实例并行（外部并行）

单次运行内不并行。需要并行测试多端口 → 启动多个工具实例，每个实例配置自己的端口和用例。实例间完全独立。

---

## 3. 执行流程

引擎层面按是否存在 `loop` 字段区分两种执行流程。

### 3.1 单个步骤的执行流程（两种场景共用）

```
1. 检查 when 条件
   ├─ false → 步骤 SKIPPED，结束
   └─ true（或无 when）→ 继续
2. 解析输入方式（command / data），模板替换 {{var}}
3. 发送 + 接收响应（委托 M1，受 timeout 约束）
   ├─ 带 retry：失败按 retry 重试
   └─ 带 poll：循环执行直到 until 满足或 poll.timeout
4. extract（对完整响应，写入用例变量池）
5. assert（对完整响应 / 提取的变量）
6. 记录步骤结果
7. FAIL 时按 on_failure 处理
```

### 3.2 流程A：常规执行（无 loop 字段）

一个用例 = 一个功能点，steps 内是该功能点的所有测试动作。

```
1. 执行 setup（若有）
   └─ 任一 setup 步骤失败 → 用例 SKIPPED，跳到 teardown
2. 按顺序执行 steps
   for 每个步骤:
     执行单个步骤流程
     ├─ PASS → 继续 next
     ├─ FAIL + on_failure=abort → 中止 steps，跳到 teardown
     ├─ FAIL + on_failure=skip → 跳过本步，继续 next
     └─ FAIL + on_failure=continue → 标记失败，继续 next
3. 执行 teardown（若有）
4. 汇总用例结果
   ├─ 所有步骤 PASS → 用例 PASS
   ├─ 任一 abort → 用例 FAIL
   └─ 存在 continue 的失败 → 用例 FAIL（执行完整）
```

### 3.3 流程B：压测执行（有 loop 字段）

```
1. 执行 setup（若有）—— 一次性
2. 压测循环
   warmup 轮（执行不计入统计）
   for 每一轮 (共 loop.count 轮):
     按顺序执行 steps（on_failure 固定 continue 语义）
     判断本轮成功（单命令:断言通过 / 序列:全步通过）
     ├─ 非 warmup → 计入统计
     └─ abort_on_failure=true 且本轮失败 → 中止压测
     等 loop.interval → 下一轮
3. 执行 teardown（若有）—— 一次性
4. 汇总压测统计（响应时间分布 + 成功率）
```

---

## 4. 失败处理与控制流

### 4.1 失败的判定

步骤失败的判定条件（满足任一）：

| 失败类型 | 触发 |
|---------|------|
| 断言失败 | assert 任一元素不通过 |
| 响应超时 | 步骤 timeout 到期未收到完整响应 |
| 发送失败 | 串口发送异常（M1 报错） |
| 数据源错误 | data.file 文件不存在/读取失败 |

> when 条件不满足 → 步骤是 SKIPPED，不是 FAIL，不触发失败处理。

### 4.2 三种机制的分层关系

```
步骤执行
  ├─ 是 poll 步骤?
  │    └─ poll 循环（poll.timeout 总控，retry/on_failure 不参与单次）
  │         每次"发送→响应"失败 → 不算步骤失败，等 interval 继续
  │         poll.timeout 到期仍未满足 → 步骤 FAIL → 走 on_failure
  │
  └─ 非 poll 步骤（可能带 retry）
       ├─ 单次执行失败:
       │    ├─ 带 retry 且未耗尽 → 重试
       │    └─ 无 retry 或 retry 耗尽 → 步骤 FAIL → 走 on_failure
       └─ on_failure: abort / skip / continue
```

**分层逻辑（从内到外）：**
1. **poll 最外层独占**：poll 步骤单次失败不触发 retry/on_failure，poll.timeout 到期后才走 on_failure。poll 与 retry 互斥。
2. **retry 中间层**：吃掉重试期间的失败。
3. **on_failure 兜底**：retry 耗尽（或无 retry）后的最终失败，决定后续控制流。

### 4.3 retry 执行细节

- `retry.count` 是重试次数（不含首次）。count=3 → 首次+3次重试=最多4次。
- 每次重试重新发送、重新 extract、重新 assert。
- **变量值保留**：保留最后一次成功的变量值；全失败则保留最后一次执行的值（可能为空）。
- 重试期间断连 → M1 重连，重连计入重试次数（算一次失败执行）。
- 压测循环内的 retry 不影响压测统计（按"该轮该步是否最终成功"计一次）。

### 4.4 poll 执行细节

- poll 的语义是"等待条件满足"，每次"发送→条件不满足"是正常轮询节奏，不是失败。
- 单次响应超时 → 该次 extract 取不到值 → until 通常 false → 等 interval 继续（只要 poll.timeout 没到）。
- 只有 poll.timeout 到期才算步骤失败。
- poll.timeout 从第一次执行开始计时，含所有 interval 等待和单次执行时间。

### 4.5 on_failure 执行细节

**生效优先级：** 步骤级 `on_failure` > 用例级 `on_failure` > 默认 abort。

| 策略 | 常规执行 | 压测执行 |
|------|---------|---------|
| abort | 中止用例 steps，用例 FAIL，执行 teardown | 固定转 continue（除非 abort_on_failure=true 则中止整个压测） |
| skip | 跳过本步，继续下一步 | continue 语义 |
| continue | 标记失败，继续下一步 | 记一次失败继续 |

### 4.6 用例结果汇总

```
用例结果汇总规则
────────────────
1. setup 阶段:
   └─ 任一 setup 步骤失败（含 retry 耗尽）→ 用例 = SKIPPED
2. steps 阶段（常规执行）:
   ├─ 所有步骤 PASS → 用例 = PASS
   ├─ 任一 abort → 用例 = FAIL（执行中止）
   ├─ 存在 FAIL 但无 abort → 用例 = FAIL（执行完整）
   └─ 步骤被 when 跳过（SKIPPED）→ 不影响结果
3. steps 阶段（压测执行）:
   └─ 用例结果 = 压测统计的成功率判定（阈值待 M4 细化）
4. teardown 阶段:
   └─ 失败不影响用例结果，仅记录警告
```

**用例状态：** PASS / FAIL / SKIPPED / INTERRUPTED（见 §7）。

---

## 5. 超时控制

### 5.1 仅步骤级超时

超时只在**步骤级**配置（M2 步骤的 `timeout` 字段），不存在用例级或全局级继承。

- 步骤显式配了 `timeout` → 用配置值。
- 步骤未配 → 用配置文件默认值（默认 5 秒，可在配置文件修改）。

```
配置文件示例:
  default:
    step_timeout: 5
```

### 5.2 timeout 作用对象

timeout 作用于**单个步骤的"发送命令→等待完整响应"**：

- 普通步骤：单次发送的响应等待。
- retry 步骤：每次单次执行的响应等待（retry 不延长单次 timeout）。
- poll 步骤：单次响应等待；poll 另有独立的 `poll.timeout`（轮询总时长）。

### 5.3 poll 步骤的双重 timeout

| 超时 | 字段 | 含义 |
|------|------|------|
| 轮询总超时 | `poll.timeout` | 整个轮询最大时长，到期未满足 until 则失败 |
| 单次响应超时 | 步骤 `timeout`（走配置默认） | 每次"发送→等待响应"的超时 |

### 5.4 超时后的处理

timeout 到期 → M1 返回"响应超时" → 步骤 FAIL → 进入失败处理（retry/poll/on_failure）。

**压测场景**：超时的响应时间**不计入**性能统计（避免污染分布），但失败次数计入。

### 5.5 边界

- 单位：秒。
- 最小值：建议 ≥ 0.1 秒。
- 不支持 timeout=0（必然超时无意义）。
- 不支持无限等待（必须有超时保护，需要长等待可设大值如 3600）。

---

## 6. 跨端口用例执行

### 6.1 执行模型

跨端口用例（双模块测试等）的步骤分布在不同端口，串行执行：

```
用例：双模块-TCP通信测试
─────────────────────────
步骤1 (port=COM3): AT+CIPSERVER=1,8080 → extract server_ip
步骤2 (port=COM5): AT+CIPSTART="TCP","{{server_ip}}",8080 → 引用变量
步骤3 (port=COM3): AT+CIPSEND=5
```

- 步骤按顺序执行，每步在 `port` 字段指定的端口发送。
- 步骤级 port 覆盖用例级 port。
- 变量池随用例走，跨端口步骤共享同一用例变量池。

### 6.2 端口使用

- 用例未指定 port 的步骤 → 用用例级 port（或默认端口）。
- 用例级 port 未指定 → 用执行参数的默认端口。
- 单端口用例：所有步骤在同一端口。
- 跨端口用例：步骤分布在不同端口，串行切换。

---

## 7. 执行状态机与中断

### 7.1 引擎级状态

| 状态 | 说明 | 转换 |
|------|------|------|
| IDLE | 未运行 | start → RUNNING |
| RUNNING | 正在执行用例序列 | 正常完成 → FINISHED；不可恢复异常 → ERROR |
| FINISHED | 正常结束 | — |
| ERROR | 不可恢复异常 | — |

```
IDLE ──start──→ RUNNING ──正常完成──→ FINISHED
                  │
                  └──不可恢复异常──→ ERROR
```

> 串口断连不是引擎级异常（M1 自动重连），不改变引擎状态。stop 也不改变引擎状态（见 §7.3）。

### 7.2 引擎接口（仅 start/stop）

| 接口 | 作用 |
|------|------|
| **start(配置)** | 启动执行，跑到所有用例完成 |
| **stop(mode)** | 中断当前用例（标记 INTERRUPTED），mode 决定是否继续后续用例 |

**stop mode 参数（M5 §5.3 引入，仍是同一个 stop 接口）：**

| mode | 语义 | 引擎状态 |
|------|------|---------|
| `current`（默认） | 中断当前用例，**继续执行下一个用例** | 保持 RUNNING |
| `all` | 中断当前用例，**不再执行后续用例**，正常收尾 | → FINISHED |

**stop 语义（两种 mode 共用）：**
- 当前步骤立即中止（委托 M1 取消阻塞操作，见 M1 §4.3）。
- 不执行后续步骤，不执行 teardown。
- 当前用例标记 INTERRUPTED。
- mode=current → 继续下一个用例，引擎保持 RUNNING。
- mode=all → 不再执行后续用例，正常收尾（关闭端口、聚合结果），引擎 → FINISHED。

> `mode=all` 是为 CLI 的 Ctrl+C "停止全部"出口而设（M5 §5.2），不破坏极简控制原则——仍是一个 stop 接口、仅多一个枚举参数。

### 7.3 用例状态

| 用例状态 | 说明 |
|---------|------|
| PASS | 所有关键步骤通过 |
| FAIL | 存在失败步骤（按 §4.6 汇总） |
| SKIPPED | setup 失败 |
| INTERRUPTED | 被 stop 中断（仅当前用例） |

### 7.4 执行进度（供 M5 展示）

引擎执行过程中通过事件暴露进度（只读输出，非控制接口）：

```
进度事件（引擎 → M5）:
- 用例开始: {case_name, case_index, total_cases}
- 步骤开始: {step_index, command, port}
- 步骤结果: {step_index, status, duration, response}
- 用例结果: {case_name, status, duration}
- 引擎结束: {summary}
```

M5 订阅这些事件做实时展示。

### 7.5 中断场景与恢复

**场景A：串口断连（执行中）**

```
1. M1 检测断连 → 自动重连（固定间隔3秒，最多10次）
2. 重连期间: 当前步骤暂停等待（不计入步骤 timeout）
3. 重连成功 → 当前用例从头重新执行（用例级重试），变量池重建
4. 重连失败（M1 超10次）→ 当前用例 FAIL，继续下一个用例
5. 安全阀: 同一用例因断连连续重试3次仍断连 → 放弃该用例，继续下一个
```

**场景B：用户 stop（主动中断）**

```
1. 当前用例立即中断（步骤级，不等结束，不执行 teardown）
2. 当前用例标记 INTERRUPTED
3. 继续执行下一个用例
```

**场景C：不可恢复异常**

```
触发: 端口全部打开失败 / 配置解析失败等致命错误
处理: 引擎 → ERROR，不执行任何用例，输出错误信息
```

> 单个端口打开失败不是不可恢复异常。用到该端口的用例 FAIL，其他用例继续。

---

## 8. 执行结果数据结构

引擎产出的结构化数据，是 M4 报告的输入。

### 8.1 分层结构

```
执行结果（ExecutionResult）
├── 概览（Summary）
├── 用例结果列表（CaseResult[]）
│   └── 每个用例:
│       ├── 用例信息（名称、文件、标签、端口）
│       ├── 用例状态（PASS/FAIL/SKIPPED/INTERRUPTED）
│       ├── 步骤结果列表（StepResult[]）
│       └── 压测统计（PressureStats，若有 loop）
└── 原始日志索引（LogIndex）
```

### 8.2 概览（Summary）

| 字段 | 类型 | 说明 |
|------|------|------|
| start_time | 时间戳 | 执行开始时间 |
| end_time | 时间戳 | 执行结束时间 |
| duration | 数值（秒） | 总耗时 |
| total_cases | 数值 | 用例总数 |
| passed / failed / skipped / interrupted | 数值 | 各状态数量 |
| pass_rate | 数值（%） | 通过率 = passed / (total - skipped - interrupted) |

> pass_rate 分母排除 SKIPPED 和 INTERRUPTED。

### 8.3 用例结果（CaseResult）

| 字段 | 类型 | 说明 |
|------|------|------|
| case_name | 字符串 | 用例名称（参数化用例带 #1/#2 后缀） |
| case_file | 字符串 | 用例文件路径 |
| tags | 字符串[] | 用例标签 |
| ports | 字符串[] | 该用例使用的端口列表 |
| status | 枚举 | PASS / FAIL / SKIPPED / INTERRUPTED |
| start_time | 时间戳 | 用例开始时间 |
| duration | 数值（秒） | 用例耗时 |
| setup_results / step_results / teardown_results | StepResult[] | 各阶段步骤结果 |
| pressure_stats | PressureStats | 压测统计（仅压测用例） |
| log_ref | 字符串 | 该用例原始日志文件引用 |
| error_msg | 字符串 | 失败/跳过/中断原因 |

### 8.4 步骤结果（StepResult）

| 字段 | 类型 | 说明 |
|------|------|------|
| step_index | 数值 | 步骤序号（从1开始） |
| input_type | 枚举 | command / data |
| command | 字符串 | 发送的命令或数据摘要 |
| port | 字符串 | 执行端口 |
| status | 枚举 | PASS / FAIL / SKIPPED / INTERRUPTED |
| request | 字符串 | 实际发送内容（模板替换后） |
| response | 字符串 | 完整响应内容 |
| assertions | AssertionResult[] | 断言明细 |
| extracted_vars | 键值对 | 本次 extract 的变量 |
| duration | 数值（毫秒） | 步骤耗时 |
| retry_count | 数值 | 实际重试次数（0=未重试） |
| poll_iterations | 数值 | poll 轮询次数（非poll为0） |
| error_msg | 字符串 | 失败原因 |

### 8.5 断言明细（AssertionResult）

| 字段 | 类型 | 说明 |
|------|------|------|
| name | 字符串 | 断言名称（缺省自动生成） |
| type | 枚举 | 响应原文断言 / 变量断言 |
| expected | 字符串 | 期望值 |
| actual | 字符串 | 实际值 |
| passed | 布尔 | 是否通过 |
| reason | 字符串 | 失败原因（通过时为空） |

### 8.6 压测统计（PressureStats）

| 字段 | 类型 | 说明 |
|------|------|------|
| total_rounds | 数值 | 总轮次（含warmup） |
| warmup_rounds | 数值 | 预热轮次 |
| counted_rounds | 数值 | 计入统计的轮次 |
| success_rounds / failed_rounds | 数值 | 成功/失败轮次 |
| success_rate | 数值（%） | 成功率 |
| aborted | 布尔 | 是否因 abort_on_failure 中止 |
| step_stats | StepPressureStats[] | 每步统计 |

### 8.7 步骤压测统计（StepPressureStats）

| 字段 | 类型 | 说明 |
|------|------|------|
| step_index | 数值 | 步骤序号 |
| command | 字符串 | 命令 |
| success_count / fail_count | 数值 | 成功/失败次数 |
| response_times | 数值[]（毫秒） | 所有成功响应时间 |
| min / max / avg | 数值（毫秒） | 响应时间统计 |
| p95 / p99 | 数值（毫秒） | 百分位响应时间 |

### 8.8 设计决策

- **结果数据与原始日志分离**：结果存结构化信息，原始日志（HEX+TEXT）由 M1 记录，结果只引用，避免数据膨胀。
- **response 存完整响应文本**（M1 判定完整后的文本），不存 HEX 格式。
- **error_msg 规范化**：断言失败/响应超时/发送失败/数据源错误/条件跳过/中断/setup失败，各类有明确文案。

---

## 9. 待细化项

以下项已在后续模块细化中落地（保留以备追溯）：

| 项 | 说明 | 落地位置 |
|----|------|---------|
| 压测用例 PASS/FAIL 阈值 | 压测结果的成功率阈值判定 | M5 §3.5 配置 `pressure.pass_rate_threshold`（默认 95%） |
| 配置文件完整格式 | default.step_timeout 等配置项的完整定义 | M5 §3.5 `atprobe.yaml` 结构 |
| 进度事件详细字段 | §7.4 进度事件的具体字段定义 | M5 §6.2 进度事件字段映射表 |
| 内置变量 timestamp 格式 | `{{timestamp}}` 的具体时间格式 | M5 §8 `YYYY-MM-DD HH:MM:SS` |
| stop 全停出口 | Ctrl+C "停止全部"所需的能力 | M5 §5.3 引入 `stop(mode=all)`，已回填本文件 §7.2 |

---

## 10. 与其他模块的接口

| 接口 | 方向 | 说明 |
|------|------|------|
| 串口通信 | M3 → M1 | 委托 M1 发送命令/接收响应/记录日志；调用 M1 操作取消（M1 §4.3） |
| 用例定义 | M3 读 M2 | 加载并解析 M2 定义的用例/套件 YAML |
| 报告 | M3 → M4 | 产出 ExecutionResult 供 M4 生成报告 |
| CLI | M5 → M3 | M5 调用 start/stop，订阅进度事件 |
| 环境配置 | M7 → M3 | M3 start 时加载 env.yaml，注入用例模板替换上下文（点号引用数据源，M7） |
| 响应完整性 | M1 → M3 | M1 判定响应完整后交付，M3 不自行判定（见 M2 §15.1） |
