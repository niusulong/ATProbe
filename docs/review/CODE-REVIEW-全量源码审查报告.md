# ATProbe 源码审查报告

> 版本：v1.0
> 日期：2026-07-06
> 状态：审查完成
> 审查对象：`src/atprobe/` 全量源码（v0.5.0）
> 审查范围：domain / engine / infra / reporting / gui 五层，共 ~90 个 Python 文件

---

## 1. 审查目的与方法

### 1.1 目的

对 ATProbe v0.5.0 的全量源码进行系统性审查，发现逻辑错误、线程安全问题、资源泄漏、边界缺陷与语义矛盾，为后续修复提供优先级排序。

### 1.2 方法

- 逐文件阅读 `src/atprobe/` 下全部模块（不含 GUI 渲染细节）。
- 对疑似 bug 编写验证脚本确认（非推测式报告）。
- 对照 `docs/requirements/` 需求文档与 `docs/design/` 技术选型文档交叉验证语义。

### 1.3 项目架构概览

```
src/atprobe/
├── domain/          # 领域层（case / report / suite / quickcmd）—— 纯逻辑，无 IO
│   ├── case/        #   用例模型、解析器、模板、提取器、断言、条件求值
│   ├── report/      #   报告模型、聚合器
│   ├── suite/       #   套件模型与解析
│   └── quickcmd/    #   快捷命令库
├── engine/          # 引擎层（调度器、步骤执行器、压测、配置）
├── infra/           # 基础设施层（serial / config / update / resources / runtime）
│   ├── serial/      #   串口连接、端口管理、虚拟模组、原始日志
│   └── update/      #   自更新（版本检查 / 下载 / 安装）
├── reporting/       # 报告渲染（HTML / 控制台）
├── gui/             # PySide6 桌面 GUI
└── cli/             # Typer CLI 入口
```

分层清晰（DIP/SRP），domain 层纯函数无副作用，infra 层封装 pyserial。整体工程质量较高。

---

## 2. 总体结论

架构设计与分层纪律优秀。domain 层纯函数化、不可变模型（frozen Pydantic）、接口隔离（Protocol）等实践到位。发现的问题集中在：

1. 引擎层的生命周期管理疏漏：时间戳丢失、错误原因丢弃、读线程重建缺失。
2. 虚拟模组应答器的语义矛盾：格式错误指令返回 OK。
3. 串口层的连接韧性（resilience）缺陷：重连后无读线程、空闲缓冲区增长。

问题分级：

| 级别 | 含义 | 数量 |
|------|------|------|
| P0 严重 | 影响核心功能正确性或导致静默错误 | 2 |
| P1 重要 | 影响可用性或诊断能力，强烈建议修复 | 4 |
| P2 次要 | 逻辑缺陷或边界遗漏，影响特定场景 | 4 |
| P3 风险 | 代码质量或潜在风险，建议优化 | 3 |

---

## 3. P0 严重问题

### P0-1. `_error_result()` 丢失端口打开失败的错误原因

**位置**：`src/atprobe/engine/scheduler.py:117`（调用）、`src/atprobe/engine/scheduler.py:466`（定义）

**现状**：端口全部打开失败时，`Engine.start()` 返回 `_error_result(config, msg)`，但该方法构造的 `ExecutionResult` 只有一个空 `Summary`（`total_cases=0`），传入的错误消息字符串完全丢失。`ExecutionResult` 模型本身也没有 `error` 字段。

```python
# scheduler.py:117
return self._error_result(config, f"端口打开失败：{exc}")

# scheduler.py:466
def _error_result(self, config: EngineConfig, msg: str) -> ExecutionResult:
    summary = Summary(start_time="", end_time="", duration_ms=0.0)
    return ExecutionResult(summary=summary, case_results=())  # msg 未被使用
```

**验证**：

```
>>> e._error_result(None, '端口打开失败：COM3 not found')
ExecutionResult(summary=Summary(start_time='', ...), case_results=())
# '端口打开失败' 不出现在结果的任何字段中
```

