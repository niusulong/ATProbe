# 手动调试「文件发送」功能设计

- **日期**: 2026-06-27
- **范围**: `src/atprobe/gui/tabs/manual_debug.py`、`src/atprobe/gui/mainwindow.py`、`src/atprobe/infra/serial/connection.py`、`src/atprobe/infra/serial/portmanager.py`
- **关联**: 延续「命令库侧栏」改造（`2026-06-27-manual-debug-command-library-design.md`）同一手动调试页

## 1. 背景与目标

手动调试页目前只能发送**文本 AT 指令**（`send_manual` → `write_command`，自动追加 `\r\n`）。调试现场存在将**整个文件作为原始数据**写入串口的需求（固件烧录包、二进制配置 blob、长文本脚本等）。

现有 `write_command` 链路 str-only 且强制追加结束符，不适合原始字节。但基础设施层已存在原始字节咽喉点 `SerialConnection.write_bytes`（不加结束符、不分块）与分块发送器 `send_data_stream`（可取消），可直接复用。

**目标**：在手动调试页新增「文件发送」卡片，支持选择文件并以**原始字节**（不加结束符）写入当前端口；大文件后台分块发送、进度可取消、TX 原始数据流式上屏（与现有 RX 渲染一致）。

## 2. 需求（已与用户确认）

1. **发送语义**: 原始字节，**不加结束符**。
2. **TX 显示**: 流式逐块上屏 —— 与现有 RX 渲染逻辑一致（按行/HEX 切分），尊重「HEX显示」开关，受 10000 行环形缓冲约束。
3. **UI 位置**: 在「端口」卡片与「发送」卡片之间新增独立的「文件发送」卡片。
4. **大文件处理**: 分块 + 后台线程 + 进度 + 可取消。
5. **块参数**: 紧凑默认值（块 1024 字节、间隔 5ms），代码常量，UI 不可调。

## 3. 架构与数据流

新增文件发送走**原始字节链路**，与现有文本发送并列：

```
ManualDebugWidget (GUI 主线程)
  ├─ _send_text()        → main.send_manual(port, str)         [现有，追加结束符]
  └─ _send_file()
       ├─ 小文件(≤4KB):  main.send_file(port, bytes)           [新增，同步单次写]
       │                    └─ port_manager.write_bytes(port, data)   [新增]
       │                          └─ conn.write_bytes(chunk) + 通知 TX 观察者
       └─ 大文件(>4KB):  FileSendWorker(QThread)
                            └─ 内联分块循环（算法同 send_data_stream，逐块发信号）
                                  └─ conn.write_bytes(chunk) + 通知 TX 观察者
```

**分层职责**:

- **GUI 层**（`manual_debug.py`）: 新增「文件发送」卡片；主线程读取文件为 bytes；根据大小路由小文件/大文件分支；显示进度/取消；worker 通过 Qt 信号回主线程上屏。
- **后台线程**（`FileSendWorker(QObject)`）: 包裹现有 `send_data_stream`，分块写入、可取消；信号回主线程报进度/逐块 TX/完成/失败。
- **MainWindow 层**（`mainwindow.py`）: 新增 `send_file(port, data) -> bool`（同步薄封装，仅服务小文件路径）；新增 `get_connection(port)` 透传（供大文件 worker 持有连接）。
- **PortManager 层**（`portmanager.py`）: 新增 `write_bytes(port, data)`，转调 `conn.write_bytes`。

**关键决策 —— 小文件 / 大文件分流**:

- 阈值复用 `DataStreamSpec.chunk_threshold`（默认 4096 字节）。
- 小文件（≤4KB）: 走 `main.send_file()` 同步单次写入，不开线程。TX 整块一次性上屏（复用同一 `_render_tx_bytes`）。瞬发，无进度。
- 大文件（>4KB）: 后台 `QThread` 分块发送（默认 1024 字节/块、5ms 间隔），进度条 + 可取消。worker 直接持 `SerialConnection`，**内联分块循环**（算法同 `send_data_stream`，逐块发 `chunk_sent`/`progress` 信号），不经 `send_file` 也不经 `send_data_stream` 外壳（外壳无逐块回调插桩点；详见 §7）。

## 4. UI 布局与交互

在「端口」与「发送」卡片之间插入新卡片:

