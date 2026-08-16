"""M8 JobManager：异步测试作业（单并发 BUSY、进度快照、HTML 报告）.

job 在专用线程执行（engine.start 阻塞）；进度事件在引擎线程回调 → 加锁写快照。
job_id 复用 session_id 规则（%Y%m%d_%H%M%S_4hex，M5 §7.2），同时即报告目录名。
端口所有权由引擎管理（scheduler 只关闭自己新开的端口，TSD §6.2）——本层不碰端口。
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from atprobe.domain.report.models import ExecutionResult
from atprobe.engine import Engine, EngineConfig
from atprobe.engine.config import StopMode
from atprobe.engine.interfaces import (
    CaseResultEvent,
    CaseStartEvent,
    StepResultEvent,
)
from atprobe.infra.serial.interfaces import ICommandSender
from atprobe.infra.serial.rawlog import RawLogger
from atprobe.mcp.errors import busy, not_found
from atprobe.reporting.html import HtmlReporter
from atprobe.reporting.interfaces import ReportOutput

_log = logging.getLogger("atprobe.mcp.jobs")

EVENT_BUFFER = 50
EVENT_CMD_TRUNCATE = 80  # step 事件 command 摘要截断长度
EVENT_ERROR_TRUNCATE = 200  # 事件/日志 error 摘要截断长度
DEFAULT_MAX_HISTORY = 100


class _Job:
    """单个作业的可变状态（跨线程共享：所有字段读写必须持有 JobManager._lock）."""

    def __init__(self, job_id: str) -> None:
        self.id = job_id
        self.status: str = "running"  # running | finished | failed
        # 进度（CaseStartEvent / CaseResultEvent 驱动）
        self.total = 0
        self.done = 0
        self.current_case = ""
        self.current_index = 0
        # 终态填充（渲染在置终态之前完成 → 快照见非 running 时字段已就绪）
        self.summary: dict[str, Any] | None = None
        self.report_path = ""
        self.error = ""
        # 进度事件环形缓冲（最近 EVENT_BUFFER 条）
        self.events: deque[dict[str, Any]] = deque(maxlen=EVENT_BUFFER)


class JobManager:
    """进程内异步作业管理器（单并发：running 期间再 start 抛 BUSY）.

    线程模型（M8 §4）：start/cancel/snapshot 由 MCP 工具线程调用，
    _run 与进度回调在 ``mcp-job-{job_id}`` 引擎线程执行——共享状态全部
    经 ``_lock`` 互斥；engine.start 不持锁（长阻塞）。
    """

    def __init__(
        self,
        report_root: Path | str = "reports",
        max_history: int = DEFAULT_MAX_HISTORY,
        raw_logger: RawLogger | None = None,
    ) -> None:
        self._report_root = Path(report_root)
        self._max_history = max_history
        # 注入的 RawLogger 生命周期归调用方（service 常驻实例）；None 时引擎
        # 每次自建（stop 随 engine.start 结束）。注入后作业原始日志经共享
        # PortManager 的 connection 写入（M8 修复：共享 PM 模式此前不落盘）。
        self._raw_logger = raw_logger
        self._jobs: dict[str, _Job] = {}
        self._order: list[str] = []  # 创建顺序（历史淘汰弹最旧）
        self._engines: dict[str, Engine] = {}  # running 作业的引擎（cancel 用）
        self._lock = threading.Lock()

    @property
    def report_root(self) -> Path:
        """报告根目录（只读；service.server_info 等外部展示用——构造参数 report_root
        可能与 app_cfg.report_dir 不同（如测试/自定义部署锚定别处），展示以本值为准）."""
        return self._report_root

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------
    def start(
        self,
        build_engine_cfg: Callable[[str], EngineConfig],
        sender_factory: Callable[[], ICommandSender],
    ) -> str:
        """启动作业并立即返回 job_id（job_id 即 session_id 即报告目录名）.

        工厂收到 job_id 并注入 EngineConfig.session_id；工厂抛出的异常
        （INVALID_INPUT 类，service 层抛）原样透传，不注册任何作业状态。
        build_engine_cfg 在管理器锁内调用，不得回调本管理器方法
        （Lock 不可重入）。

        Raises:
            McpError: BUSY——已有作业在执行（detail.job_id 为占用中的作业 id）。
        """
        with self._lock:
            running = self._running_locked()
            if running is not None:
                raise busy(f"已有作业在执行：{running.id}", job_id=running.id)
            # 先生成 job_id 再调工厂：秒级时间戳相同靠 token_hex(2) 保证唯一（M5 §7.2）
            job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
            cfg = build_engine_cfg(job_id)
            job = _Job(job_id)
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._evict_locked()
            # 引擎在此创建并注册（而非 _run 内）：start 返回即可 cancel，
            # 消除「引擎线程尚未跑到注册语句」窗口内 cancel 找不到引擎的竞态。
            # raw_logger 注入（M8）：_owns_raw_logger=False，start/stop 不管它。
            engine = Engine(sender_factory=sender_factory, raw_logger=self._raw_logger)
            self._engines[job_id] = engine
            threading.Thread(
                target=self._run, args=(job, cfg, engine), name=f"mcp-job-{job_id}", daemon=True
            ).start()
        # 启动 info 日志（锁外）：线程已成功启动，total 取配置用例数
        _log.info("job %s 启动：%d 用例", job_id, len(cfg.cases))
        return job_id

    # ------------------------------------------------------------------
    # 取消
    # ------------------------------------------------------------------
    def cancel(self, job_id: str) -> bool:
        """取消 running 作业（StopMode.ALL）；非 running 返回 False（幂等）.

        Raises:
            McpError: NOT_FOUND——作业不存在或已被历史淘汰。
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise not_found(f"作业不存在或已被淘汰：{job_id}", job_id=job_id)
            if job.status != "running":
                return False
            engine = self._engines.get(job_id)
        if engine is not None:
            engine.stop(StopMode.ALL)  # 锁外调用：stop 仅置标志，避免持锁做外部调用
        return True

    # ------------------------------------------------------------------
    # 快照 / 查询
    # ------------------------------------------------------------------
    def snapshot(self, job_id: str) -> dict[str, Any]:
        """作业快照：状态、进度（running 时）、summary/report_path/error 与最近事件.

        Raises:
            McpError: NOT_FOUND——作业不存在或已被历史淘汰。
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise not_found(f"作业不存在或已被淘汰：{job_id}", job_id=job_id)
            snap: dict[str, Any] = {
                "job_id": job.id,
                "status": job.status,
                "events": list(job.events),
            }
            if job.status == "running":
                snap["progress"] = {
                    "total": job.total,
                    "done": job.done,
                    "current_case": job.current_case,
                    "current_index": job.current_index,
                }
            if job.summary is not None:
                snap["summary"] = dict(job.summary)
            if job.report_path:
                snap["report_path"] = job.report_path
            if job.error:
                snap["error"] = job.error
            return snap

    def running_job_id(self) -> str | None:
        """当前 running 作业 id（无则 None）."""
        with self._lock:
            running = self._running_locked()
            return running.id if running is not None else None

    # ------------------------------------------------------------------
    # 内部（引擎线程）
    # ------------------------------------------------------------------
    def _run(self, job: _Job, cfg: EngineConfig, engine: Engine) -> None:
        """作业线程主体：阻塞跑引擎 → 渲染报告 → 置终态.

        最外层 except Exception 为终态兜底：任何逃逸异常（渲染外的路径
        缺陷等）都转为 failed 终态，保证 job 永不卡 running（对齐
        scheduler.py 引擎主循环兜底的同类修复）。
        """
        try:
            try:
                result = engine.start(cfg, handler=lambda ev: self._record_event(job, ev))
            except Exception as exc:  # noqa: BLE001 - 引擎异常转 failed 终态，不逃逸线程
                _log.exception("引擎执行异常 job=%s", job.id)
                self._fail(job, f"{type(exc).__name__}: {exc}")
                return
            # 报告渲染（引擎线程内）：先于置终态，保证轮询方见非 running 时
            # report_path 已就绪；渲染失败仅记日志，不影响 job 状态。
            self._render_report(job, result)
            with self._lock:
                if result.error:
                    job.status = "failed"
                    job.error = result.error
                else:
                    job.status = "finished"
                    s = result.summary
                    job.summary = {
                        "total": s.total_cases,
                        "passed": s.passed,
                        "failed": s.failed,
                        "skipped": s.skipped,
                        "interrupted": s.interrupted,
                        "pass_rate": round(s.pass_rate, 2),
                    }
            # 终态 info 概览（锁外）：一条日志同时可见状态与关键数字
            if result.error:
                _log.info("job %s 失败：%s", job.id, result.error[:EVENT_ERROR_TRUNCATE])
            else:
                s = result.summary
                _log.info(
                    "job %s 完成：passed=%d failed=%d skipped=%d interrupted=%d",
                    job.id,
                    s.passed,
                    s.failed,
                    s.skipped,
                    s.interrupted,
                )
        except Exception as exc:  # noqa: BLE001 - 终态兜底：逃逸异常转 failed，不卡 running
            _log.exception("作业线程未捕获异常 job=%s", job.id)
            self._fail(job, f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._engines.pop(job.id, None)

    def _fail(self, job: _Job, error: str) -> None:
        """置 failed 终态并记 info 概览（摘要截断，详细堆栈走 exception 日志）."""
        with self._lock:
            job.status = "failed"
            job.error = error
        _log.info("job %s 失败：%s", job.id, error[:EVENT_ERROR_TRUNCATE])

    def _record_event(self, job: _Job, event: object) -> None:
        """引擎线程回调：CaseStart/CaseResult 更新进度，非 PASS 步骤记事件.

        EngineFinishedEvent 忽略（终态由 result 驱动）；PressureProgressEvent
        不进缓冲（快照体积考虑，进度面板语义属于 GUI 订阅方）。
        """
        if isinstance(event, CaseStartEvent):
            with self._lock:
                job.total = event.total_cases
                job.current_case = event.case_name
                job.current_index = event.case_index
                job.events.append(
                    {
                        "event": "case_start",
                        "case": event.case_name,
                        "case_index": event.case_index,
                        "total": event.total_cases,
                    }
                )
        elif isinstance(event, CaseResultEvent):
            with self._lock:
                job.done += 1
                ev: dict[str, Any] = {
                    "event": "case_result",
                    "case": event.case_name,
                    "case_index": event.case_index,
                    "status": event.status,
                    "duration_ms": round(event.duration_ms, 1),
                }
                if event.error_msg:
                    ev["error"] = event.error_msg[:EVENT_ERROR_TRUNCATE]
                job.events.append(ev)
        elif isinstance(event, StepResultEvent) and event.status != "PASS":
            with self._lock:
                job.events.append(
                    {
                        "event": "step_result",
                        "case": job.current_case,
                        "phase": event.phase,
                        "step_index": event.step_index,
                        "status": event.status,
                        "command": event.command[:EVENT_CMD_TRUNCATE],
                        "error": event.error_msg[:EVENT_ERROR_TRUNCATE],
                    }
                )

    def _render_report(self, job: _Job, result: ExecutionResult) -> None:
        html_path = self._report_root / job.id / "report.html"
        try:
            HtmlReporter().render(result, ReportOutput(html_path=html_path, to_console=False))
        except Exception:  # noqa: BLE001 - 渲染失败不影响 job 状态
            _log.exception("报告渲染失败 job=%s", job.id)
            return
        with self._lock:
            job.report_path = str(html_path)

    # ------------------------------------------------------------------
    # 内部（调用方持锁）
    # ------------------------------------------------------------------
    def _running_locked(self) -> _Job | None:
        for job in self._jobs.values():
            if job.status == "running":
                return job
        return None

    def _evict_locked(self) -> None:
        """历史淘汰：超 max_history 弹最旧（单并发保证被淘汰者非 running）."""
        while len(self._order) > self._max_history:
            oldest = self._order.pop(0)
            self._jobs.pop(oldest, None)
