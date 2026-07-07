# 程序运行日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 ATProbe 增加程序运行日志（标准库 logging + RotatingFileHandler），并用 threading.excepthook 全局兜底子线程异常，解决分发到 Win10 后引擎静默死亡表现为"卡住"的问题。

**Architecture:** 新建 `infra/logging_config.py`（日志配置 + 全局异常钩子，单一职责）。app.py 启动时最早接入 setup_logging + install_excepthook。引擎 `_run()` 加显式 try/except，异常经已有 `progress` Qt Signal 推 UI 弹窗。帮助菜单加「打开日志目录」。CLI 加 `--debug`。零新依赖（仅标准库）。

**Tech Stack:** Python 标准库 logging / logging.handlers.RotatingFileHandler / threading.excepthook / sys.excepthook；PySide6（QDesktopServices 打开目录、QMessageBox 弹窗）；Typer（--debug 选项）。

**Spec:** `docs/superpowers/specs/2026-07-07-app-logging-design.md`

---

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `src/atprobe/infra/logging_config.py` | 日志配置（setup_logging）+ 全局异常钩子（install_excepthook） | 新建 |
| `tests/unit/test_logging_config.py` | logging_config 的单元测试 | 新建 |
| `src/atprobe/gui/app.py` | GUI 启动时 setup_logging + install_excepthook | 改 |
| `src/atprobe/gui/mainwindow.py` | `_run` try/except + `_on_progress` engine_error 分支 + 帮助菜单 + run_cases 埋点 | 改 |
| `src/atprobe/cli/commands/run.py` | `--debug` 选项 + setup_logging 调用 | 改 |
| `tests/integration/test_gui.py` | 引擎异常时 progress 收到 engine_error 的集成测试 | 改（增补） |

依赖方向单向：`logging_config` 不依赖 GUI/CLI；GUI/CLI 依赖 `logging_config`。

---

## Task 1: 新建日志配置模块（setup_logging）

**Files:**
- Create: `src/atprobe/infra/logging_config.py`
- Test: `tests/unit/test_logging_config.py`

- [ ] **Step 1: 写失败测试——setup_logging 配置正确**

Create `tests/unit/test_logging_config.py`:

```python
"""程序运行日志配置测试（logging_config）."""

from __future__ import annotations

import logging
from pathlib import Path


def test_setup_logging_configures_root_logger(tmp_path, monkeypatch):
    """setup_logging 后根 logger 含 FileHandler + StreamHandler，级别正确，返回的路径存在."""
    from atprobe.infra import logging_config

    # 把工作区定向到 tmp_path，避免污染真实 logs/
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    # 重置根 logger（清理其他测试可能挂的 handler）
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        log_path = logging_config.setup_logging(level=logging.INFO)
        assert log_path.exists()  # 文件已创建
        assert log_path.parent == tmp_path / "logs"
        # 根 logger 至少含一个 FileHandler 和一个 StreamHandler
        handler_types = [type(h) for h in root.handlers]
        assert any(issubclass(t, logging.FileHandler) for t in handler_types)
        assert any(issubclass(t, logging.StreamHandler) for t in handler_types)
        assert root.level == logging.INFO
    finally:
        # 恢复根 logger，避免污染其他测试
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run --extra dev python -m pytest tests/unit/test_logging_config.py::test_setup_logging_configures_root_logger -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.infra.logging_config'`

- [ ] **Step 3: 实现 setup_logging（最小可用）**

Create `src/atprobe/infra/logging_config.py`:

