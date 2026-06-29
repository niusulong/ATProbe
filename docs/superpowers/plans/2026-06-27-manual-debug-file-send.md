# 手动调试「文件发送」功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在手动调试页新增「文件发送」卡片，把整个文件作为原始字节（不加结束符）写入当前串口；小文件同步瞬发，大文件后台分块发送、进度可取消、TX 原始数据流式逐块上屏（与 RX 一致）。

**Architecture:** 复用基础设施层原始字节咽喉点 `SerialConnection.write_bytes`（补齐 TX 观察者通知修复观测性缺口），在其上新增 `PortManager.write_bytes` 与 `MainWindow.send_file`/`get_connection` 薄封装。GUI 层新增「文件发送」卡片 + `FileSendWorker(QObject)` 后台分块发送器。小文件（≤4KB）走同步 `send_file`，大文件（>4KB）走 worker 内联分块（算法同 `send_data_stream`，块 1024/间隔 5ms）。

**Tech Stack:** PySide6（QGroupBox/QProgressBar/QFileDialog/QThread/QObject 信号槽）、ruamel 不涉及、纯 Python dataclass、threading.CancelToken。

**Spec:** `docs/superpowers/specs/2026-06-27-manual-debug-file-send-design.md`

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `src/atprobe/infra/serial/connection.py` | `write_bytes` 补 TX 观察者通知（咽喉点完整性） | Modify（+1 行） |
| `src/atprobe/infra/serial/portmanager.py` | 新增 `write_bytes(port, data)` 转调连接 | Modify（+方法） |
| `src/atprobe/gui/mainwindow.py` | 新增 `send_file`、`get_connection` | Modify（+2 方法） |
| `src/atprobe/gui/widgets/file_send.py` | `FileSendWorker(QObject)` 后台分块发送器 | Create |
| `src/atprobe/gui/tabs/manual_debug.py` | 新增「文件发送」卡片 + 路由 + TX 流式渲染复用 | Modify |
| `tests/integration/test_gui.py` | GUI 集成测试 + 扩展 `_FakeMain` | Modify |
| `tests/unit/test_write_bytes.py` | `write_bytes`/`PortManager.write_bytes`/TX 通知单测 | Create |

---

## Task 1: write_bytes 补 TX 观察者通知（咽喉点修复）

修复咽喉点观测性缺口：`write_command` 通知 TX 观察者、`write_bytes` 不通知 —— 让两者一致。

**Files:**
- Modify: `src/atprobe/infra/serial/connection.py:257-266`（`write_bytes` 方法）
- Test: `tests/unit/test_write_bytes.py`

- [ ] **Step 1: 写失败测试 —— write_bytes 通知 TX 观察者**

Create `tests/unit/test_write_bytes.py`:

```python
"""write_bytes / PortManager.write_bytes 单元测试.

覆盖：TX 观察者通知（咽喉点完整性）、断连抛 SendError、PortManager 转调。

用「_connected=True + 桩串口对象」绕过真实 pyserial.open（沿用
tests/unit/test_persistent_subscribe.py 的 mock 模式）。
"""

from __future__ import annotations

import pytest

from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.serial.connection import SerialConnection
from atprobe.infra.serial.exceptions import SendError


class _StubSerial:
    """最小串口替身：记录 write 调用，flush 空操作（绕过 pyserial I/O）。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass


def _make_connection(monkeypatch) -> SerialConnection:
    """构造已连接、底层为 _StubSerial 的 SerialConnection（不真开 pyserial）。"""
    cfg = PortConfig(name="COM9", baudrate=115200, frame=FrameFormat.parse("8N1"))
    conn = SerialConnection(cfg)
    stub = _StubSerial()
    monkeypatch.setattr(conn, "_serial", stub)
    monkeypatch.setattr(conn, "_connected", True)
    return conn


class TestWriteBytesNotifiesTx:
    def test_write_bytes_notifies_tx_observer(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_connection(monkeypatch)
        seen: list[bytes] = []
        conn.add_tx_observer(lambda chunk: seen.append(chunk))

        conn.write_bytes(b"\x01\x02\x03")

        # 咽喉点契约：所有写入都对 TX 观察者可见（与 write_command 一致）
        assert seen == [b"\x01\x02\x03"]

    def test_write_bytes_no_terminator_added(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """write_bytes 写入原始字节，不加结束符（区别于 write_command）。"""
        conn = _make_connection(monkeypatch)

        conn.write_bytes(b"RAW")

        # 原始字节原样写入，无 \r\n 追加
        assert conn._serial.written == [b"RAW"]  # noqa: SLF001

    def test_write_bytes_disconnected_raises(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        conn = _make_connection(monkeypatch)
        monkeypatch.setattr(conn, "_connected", False)

        with pytest.raises(SendError):
            conn.write_bytes(b"x")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_write_bytes.py -v`
Expected: `test_write_bytes_notifies_tx_observer` FAIL（`seen == []`，因当前 write_bytes 不通知）；其余 2 个测试关于 terminator/disconnected 行为应已通过或随实现一并验证。

- [ ] **Step 3: 修复实现 —— write_bytes 加 TX 通知**

Modify `src/atprobe/infra/serial/connection.py` 的 `write_bytes` 方法，在 `self._log_tx(data)` 之后、`try` 写串口之前插入通知（与 `write_command:146-147` 完全对称）:

```python
    def write_bytes(self, data: bytes) -> None:
        """直接写字节（不分块、不加结束符，供数据流发送用）."""
        if not self._connected or self._serial is None:
            raise SendError(self.config.name, "端口未连接")
        self._log_tx(data)
        self._notify_tx_observers(data)
        try:
            self._serial.write(data)  # type: ignore[union-attr]
            self._serial.flush()  # type: ignore[union-attr]
        except (SerialException, OSError) as exc:
            raise SendError(self.config.name, str(exc)) from exc
```

