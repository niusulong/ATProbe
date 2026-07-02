# 控制流（when 条件 / if-else / on_failure / retry / poll）

控制步骤是否执行、失败后怎么办、如何等异步事件。

## when：条件跳过步骤

`when` 是条件表达式，求值为 false 时跳过该步骤（标记 SKIPPED，不算失败）。用于"只在某状态下才测"的场景。

### 表达式语法

```
表达式   := 或表达式
或表达式 := 与表达式 ( 'or' 与表达式 )*
与表达式 := 比较表达式 ( 'and' 比较表达式 )*
比较表达式 := 操作数 运算符 操作数  |  操作数 'is' 'null'  |  操作数 'is' 'not' 'null'
操作数   := 变量名 | 字符串字面量 | 数值字面量
运算符   := == | != | > | < | >= | <=
```

- 字符串字面量：双引号包裹，如 `"READY"`
- 数值字面量：纯数字，如 `15`
- 变量名：**裸写**（不加 `{{}}`），引擎按作用域取值（变量系统见 `variables.md`）

### 求值规则

1. 变量取值：从用例变量池解析。未定义 → null。
2. null 比较：除 `is null` / `is not null` 外，含 null 的比较一律 **false**。
3. `==` / `!=`：按字符串比较。
4. `>` / `<` / `>=` / `<=`：按数值比较，两侧自动尝试转数值，失败则该比较为 false。
5. 变量值向字面量类型靠拢（字面量是数值则尝试转数值）。
6. 提取失败（空值）：按空字符串处理（非 null）。

### 示例

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
  - command: AT+COPS?
    when: 'stat == "1" and rssi >= 15'       # AND 组合
```

> 旧写法 `when: '{{var}} == "OK"'` 仍兼容（检测到 `{{}}` 先文本替换再求值），但**不推荐用于新用例**，用裸变量名。

## 模拟 if-else（互斥 when 两步）

`when` 只能跳过，没有 else。要模拟 if-else，用两个 `when` 互斥的步骤：

```yaml
steps:
  - command: AT+CIPSEND=10
    when: 'mode == "online"'
    assert: { contains: "OK" }
  - command: AT+CIPSEND=0
    when: 'mode != "online"'      # 与上一步互斥
    assert: { contains: "OK" }
```

## on_failure：失败策略

步骤或用例失败时怎么处理。三策略：

| 策略 | 说明 |
|---|---|
| `abort` | 中止当前用例，标记为失败（**默认**） |
| `skip` | 跳过当前步骤，继续执行后续步骤 |
| `continue` | 标记当前步骤失败，继续执行后续步骤 |

支持用例级默认 + 步骤级覆盖：

```yaml
on_failure: continue          # 用例级默认失败策略

steps:
  - command: AT+CSQ
    assert: { contains: "+CSQ:" }
    on_failure: skip           # 步骤级覆盖
```

**与 retry 的交互**：retry 先于 on_failure 生效。步骤先按 retry 重试，所有重试耗尽仍失败后，才按 on_failure 处理。

## retry：失败重试

步骤失败后自动重试（断言失败、响应超时都算）。setup 和 steps 支持，**teardown 不支持**。

```yaml
steps:
  - command: AT+CEREG?
    assert: { var: stat, op: in, values: ["1", "5"] }
    extract: { stat: 'CEREG:\s*\d,(\d)' }
    retry:
      count: 3            # 最大重试次数（不含首次），默认 0（不重试）
      interval: 2000      # 重试间隔(ms)，默认 0
```

执行语义：
1. 首次失败 → 按 `interval` 等待 → 重试。
2. 重试上限：首次 + `count` 次。如 `count: 3` 共执行最多 4 次。
3. 任一次成功 → 步骤成功，停止重试。
4. 全部失败 → 步骤失败，按 `on_failure` 处理。
5. **重试粒度**：每次重试是"重新发送命令 + 重新断言 + 重新 extract"的完整步骤执行（extract 重算，保留最后一次成功的变量值）。
6. **retry 与 poll 互斥。**

## poll：轮询等待异步事件

等待异步事件（如等注网、等连接建立）。`timeout` 必填。

```yaml
steps:
  - command: AT+CEREG?
    extract: { stat: 'CEREG:\s*\d,(\d)' }
    poll:
      until: 'stat == "1" or stat == "5"'   # 条件表达式（用上面的语法）
      timeout: 60                            # 总超时(秒)，必填
      interval: 3000                         # 轮询间隔(ms)，默认 1000
    on_failure: continue                      # 超时未满足→按此策略
```

执行语义：
1. 执行命令 → extract → 求 `until` 表达式。
2. 满足 → 步骤成功，停止。
3. 不满足 → 等 `interval` → 再次执行命令（重新 extract）。
4. 累计达 `timeout` 仍未满足 → 步骤失败，按 `on_failure`。
5. 报告中展示轮询次数和总耗时。
6. **poll 与 retry 互斥**（语义重叠，避免双重循环）。

## wait_urc：等异步 URC 终结（与 poll 对比）

异步指令（如 `AT+CTM2MREG`）返回 `OK` 仅表受理，真正结果是后续上报的 URC。`wait_urc`
声明本步的真正终结是某条 URC（正则匹配），而非 `OK`。详见 SKILL.md「异步指令陷阱」。

```yaml
steps:
  - command: AT+CTM2MDEREG
    wait_urc: '\+CTM2M:dereg,0,\d+'   # 等这条 URC 才终结
    timeout: 10
    assert: { matches: '^\r\nOK\r\n\r\n\+CTM2M:dereg,0,\d+\r\n$' }
```

**poll 与 wait_urc 选哪个？**

| 维度 | poll | wait_urc |
|---|---|---|
| 适用 | 有同步查询指令（如 `AT+CTM2MREG?`）可查末态 | 需断言 URC 字节格式本身（冒号空格、成功码、id） |
| 机制 | 重复发查询指令轮询 `until` 条件 | 一次发指令，被动等 URC 上报 |
| URC 进 text | 否（只看查询响应） | 是（整段 OK+URC 进 text，可字节级断言） |

二者**互斥**（不能同一步同时用）。需断言 URC 格式 → `wait_urc`；只需确认操作完成 → `poll`。

## setup / teardown 对控制流的限制

| 修饰符 | setup | steps | teardown |
|---|---|---|---|
| `when` | ✅（条件不满足则跳过该 setup 步骤） | ✅ | ❌（仅 teardown 不支持） |
| `retry` | ✅ | ✅ | ✅（失败仅记警告，retry 耗尽也不影响用例结果） |
| `poll` | ✅（setup 中较少用） | ✅ | ❌ |
| `wait_urc` | ✅ | ✅ | ❌ |
| `on_failure` | ❌（setup 失败一律跳过整个用例） | ✅ | ❌（teardown 失败仅记警告） |

- setup 任一步骤失败（含 retry 耗尽）→ 跳过整个用例（标记"跳过"非"失败"），但 teardown 仍执行。
- teardown 无条件执行（用例成功/失败/被跳过都执行），其失败不影响用例结果，仅记警告。