**影响**：用户执行时如果端口打不开，CLI 退出码为 1 但不显示原因，GUI 无法弹出有意义的错误提示。用户只能猜测是端口占用、权限不足还是不存在。

**建议**：

- `ExecutionResult` 增加可选字段 `error: str = ""`。
- `_error_result` 将 `msg` 写入该字段。
- CLI `run` 命令在 `result.error` 非空时输出到 stderr。

---

### P0-2. `AtResponder` 对格式错误的指令返回 OK 而非 ERROR

**位置**：`src/atprobe/infra/serial/atresponder.py:75`、`src/atprobe/infra/serial/atresponder.py:113`

**现状**：`_h_cereg_set` 和 `_h_cmgf` 在参数解析失败时 `return []`，注释写"落到 ERROR"，但空列表被 `respond()` 当作正常 body 处理，最终追加 `OK`。

```python
# atresponder.py:75 (_h_cereg_set)
def _h_cereg_set(self, cmd: str) -> list[str]:
    try:
        n = int(cmd.split("=", 1)[1].split(",")[0])
        self.cereg_n = n
    except (IndexError, ValueError):
        return []  # 注释说"落到 ERROR"，但实际走 OK 路径
    return []  # OK

# atresponder.py:113 (_h_cmgf) — 同样的问题
except (IndexError, ValueError):
    return []
return []
```

`respond()` 的逻辑：

```python
if body is None:
    return echo + _line("ERROR")
# body == [] 不等于 None，走下面的 OK 路径
frame = echo
for line in body:  # 空列表，不循环
    frame += _line(line)
frame += _line("OK")  # 追加 OK
return frame
```

**验证**：

```
AT+CEREG=abc  ->  b'AT+CEREG=abc\r\nOK\r\n'   # 应返回 ERROR
AT+CMGF=xyz   ->  b'AT+CMGF=xyz\r\nOK\r\n'    # 应返回 ERROR
```

**影响**：`--vsim` 模式下格式错误的指令被误判为成功。测试用例可能假 PASS（断言 `contains: OK` 通过），掩盖真实 bug。虚拟模组本应模拟真实模组的错误拒绝行为。

**建议**：引入哨兵值区分"正常空 body（返回 OK）"与"解析失败（返回 ERROR）"，解析失败处改为 `return None`，`respond()` 中 `if body is None` 走 ERROR 分支。

---

## 4. P1 重要问题

### P1-1. `Engine.start()` 不记录执行时间戳和总耗时

**位置**：`src/atprobe/engine/scheduler.py:209`

**现状**：`aggregate(case_results)` 调用时没有传入 `start_time`、`end_time`、`duration_ms`，三者始终为默认空值/零。

```python
summary = aggregate(case_results)
# aggregate 签名：aggregate(case_results, *, start_time="", end_time="", duration_ms=0.0)
```

`Engine.start` 入口处没有记录开始时间，结束时也不计算耗时。

**验证**：

```
>>> aggregate([CaseResult(...)]).start_time
''
>>> aggregate([CaseResult(...)]).duration_ms
0.0
```

**影响**：

- 控制台报告输出"总耗时: 0.0s"（console.py 的 else 分支）。
- HTML 报告的时间区间为空，无法追溯执行时间。
- 用户无法从报告中判断执行是否异常缓慢。

**建议**：在 `start()` 入口记录 `t_start = datetime.now()` 和 `clock()`，结束前计算耗时传入 `aggregate`。

---

### P1-2. 串口 `reconnect()` 不重建读线程

**位置**：`src/atprobe/infra/serial/connection.py:350`（`_try_open_once`）

**现状**：`_try_open_once()` 重新打开串口并设置 `_connected=True`，但没有重启 `_read_thread`。如果断连导致读线程退出，重连后端口显示"已连接"但无人读取数据。

```python
def _try_open_once(self) -> bool:
    self._serial = serial.Serial(...)
    self._connected = True
    return True
    # 缺少：重启 _read_thread
```

读线程 `_read_loop` 在 `_handle_disconnect` 后会退避并重试读取。如果 `_serial` 被替换为新对象但 `_stop_event` 未被 clear，读线程可能仍在循环但读旧对象，或已退出。

