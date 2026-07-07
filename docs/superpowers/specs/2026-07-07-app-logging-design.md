# 程序运行日志（诊断 + 长期运维）设计

> 日期：2026-07-07
> 状态：设计完成，待实现
> 关联问题：分发到 Win10 上跑用例（尤其压测）"卡住、不实际执行"，本机正常

---

## 1. 背景与根因

ATProbe 分发到 Win10 上跑用例（尤其压测）会"卡住、不实际执行"，本机（开发机）正常。

**根因**：引擎在子线程运行（`mainwindow.py::_run()` 在 `threading.Thread` 内），该线程**没有 try/except**。任何目标机环境差异（串口驱动、权限、路径编码、依赖缺失、反病毒拦截等）触发的异常，会让子线程**静默死亡**——Python 子线程的未捕获异常默认只打印到 stderr 后消失。而打包态 GUI 是 `console=False`，连 stderr 都无处可看，UI 表现为"卡住不动"。

本机正常是因为开发机的环境恰好不触发那些异常路径。

## 2. 目标

1. **长期运维功能**：每次运行自动记录关键事件（启动、端口、引擎、异常），默认 INFO 级，作为产品正式能力长期保留。
2. **让"卡住"变可见**：双层异常兜底 + UI 即时提示，让目标机用户能立刻区分"卡住 vs 出错"，并知道去哪查日志。
3. **零新依赖**：仅用 Python 标准库 `logging`。

## 3. 非目标（YAGNI）

- 不手写日志器（复用标准库 `logging`，不重复造轮子）。
- 不给 GUI 加 `--debug` 或"详细日志"菜单项（CLI `--debug` 已足够排查；本次不做）。
- 不改 GUI 渲染细节、不改串口/引擎核心逻辑（仅埋点 + 异常兜底）。
- 不做日志的远程上报/聚合（本地文件足够）。

## 4. 架构与组件

新增 1 个模块 + 改动 3 个入口，职责清晰、依赖单向：

| 组件 | 位置 | 职责 |
|------|------|------|
| **日志配置模块**（新建） | `src/atprobe/infra/logging_config.py` | `setup_logging(level, debug=False) -> Path`：配置根 logger，挂 `RotatingFileHandler`（`user_workspace()/logs/atprobe.log`，2MB×5 轮转）+ 控制台 handler。返回日志文件路径，供菜单使用。单一职责：只管"日志怎么写"。 |
| **全局异常钩子**（同模块） | `install_excepthook(error_cb=None)` | 安装 `threading.excepthook`（子线程）+ `sys.excepthook`（主线程未捕获），异常格式化后 `logger.error` + 经可选 `error_cb` 回调转发到 UI。一劳永逸兜底所有线程静默死亡。 |
| **GUI 启动**（改） | `src/atprobe/gui/app.py` | `run_gui()` 开头调 `setup_logging()` + `install_excepthook()`。最早接入，确保启动期异常也被记录。 |
| **引擎执行**（改） | `src/atprobe/gui/mainwindow.py` | `_run()` 加 try/except：捕获异常 → `logger.exception` + 经 `progress` 信号推 `("engine_error", 摘要)`；`_on_progress` 新增 `engine_error` 分支（状态栏变红 + 弹窗提示看日志）。 |
| **菜单 + CLI**（改） | mainwindow 菜单栏 / `cli/commands/run.py` | 「帮助 → 打开日志目录」（`QDesktopServices.openUrl`）；CLI `run` 加 `--debug` 提到 DEBUG 级。 |

**日志格式**：
```
2026-07-07 14:30:25.123 [INFO] [Thread-1 engine] 端口 COM5 已打开
```
含时间戳（毫秒）、级别、线程名、模块、消息——定位远程问题够用。

**依赖方向**：单向。`logging_config` 不依赖 GUI；GUI/引擎依赖 `logging_config`；引擎 → `progress` 信号 → UI（不反向）。

## 5. 数据流与错误处理（核心：让"卡住"不再静默）

### 5.1 正常执行流（INFO 级埋点）

```
[INFO] [MainThread app] ATProbe 启动 (version=X, frozen=打包态/开发态)
[INFO] [MainThread app] 配置: atprobe.yaml=<路径>, cases_dir=<路径>, log_dir=<路径>
[INFO] [engine] 开始执行: 2 个用例, 端口 COM5, 阈值 95%
[INFO] [engine] 端口 COM5 已打开
[INFO] [engine] 用例 1/2: 信号查询
[INFO] [engine] 用例 1/2 完成: PASS (120ms)
...
[INFO] [engine] 执行结束: 2通过/0失败, 耗时 312ms
```

### 5.2 异常流——双层兜底

**第一层：引擎线程显式 try/except**（最常见异常源，给最精准的 UI 反馈）

```python
# mainwindow.py::_run()（引擎线程）
def _run():
    try:
        result = self._engine.start(cfg, handler=lambda ev: self.progress.emit(ev))
        # 生成报告...
        self.progress.emit(("done", str(rdir), passed, failed))
    except Exception as exc:
        logger.exception("引擎执行异常")                          # 完整 traceback 写日志
        self.progress.emit(("engine_error", f"执行异常：{exc}"))   # 推 UI
```

`_on_progress` 新增 `engine_error` 分支：
- 状态栏变红显示错误摘要
- `QMessageBox.critical(self, "执行异常", "...详见日志：<路径>")`

用户立刻知道"是出错了，不是卡住"，且知道去哪看完整原因。