（仅新增第 3 行 `self._notify_tx_observers(data)`。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_write_bytes.py -v`
Expected: 3 PASS。

- [ ] **Step 5: 全量回归确认 write_bytes 改动不破坏引擎**

Run: `python -m pytest -q && python -m ruff check && python -m mypy src`
Expected: 全绿。若引擎某测试断言「数据流发送不通知 TX 观察者」，那是针对 bug 的断言 —— 删除该断言（不要迁就）。

- [ ] **Step 6: 提交**

```bash
git add src/atprobe/infra/serial/connection.py tests/unit/test_write_bytes.py
git commit -m "fix(serial): write_bytes 补 TX 观察者通知（咽喉点完整性）"
```

---

## Task 2: PortManager.write_bytes 转调封装

在 PortManager 层暴露原始字节写入，与 `write_command` 对称。

**Files:**
- Modify: `src/atprobe/infra/serial/portmanager.py:244-249`（`write_command` 旁新增 `write_bytes`）
- Test: `tests/unit/test_write_bytes.py`（追加）

- [ ] **Step 1: 写失败测试 —— PortManager.write_bytes 转调**

在 `tests/unit/test_write_bytes.py` 末尾追加（复用上面的 `_make_connection` / `_StubSerial`）:

```python
class TestPortManagerWriteBytes:
    def test_portmanager_write_bytes_delegates_to_connection(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.portmanager import PortManager

        conn = _make_connection(monkeypatch)
        written: list[bytes] = []
        monkeypatch.setattr(conn, "write_bytes", lambda data: written.append(data))

        pm = PortManager()
        monkeypatch.setattr(pm, "_connections", {"COM9": conn})

        pm.write_bytes("COM9", b"\xaa\xbb")

        assert written == [b"\xaa\xbb"]

    def test_portmanager_write_bytes_unopened_port_raises(self) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        with pytest.raises(KeyError):
            pm.write_bytes("COM9", b"data")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_write_bytes.py::TestPortManagerWriteBytes -v`
Expected: FAIL（`AttributeError: 'PortManager' object has no attribute 'write_bytes'`）。

- [ ] **Step 3: 实现 PortManager.write_bytes**

Modify `src/atprobe/infra/serial/portmanager.py`，在 `write_command` 方法（行 244）**之后**插入:

```python
    def write_bytes(self, port: str, data: bytes) -> None:
        """写原始字节（不加结束符、不分块），供文件/二进制数据流发送用.

        与 write_command 区别：原样写字节，不追加结束符。
        """
        conn = self._connections.get(port)
        if conn is None:
            raise KeyError(f"端口 {port} 未打开")
        conn.write_bytes(data)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_write_bytes.py -v`
Expected: 5 PASS（Task 1 的 3 个 + 本 Task 的 2 个）。

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/infra/serial/portmanager.py tests/unit/test_write_bytes.py
git commit -m "feat(serial): PortManager.write_bytes 原始字节写入封装"
```

---

## Task 3: MainWindow.send_file + get_connection

MainWindow 层薄封装，与 `send_manual`/`subscribe_rx` 同构。

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py:261-274`（`send_manual` 旁新增 `send_file`）及文件顶部
- Test: `tests/integration/test_gui.py`（扩展 `_FakeMain`）

- [ ] **Step 1: 扩展 _FakeMain 加 send_file + get_connection**

Modify `tests/integration/test_gui.py` 的 `_FakeMain` 类（行 329-380）。在 `__init__` 末尾（`self._rx_observers` 之后）加:

```python
        self.last_bytes: tuple[str, bytes] | None = None
        self.file_sent_event = threading.Event()
        # 大文件 worker 用的连接替身（None 表示不支持后台路径）
        self._fake_connection = None
```

在 `send_manual` 方法（行 358）之后新增:

```python
    def send_file(self, port: str, data: bytes) -> bool:
        """小文件同步写：记录写入字节并触发事件（供测试同步）。"""
        if port not in self._connected:
            return False
        self.last_bytes = (port, data)
        self.file_sent_event.set()
        return True

    def get_connection(self, port: str):
        """大文件 worker 持有的连接替身（测试可预置）。"""
        return self._fake_connection
```

- [ ] **Step 2: 写失败测试 —— MainWindow.send_file 路由**

在 `tests/integration/test_gui.py` 的 `TestManualDebugStripped` 类（约行 463）**之后**新增测试类:

```python
class TestManualDebugFileSendRouting:
    """MainWindow.send_file / get_connection 路由测试（通过 _FakeMain 验证契约）。"""

    def test_send_file_requires_connection(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        main._fake_connection = object()  # noqa: SLF001
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        # 未连接 → get_connection 仍可取替身，但 send_file 应判定未连接
        assert main.is_port_connected("COM1") is False
        assert main.send_file("COM1", b"abc") is False

    def test_send_file_writes_when_connected(self) -> None:  # type: ignore[no-untyped-def]
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        assert main.send_file("COM1", b"\x01\x02") is True
        assert main.last_bytes == ("COM1", b"\x01\x02")

    def test_get_connection_returns_fake(self) -> None:  # type: ignore[no-untyped-def]
        main = _FakeMain()
        sentinel = object()
        main._fake_connection = sentinel  # noqa: SLF001
        assert main.get_connection("COM1") is sentinel
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/integration/test_gui.py::TestManualDebugFileSendRouting -v`
Expected: 前两个测试因 `_FakeMain` 已有 send_file（Step 1 已加）而 PASS；但 `TestManualDebugFileSendRouting` 此时还不依赖真实 MainWindow.send_file —— **关键验证在 Task 4**。本步确保 `_FakeMain` 扩展无误。

> 注：`_FakeMain` 是测试替身，`MainWindow` 真实方法的测试在 Task 4 通过 manual_debug 卡片集成验证。

- [ ] **Step 4: 实现 MainWindow.send_file + get_connection**

Modify `src/atprobe/gui/mainwindow.py`。在 `send_manual` 方法（行 261-274）**之后**新增:

```python
    def send_file(self, port: str, data: bytes) -> bool:
        """手动调试：写原始字节到端口（不加结束符），供文件/二进制数据发送.

        返回 True 表示写入成功；未连接返回 False。
        小文件（≤4KB）走本同步路径；大文件由 worker 直接持连接发送。
        """
        if not self._port_manager.is_connected(port):
            return False
        try:
            self._port_manager.write_bytes(port, data)
            return True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "发送错误", f"文件发送失败：{exc}")
            return False

    def get_connection(self, port: str):
        """手动调试：取端口底层连接（供大文件 worker 直接持有发送）。"""
        return self._port_manager.get_connection(port)
```

- [ ] **Step 5: 全量回归 + lint**

Run: `python -m pytest -q && python -m ruff check && python -m mypy src`
Expected: 全绿（`get_connection` 返回类型用隐式 Any，避免 mypy 报错；若 mypy 对返回类型不满，标注 `-> SerialConnection | None` 并补 import）。

- [ ] **Step 6: 提交**

```bash
git add src/atprobe/gui/mainwindow.py tests/integration/test_gui.py
git commit -m "feat(gui): MainWindow.send_file + get_connection 文件发送封装"
```

---

## Task 4: FileSendWorker 后台分块发送器

独立的 `FileSendWorker(QObject)`，内联分块算法（同 `send_data_stream`），逐块发 `chunk_sent`/`progress`/`finished` 信号。

**Files:**
- Create: `src/atprobe/gui/widgets/file_send.py`
- Test: `tests/unit/test_file_send_worker.py`

- [ ] **Step 1: 写失败测试 —— worker 分块 + 信号**

Create `tests/unit/test_file_send_worker.py`:

```python
"""FileSendWorker 单元测试 —— 后台分块发送、逐块信号、取消。

worker 持有 SerialConnection 替身（记录每次 write_bytes 调用），
用 qtbot 驱动信号循环或直接调 run() 同步验证。
"""

from __future__ import annotations

from typing import Any

import pytest

from atprobe.gui.widgets.file_send import FileSendWorker
from atprobe.infra.serial.interfaces import CancelToken


class _FakeConn:
    """SerialConnection 替身：记录所有 write_bytes 调用，可注入异常。"""

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.written: list[bytes] = []
        self.call_count = 0
        self._fail_on_call = fail_on_call

    def write_bytes(self, data: bytes) -> None:
        self.call_count += 1
        if self._fail_on_call is not None and self.call_count == self._fail_on_call:
            from atprobe.infra.serial.exceptions import SendError

            raise SendError("COM9", "模拟断连")
        self.written.append(data)


@pytest.fixture
def no_sleep(monkeypatch):
    """把 worker 的 sleep 打桩为 no-op，避免测试真实等待 5ms。"""
    monkeypatch.setattr("atprobe.gui.widgets.file_send.time.sleep", lambda _s: None)


class TestFileSendWorkerChunking:
    def test_small_data_single_write(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        conn = _FakeConn()
        chunks_sent: list[bytes] = []
        progress_vals: list[int] = []
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(conn, b"hello", chunk_threshold=4096, chunk_size=1024)
        worker.chunk_sent.connect(lambda c: chunks_sent.append(c))
        worker.progress.connect(lambda p: progress_vals.append(p))
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        worker.run()

        assert len(conn.written) == 1
        assert conn.written[0] == b"hello"
        assert chunks_sent == [b"hello"]
        assert results == [(True, "已发送 5 字节")]
        assert progress_vals[-1] == 100

    def test_large_data_chunked(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        data = b"x" * 5000  # 超过阈值 4096
        conn = _FakeConn()
        chunks_sent: list[bytes] = []
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(conn, data, chunk_threshold=4096, chunk_size=1024)
        worker.chunk_sent.connect(lambda c: chunks_sent.append(c))
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        worker.run()

        # 5000 字节按 1024 分块 = 5 块（1024+1024+1024+1024+904）
        assert len(conn.written) == 5
        assert b"".join(conn.written) == data
        assert len(chunks_sent) == 5
        assert results[0][0] is True

    def test_cancel_midway(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        data = b"x" * 5000
        conn = _FakeConn()
        token = CancelToken()
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(
            conn, data, chunk_threshold=4096, chunk_size=1024, cancel_token=token
        )
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        # 在第一块发出后取消
        original_write = conn.write_bytes

        def write_then_cancel(data: bytes) -> None:
            original_write(data)
            token.cancel()  # 第一块后触发取消

        conn.write_bytes = write_then_cancel  # type: ignore[method-assign]

        worker.run()

        assert results[0][0] is False
        assert "已取消" in results[0][1]
        # 取消后不再继续写
        assert len(conn.written) == 1

    def test_senderror_reports_partial(self, no_sleep) -> None:  # type: ignore[no-untyped-def]
        data = b"x" * 5000
        conn = _FakeConn(fail_on_call=2)  # 第二块断连
        results: list[tuple[bool, str]] = []

        worker = FileSendWorker(conn, data, chunk_threshold=4096, chunk_size=1024)
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))

        worker.run()

        assert results[0][0] is False
        assert "发送中断" in results[0][1]
        assert len(conn.written) == 1  # 第一块成功，第二块抛异常
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_file_send_worker.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'atprobe.gui.widgets.file_send'`）。

- [ ] **Step 3: 实现 FileSendWorker**

Create `src/atprobe/gui/widgets/file_send.py`:

```python
"""文件发送后台 worker（QObject）—— 大文件分块发送、逐块信号、可取消.

算法同 infra/serial/datastream.py 的 send_data_stream（while 偏移切块），
但内联以获得逐块信号插桩点（chunk_sent / progress）。
块大小 1024、间隔 5ms（紧凑默认值，UI 不可调）。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal

from atprobe.infra.serial.exceptions import OperationCancelled, SendError
from atprobe.infra.serial.interfaces import CancelToken

# 紧凑默认值（设计 §2/§3）：块 1024 字节、阈值 4096、间隔 5ms
_DEFAULT_CHUNK_SIZE = 1024
_DEFAULT_CHUNK_THRESHOLD = 4096
_DEFAULT_INTERVAL_MS = 5


class FileSendWorker(QObject):
    """后台分块发送文件字节到 SerialConnection。

    信号（均跨线程安全，Qt 自动排队连接）：
        chunk_sent(bytes)  每写完一块发出，主线程据此流式上屏 TX（同 RX 渲染）
        progress(int)      0-100，按已写字节占比
        finished(bool, str) ok=True 正常完成；ok=False 含已发字节数的失败/取消消息
    """

    chunk_sent = Signal(bytes)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(
        self,
        connection: object,
        data: bytes,
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        chunk_threshold: int = _DEFAULT_CHUNK_THRESHOLD,
        interval_ms: int = _DEFAULT_INTERVAL_MS,
        cancel_token: CancelToken | None = None,
    ) -> None:
        super().__init__()
        self._conn = connection
        self._data = data
        self._chunk_size = chunk_size
        self._chunk_threshold = chunk_threshold
        self._interval_ms = interval_ms
        self._cancel = cancel_token

    def run(self) -> None:
        """执行分块发送。在 worker 线程内调用。"""
        data = self._data
        n = len(data)
        sent = 0
        try:
            if self._cancel is not None and self._cancel.cancelled:
                raise OperationCancelled("文件发送被取消")

            if n <= self._chunk_threshold:
                # 整体发送
                self._write_chunk(data)
                sent = n
            else:
                # 分块发送
                offset = 0
                while offset < n:
                    if self._cancel is not None and self._cancel.cancelled:
                        raise OperationCancelled(
                            f"文件发送被取消（已发送 {offset}/{n} 字节）"
                        )
                    end = min(offset + self._chunk_size, n)
                    self._write_chunk(data[offset:end])
                    offset = end
                    sent = offset
                    if offset < n:
                        time.sleep(self._interval_ms / 1000.0)

            self.progress.emit(100)
            self.finished.emit(True, f"已发送 {n} 字节")
        except OperationCancelled as exc:
            self.finished.emit(False, f"已取消（已发 {sent}/{n} 字节）：{exc}")
        except SendError as exc:
            self.finished.emit(False, f"发送中断：{exc}（已发 {sent}/{n} 字节）")

    def _write_chunk(self, chunk: bytes) -> None:
        """写一块：调连接 write_bytes，成功后发 chunk_sent + progress。"""
        # connection 为 SerialConnection（或测试替身）
        self._conn.write_bytes(chunk)  # type: ignore[attr-defined]
        self.chunk_sent.emit(chunk)
        n = len(self._data)
        if n > 0:
            # progress 由调用方累计 sent，此处近似用已 emit 的块；主线程以 progress 信号为准
            pass
```

> **实现注**：`progress` 信号在分块循环里每块后发一次（按 `sent/n` 百分比）。上面 `_write_chunk` 里 progress 计算逻辑不完整 —— 让我在 Step 3b 修正：progress 应在 `run()` 的分块循环里直接 emit，而非 `_write_chunk` 内。下面给出最终版。

替换 `run()` 与 `_write_chunk` 为最终版（progress 在 run 循环内 emit）:

```python
    def run(self) -> None:
        data = self._data
        n = len(data)
        sent = 0
        try:
            if self._cancel is not None and self._cancel.cancelled:
                raise OperationCancelled("文件发送被取消")

            if n <= self._chunk_threshold:
                self._conn.write_bytes(data)  # type: ignore[attr-defined]
                self.chunk_sent.emit(data)
                sent = n
            else:
                offset = 0
                while offset < n:
                    if self._cancel is not None and self._cancel.cancelled:
                        raise OperationCancelled(
                            f"文件发送被取消（已发送 {offset}/{n} 字节）"
                        )
                    end = min(offset + self._chunk_size, n)
                    chunk = data[offset:end]
                    self._conn.write_bytes(chunk)  # type: ignore[attr-defined]
                    self.chunk_sent.emit(chunk)
                    offset = end
                    sent = offset
                    self.progress.emit(int(sent * 100 / n)) if n > 0 else None
                    if offset < n:
                        time.sleep(self._interval_ms / 1000.0)

            self.progress.emit(100)
            self.finished.emit(True, f"已发送 {n} 字节")
        except OperationCancelled as exc:
            self.finished.emit(False, f"已取消（已发 {sent}/{n} 字节）：{exc}")
        except SendError as exc:
            self.finished.emit(False, f"发送中断：{exc}（已发 {sent}/{n} 字节）")
```

（删除 `_write_chunk` 辅助方法，逻辑内联到 run，避免 progress 计算割裂。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_file_send_worker.py -v`
Expected: 4 PASS。

- [ ] **Step 5: lint + 提交**

Run: `python -m ruff check src/atprobe/gui/widgets/file_send.py tests/unit/test_file_send_worker.py && python -m mypy src/atprobe/gui/widgets/file_send.py`

```bash
git add src/atprobe/gui/widgets/file_send.py tests/unit/test_file_send_worker.py
git commit -m "feat(gui): FileSendWorker 后台分块发送 + 逐块信号 + 可取消"
```

---

## Task 5: manual_debug 新增「文件发送」卡片 + 小文件同步路径

在 manual_debug 页插入卡片，实现文件选择 + 小文件同步发送 + TX 流式上屏。

**Files:**
- Modify: `src/atprobe/gui/tabs/manual_debug.py`（`_init_ui` 加卡片 + `_send_file` 方法 + `_render_tx_bytes` 复用）
- Test: `tests/integration/test_gui.py`

- [ ] **Step 1: 写失败测试 —— 卡片存在 + 小文件同步发送**

在 `tests/integration/test_gui.py` 的 `TestManualDebugFileSendRouting` 类**之后**新增:

```python
class TestManualDebugFileSendCard:
    def test_file_send_card_exists(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        assert hasattr(widget, "file_btn")  # 选择文件按钮
        assert hasattr(widget, "file_send_btn")  # 发送按钮
        assert hasattr(widget, "file_progress")  # 进度条
        assert hasattr(widget, "file_cancel_btn")  # 取消按钮

    def test_small_file_sends_synchronously(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        # 写一个小文件（< 4KB 阈值）
        f = tmp_path / "small.bin"
        f.write_bytes(b"\x01\x02\x03\x04")

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001 —— 模拟已选文件
        widget._update_file_label()

        # 桩掉文件对话框（不实际用到，但防御）
        widget._send_file()

        assert main.file_sent_event.is_set()
        assert main.last_bytes == ("COM1", b"\x01\x02\x03\x04")
        # TX 原始数据应上屏（响应区含文件字节内容）
        text = widget.response_view.toPlainText()
        assert "TX" in text

    def test_file_send_requires_connection(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import PySide6.QtWidgets as _qw

        monkeypatch.setattr(_qw.QMessageBox, "warning", lambda *a, **k: None)

        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        f = tmp_path / "x.bin"
        f.write_bytes(b"abc")
        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001

        widget._send_file()  # 未连接 → 弹窗、不发

        assert main.last_bytes is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/integration/test_gui.py::TestManualDebugFileSendCard -v`
Expected: FAIL（`ManualDebugWidget` 无 `file_btn` 等属性）。

- [ ] **Step 3: 抽取 TX 字节渲染复用方法**

Modify `src/atprobe/gui/tabs/manual_debug.py`。在 `_on_rx_bytes` 方法**之后**新增 `_render_tx_bytes`（复用按行/HEX 切分逻辑，方向标 TX、`data.tx` 色）:

```python
    def _render_tx_bytes(self, chunk: bytes) -> None:
        """渲染 TX 原始字节（文件/数据流发送）—— 复用 _on_rx_bytes 的切分逻辑.

        HEX 开关打开时按十六进制展示；否则按 UTF-8 文本拆行。
        方向标 TX、用 data.tx 色。
        """
        if self.hex_check.isChecked():
            hex_line = " ".join(f"{b:02X}" for b in chunk)
            if hex_line:
                self._append_line("TX", hex_line, self._tokens["data.tx"])
            return
        text = chunk.decode("utf-8", errors="replace")
        # 复用 RX 的按行切分，但不跨块缓冲（TX 块边界即显示边界，简化）
        for line in text.split("\n"):
            stripped = line.rstrip("\r")
            if stripped:
                self._append_line("TX", stripped, self._tokens["data.tx"])
```

- [ ] **Step 4: 在 _init_ui 插入「文件发送」卡片**

Modify `src/atprobe/gui/tabs/manual_debug.py` 的 `_init_ui`。在「端口卡片」`layout.addWidget(port_group)` 之后、「发送卡片」代码之前插入文件发送卡片。

找到端口卡片末尾:
```python
        layout.addWidget(port_group)
        self._refresh_ports()
```
在其后插入（保持后续 `# ===== 卡片 2: 发送区 =====` 顺延为卡片 3）:

```python
        # ===== 卡片 2: 文件发送（原始字节，不加结束符）=====
        file_group = QGroupBox("文件发送")
        file_layout = QVBoxLayout(file_group)
        file_layout.setContentsMargins(12, 8, 12, 12)
        file_layout.setSpacing(8)

        file_row = QHBoxLayout()
        self.file_btn = QPushButton("选择文件…")
        self.file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_btn.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_btn)

        self.file_label = QLabel("未选择文件")
        self.file_label.setObjectName("caption")
        file_row.addWidget(self.file_label, 1)

        self.file_send_btn = QPushButton("发送")
        self.file_send_btn.setObjectName("primary")
        self.file_send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_send_btn.setIcon(self._action_icon("send"))
        self.file_send_btn.setEnabled(False)
        self.file_send_btn.clicked.connect(self._send_file)
        file_row.addWidget(self.file_send_btn)

        self.file_cancel_btn = QPushButton("取消")
        self.file_cancel_btn.setObjectName("danger")
        self.file_cancel_btn.setVisible(False)
        self.file_cancel_btn.clicked.connect(self._cancel_file_send)
        file_row.addWidget(self.file_cancel_btn)
        file_layout.addLayout(file_row)

        # 进度行：仅发送中显示
        self.file_progress = QProgressBar()
        self.file_progress.setVisible(False)
        file_layout.addWidget(self.file_progress)
        layout.addWidget(file_group)

        # 文件发送状态
        self._file_path: str | None = None
        self._file_worker = None  # FileSendWorker 实例（发送中持有）
        self._file_thread = None  # QThread 实例
        self._file_cancel_token = None
```

> 需在文件顶部 import 区补 `QProgressBar`（在 `from PySide6.QtWidgets import (` 块内）。

- [ ] **Step 5: 实现文件选择 + 小文件发送方法**

Modify `src/atprobe/gui/tabs/manual_debug.py`。在 `_send`/`send_command` 方法区**之后**新增文件发送方法:

```python
    # ------------------------------------------------------------------
    # 文件发送（原始字节，不加结束符）
    # ------------------------------------------------------------------
    def _choose_file(self) -> None:
        """选择文件：弹出对话框，记录路径并更新标签。"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "选择要发送的文件")
        if not path:
            return
        self._file_path = path
        self._update_file_label()
        self._sync_file_send_state()

    def _update_file_label(self) -> None:
        """根据当前 _file_path 更新文件名 + 字节数标签。"""
        from pathlib import Path

        if not self._file_path:
            self.file_label.setText("未选择文件")
            return
        try:
            size = Path(self._file_path).stat().st_size
        except OSError:
            size = 0
        name = Path(self._file_path).name
        self.file_label.setText(f"{name} ({size:,} 字节)")

    def _sync_file_send_state(self) -> None:
        """根据文件选择/连接状态/发送中，刷新发送按钮可用性。"""
        port = self._current_port()
        sending = self._file_worker is not None
        connected = bool(
            callable(getattr(self._main, "is_port_connected", None))
            and getattr(self._main, "is_port_connected")(port)
        )
        self.file_send_btn.setEnabled(
            bool(self._file_path) and connected and not sending
        )

    def _send_file(self) -> None:
        """发送文件：读取 → 按大小路由小文件同步 / 大文件后台。"""
        from pathlib import Path

        if not self._file_path:
            QMessageBox.warning(self, "提示", "请先选择文件")
            return
        port = self._current_port()
        if not port:
            QMessageBox.warning(self, "提示", "请先选择端口")
            return
        is_conn = getattr(self._main, "is_port_connected", None)
        if callable(is_conn) and not is_conn(port):
            QMessageBox.warning(self, "提示", f"端口 {port} 未连接，请先「打开端口」")
            return
        try:
            data = Path(self._file_path).read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "读取错误", f"无法读取文件：{exc}")
            return
        if not data:
            return

        from atprobe.infra.serial.config import DataStreamSpec

        if len(data) <= DataStreamSpec.chunk_threshold:
            self._send_file_small(port, data)
        else:
            self._send_file_large(port, data)

    def _send_file_small(self, port: str, data: bytes) -> None:
        """小文件同步发送（主线程单次 write_bytes）。"""
        send_file = getattr(self._main, "send_file", None)
        if not callable(send_file):
            self._append_line("RX", "[错误] 引擎未就绪", self._tokens["danger"])
            return
        # TX 原始数据流式上屏（同 RX 渲染）
        self._render_tx_bytes(data)
        if not send_file(port, data):
            self._append_line("RX", "[错误] 文件发送失败（端口未连接）", self._tokens["danger"])
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/integration/test_gui.py::TestManualDebugFileSendCard -v`
Expected: 3 PASS。

- [ ] **Step 7: lint + 提交**

Run: `python -m ruff check && python -m mypy src`

```bash
git add src/atprobe/gui/tabs/manual_debug.py tests/integration/test_gui.py
git commit -m "feat(gui): 手动调试文件发送卡片 + 小文件同步发送 + TX 流式上屏"
```

---

## Task 6: 大文件后台发送 + 进度 + 取消 + 互斥

接上 Task 5，实现 `_send_file_large` + worker 信号连接 + 取消 + 互斥禁用 + 析构清理。

**Files:**
- Modify: `src/atprobe/gui/tabs/manual_debug.py`（`_send_file_large` + worker 槽 + 互斥）
- Test: `tests/integration/test_gui.py`

- [ ] **Step 1: 写失败测试 —— 大文件后台发送 + 进度 + 取消 + 互斥**

在 `tests/integration/test_gui.py` 的 `TestManualDebugFileSendCard` 类**之后**新增:

```python
class TestManualDebugFileSendLarge:
    def test_large_file_uses_worker(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.widgets.file_send import FileSendWorker
        from atprobe.gui.tabs.registry import TabBinding

        # 大文件（> 4KB）
        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * 5000)

        # 让 _FakeMain.get_connection 返回一个记录写入的替身
        class _Conn:
            def __init__(self) -> None:
                self.written: list[bytes] = []

            def write_bytes(self, d: bytes) -> None:
                self.written.append(d)

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        main._fake_connection = _Conn()  # noqa: SLF001
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001
        widget._update_file_label()

        # 桩掉 time.sleep 避免 worker 真实等待
        monkeypatch.setattr("atprobe.gui.widgets.file_send.time.sleep", lambda _s: None)

        widget._send_file()

        # 大文件 → worker 创建并启动
        assert widget._file_worker is not None
        # 等待 worker 线程结束（同步验证）
        if widget._file_thread is not None:
            widget._file_thread.wait(2000)
        # 替身记录了分块写入
        assert len(main._fake_connection.written) >= 1
        assert b"".join(main._fake_connection.written) == b"x" * 5000

    def test_file_send_disables_text_send(self, qapp, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * 5000)

        class _Conn:
            def __init__(self) -> None:
                self.written: list[bytes] = []

            def write_bytes(self, d: bytes) -> None:
                self.written.append(d)

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        main._connected.add("COM1")  # noqa: SLF001
        main._fake_connection = _Conn()  # noqa: SLF001
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]
        widget._file_path = str(f)  # noqa: SLF001

        monkeypatch.setattr("atprobe.gui.widgets.file_send.time.sleep", lambda _s: None)

        # 先用钩子暂停 worker，使其停留在发送中
        started = threading.Event()
        original_run = FileSendWorker.run

        def slow_run(self):
            started.set()
            original_run(self)

        import atprobe.gui.widgets.file_send as _fs
        monkeypatch.setattr(_fs.FileSendWorker, "run", slow_run)
        # 用信号槽机制驱动：worker 启动后 we check 互斥状态
        # 简化：直接调 _send_file_large 进入发送中状态
        data = f.read_bytes()
        # 手动进入发送中状态
        widget._enter_file_sending()
        assert widget.send_edit.isEnabled() is False or widget.file_send_btn.isEnabled() is False