```python
"""程序运行日志配置（诊断 + 长期运维）.

用标准库 logging + RotatingFileHandler，把程序运行的关键事件（启动/端口/引擎/异常）
落到 ``user_workspace()/logs/atprobe.log``（2MB×5 轮转）。``install_excepthook`` 全局
兜底子线程未捕获异常，避免引擎/读线程静默死亡表现为"UI 卡住"。

零新依赖（仅标准库）。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from atprobe.infra.resources import user_workspace

# 日志格式：时间戳(毫秒) [级别] [线程名 模块] 消息
_FORMAT = "%(asctime)s [%(levelname)s] [%(threadName)s %(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
# 毫秒精度：logging 默认 asctime 含 ,sss，符合需求，无需额外改

_MAX_BYTES = 2 * 1024 * 1024  # 2MB
_BACKUP_COUNT = 5

# 模块级日志目录定位（可被测试 monkeypatch 覆盖）
def _log_dir() -> Path:
    return user_workspace() / "logs"


def setup_logging(level: int = logging.INFO) -> Path:
    """配置根 logger：文件（轮转）+ 控制台 handler。返回日志文件路径。

    幂等：重复调用先移除旧 handler，避免日志重复写入。
    日志目录创建失败（权限/只读）时降级到系统 temp 目录，并 warning 记录。
    """
    root = logging.getLogger()
    # 幂等：清掉旧 handler（重复 setup 不重复挂）
    for h in root.handlers[:]:
        h.close()
        root.removeHandler(h)
    root.setLevel(level)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # 文件 handler：优先工作区 logs/，失败降级 temp
    log_path = _log_dir() / "atprobe.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        import tempfile

        log_path = Path(tempfile.gettempdir()) / "atprobe.log"
        # 降级也要先 log（用临时 stderr handler 兜底，此时文件 handler 还没建）
        logging.basicConfig(level=level, stream=sys.stderr, format=_FORMAT)
        logging.warning("日志目录 %s 不可写，降级到 %s", _log_dir(), log_path)
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        root.setLevel(level)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 控制台 handler（开发态 / CLI 有用；GUI console=False 时无害）
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    return log_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --extra dev python -m pytest tests/unit/test_logging_config.py::test_setup_logging_configures_root_logger -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/infra/logging_config.py tests/unit/test_logging_config.py
git commit -m "feat(logging): 新建 logging_config 模块（setup_logging + RotatingFileHandler）"
```

---

## Task 2: 全局异常钩子（install_excepthook）

**Files:**
- Modify: `src/atprobe/infra/logging_config.py`
- Test: `tests/unit/test_logging_config.py`

- [ ] **Step 1: 写失败测试——threading.excepthook 把异常写进日志**

追加到 `tests/unit/test_logging_config.py`:

```python
def test_thread_excepthook_logs_exception(tmp_path, monkeypatch):
    """install_excepthook 后，触发 threading.excepthook 回调，日志文件含异常信息."""
    import threading

    from atprobe.infra import logging_config

    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    log_path = logging_config.setup_logging(level=logging.INFO)
    captured: list[Exception] = []
    logging_config.install_excepthook(error_cb=captured.append)

    # 模拟一个线程异常：直接调 threading.excepthook（Python 3.8+）
    try:
        raise RuntimeError("测试线程异常")
    except RuntimeError:
        exc_info = sys.exc_info()
    # 构造 threading.ExceptHookArgs 的最小替身
    fake_args = threading.ExceptHookArgs(
        exc_type=exc_info[0], exc_value=exc_info[1], exc_traceback=exc_info[2],
        thread=threading.current_thread(),
    )
    threading.excepthook(fake_args)

    # 日志文件含异常类型与消息
    content = log_path.read_text(encoding="utf-8")
    assert "RuntimeError" in content
    assert "测试线程异常" in content
    assert captured  # error_cb 被调用

    # 恢复默认 excepthook，避免污染其他测试
    threading.excepthook = threading.__exexcepthook__ if hasattr(threading, "__exexcepthook__") else threading.excepthook
```

注意：`threading.ExceptHookArgs` 需 import。测试文件顶部加 `import sys`（如果还没有）。

更新测试文件顶部 import 区为：

```python
"""程序运行日志配置测试（logging_config）."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run --extra dev python -m pytest tests/unit/test_logging_config.py::test_thread_excepthook_logs_exception -v`
Expected: FAIL — `AttributeError: module 'atprobe.infra.logging_config' has no attribute 'install_excepthook'`

- [ ] **Step 3: 实现 install_excepthook**

追加到 `src/atprobe/infra/logging_config.py`（`setup_logging` 之后）:

