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
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class _Record:
    """一条日志记录（投入队列的对象，跨线程传递，不可变）."""

    direction: str  # "TX" / "RX"
    data: bytes
    timestamp: str  # 已格式化的时间戳字符串
    file_path: Path


class RawLogger:
    """原始日志记录器（HEX+TEXT，异步落盘，§7）.

    用法：每端口每用例开一个文件（``begin_case``），用例结束时 ``end_case``
    关闭句柄；句柄总数另有 LRU 上限兜底（P1-2，常驻进程不泄漏）。
    """

    # P1-2：并发缓存的句柄对上限（LRU 兜底）。类属性——测试可 monkeypatch
    # 缩小上限以验证逐出行为。
    _MAX_STEMS = 64
    # evicted 观测队列封顶（批 5）：常驻进程跨海量用例时逐出记录不得无界
    # 增长，旧记录滚动丢弃（仅统计/测试断言用）。构造期取值——运行期改
    # 上限不会作用到已建实例，观测面无此需求。
    _MAX_EVICTED = 1024

    def __init__(self) -> None:
        # P1-2：有界队列——日志是 best-effort 通道，慢盘时丢弃新记录优于
        # 无限积压拖垮内存/阻塞读线程。
        self._queue: queue.Queue[_Record | None | Path] = queue.Queue(maxsize=10000)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._started = False
        # P3 修复：join 超时后的「永久停止」标志——旧实现 stop 超时后 _started=False，
        # 再次 start() 会起第二个写入线程，双线程消费同一队列/句柄交错写坏日志
        self._permanently_stopped = False
        # P1-2 观测属性（仅观测/测试断言用，不参与控制流）：写入线程更新、
        # 任意线程读取，非原子可接受——只做统计。
        self.dropped_count = 0  # 队列满被丢弃的记录数
        # 被 LRU 逐出（句柄已关）的 stem——deque 封顶（_MAX_EVICTED），防观测
        # 属性在常驻进程下无界增长
        self.evicted: deque[Path] = deque(maxlen=self._MAX_EVICTED)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动后台写入线程."""
        with self._lock:
            if self._started or self._permanently_stopped:
                return
            # P1-2：排空上次 stop 后残留的陈旧记录——否则再次 start 会把上个
            # 会话未消费的记录（时间戳/文件归属均已过期）写进新会话。
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._started = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="atprobe-rawlog", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """停止并等待所有缓冲落盘（join）."""
        with self._lock:
            if not self._started:
                return
            try:
                # P1-2：有界队列下哨兵投递加超时——写入线程已死且队列满时，
                # 阻塞 put 会让 stop() 永久卡死；超时后走下方 join 超时 →
                # _permanently_stopped 兜底。正常情况下线程在持续消费，
                # 一个空位毫秒级出现，超时不会触发。
                self._queue.put(None, timeout=1.0)
            except queue.Full:
                pass
            assert self._thread is not None
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                # 写入线程卡死（如日志盘被拔）：禁止重启（防双线程交错写），丢弃句柄
                self._permanently_stopped = True
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
        rec = _Record(direction=direction, data=data, timestamp=ts, file_path=file_path)
        try:
            self._queue.put_nowait(rec)
        except queue.Full:
            # P1-2：日志通道 best-effort——慢盘时丢弃新记录优于无限积压拖垮内存/
            # 阻塞读线程。丢弃计数供观测（测试断言）。
            self.dropped_count += 1

    def begin_case(self, log_dir: Path, session: str, port: str, case_name: str) -> Path:
        """为某用例某端口准备日志文件路径（按 §7.3 目录组织）.

        返回基础路径（stem，无后缀）；实际写入时派生 ``<stem>.text.log`` 和
        ``<stem>.hex.log`` 两个独立文件（§7.2 TEXT 与 HEX 分离）。

        S-1：三个片段全部消毒——session/port 与 case_name 同为不可信输入
        （port 来自用例 step.port），旧实现仅 case_name 过 ``_sanitize``，
        session/port 直接拼接可实现跨目录任意写（如 session="../../evil"）。
        """
        # S-1：port 先取 basename 消路径语义——Linux /dev/ttyUSB0 变 ttyUSB0
        # （不再嵌套 dev/ttyUSB0 目录），Windows ..\..\evil 变 evil（遍历封死）；
        # name 为空（如 port="" 或 "/"）时回退原串，交由 _sanitize 兜底占位。
        safe_port = _sanitize(Path(port).name or port)
        safe_session = _sanitize(session)
        safe_case = _sanitize(case_name)
        case_dir = log_dir / safe_session / safe_port
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir / safe_case

    def end_case(self, stem: Path) -> None:
        """关闭某用例的日志句柄（引擎 clear_case_log 时调用）——常驻进程下
        句柄不再无限累积（P1-2）。后续同 stem 记录将重开文件（append 模式）。
        """
        if not self._started:
            return
        try:
            self._queue.put_nowait(stem)
        except queue.Full:
            # 队列满：end_case 消息丢弃——该 stem 的句柄由 _write 的 LRU
            # 上限兜底关闭，不在此阻塞调用方（可能在 PortManager 锁内）。
            pass

    # ------------------------------------------------------------------
    # 后台线程
    # ------------------------------------------------------------------
    def _run(self) -> None:
        # B4 修复：缓存文件句柄（按 file_path），消除每条记录重开 2 个文件的 I/O 放大。
        # 哨兵退出时统一 close 所有句柄，确保缓冲落盘。
        # P1-2：队列元素为 _Record | None | Path——None 是停止哨兵；Path 表示
        # end_case 该 stem（类型窄化明确：消息即 stem 路径本身）。
        files: dict[Path, tuple[Any, Any]] = {}  # text_path -> (text_fp, hex_fp)
        try:
            while True:
                rec = self._queue.get()
                if rec is None:
                    self._drain(files)
                    return
                if isinstance(rec, Path):
                    self._close_stem(files, rec)
                    continue
                self._write(rec, files)
        finally:
            # 兜底：线程退出（含异常）时关闭所有句柄
            for text_fp, hex_fp in files.values():
                for fp in (text_fp, hex_fp):
                    try:
                        fp.close()
                    except OSError:
                        pass

    def _drain(self, files: dict[Path, tuple[Any, Any]]) -> None:
        while True:
            try:
                rec = self._queue.get_nowait()
            except queue.Empty:
                return
            if rec is None:
                continue
            if isinstance(rec, Path):
                self._close_stem(files, rec)
            else:
                self._write(rec, files)

    def _close_stem(self, files: dict[Path, tuple[Any, Any]], stem: Path) -> None:
        """end_case 消息处理：关闭并弹出该 stem 的句柄对（不存在则忽略）.

        每次写后已 flush，close 仅为释放句柄（Linux fd 上限 / Windows 文件占用），
        无数据丢失；后续同 stem 记录由 _write 以 append 模式重开。
        """
        text_path = stem.parent / f"{stem.name}.text.log"
        pair = files.pop(text_path, None)
        if pair is None:
            return
        for fp in pair:
            try:
                fp.close()
            except OSError:
                pass

    def _write(self, rec: _Record, files: dict[Path, tuple[Any, Any]]) -> None:
        try:
            text = rec.data.decode("utf-8", errors="replace")
            hexs = " ".join(f"{b:02X}" for b in rec.data)
            stem = rec.file_path  # begin_case 返回的基础路径（无后缀）
            parent, name = stem.parent, stem.name
            text_path = parent / f"{name}.text.log"
            hex_path = parent / f"{name}.hex.log"
            # 按句柄缓存 key（text_path）获取或新建一对文件句柄
            pair = files.get(text_path)
            if pair is None:
                # B4：缓存句柄而非每次重开（消除 I/O 放大）。不用 with——
                # 句柄在线程生命周期内常驻，哨兵退出时 finally 统一 close。
                text_fp = open(text_path, "a", encoding="utf-8")  # noqa: SIM115
                hex_fp = open(hex_path, "a", encoding="utf-8")  # noqa: SIM115
                pair = (text_fp, hex_fp)
                files[text_path] = pair  # 用 text_path 作 key（与 hex_path 一一对应）
                # P1-2 兜底：句柄数封顶——即便上游忘记 end_case（GUI/MCP 常驻
                # 进程跨大量用例），超上限时按插入序（dict 保序）逐出最旧并
                # close。每次写后已 flush，close 不丢已写内容。被逐 stem 记入
                # 公开 evicted（仅观测/测试断言用）。
                while len(files) > self._MAX_STEMS:
                    oldest = next(iter(files))
                    old_pair = files.pop(oldest)
                    for fp in old_pair:
                        try:
                            fp.close()
                        except OSError:
                            pass
                    self.evicted.append(oldest.with_name(oldest.name.removesuffix(".text.log")))
            text_fp, hex_fp = pair
            # TEXT 与 HEX 分离到两个独立文件（§7.2）
            text_fp.write(f"[{rec.timestamp}] [{rec.direction}] {text}")
            if not text.endswith("\n"):
                text_fp.write("\n")
            text_fp.flush()
            hex_fp.write(f"[{rec.timestamp}] [{rec.direction}] {hexs}\n")
            hex_fp.flush()
        except OSError:
            # 日志失败不应影响测试主流程（吞掉，避免读线程崩）
            pass


def _sanitize(name: str) -> str:
    """把用例名转为安全的文件名片段.

    纯点号（"." / ".." / "..."）在字符白名单内但构成路径遍历成分（拼接时
    即上级目录），整体替换为占位 "case"。其余输入按白名单逐字符过滤，
    分隔符（/ 与 \\）必然被替换为 "_"，结果恒为单一片段。
    """
    out: list[str] = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    if not out or set(out) <= {"."}:
        return "case"
    return "".join(out)
