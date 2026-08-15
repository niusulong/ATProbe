"""JobManager 状态机测试（M8 §5）：BUSY/进度/快照/取消/历史淘汰."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from atprobe.engine.config import EngineConfig
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.vsim import VSIM_PORT, VsimPortManager
from atprobe.mcp.errors import McpError
from atprobe.mcp.jobs import JobManager

MINIMAL_CASE = """\
name: mini
tags: [smoke]
steps:
  - command: "AT"
    port: VSIM0
    assert:
      - contains: "OK"
"""


def _make_cfg(tmp_path: Path, session: str = "jobtest") -> EngineConfig:
    from atprobe.domain.suite.collect import load_cases

    case_file = tmp_path / "mini.yaml"
    if not case_file.exists():
        case_file.write_text(MINIMAL_CASE, encoding="utf-8")
    collected = load_cases([case_file])
    return EngineConfig(
        ports=(PortConfig(name=VSIM_PORT),),
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


def test_busy_rejects_second_start(tmp_path, vsim_pm):
    jobs = JobManager(report_root=tmp_path / "reports")
    # 用多用例拖长第一个 job：写 100 个用例文件（保证第二个 start 时仍在运行）
    for i in range(100):
        (tmp_path / f"case{i:02d}.yaml").write_text(
            MINIMAL_CASE.replace("name: mini", f"name: mini{i:02d}"), encoding="utf-8"
        )
    from atprobe.domain.suite.collect import load_cases

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
    from atprobe.domain.suite.collect import load_cases

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