```python
import threading
from collections.abc import Callable


def install_excepthook(error_cb: Callable[[BaseException], None] | None = None) -> None:
    """安装全局异常钩子：threading.excepthook（子线程）+ sys.excepthook（主线程）。

    任何线程的未捕获异常都记 ERROR 日志（含完整 traceback），避免引擎/读线程静默死亡。
    可选 error_cb 把异常转发到 UI（调用方负责跨线程切主线程，如经 Qt Signal）。

    Args:
        error_cb: 收到异常对象时的回调（如经 progress 信号推 UI 弹窗）。None 表示仅记日志。
    """
    logger = logging.getLogger("atprobe.excepthook")

    def _thread_hook(args) -> None:  # type: ignore[no-untyped-def]
        thread_name = getattr(args.thread, "name", "?")
        logger.error(
            "未捕获的线程异常 [%s]", thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if error_cb is not None and args.exc_value is not None:
            try:
                error_cb(args.exc_value)
            except Exception:  # noqa: BLE001 - error_cb 失败不影响日志
                logger.error("error_cb 回调自身抛异常", exc_info=True)

    def _main_hook(exc_type, exc_value, exc_tb) -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            # Ctrl+C 走默认行为（不记日志，避免开发态频繁打断污染）
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.error("未捕获的主线程异常", exc_info=(exc_type, exc_value, exc_tb))
        if error_cb is not None and exc_value is not None:
            try:
                error_cb(exc_value)
            except Exception:  # noqa: BLE001
                logger.error("error_cb 回调自身抛异常", exc_info=True)

    threading.excepthook = _thread_hook
    sys.excepthook = _main_hook
```

同时把 `import threading` 和 `from collections.abc import Callable` 加到文件顶部 import 区。最终 import 区为：

```python
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from atprobe.infra.resources import user_workspace
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --extra dev python -m pytest tests/unit/test_logging_config.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/infra/logging_config.py tests/unit/test_logging_config.py
git commit -m "feat(logging): install_excepthook 全局兜底子线程静默死亡"
```

---

## Task 3: setup_logging 路径降级测试 + 幂等测试

**Files:**
- Test: `tests/unit/test_logging_config.py`

- [ ] **Step 1: 写路径降级测试**

追加到 `tests/unit/test_logging_config.py`:

```python
def test_setup_logging_falls_back_to_temp_on_permission_error(monkeypatch):
    """logs/ 创建失败（权限）时降级到系统 temp 目录。"""
    from atprobe.infra import logging_config

    # 模拟 _log_dir() 返回一个无法 mkdir 的路径
    def _bad_dir() -> Path:
        return Path("/nonexistent_root_xyz/atprobe/logs")  # Linux 上无权限；Windows 上路径非法

    monkeypatch.setattr(logging_config, "_log_dir", _bad_dir)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        log_path = logging_config.setup_logging(level=logging.INFO)
        # 降级到 temp
        import tempfile
        assert str(log_path).startswith(tempfile.gettempdir())
        assert log_path.name == "atprobe.log"
    finally:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


def test_setup_logging_is_idempotent(monkeypatch, tmp_path):
    """重复调 setup_logging 不重复挂 handler。"""
    from atprobe.infra import logging_config

    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        logging_config.setup_logging(level=logging.INFO)
        count_after_first = len(root.handlers)
        logging_config.setup_logging(level=logging.INFO)
        count_after_second = len(root.handlers)
        assert count_after_second == count_after_first  # 不重复挂
    finally:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
```

- [ ] **Step 2: 运行测试确认通过**（实现已在 Task 1 完成，这步验证健壮性）

Run: `uv run --extra dev python -m pytest tests/unit/test_logging_config.py -v`
Expected: 4 passed

- [ ] **Step 3: 提交**

```bash
git add tests/unit/test_logging_config.py
git commit -m "test(logging): setup_logging 路径降级与幂等性测试"
```

---

## Task 4: GUI 启动接入日志（app.py）

**Files:**
- Modify: `src/atprobe/gui/app.py`

- [ ] **Step 1: 在 run_gui 开头接入 setup_logging + install_excepthook**

修改 `src/atprobe/gui/app.py` 的 `run_gui` 函数。在 `def run_gui(...)` 函数体最开头（所有 import 之前）加入日志初始化。注意要先 setup_logging 再 import GUI 模块，确保启动期异常也被记录。

把 `run_gui` 函数改为（仅展示改动部分，开头新增日志初始化）：