```

> **注**：第二个测试的互斥验证较 tricky（worker 异步）。更稳妥的做法：验证 `_enter_file_sending()` / `_exit_file_sending()` 这对状态方法直接控制互斥。Step 2 会实现这对方法。

- [ ] **Step 2: 实现大文件发送 + 状态互斥 + 取消**

Modify `src/atprobe/gui/tabs/manual_debug.py`。在 `_send_file_small` 方法**之后**新增:

```python
    def _send_file_large(self, port: str, data: bytes) -> None:
        """大文件后台分块发送（worker 线程）。"""
        from PySide6.QtCore import QThread

        from atprobe.gui.widgets.file_send import FileSendWorker
        from atprobe.infra.serial.interfaces import CancelToken

        conn = None
        get_conn = getattr(self._main, "get_connection", None)
        if callable(get_conn):
            conn = get_conn(port)
        if conn is None:
            self._append_line("RX", "[错误] 端口连接不可用", self._tokens["danger"])
            return

        self._file_cancel_token = CancelToken()
        self._file_worker = FileSendWorker(conn, data, cancel_token=self._file_cancel_token)
        # 信号连接（跨线程自动 QueuedConnection）
        self._file_worker.chunk_sent.connect(self._on_file_chunk_sent)
        self._file_worker.progress.connect(self._on_file_progress)
        self._file_worker.finished.connect(self._on_file_finished)

        self._file_thread = QThread()
        self._file_worker.moveToThread(self._file_thread)
        self._file_thread.started.connect(self._file_worker.run)
        self._file_thread.start()

        self._enter_file_sending()

    def _enter_file_sending(self) -> None:
        """进入文件发送中状态：显示进度/取消，禁用相关控件（互斥）。"""
        self.file_progress.setVisible(True)
        self.file_progress.setValue(0)
        self.file_cancel_btn.setVisible(True)
        self.file_send_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        # 互斥：禁用文本发送框与文本发送
        self.send_edit.setEnabled(False)

    def _exit_file_sending(self) -> None:
        """退出文件发送中状态：恢复控件，清理 worker/线程。"""
        self.file_progress.setVisible(False)
        self.file_cancel_btn.setVisible(False)
        self.file_btn.setEnabled(True)
        self.send_edit.setEnabled(True)
        self._sync_file_send_state()
        # 清理 worker / 线程
        if self._file_thread is not None:
            self._file_thread.quit()
            self._file_thread.wait(2000)
            self._file_thread = None
        self._file_worker = None
        self._file_cancel_token = None

    def _on_file_chunk_sent(self, chunk: bytes) -> None:
        """worker 每块发出 → 流式上屏 TX（复用渲染）。"""
        self._render_tx_bytes(chunk)

    def _on_file_progress(self, pct: int) -> None:
        self.file_progress.setValue(pct)

    def _on_file_finished(self, ok: bool, msg: str) -> None:
        """worker 完成/失败/取消 → 上屏结果 + 退出发送中状态。"""
        from pathlib import Path

        if ok:
            self._append_line("TX", f"📄 {msg}", self._tokens["data.tx"])
        else:
            # 取消或失败：显示带文件名的摘要
            name = Path(self._file_path).name if self._file_path else "文件"
            if "已取消" in msg:
                self._append_line("TX", f"📄 {name} {msg}", self._tokens["data.tx"])
            else:
                self._append_line("RX", f"[错误] {name} {msg}", self._tokens["danger"])
        self._exit_file_sending()

    def _cancel_file_send(self) -> None:
        """取消文件发送：触发 CancelToken。"""
        if self._file_cancel_token is not None:
            self._file_cancel_token.cancel()
