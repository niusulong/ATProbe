"""M1 串口原始日志记录（REQ-M1 §7）.

记录串口所有收发的原始字节流，HEX 与 TEXT 分离到两个独立文件（§7.2），按「会话/端口/用例」
三维度组织（§7.3）。读线程不直接写文件（避免 I/O 拖慢字节读取），由独立写入线程异步落盘
（TSD §7.4）。

每用例每端口生成两个文件（§7.2 TEXT 与 HEX 分离）::

    <case>.text.log  —— 文本格式：
        [2026-05-19 14:30:25.123] [TX] AT\r\n
        [2026-05-19 14:30:25.456] [RX] OK\r\n
    <case>.hex.log   —— 十六进制格式：
        [2026-05-19 14:30:25.123] [TX] 41 54 0D 0A
        [2026-05-19 14:30:25.456] [RX] 4F 4B 0D 0A
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class _Record:
    """一条日志记录（投入队列的对象，跨线程传递，不可变）."""

    direction: str  # "TX" / "RX"
    data: bytes
    timestamp: str  # 已格式化的时间戳字符串
    file_path: Path


class RawLogger:
    """原始日志记录器（HEX+TEXT，异步落盘，§7）.

    用法：每端口每用例开一个文件（``begin_case``），结束时 ``flush`` 确保落盘。
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[_Record | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._started = False
        self._open_files: dict[Path, object] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动后台写入线程."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="atprobe-rawlog", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        """停止并等待所有缓冲落盘（join）."""
        with self._lock:
            if not self._started:
                return
            self._queue.put(None)  # 哨兵
            assert self._thread is not None
            self._thread.join(timeout=10.0)
            self._started = False
            self._thread = None

    # ------------------------------------------------------------------
    # 写入接口（由读线程/发送路径调用，非阻塞）
    # ------------------------------------------------------------------
    def log(self, file_path: Path, direction: str, data: bytes) -> None:
        """记录一条收发数据."""
        if not self._started:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._queue.put(_Record(direction=direction, data=data, timestamp=ts, file_path=file_path))

    def begin_case(self, log_dir: Path, session: str, port: str, case_name: str) -> Path:
        """为某用例某端口准备日志文件路径（按 §7.3 目录组织）.

        返回基础路径（stem，无后缀）；实际写入时派生 ``<stem>.text.log`` 和
        ``<stem>.hex.log`` 两个独立文件（§7.2 TEXT 与 HEX 分离）。
        """
        safe_case = _sanitize(case_name)
        case_dir = log_dir / session / port
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir / safe_case

    # ------------------------------------------------------------------
    # 后台线程
    # ------------------------------------------------------------------
    def _run(self) -> None:
        while True:
            rec = self._queue.get()
            if rec is None:
                # 哨兵：把队列里剩余的全部写完
                self._drain()
                return
            self._write(rec)

    def _drain(self) -> None:
        while True:
            try:
                rec = self._queue.get_nowait()
            except queue.Empty:
                return
            if rec is not None:
                self._write(rec)

    def _write(self, rec: _Record) -> None:
        try:
            text = rec.data.decode("utf-8", errors="replace")
            hexs = " ".join(f"{b:02X}" for b in rec.data)
            stem = rec.file_path  # begin_case 返回的基础路径（无后缀）
            parent, name = stem.parent, stem.name
            # TEXT 与 HEX 分离到两个独立文件（§7.2）
            with open(parent / f"{name}.text.log", "a", encoding="utf-8") as f:
                f.write(f"[{rec.timestamp}] [{rec.direction}] {text}")
                if not text.endswith("\n"):
                    f.write("\n")
            with open(parent / f"{name}.hex.log", "a", encoding="utf-8") as f:
                f.write(f"[{rec.timestamp}] [{rec.direction}] {hexs}\n")
        except OSError:
            # 日志失败不应影响测试主流程（吞掉，避免读线程崩）
            pass


def _sanitize(name: str) -> str:
    """把用例名转为安全的文件名片段."""
    out: list[str] = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "case"