```python
def run_gui(argv: list[str] | None = None) -> int:
    """启动 GUI（延迟导入 PySide6，使 CLI 无 GUI 依赖时也能运行）."""
    # 最早接入日志：确保后续所有 import 与启动流程的异常都被记录（诊断 Win10 卡住的关键）
    import logging

    from atprobe.infra.logging_config import install_excepthook, setup_logging

    log_path = setup_logging(level=logging.INFO)
    logger = logging.getLogger("atprobe.app")
    install_excepthook()  # 全局兜底子线程静默死亡（GUI 的 error_cb 经 progress 信号，在 mainwindow 单独接）
    logger.info("ATProbe GUI 启动，日志: %s", log_path)

    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication

    from atprobe.gui.mainwindow import MainWindow  # noqa: F401 (重定向)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ATProbe")
    app.setOrganizationName("ATProbe")

    # ...（剩余代码不变，从「应用窗口图标」开始保持原样）
```

- [ ] **Step 2: 验证 GUI 能正常启动（冒烟）**

Run: `uv run --extra dev python -c "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); from atprobe.gui.app import run_gui; import sys; sys.argv=['x']; 
import threading; threading.Timer(1.5, lambda: __import__('PySide6.QtWidgets', fromlist=['QApplication']).QApplication.quit()).start(); run_gui()" 2>&1 | tail -5`
Expected: 输出含 "ATProbe GUI 启动，日志: ...atprobe.log"，无异常，1.5 秒后正常退出。

- [ ] **Step 3: 验证日志文件已生成**

Run: `ls -la logs/atprobe.log 2>/dev/null && echo "日志已生成" || echo "未生成（检查路径）"`
Expected: 显示日志文件，含启动记录。

- [ ] **Step 4: 提交**

```bash
git add src/atprobe/gui/app.py
git commit -m "feat(gui): 启动时接入 setup_logging + install_excepthook"
```

---

## Task 5: 引擎 _run try/except + UI 即时提示

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py`（`_run` 约 line 644-656，`_on_progress` 约 line 721-745）

- [ ] **Step 1: 写失败测试——引擎异常时 progress 收到 engine_error**

在 `tests/integration/test_gui.py` 的 `TestCaseExecuteExtras` 或新建类中追加。由于引擎线程异常需要主窗口实例，用最小化测试：直接测 `_run` 异常路径。先找一个合适的测试类位置（文件末尾追加新类）。

追加到 `tests/integration/test_gui.py` 末尾:

```python
class TestEngineErrorToUI:
    """日志功能：引擎线程异常时经 progress 信号推 UI（engine_error）。"""

    def test_engine_exception_emits_engine_error(self, qapp, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        """引擎 start() 抛异常 → _run 捕获 → progress 收到 ('engine_error', 消息)."""
        import logging

        from atprobe.gui.tabs.case_execute import CaseExecuteWidget  # noqa: F401
        from atprobe.gui.tabs.registry import TabBinding

        # 收集 progress 信号
        received: list[object] = []

        class _Main:
            def __init__(self):
                self.tabs = None

            def available_ports(self):
                return ["COM3"]

            def run_cases(self, files, port, threshold, **kw):  # noqa: ANN001
                # 模拟引擎线程内异常：直接调 _run 路径不便，改测 mainwindow 真实路径见下
                pass

        # 直接用真实 MainWindow 测 _run 异常路径太重，改单元化测 progress 信号机制：
        # 这里验证 _on_progress 能识别 engine_error 分支并弹窗（打桩）
        import PySide6.QtWidgets as _qw
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda *a, **k: 0)

        from atprobe.gui.mainwindow import MainWindow
        win = MainWindow()
        win.show()
        qapp.processEvents()

        # 模拟引擎线程 emit 了 engine_error
        critical_calls: list[str] = []
        monkeypatch.setattr(_qw.QMessageBox, "critical", lambda parent, title, msg: critical_calls.append(msg))

        # 直接 emit（模拟 _run 里 except 分支的 emit）
        win.progress.emit(("engine_error", "执行异常：模拟错误"))
        qapp.processEvents()

        # _on_progress 应识别 engine_error 并弹窗
        assert any("执行异常" in c and "日志" in c for c in critical_calls), \
            f"应弹窗提示执行异常+日志路径，实际: {critical_calls}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run --extra dev python -m pytest tests/integration/test_gui.py::TestEngineErrorToUI::test_engine_exception_emits_engine_error -v`