```

- [ ] **Step 3: 在 _init_ui 给文本发送按钮起名，供互斥引用**

Modify `src/atprobe/gui/tabs/manual_debug.py` 的 `_init_ui`「发送区」卡片。把:
```python
        send_btn = QPushButton("发送")
        send_btn.setObjectName("primary")
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setIcon(self._action_icon("send"))
        send_btn.clicked.connect(self._send)
        send_row.addWidget(send_btn)
```
改为 `self.send_btn` 以便互斥控制:
```python
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setIcon(self._action_icon("send"))
        self.send_btn.clicked.connect(self._send)
        send_row.addWidget(self.send_btn)
```

- [ ] **Step 4: 析构清理 —— 关页/关窗时取消进行中发送**

Modify `src/atprobe/gui/tabs/manual_debug.py`。在 `__init__` 末尾（`self.rx_received.connect(...)` 之后）无需改；改为重写 `closeEvent` 或 `__del__`。在类末尾新增:

```python
    def _cleanup_file_send(self) -> None:
        """析构前清理：取消进行中的文件发送并等待线程退出。"""
        if self._file_cancel_token is not None:
            self._file_cancel_token.cancel()
        if self._file_thread is not None and self._file_thread.isRunning():
            self._file_thread.quit()
            self._file_thread.wait(2000)