**影响**：断连重连后，`send_command` 会永久超时（响应队列永远收不到数据），表现为"卡住"。

**建议**：`_try_open_once` 成功后重启读线程，注意先 join 旧线程避免泄漏。

---

### P1-3. 空闲状态下串口缓冲区无限增长

**位置**：`src/atprobe/infra/serial/connection.py:317`（`_process_incoming`）

**现状**：`_buffer` 在每次 `send_command` 调用时清空。但如果设备持续发送数据（URC、心跳、日志）而无人调用 `send_command`（例如 GUI 监控页面长时间挂着），`_buffer` 会在 `_process_incoming` 中不断 `extend(chunk)` 而从不被清空。

在"非等待响应"分支中，URC 行被 `_dispatch_urc` 处理，但 `_buffer` 本身只在"找到终结符"时才截断为 `tail`。空闲时不会遇到终结符匹配（`awaiting` 为 False），所以 `_buffer` 持续累积所有历史字节。

**影响**：长时间运行的 GUI 会话（数小时）中，内存缓慢增长，最终可能 OOM。

**建议**：在"非等待响应"分支中，处理完完整行后只保留 tail。

---

### P1-4. `AtResponder` 解析失败与成功返回值不可区分

**位置**：`src/atprobe/infra/serial/atresponder.py:75`

**现状**：`_h_cereg_set` 和 `_h_cmgf` 的 except 块当前 `return []` 与成功路径 `return []` 完全相同，无法区分。这是 P0-2 的根因，也是接口设计缺陷：handler 的返回值类型应能表达"成功空响应"与"失败"两种语义。

**影响**：新增任何带参数解析的 handler 都会重复同样的错误模式。

**建议**：统一 handler 返回值约定为 `list[str] | None`，`None` 表示 ERROR。所有现有 handler 的 `return []` 保持不变，解析失败处改为 `return None`。

---

## 5. P2 次要问题

### P2-1. 目录递归漏扫 `.yml` 文件

**位置**：`src/atprobe/cli/commands/run.py:272`

**现状**：目录递归用 `rglob("*.yaml")`，但单文件检查接受 `(".yaml", ".yml")` 两种后缀。

```python
for f in sorted(p.rglob("*.yaml")):  # 只匹配 .yaml
    ...
elif p.is_file() and p.suffix in (".yaml", ".yml"):  # 单文件接受 .yml
```

**影响**：用户用 `.yml` 后缀的用例文件放在目录下时不会被自动发现，但显式传文件路径可以执行。行为不一致。

**建议**：用列表推导覆盖两种后缀。

---

### P2-2. `_run_poll` 首轮立即发送，不等待 interval

**位置**：`src/atprobe/engine/step_runner.py:196`

**现状**：poll 循环 `while True` 第一轮立即执行 `_single_attempt`，`sleep(interval)` 在循环末尾。

**影响**：如果设备需要时间准备结果，首轮查询过早，可能拿到上一条命令的残留响应。

**建议**：在循环开头 `sleep(interval)`（首轮也等待），或在代码注释中明确"首轮立即查询"是有意设计。

---

### P2-3. `aggregate()` 的 `by_tag` 标签分布不完整

**位置**：`src/atprobe/domain/report/aggregator.py:34`

**现状**：`by_tag` 只统计 `total`/`passed`/`failed`，SKIPPED 和 INTERRUPTED 的用例会计入 `total` 但不计入 `passed` 或 `failed`，导致 `passed + failed < total`。

**影响**：报告中按标签查看时数字对不上，SKIPPED 用例"消失"。

**建议**：增加 `skipped` 和 `interrupted` 计数。

---

### P2-4. 套件文件 `.yml` 与目录扫描联动问题

**位置**：`src/atprobe/cli/commands/run.py:272`

**现状**：套件文件识别靠 `p.name.startswith("suite-")`，对 `.yml` 后缀也生效（显式传路径时）。但目录递归时不覆盖 `.yml`，所以 `suite-*.yml` 只能显式传路径。

**建议**：修复 P2-1 时一并确保 `rglob` 覆盖两种后缀的 suite 文件。