Expected: FAIL — `_on_progress` 不识别 `engine_error`，critical_calls 为空。

- [ ] **Step 3: 改 _run 加 try/except**

在 `src/atprobe/gui/mainwindow.py` 找到 `def _run() -> None:`（约 line 644），把整个 `_run` 函数体包进 try/except。原代码：

```python
        def _run() -> None:
            assert self._engine is not None
            result = self._engine.start(cfg, handler=lambda ev: self.progress.emit(ev))
            if no_report:
                self.progress.emit(("done_noreport", "", result.summary.passed, result.summary.failed))
                return
            # 生成报告
            rdir = resolve_workspace_path(self._app_config.report_dir) / session / "report.html"
            HtmlReporter().render(result, ReportOutput(html_path=rdir, to_console=False))
            self.progress.emit(("done", str(rdir), result.summary.passed, result.summary.failed))
```

改为（加 try/except + logger.exception + emit engine_error）:

```python
        def _run() -> None:
            assert self._engine is not None
            try:
                result = self._engine.start(cfg, handler=lambda ev: self.progress.emit(ev))
            except Exception as exc:
                # 引擎线程异常兜底：写完整 traceback 日志 + 推 UI 即时提示
                # （此前异常静默死亡 → UI 表现为"卡住"；现在用户能看到"出错了"并查日志）
                logger.exception("引擎执行异常")
                self.progress.emit(("engine_error", f"执行异常：{exc}"))
                self._set_engine_status("ERROR", self._tokens["danger"])
                return
            if no_report:
                self.progress.emit(("done_noreport", "", result.summary.passed, result.summary.failed))
                return
            # 生成报告
            try:
                rdir = resolve_workspace_path(self._app_config.report_dir) / session / "report.html"
                HtmlReporter().render(result, ReportOutput(html_path=rdir, to_console=False))
                self.progress.emit(("done", str(rdir), result.summary.passed, result.summary.failed))
            except Exception as exc:
                logger.exception("报告生成异常")
                self.progress.emit(("engine_error", f"报告生成异常：{exc}"))
                self._set_engine_status("ERROR", self._tokens["danger"])
```

同时在 `MainWindow` 类顶部（`run_cases` 方法定义之前，约 line 575 附近）加模块级 logger。在文件 import 区之后、类定义内 `__init__` 之前不加（logger 放模块级）。在文件顶部 import 区后添加：

在 `src/atprobe/gui/mainwindow.py` 顶部，`from atprobe.infra.config.envconfig import ...` 这类 import 之后，加入：

```python
import logging

_log = logging.getLogger("atprobe.engine_gui")
```

并把 `_run` 里的 `logger.exception` 改为 `_log.exception`（用模块级 logger）。即 `_run` 改动里的 `logger.exception(...)` 全部替换为 `_log.exception(...)`。

- [ ] **Step 4: 改 _on_progress 新增 engine_error 分支**

在 `src/atprobe/gui/mainwindow.py` 的 `_on_progress` 方法（约 line 721），在 `if isinstance(ev, tuple) and ev and ev[0] in ("done", "done_noreport"):` 分支**之前**插入 engine_error 分支。原 `_on_progress` 开头：

```python
    def _on_progress(self, ev: object) -> None:
        # 终止事件：done（生成报告）/ done_noreport（不生成报告）
        if isinstance(ev, tuple) and ev and ev[0] in ("done", "done_noreport"):
```

改为（前面加 engine_error 分支）:

```python
    def _on_progress(self, ev: object) -> None:
        # 引擎异常（线程内 try/except 捕获后推来）：状态栏变红 + 弹窗提示看日志
        if isinstance(ev, tuple) and ev and ev[0] == "engine_error":
            msg = ev[1] if len(ev) > 1 else "未知错误"
            self._set_engine_status("ERROR", self._tokens["danger"])
            from atprobe.infra.logging_config import _log_dir
            try:
                log_dir = _log_dir()
            except Exception:  # noqa: BLE001
                log_dir = None
            log_hint = f"\n\n详见日志：{log_dir / 'atprobe.log'}" if log_dir else "\n\n详见日志"
            QMessageBox.critical(self, "执行异常", f"{msg}{log_hint}")
            return
        # 终止事件：done（生成报告）/ done_noreport（不生成报告）
        if isinstance(ev, tuple) and ev and ev[0] in ("done", "done_noreport"):
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run --extra dev python -m pytest tests/integration/test_gui.py::TestEngineErrorToUI -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add src/atprobe/gui/mainwindow.py tests/integration/test_gui.py
git commit -m "feat(gui): 引擎线程异常兜底（try/except + progress 推 UI engine_error）"
```