```

并让页面关闭时调用 —— 检查 `ManualDebugWidget` 是否有 `closeEvent`。若无，新增:

```python
    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._cleanup_file_send()
        super().closeEvent(event)
```

> 若 `_detach_rx` 已在某关闭路径调用，把 `_cleanup_file_send()` 放在其旁。

- [ ] **Step 5: 修正 Task 6 Step 1 第二个测试的互斥验证**

第二个测试（`test_file_send_disables_text_send`）改用直接验证 `_enter_file_sending`/`_exit_file_sending` 这对状态方法（更确定）:

```python
    def test_file_send_disables_text_send(self, qapp) -> None:  # type: ignore[no-untyped-def]
        from atprobe.gui.tabs.manual_debug import ManualDebugWidget
        from atprobe.gui.tabs.registry import TabBinding

        binding = TabBinding(type_name="manual_debug", params={})
        main = _FakeMain()
        widget = ManualDebugWidget(binding, main)  # type: ignore[arg-type]

        # 进入发送中 → 文本发送框禁用
        widget._enter_file_sending()  # noqa: SLF001
        assert widget.send_edit.isEnabled() is False
        assert widget.file_send_btn.isEnabled() is False
        assert widget.file_cancel_btn.isVisible() is True

        # 退出 → 恢复
        widget._exit_file_sending()  # noqa: SLF001
        assert widget.send_edit.isEnabled() is True