```
┌─ 端口 ─────────────────────────────────────┐
│ COM5  刷新  波特率 115200  帧格式 8N1  [打开端口] │
└────────────────────────────────────────────┘
┌─ 文件发送 ─────────────────────────────────┐  ← 新增
│ [选择文件…]  固件.bin (12,345 字节)            │
│ ──────────────────────────────── 57%  [发送][取消]│  ← 进度条仅发送中显示
└────────────────────────────────────────────┘
┌─ 发送 ─────────────────────────────────────┐
│ 输入 AT 指令…               [发送][清空] 结束符  │
└────────────────────────────────────────────┘
┌─ 响应 ─────────────────────────────────────┐
│ TX> <文件分块原始数据>                        │  ← 文件 TX 流式上屏
│ RX> OK                                       │
└────────────────────────────────────────────┘
```

**控件**:

- 「选择文件…」按钮 → `QFileDialog.getOpenFileName`。选完显示文件名 + 字节数（只读预览标签）。
- 「发送」按钮 → 校验端口已连接 → 读取文件 bytes → 路由小文件/大文件分支。
- 「取消」按钮 → 仅发送中可见，触发 `CancelToken` 中断 worker。
- `QProgressBar`（0–100）+ 百分比标签 → 仅发送中可见。

**交互规则**:

- **互斥**: 文件发送期间，文本「发送」按钮、文本发送框、「选择文件」按钮均禁用（避免双路并发写入同一串口）。反之文本发送进行时文件发送按钮也禁用（文本发送同步瞬发，实际仅文件发送期需要互斥，但为稳妥双向禁用）。
- 「发送」未选文件时禁用；未连接端口时禁用。
- 发送中「发送」「选择文件」禁用，仅「取消」可用。
- 响应区 TX 行: 文件**原始数据**流式逐块上屏（同 RX 渲染，尊重 HEX 开关 + 10000 行环形缓冲）。完成时不再额外加摘要行。取消时追加 `TX> 📄 文件名 已取消 (已发 X/N 字节)` 摘要行；失败断连追加 `RX> [错误] 发送中断 (已发 X/N 字节)`。

**生命周期**: worker（`QThread` + `moveToThread`）在完成/失败/取消后 `quit()`+`wait()` 释放；页面析构（关页/关窗）时若有进行中发送，先 `cancel.set()` 再 `wait()`，避免悬挂线程。

## 5. 基础设施层改动（最小）

| 文件 | 改动 | 说明 |
|---|---|---|
| `infra/serial/connection.py` | `write_bytes` 增加 `self._notify_tx_observers(data)` | 修复咽喉点观测性缺口（详见 §6） |
| `infra/serial/portmanager.py` | 新增 `write_bytes(port, data) -> None` | 取连接后转调 `conn.write_bytes` |
| `gui/mainwindow.py` | 新增 `send_file(port, data) -> bool` | 判断连接 → `port_manager.write_bytes`；异常弹窗 + 返回 False（与 `send_manual` 同构） |
| `gui/mainwindow.py` | 新增 `get_connection(port)` 透传 | 供大文件 worker 持有连接 |

## 6. 设计原则：TX 观察者通知置于咽喉点（已定案）

**决策**: 在共享的 `SerialConnection.write_bytes` 中加 `self._notify_tx_observers(data)`，而非把通知放到调用方（worker/`send_file`）。

**理由**:

1. **咽喉点完整性**: `SerialConnection` 是所有字节写入的唯一咽喉点，TX 观察者挂在此处的核心契约是「订阅一次即见这条链路的一切」。调用方通知会永久破坏此不变量（引擎 `send_data_stream` 仍静默 → 抽象泄漏）。
2. **一致性**: `write_command` 通知、`write_bytes` 不通知是不同时期写下的疏漏（非有意设计）。改 `write_bytes` 让两个写方法对观测性一致，修复一处不对称。
3. **DRY/内聚**: 通知与它观测的写操作同居咽喉点，单一来源；调用方通知会让「想被监控就得记得自己通知」成为分散、易漏的逻辑。
4. **变更性质是正确性改进**: 引擎数据流发送后对监控页不可见本身是潜在 bug；A 顺手修复。无 opt-out 参数（YAGNI）—— 引擎本就该通知，无静默合法用例。

