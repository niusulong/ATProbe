"""JobManager 状态机测试（M8 §4）：BUSY/进度/快照/取消/历史淘汰."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

import atprobe.mcp.jobs as jobs_mod
from atprobe.domain.suite.collect import load_cases
from atprobe.engine.config import EngineConfig
from atprobe.engine.interfaces import CaseStartEvent, StepResultEvent
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.portmanager import PortManager
from atprobe.infra.serial.vsim import VSIM_PORT, VsimPortManager
from atprobe.mcp.errors import McpError
from atprobe.mcp.jobs import EVENT_BUFFER, JobManager, _Job

MINIMAL_CASE = """\
name: mini
tags: [smoke]
steps:
  - command: "AT"
    port: VSIM0
    assert:
      - contains: "OK"
"""


def _make_cfg(tmp_path: Path, session: str = "jobtest", port: str = VSIM_PORT) -> EngineConfig:
    case_file = tmp_path / "mini.yaml"
    if not case_file.exists():
        case_file.write_text(MINIMAL_CASE, encoding="utf-8")
    collected = load_cases([case_file])
    return EngineConfig(
        ports=(PortConfig(name=port),),
        cases=collected.cases,
        session_id=session,
        log_dir=str(tmp_path / "logs"),
    )


def _wait_finished(jobs: JobManager, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = jobs.snapshot(job_id)
        if snap["status"] != "running":
            return snap
        time.sleep(0.05)
    raise AssertionError("job 未在超时内结束")


@pytest.fixture
def vsim_pm():
    pm = VsimPortManager()
    pm.open(PortConfig(name=VSIM_PORT))
    return pm


def test_start_and_finish(tmp_path, vsim_pm):
    jobs = JobManager(report_root=tmp_path / "reports")
    job_id = jobs.start(
        build_engine_cfg=lambda jid: _make_cfg(tmp_path, session=jid),
        sender_factory=lambda: vsim_pm,
    )
    snap = _wait_finished(jobs, job_id)
    assert snap["status"] == "finished"
    assert snap["summary"]["passed"] == 1
    assert snap["summary"]["failed"] == 0
    assert snap["report_path"] and Path(snap["report_path"]).exists()
    assert jobs.running_job_id() is None
    # job_id 即 session_id：报告目录名与 job_id 一致
    assert Path(snap["report_path"]).parent.name == job_id
    # 快照携带本次作业的日志目录（不只是根目录）：cfg.log_dir/<job_id>，
    # 与引擎实际落盘布局（logs/<session>/<端口>/<用例>.*）一致
    assert snap["log_dir"] == str(tmp_path / "logs" / job_id)


def test_busy_rejects_second_start(tmp_path, vsim_pm):
    jobs = JobManager(report_root=tmp_path / "reports")
    # 用多用例拖长第一个 job：写 100 个用例文件（保证第二个 start 时仍在运行）
    for i in range(100):
        (tmp_path / f"case{i:02d}.yaml").write_text(
            MINIMAL_CASE.replace("name: mini", f"name: mini{i:02d}"), encoding="utf-8"
        )
    files = sorted(tmp_path.glob("case*.yaml"))
    collected = load_cases(list(files))

    def _cfg(jid: str) -> EngineConfig:
        return EngineConfig(
            ports=(PortConfig(name=VSIM_PORT),),
            cases=collected.cases,
            session_id=jid,
            log_dir=str(tmp_path / "logs"),
        )

    job_id = jobs.start(build_engine_cfg=_cfg, sender_factory=lambda: vsim_pm)
    try:
        # 前置校验：确保第二个 start 时第一个 job 确实在跑（否则测试需加固）
        assert jobs.running_job_id() == job_id
        jobs.start(build_engine_cfg=_cfg, sender_factory=lambda: vsim_pm)
        raise AssertionError("应抛 BUSY")
    except McpError as exc:
        assert exc.kind == "BUSY"
        assert exc.detail.get("job_id") == job_id
    finally:
        assert jobs.cancel(job_id) is True
        _wait_finished(jobs, job_id)


def test_snapshot_unknown_job():
    jobs = JobManager()
    with pytest.raises(McpError) as ei:
        jobs.snapshot("nope")
    assert ei.value.kind == "NOT_FOUND"


def test_cancel_idempotent_semantics(tmp_path, vsim_pm):
    jobs = JobManager(report_root=tmp_path / "reports")
    job_id = jobs.start(
        build_engine_cfg=lambda jid: _make_cfg(tmp_path, session=jid),
        sender_factory=lambda: vsim_pm,
    )
    _wait_finished(jobs, job_id)
    # 已结束的 job 再 cancel → False（幂等不报错）
    assert jobs.cancel(job_id) is False


def test_cancel_unknown_job():
    jobs = JobManager()
    with pytest.raises(McpError) as ei:
        jobs.cancel("nope")
    assert ei.value.kind == "NOT_FOUND"


def test_history_eviction(tmp_path, vsim_pm):
    jobs = JobManager(report_root=tmp_path / "reports", max_history=2)
    for _ in range(3):
        jid = jobs.start(
            build_engine_cfg=lambda j: _make_cfg(tmp_path, session=j),
            sender_factory=lambda: vsim_pm,
        )
        _wait_finished(jobs, jid)
    assert len(jobs._jobs) == 2  # 只保留最近 2 条


def test_progress_events_recorded(tmp_path, vsim_pm):
    jobs = JobManager(report_root=tmp_path / "reports")
    for i in range(3):
        (tmp_path / f"p{i}.yaml").write_text(
            MINIMAL_CASE.replace("name: mini", f"name: p{i}"), encoding="utf-8"
        )
    collected = load_cases(sorted(tmp_path.glob("p?.yaml")))
    job_id = jobs.start(
        build_engine_cfg=lambda jid: EngineConfig(
            ports=(PortConfig(name=VSIM_PORT),),
            cases=collected.cases,
            session_id=jid,
            log_dir=str(tmp_path / "logs"),
        ),
        sender_factory=lambda: vsim_pm,
    )
    snap = _wait_finished(jobs, job_id)
    kinds = [e["event"] for e in snap["events"]]
    assert "case_start" in kinds
    assert "case_result" in kinds
    assert snap["summary"]["total"] == 3
    # 事件缓冲上限契约：快照事件数不得超过 EVENT_BUFFER（当前 50）
    assert len(snap["events"]) <= 50
    assert EVENT_BUFFER == 50
    # 事件 schema（Task 6 冻结前定名）：case 级事件统一 case_index 字段
    for e in snap["events"]:
        if e["event"] == "case_start":
            assert "case_index" in e
            assert "index" not in e
        if e["event"] == "case_result":
            assert "case_index" in e


def test_port_open_failure_fails_job(tmp_path):
    """全部端口打开失败 → result.error → job 置 failed（覆盖 failed 终态路径）.

    用真 PortManager + 不存在的端口名：open 抛错且无任何端口连上 →
    scheduler 语义（全部端口失败 = 启动错误）→ result.error 非空。
    """
    jobs = JobManager(report_root=tmp_path / "reports")
    job_id = jobs.start(
        build_engine_cfg=lambda jid: _make_cfg(
            tmp_path, session=jid, port="COM_ATPROBE_NONEXISTENT_99"
        ),
        sender_factory=lambda: PortManager(),
    )
    snap = _wait_finished(jobs, job_id)
    assert snap["status"] == "failed"
    assert "error" in snap
    assert "端口打开失败" in snap["error"]
    assert jobs.running_job_id() is None


def test_start_thread_failure_rolls_back(tmp_path, vsim_pm, monkeypatch):
    """F-6：Thread.start 抛错 → start 抛 BUSY 且三注册表回滚，不留僵尸 running.

    回滚后 running_job_id() 为 None；用真 Thread 再走一次成功路径验证可恢复。
    """
    jobs = JobManager(report_root=tmp_path / "reports")
    real_thread = threading.Thread

    class ExplodingThread(real_thread):  # type: ignore[type-arg]
        def start(self) -> None:
            raise RuntimeError("无法启动新线程")

    monkeypatch.setattr(jobs_mod.threading, "Thread", ExplodingThread)
    with pytest.raises(McpError) as ei:
        jobs.start(
            build_engine_cfg=lambda jid: _make_cfg(tmp_path, session=jid),
            sender_factory=lambda: vsim_pm,
        )
    assert ei.value.kind == "BUSY"
    assert "作业线程启动失败" in ei.value.message
    assert ei.value.detail.get("job_id")
    # 回滚验证：三注册表均无残留（否则此后所有 start 永久 BUSY）
    assert jobs.running_job_id() is None
    assert jobs._jobs == {}
    assert jobs._order == []
    assert jobs._engines == {}
    # 恢复验证：真 Thread 一次成功路径
    monkeypatch.undo()
    jid = jobs.start(
        build_engine_cfg=lambda j: _make_cfg(tmp_path, session=j),
        sender_factory=lambda: vsim_pm,
    )
    snap = _wait_finished(jobs, jid)
    assert snap["status"] == "finished"


def test_job_id_collision_regenerates(monkeypatch):
    """F-7：token_hex 碰撞既有 _jobs 时重生成，直至不冲突（时间戳冻结避免秒边界抖动）."""

    class FrozenClock:
        @staticmethod
        def now() -> FrozenClock:
            return FrozenClock()

        def strftime(self, fmt: str) -> str:
            return "20260828_120000"

    monkeypatch.setattr(jobs_mod, "datetime", FrozenClock)
    jobs = JobManager()
    jobs._jobs["20260828_120000_aaaaaaaa"] = _Job("20260828_120000_aaaaaaaa")
    seq: Iterator[str] = iter(("aaaaaaaa", "aaaaaaaa", "bbbbbbbb"))
    monkeypatch.setattr(secrets, "token_hex", lambda _n: next(seq))
    assert jobs._new_job_id() == "20260828_120000_bbbbbbbb"
    # 既有条目不受生成过程影响
    assert "20260828_120000_aaaaaaaa" in jobs._jobs


def test_eviction_skips_running(tmp_path):
    """驱逐跳过 running 条目：最旧 running 时淘汰次旧，running 存活（F-7 组合防线）."""
    jobs = JobManager(report_root=tmp_path / "reports", max_history=2)
    for jid, status in (("j1", "running"), ("j2", "finished"), ("j3", "finished")):
        job = _Job(jid)
        job.status = status
        jobs._jobs[jid] = job
        jobs._order.append(jid)
    jobs._evict_locked()
    assert "j1" in jobs._jobs and jobs._jobs["j1"].status == "running"
    assert "j2" not in jobs._jobs  # 最旧非 running 的 j2 被淘汰
    assert "j3" in jobs._jobs
    assert jobs._order == ["j1", "j3"]  # 顺序语义不被破坏


def test_events_truncated_counted(tmp_path):
    """P3：事件超出 EVENT_BUFFER 后 snapshot 报 events_truncated（丢量可见）."""
    jobs = JobManager(report_root=tmp_path / "reports")
    # 未溢出场景：恒附 int 0（轮询方比对语义）
    fresh = _Job("fresh-job")
    jobs._jobs["fresh-job"] = fresh
    jobs._record_event(
        fresh,
        CaseStartEvent(case_name="c0", case_index=1, total_cases=1, case_type="regular"),
    )
    assert jobs.snapshot("fresh-job")["events_truncated"] == 0
    # 溢出场景：60 条 CaseStart → 缓冲 50，丢 10
    job = _Job("evt-job")
    jobs._jobs["evt-job"] = job
    for i in range(60):
        jobs._record_event(
            job,
            CaseStartEvent(
                case_name=f"c{i}", case_index=i + 1, total_cases=60, case_type="regular"
            ),
        )
    snap = jobs.snapshot("evt-job")
    assert len(snap["events"]) == EVENT_BUFFER
    assert snap["events_truncated"] == 10


def test_step_event_command_masked_when_enabled(tmp_path):
    """T6-10：mask_credentials 开启时 step_result 事件的 command 字段脱敏."""

    def _step_event(command: str) -> StepResultEvent:
        return StepResultEvent(
            step_index=1,
            phase="steps",
            port="V0",
            command=command,
            status="FAIL",
            duration_ms=1.0,
            response="",
            error_msg="",
        )

    for mask, expected in ((True, "AT+CPIN=****"), (False, "AT+CPIN=1234")):
        jobs = JobManager(report_root=tmp_path / "reports", mask_credentials=mask)
        job = _Job("m-job")
        jobs._jobs["m-job"] = job
        jobs._record_event(job, _step_event("AT+CPIN=1234"))
        snap = jobs.snapshot("m-job")
        step_evs = [e for e in snap["events"] if e["event"] == "step_result"]
        assert step_evs and step_evs[0]["command"] == expected