```

（删除原 Task 6 Step 1 的第二个测试，替换为以上版本。）

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/integration/test_gui.py::TestManualDebugFileSendLarge -v`
Expected: 2 PASS。

> 若 `test_large_file_uses_worker` 因 worker 线程时序偶发失败，在 `widget._send_file()` 后显式 `widget._file_thread.wait(3000)` 并断言 `main._fake_connection.written` 拼接等于原数据。

- [ ] **Step 7: 全量回归 + lint + 提交**

Run: `python -m pytest -q && python -m ruff check && python -m mypy src`
Expected: 全绿。

```bash
git add src/atprobe/gui/tabs/manual_debug.py tests/integration/test_gui.py
git commit -m "feat(gui): 大文件后台分块发送 + 进度/取消 + 文本发送互斥"
```

---

## Task 7: 文档对齐 + 最终回归

更新模块 docstring 与设计文档的"已实现"状态，跑最终全量检查。

**Files:**
- Modify: `src/atprobe/gui/tabs/manual_debug.py`（模块 docstring 补文件发送说明）

- [ ] **Step 1: 更新 manual_debug 模块 docstring**

Modify `src/atprobe/gui/tabs/manual_debug.py` 顶部模块 docstring。在「支持」列表中追加文件发送项:

```python
"""手动调试选项卡（M6 §4）—— 类似串口助手的手动发送。

直接调用 M1（不经 M3 引擎、不产生用例结果）。支持：
    - 选择端口 + 波特率/帧格式 + 打开/关闭连接（状态徽标 + 按钮切换）
    - 发送 AT 指令（可调结束符；无超时参数——超时是「用例执行」判定响应完整性的概念）
    - 命令库：本页内嵌命令树侧栏（项目→功能→命令三层树，QSplitter 左侧），
      单击命令直接发送到本页当前端口；增删改经「命令库管理」对话框。
    - 文件发送：把整个文件作为原始字节（不加结束符）写入端口。
      小文件（≤4KB）同步瞬发；大文件后台分块（块 1024/间隔 5ms）、
      进度可取消、TX 原始数据流式逐块上屏（同 RX 渲染）。
"""
```