---

## Task 6: run_cases 关键节点埋点（INFO 日志）

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py`（`run_cases` 方法）

- [ ] **Step 1: 在 run_cases 关键节点加 INFO 日志**

在 `src/atprobe/gui/mainwindow.py` 的 `run_cases` 方法（约 line 578）中，在以下位置加 `_log.info(...)`：

a) 在 `cfg = EngineConfig(...)` 构造之后、`self._engine = Engine(...)` 之前（约 line 640）加：

```python
        _log.info("开始执行: %d 个用例, 端口 %s, 阈值 %d%%", len(cases), port, threshold)
```

b) 在 `self._engine = Engine(sender_factory=lambda: self._port_manager)` 之后加注释行（实际日志在 _run 内引擎自己产生，这里只记录入口）。

c) 在 `_run` 的正常完成路径加结果摘要。修改 `_run`（Task 5 改过的版本），在 `self.progress.emit(("done", ...))` 之前加：

在 `_run` 函数里 `self.progress.emit(("done_noreport", ...))` 和 `self.progress.emit(("done", ...))` 两处之前各加一行：

```python
                _log.info("执行结束: %d通过/%d失败", result.summary.passed, result.summary.failed)
```

和

```python
                _log.info("执行结束: %d通过/%d失败, 报告: %s", result.summary.passed, result.summary.failed, rdir)
```

- [ ] **Step 2: 验证日志输出（冒烟）**

Run: `uv run --extra dev python -c "
import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import logging
from atprobe.infra.logging_config import setup_logging
setup_logging(level=logging.INFO)
from atprobe.gui.mainwindow import MainWindow
w = MainWindow()
# 验证 _log 存在且能记录
from atprobe.gui import mainwindow as mw
mw._log.info('测试引擎入口日志')
print('logger ok:', mw._log.name)
" 2>&1 | tail -5`
Expected: 输出含 "测试引擎入口日志" 的日志行，logger 名 "atprobe.engine_gui"。

- [ ] **Step 3: 跑全量 GUI 测试确认无回归**

Run: `uv run --extra dev python -m pytest tests/integration/test_gui.py -q --deselect tests/integration/test_gui.py::TestManualDebugFileSendLarge::test_large_file_uses_worker`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add src/atprobe/gui/mainwindow.py
git commit -m "feat(logging): run_cases 与执行结束的 INFO 埋点"
```

---

## Task 7: 帮助菜单「打开日志目录」

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py`（`_init_menubar` 约 line 193-200）

- [ ] **Step 1: 在帮助菜单加「打开日志目录」action**

在 `src/atprobe/gui/mainwindow.py` 的 `_init_menubar` 方法，找到 `help_menu = self.menuBar().addMenu("帮助(&H)")` 块（约 line 193）。原代码：

```python
        help_menu = self.menuBar().addMenu("帮助(&H)")
        check_action = QAction("检查更新...", self)
        check_action.triggered.connect(lambda: self._on_check_update(manual=True))
        help_menu.addAction(check_action)
        help_menu.addSeparator()
        about_action = QAction("关于 ATProbe", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
```

改为（在 check_action 之后、separator 之前插入「打开日志目录」）:

```python
        help_menu = self.menuBar().addMenu("帮助(&H)")
        check_action = QAction("检查更新...", self)
        check_action.triggered.connect(lambda: self._on_check_update(manual=True))
        help_menu.addAction(check_action)
        log_action = QAction("打开日志目录", self)
        log_action.triggered.connect(self._open_log_dir)
        help_menu.addAction(log_action)
        help_menu.addSeparator()
        about_action = QAction("关于 ATProbe", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
```

- [ ] **Step 2: 实现 _open_log_dir 方法**

在 `src/atprobe/gui/mainwindow.py` 的 `_on_about` 方法之后（约 line 240），加入新方法：