**第二层：`threading.excepthook` 全局兜底**（捕获任何未 try/except 的线程异常，如串口读线程、文件发送 worker）

```python
def _thread_excepthook(args):
    logger.error(
        "未捕获的线程异常 [%s]",
        getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
threading.excepthook = _thread_excepthook
```

`sys.excepthook` 同理覆盖主线程未捕获异常（开发态崩溃也落盘，而非只闪退）。

### 5.3 跨线程安全

两层的 UI 通知路径：
- **第一层（引擎 `_run`）**：直接用已有的 `self.progress.emit(...)`——`progress` 是 Qt Signal，在子线程 emit 天生安全地转发到主线程事件循环。**不新增信号**。
- **第二层（excepthook）**：`error_cb` 是可选回调（由 app.py 注入，内部也走 Qt 信号转发主线程）。excepthook 兜底的线程（如串口读线程）可能不属于任何带 Signal 的对象，故用独立回调而非直接 emit。

两条路径都不在子线程直接操作 UI 控件。

### 5.4 日志路径健壮性

`setup_logging` 内 `logs/` 目录创建失败（权限/只读/路径非法）时，**降级到** `tempfile.gettempdir()/atprobe.log`，并 `logger.warning` 记录降级——确保任何环境下都能写日志（哪怕在工作目录无写权限的受限机器上）。

## 6. 日志位置、UI 入口与配置

### 6.1 日志文件位置

复用现有 `user_workspace()`（打包态 = exe 同级，开发态 = 仓库根）：
- 打包态：`<exe 同级>/logs/atprobe.log`（便携式，用户最容易找到）
- 开发态：`<仓库根>/logs/atprobe.log`

**与 `atprobe.yaml` 的 `log_dir` 关系**：`log_dir`（默认 `./logs`）存放的是**串口原始字节日志**（已有 `RawLogger`，按会话/端口/用例分文件）；`atprobe.log` 是**程序运行日志**（本功能）。两者**同目录、不同文件、职责分离**，不混淆。

### 6.2 轮转

`RotatingFileHandler(maxBytes=2MB, backupCount=5)`：最多 6 个文件约 12MB。压测/监控长跑也安全，不会撑爆磁盘。轮转文件名：`atprobe.log` / `atprobe.log.1` ~ `atprobe.log.5`。

### 6.3 UI 入口——「帮助」菜单

菜单栏新增「帮助」菜单：
- **「打开日志目录」**：`QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))`，资源管理器直接打开。非技术用户一键定位，无需懂路径。

### 6.4 `--debug` 开关（CLI）

`atprobe run --debug` → `setup_logging(level=DEBUG)`，记录串口收发、引擎每步、变量提取等细节。GUI 本次不加（双击启动无参数；YAGNI）。

### 6.5 INFO 埋点范围（本次，不过度）

| 位置 | 埋点 |
|------|------|
| `app.py` | 启动（版本、frozen 态）、配置路径 |
| `mainwindow.run_cases` | 开始执行（用例数/端口/阈值）、端口打开、执行结束（结果摘要/耗时） |
| `mainwindow._run` | 异常（`logger.exception` 含 traceback） |

串口/引擎深层（如每帧收发、每步状态机）**暂不埋点**，留给未来 `--debug` 扩展——保持 INFO 安静。

## 7. 测试策略

### 7.1 单元测试（`tests/unit/test_logging_config.py`，新建）

- `setup_logging` 配置正确：根 logger 含 RotatingFileHandler + StreamHandler；级别正确；返回的路径存在
- `logs/` 创建失败（mock `mkdir` 抛 PermissionError）→ 降级到 `tempfile.gettempdir()`，且 logger 记录了降级 warning
- `install_excepthook`：模拟触发 `threading.excepthook` 回调 → 日志文件含异常类型与 traceback
- 幂等性：重复调 `setup_logging` 不重复挂 handler（避免日志重复写）

### 7.2 集成测试（`tests/integration/test_gui.py` 增补）

- 引擎线程抛异常（用 FakePortManager 制造 `start()` 内部异常）→ `progress` 信号收到 `("engine_error", ...)` 元组
- 日志文件含 "引擎执行异常" + traceback

## 8. 涉及文件

- **新建**：
  - `src/atprobe/infra/logging_config.py`
  - `tests/unit/test_logging_config.py`
- **改**：
  - `src/atprobe/gui/app.py`（启动时 setup + install_excepthook）
  - `src/atprobe/gui/mainwindow.py`（`_run` try/except + `_on_progress` 新分支 + 帮助菜单 + run_cases 埋点）
  - `src/atprobe/cli/commands/run.py`（`--debug` 选项 + setup_logging 调用）

## 9. 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 日志定位 | 长期运维功能（非临时） | 用户明确要求；投入完整设计值得 |
| 默认级别 | INFO | 平衡信息量与磁盘占用；每次运行几 KB~几十 KB |
| 卡住时反馈 | 写日志 + UI 即时提示 | 让目标机用户区分"卡住 vs 出错"；知道去哪查 |
| 日志入口 | 菜单打开目录 + CLI --debug | 非技术用户一键定位；技术用户可切详细 |
| 实现方案 | 标准库 logging + threading.excepthook | 零依赖；excepthook 是子线程异常兜底最可靠手段 |
| 日志器 | 标准库（非手写） | 不重复造轮子；logging 是 Python 标配 |
| GUI --debug | 不做 | YAGNI；CLI --debug 够用 |