**风险评估**: `write_bytes` 仅被 `send_data_stream` 调用，无其他通知路径，**不会双通知**；分块后每条通知 ~1KB，正是 RX/监控本就按块处理的粒度，无性能问题。全量回归兜底；若某测试断言「数据流不通知 TX 观察者」，该断言针对的是 bug，应删而非迁就。

## 7. FileSendWorker 设计

放 `src/atprobe/gui/widgets/file_send.py`（独立模块，保持 `manual_debug.py` 聚焦于页面布局）。

**持有**:

- `SerialConnection`（经 `main.get_connection(port)` 取得）
- 文件 `bytes`（主线程预先读好）
- `DataStreamSpec`（`data=bytes`, `chunk_size=1024`, `chunk_interval_ms=5`, `append_terminator=False`）
- `CancelToken`

**信号**（均切回主线程）:

- `chunk_sent(bytes)` —— 每写完一块发一次，主线程复用 RX 渲染逻辑上屏 TX（方向标 `TX`、`data.tx` 颜色）。
- `progress(int)` —— 0–100，按已写字节占比。
- `finished(bool ok, str msg)` —— `ok=True` 正常完成；`ok=False` 含已发字节数的失败/取消消息。

**`run()`**:

```python
try:
    sent = 0
    n = len(self._data)
    # 用自定义包装包裹 send_data_stream 的 conn.write_bytes 调用以计数
    # —— 或更简单：直接遍历分块自行写入（spec 逻辑已简单），逐块 emit 信号
    ...
    self.finished.emit(True, f"已发送 {n} 字节")
except SendError as e:
    self.finished.emit(False, f"发送中断：{e}（已发 {sent}/{n} 字节）")
except OperationCancelled:
    self.finished.emit(False, f"已取消（已发 {sent}/{n} 字节）")
```

> 实现注: worker 不调 `send_data_stream` 外壳（外壳无逐块回调插桩点，无法发 `chunk_sent`/`progress`），而是内联同样的分块算法（while 偏移切块 + `_write_with_cancel`）逐块写入并发信号。算法与现有 `send_data_stream` 保持一致 —— 若复用意愿强，可把分块循环抽成共享函数，让 worker 与 `send_data_stream` 共用同一实现（实现期再定，不强求）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 文件读取失败（权限/OOM） | 弹窗「无法读取文件：…」，不进入发送 |
| 端口未连接 | 点「发送」弹窗「请先打开端口」，与文本发送一致 |
| 发送中断连 | worker 抛 `SendError` → `finished(False)` → 响应区追加 `RX> [错误] 发送中断 (已发 X/N 字节)`，进度停断点 |
| 取消 | 「取消」→ `cancel.set()` → `OperationCancelled` → `finished(False)` → 追加 `TX> 📄 文件名 已取消 (已发 X/N 字节)` |
| 重复点击 | 发送中「发送」「选择文件」禁用，仅「取消」可用 |
| 双路并发 | 文件/文本发送互斥禁用，避免并发写同一串口 |

## 9. 测试策略

- **GUI 集成测试**（`tests/integration/test_gui.py`，扩展 `_FakeMain` 加 `send_file`/`get_connection`）:
  - 文件发送卡片存在 + 选择文件后显示文件名/字节数
  - 未连接 → 弹窗/不发
  - 小文件 → 调 `send_file`、TX 整块上屏
  - 大文件 → worker 启动、进度递增、`chunk_sent` 逐块 TX 上屏、`finished(True)`
  - 取消 → `finished(False)` + 取消摘要行
  - 互斥: 文件发送中文本发送禁用
- **infra 单测**（`tests/unit/`）:
  - `PortManager.write_bytes` 转调连接
  - `write_bytes` 的 TX 观察者通知（新增）
  - 连接断开抛 `SendError`
- 不重测 `send_data_stream` 分块逻辑本身（已有覆盖），仅测 worker 的逐块信号插桩。
- 全量回归（`pytest` + `ruff` + `mypy`）确保 `write_bytes` 改动不破坏引擎。

## 10. 范围外（YAGNI）

- 块大小/间隔 UI 可调（已确认紧凑默认值常量化）。
- 文件发送的"追加结束符"选项（已确认纯原始字节）。
- 发送历史/最近文件列表。
- 多文件批量发送。
- 发送速率统计/预计剩余时间（进度百分比足够）。
- 断点续传（取消即丢弃，与现有 `send_data_stream` 语义一致）。