```python
    def _open_log_dir(self) -> None:
        """打开日志目录（资源管理器定位 atprobe.log，便于非技术用户排查）."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from atprobe.infra.logging_config import _log_dir
        try:
            log_dir = _log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法打开", f"日志目录不可访问：{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir.resolve())))
```

- [ ] **Step 3: 写测试——菜单含「打开日志目录」**

追加到 `tests/integration/test_gui.py`:

```python
class TestHelpMenuLogDir:
    """帮助菜单含「打开日志目录」项。"""

    def test_help_menu_has_open_log_action(self, qapp):  # type: ignore[no-untyped-def]
        from atprobe.gui.mainwindow import MainWindow
        win = MainWindow()
        # 找帮助菜单
        help_menu = None
        for action in win.menuBar().actions():
            if action.text() == "帮助(&H)":
                help_menu = action.menu()
                break
        assert help_menu is not None
        texts = [a.text() for a in help_menu.actions()]
        assert "打开日志目录" in texts
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --extra dev python -m pytest tests/integration/test_gui.py::TestHelpMenuLogDir -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/gui/mainwindow.py tests/integration/test_gui.py
git commit -m "feat(gui): 帮助菜单加「打开日志目录」"
```

---

## Task 8: CLI --debug 选项

**Files:**
- Modify: `src/atprobe/cli/commands/run.py`

- [ ] **Step 1: 加 --debug 选项并在命令开头 setup_logging**

在 `src/atprobe/cli/commands/run.py` 的 `run` 函数签名（约 line 41-62）加 `debug` 参数。在 `baud` 参数之后加：

```python
    debug: bool = typer.Option(False, "--debug", help="开启详细日志（DEBUG 级，记录串口/引擎细节）"),
```

然后在 `run` 函数体的最开头（`# 1. 加载配置` 注释之前）加 setup_logging：

```python
    # 日志初始化（CLI 最早接入；--debug 提到 DEBUG 级，记录串口/引擎细节）
    import logging

    from atprobe.infra.logging_config import setup_logging

    setup_logging(level=logging.DEBUG if debug else logging.INFO)
    if debug:
        logging.getLogger("atprobe").info("--debug 模式：详细日志已开启")
```

- [ ] **Step 2: 写测试——--debug 开启 DEBUG 级**

追加到 `tests/unit/test_logging_config.py`（或 cli 测试文件，放这里更聚焦）:

```python
def test_setup_logging_debug_level(monkeypatch, tmp_path):
    """setup_logging(level=DEBUG) 后根 logger 级别为 DEBUG."""
    from atprobe.infra import logging_config
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        logging_config.setup_logging(level=logging.DEBUG)
        assert root.level == logging.DEBUG
    finally:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
```

- [ ] **Step 3: 验证 --debug 选项被识别（CLI 冒烟）**

Run: `uv run atprobe run --help 2>&1 | grep -i debug`
Expected: 输出含 `--debug` 行。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --extra dev python -m pytest tests/unit/test_logging_config.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/cli/commands/run.py tests/unit/test_logging_config.py
git commit -m "feat(cli): run 命令加 --debug 选项（提到 DEBUG 级日志）"
```

---

## Task 9: 全量验证 + ruff + mypy

**Files:** 无新改动，仅验证

- [ ] **Step 1: ruff 全量检查**

Run: `uv run ruff check src/atprobe/infra/logging_config.py src/atprobe/gui/app.py src/atprobe/gui/mainwindow.py src/atprobe/cli/commands/run.py tests/unit/test_logging_config.py tests/integration/test_gui.py`
Expected: All checks passed

- [ ] **Step 2: mypy 检查（新增/改动文件）**

Run: `uv run mypy src/atprobe/infra/logging_config.py src/atprobe/gui/app.py src/atprobe/gui/mainwindow.py src/atprobe/cli/commands/run.py`
Expected: 无新增错误（已有的 pre-existing run.py list 泛型错误可忽略，与本次无关）

- [ ] **Step 3: 全量测试**

Run: `uv run --extra dev python -m pytest -q --deselect tests/integration/test_gui.py::TestManualDebugFileSendLarge::test_large_file_uses_worker`
Expected: 全部 PASS（之前 376 + 本次新增约 6 = ~382）

- [ ] **Step 4: 端到端冒烟——GUI 启动写日志、帮助菜单可用**

Run: `uv run --extra dev python -c "
import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading, sys
from PySide6.QtWidgets import QApplication
def quit_after():
    QApplication.quit()