---

## 6. P3 潜在风险

### P3-1. `FakePortManager` 字段初始化重复赋值

**位置**：`src/atprobe/infra/serial/fakeserial.py:49`

```python
self._urc_handlers: dict[str, list[URCHandler]] = field(default_factory=dict)
self._urc_handlers = {}  # 紧接着显式赋空 dict，field 声明失效
```

`dataclasses.field` 用于类级注解时才有效，在 `__init__` 方法体中写 `self.x = field(...)` 不会触发 default_factory。第一行代码完全无效且有误导性。

**建议**：删除 `field(default_factory=dict)` 那一行。

---

### P3-2. HTML 报告"全部失败"判定遗漏全部跳过场景

**位置**：`src/atprobe/reporting/html.py:38`

```python
elif s.passed == 0:
    overall = ("全部失败", "fail")   # 全部 SKIPPED 时也命中这里
```

如果所有用例都被 SKIPPED（`passed=0, failed=0, skipped=N`），误判为"全部失败"。

**建议**：增加 `s.failed > 0` 条件与"全部跳过"分支。

---

### P3-3. `installer.py` 自删除 bat 脚本的已知限制

**位置**：`src/atprobe/infra/update/installer.py:171`

bat 自删除在文件锁失败时残留。低概率，不阻塞功能。**建议**：可接受的权衡，无需修复。

---

## 7. 修复优先级建议

| 优先级 | 问题编号 | 预估工作量 | 建议排期 |
|--------|----------|-----------|----------|
| 立即修复 | P0-1（错误原因丢失） | 1h | 本周 |
| 立即修复 | P0-2（vsim 假 OK） | 1h | 本周 |
| 尽快修复 | P1-1（时间戳缺失） | 1h | 本周 |
| 尽快修复 | P1-2（读线程重建） | 2h | 本周 |
| 尽快修复 | P1-3（缓冲区增长） | 1h | 本周 |
| 尽快修复 | P1-4（handler 返回值语义） | 1h | 与 P0-2 合并 |
| 迭代修复 | P2-1（.yml 扫描） | 0.5h | 下个迭代 |
| 迭代修复 | P2-2（poll 首轮） | 0.5h | 下个迭代 |
| 迭代修复 | P2-3（标签统计） | 0.5h | 下个迭代 |
| 低优先级 | P3-1/2/3 | 各 0.5h | 顺手修复 |

**总计**：P0 + P1 约 6 小时，全部修复约 9 小时。

---

## 8. 审查覆盖范围

| 层 | 模块 | 文件数 | 状态 |
|----|------|--------|------|
| domain | case / report / suite / quickcmd | 13 | 全审 |
| engine | scheduler / step_runner / pressure / config / interfaces | 5 | 全审 |
| infra | serial（connection / portmanager / atresponder 等） | 10 | 全审 |
| infra | config / update / resources / runtime | 9 | 全审 |
| reporting | html / console / interfaces | 3 | 全审 |
| cli | main / run / list / gui / update | 5 | 全审 |
| gui | tabs / widgets / mainwindow / theme | 12 | 抽审（线程模型） |

未深入审查：GUI 渲染细节、PyInstaller 打包脚本、测试代码正确性。

---

## 附录 A. 验证脚本输出

### P0-1 验证

```
>>> e = Engine()
>>> result = e._error_result(None, '端口打开失败：COM3 not found')
>>> hasattr(result, 'error')
False
>>> '端口打开失败' in str(result)
False  # 错误消息完全丢失
```

### P0-2 验证

```
>>> r = AtResponder()
>>> r.respond('AT+CEREG=abc')
b'AT+CEREG=abc\r\nOK\r\n'   # 应为 ERROR
>>> r.respond('AT+CMGF=xyz')
b'AT+CMGF=xyz\r\nOK\r\n'    # 应为 ERROR
```

### P1-1 验证

```
>>> s = aggregate([CaseResult(case_name='t', case_file='', status=CaseStatus.PASS)])
>>> s.start_time
''
>>> s.duration_ms
0.0
```

---

*报告结束*