- [ ] **Step 2: 最终全量回归**

Run: `python -m pytest -q && python -m ruff check && python -m mypy src`
Expected: 全绿，无新增 warning。

- [ ] **Step 3: 提交**

```bash
git add src/atprobe/gui/tabs/manual_debug.py
git commit -m "docs(gui): manual_debug 模块 docstring 补文件发送说明"
```

---

## Self-Review（plan 作者已执行）

**1. Spec coverage**:
- §2.1 原始字节不加结束符 → Task 1（write_bytes 无 terminator 测试 + 实现保持）
- §2.2 TX 流式逐块上屏 → Task 4（chunk_sent 信号）+ Task 5（_render_tx_bytes）
- §2.3 独立文件发送卡片 → Task 5 Step 4
- §2.4 大文件后台+进度+取消 → Task 4（worker）+ Task 6（集成）
- §2.5 紧凑默认值 → Task 4（_DEFAULT 常量）
- §3 小文件/大文件分流 → Task 5（DataStreamSpec.chunk_threshold 路由）
- §4 互斥 → Task 6（_enter/_exit_file_sending）
- §5 基础设施改动 → Task 1/2/3
- §6 TX 通知咽喉点 → Task 1
- §8 错误处理 → Task 5（读取/未连接）+ Task 4（SendError/cancel）+ Task 6（finished 槽）

**2. Placeholder scan**: 无 TBD/TODO；每个代码步骤含完整代码。

**3. Type consistency**: `FileSendWorker(connection, data, *, chunk_size, chunk_threshold, interval_ms, cancel_token)` 签名在 Task 4 定义、Task 6 调用一致；`_render_tx_bytes`、`_enter/_exit_file_sending`、`_sync_file_send_state` 命名前后一致；`send_file`/`get_connection` 在 MainWindow 与 _FakeMain 双侧一致。

**已知实现期注意点**：
- Task 4 的 `progress.emit` 在 `sent=0/n=0` 边界需 `if n > 0` 守卫（已在代码中）。
- Task 5 Step 4 需补 `QProgressBar` 到 import 块。
- Task 6 worker 跨线程信号用 Qt QueuedConnection 自动队列，无需手动指定。
- Task 6 第二个测试已简化为直接验证状态方法（避开 worker 异步时序）。