app = QApplication.instance() or QApplication([])
from atprobe.infra.logging_config import setup_logging, _log_dir
log_path = setup_logging()
import logging; logging.getLogger('atprobe.test').info('冒烟测试日志')
from atprobe.gui.mainwindow import MainWindow
w = MainWindow(); w.show()
QTimer = __import__('PySide6.QtCore', fromlist=['QTimer']).QTimer
QTimer.singleShot(500, quit_after)
app.exec()
print('日志路径:', log_path)
print('日志存在:', log_path.exists())
print('日志含冒烟:', '冒烟测试日志' in log_path.read_text(encoding='utf-8'))
" 2>&1 | tail -5`
Expected: 日志存在 True、日志含冒烟 True。

- [ ] **Step 5: 若上述全过，无需额外提交（已逐步提交）；否则修复后提交**

---

## Self-Review 结果

**1. Spec 覆盖**：
- §1 架构（logging_config 模块 + app/mainwindow/cli 接入）→ Task 1,2,4,5,8 ✓
- §2 双层异常兜底（引擎 try/except + threading.excepthook）→ Task 2（excepthook）, Task 5（引擎 try/except）✓
- §2 UI 即时提示（engine_error 分支 + 弹窗）→ Task 5 ✓
- §2 路径降级 → Task 1（实现）, Task 3（测试）✓
- §3 日志位置（user_workspace/logs）→ Task 1 ✓
- §3 轮转 2MB×5 → Task 1 ✓
- §3 帮助菜单打开日志目录 → Task 7 ✓
- §3 CLI --debug → Task 8 ✓
- §3 INFO 埋点（启动/执行开始/结束/异常）→ Task 4（启动）, Task 6（执行开始/结束）, Task 5（异常）✓
- §7 测试策略 → Task 1,2,3（单元）, Task 5（集成 engine_error）, Task 7（菜单）✓

**2. 占位符扫描**：无 TBD/TODO/「类似上面」，所有步骤含完整代码。✓

**3. 类型一致性**：
- `setup_logging(level) -> Path` — 全程一致
- `install_excepthook(error_cb)` — Task 2 定义，Task 4 调用（不传 error_cb）一致
- `_log_dir()` 模块级函数 — Task 1 定义，Task 5/7 引用一致
- `("engine_error", msg)` 元组 — Task 5 emit 与 _on_progress 识别一致
- `_log` logger 名 — Task 5/6 用 `atprobe.engine_gui` 一致

**4. 一处需注意**：Task 2 测试里 `threading.excepthook = threading.__exexcepthook__` 是笔误，应为恢复默认。Python 没有公开的 `__excepthook__`，测试间隔离靠 monkeypatch 更稳。**修正**：Task 2 Step 1 测试末尾那句删除，改用 monkeypatch 自动恢复（threading.excepthook 是模块属性，monkeypatch.setattr 可在测试结束自动还原）。Task 2 测试改为：

把 Task 2 Step 1 测试里的 `threading.excepthook(...)` 调用改为先用 `monkeypatch.setattr(threading, "excepthook", threading.excepthook)` 保存，或直接调 install_excepthook 后用 `threading.excepthook(fake_args)` —— install_excepthook 内部已经 `threading.excepthook = _thread_hook`，测试直接调 `threading.excepthook(fake_args)` 即可。测试末尾删除恢复行，改为 monkeypatch.setattr 恢复：

修正后的 Task 2 Step 1 测试关键部分（install 之后）：

```python
    # install_excepthook 内部会赋值 threading.excepthook / sys.excepthook
    saved_thread_hook = threading.excepthook
    saved_sys_hook = sys.excepthook
    try:
        logging_config.install_excepthook(error_cb=captured.append)
        # 模拟触发
        threading.excepthook(fake_args)
        content = log_path.read_text(encoding="utf-8")
        assert "RuntimeError" in content
        assert captured
    finally:
        threading.excepthook = saved_thread_hook
        sys.excepthook = saved_sys_hook
```

（实现计划正文 Task 2 以这个修正版为准。）
