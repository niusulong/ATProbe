"""McpService 设备门面测试（M8 Task 6）：vsim 全链路、错误契约、URC 转发.

零 mock 原则：除 DEVICE_ERROR 转换路径允许 monkeypatch 外全部用真实对象
（VsimPortManager 进程内应答；真 PortManager 只在不触碰硬件的错误路径上构造）。
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from atprobe.infra.config.appconfig import AppConfig
from atprobe.infra.serial.vsim import VSIM_PORT, VsimPortManager
from atprobe.mcp.errors import McpError
from atprobe.mcp.service import McpService

MINIMAL_CASE = """\
name: mini
tags: [smoke]
steps:
  - command: "AT"
    port: VSIM0
    assert:
      - contains: "OK"
"""

VSIM_EXPR = f"{VSIM_PORT}:115200:8N1"


def _app_cfg(tmp_path: Path, **over: str) -> AppConfig:
    """测试配置：cases/logs/reports 全部锚定 tmp，env_config 指向不存在文件（→ None）."""
    cfg = AppConfig(
        cases_dir=str(tmp_path / "cases"),
        report_dir=str(tmp_path / "reports"),
        log_dir=str(tmp_path / "logs"),
        env_config=str(tmp_path / "noenv.yaml"),
    )
    return replace(cfg, **over) if over else cfg


def _write_case(dir_: Path, name: str, content: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    f = dir_ / f"{name}.yaml"
    f.write_text(content, encoding="utf-8")
    return f


def _wait_finished(svc: McpService, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = svc.get_job(job_id)
        if snap["status"] != "running":
            return snap
        time.sleep(0.05)
    raise AssertionError("job 未在超时内结束")


# ---------------------------------------------------------------------------
# 资源发现
# ---------------------------------------------------------------------------
def test_list_ports_vsim(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    ports = svc.list_ports()
    assert [p["name"] for p in ports] == [VSIM_PORT]
    assert ports[0]["connected"] is False
    svc.open_port(VSIM_EXPR)
    assert svc.list_ports()[0]["connected"] is True


def test_list_cases_and_suites(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    cases_dir = tmp_path / "cases"
    _write_case(
        cases_dir,
        "para",
        "name: para\ntags: [smoke]\nparameters:\n  - { v: A }\n  - { v: B }\n"
        'steps:\n  - command: "AT{{v}}"\n    assert:\n      - contains: "OK"\n',
    )
    _write_case(cases_dir, "broken", "name: [unclosed")  # 解析失败 → 跳过（对齐 CLI list）
    (cases_dir / "suite-demo.yaml").write_text(
        "name: 演示套件\ndescription: 冒烟\ntags: [daily]\ncases:\n  - para.yaml\n",
        encoding="utf-8",
    )

    cases = svc.list_cases(path=str(cases_dir), tags=[])
    names = [c["name"] for c in cases]
    # 参数化展开带 #N；坏文件静默跳过；套件文件不进用例列表
    assert names == ["para#1", "para#2"]
    assert cases[0]["tags"] == ["smoke"]
    assert cases[0]["file"].endswith("para.yaml")

    # 标签过滤
    assert [c["name"] for c in svc.list_cases(path=str(cases_dir), tags=["smoke"])] == names
    assert svc.list_cases(path=str(cases_dir), tags=["nonexistent"]) == []

    suites = svc.list_suites(path=str(cases_dir))
    assert len(suites) == 1
    s = suites[0]
    assert s["name"] == "演示套件"
    assert s["description"] == "冒烟"
    assert s["case_count"] == 1
    assert s["tags"] == ["daily"]
    assert s["file"].endswith("suite-demo.yaml")


# ---------------------------------------------------------------------------
# 手动调试
# ---------------------------------------------------------------------------
def test_open_port_vsim(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    result = svc.open_port(VSIM_EXPR)
    assert result["name"] == VSIM_PORT
    assert result["baud"] == 115200
    assert result["frame"] == "8N1"
    assert svc.port_manager.is_connected(VSIM_PORT) is True


def test_open_port_bad_expr(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    with pytest.raises(McpError) as ei:
        svc.open_port("COM3:notanumber")
    assert ei.value.kind == "INVALID_INPUT"


def test_open_port_device_error(tmp_path):
    """真 PortManager 打开不存在的端口 → pyserial 失败 → DEVICE_ERROR（零 mock）."""
    svc = McpService(_app_cfg(tmp_path), vsim=False)
    with pytest.raises(McpError) as ei:
        svc.open_port("COM_ATPROBE_NONEXISTENT_99:115200:8N1")
    assert ei.value.kind == "DEVICE_ERROR"


def test_send_at_requires_open(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    with pytest.raises(McpError) as ei:
        svc.send_at(VSIM_PORT, "AT")
    assert ei.value.kind == "INVALID_INPUT"


def test_send_at_ok(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    resp = svc.send_at(VSIM_PORT, "AT")
    assert "OK" in resp["text"]
    assert resp["status"] == "complete"
    assert "error" not in resp


def test_send_at_timeout_kw(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    resp = svc.send_at(VSIM_PORT, "AT", timeout=2.0)
    assert "OK" in resp["text"]


def test_close_port_idempotent(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    assert svc.close_port(VSIM_PORT) == {"closed": True, "port": VSIM_PORT}
    assert svc.port_manager.is_connected(VSIM_PORT) is False
    # 幂等：再关一次不抛错
    assert svc.close_port(VSIM_PORT) == {"closed": True, "port": VSIM_PORT}


def test_close_port_tears_down_urc_forwarding(tmp_path):
    """close_port 拆除该端口的 pm 层 URC 转发（订阅本身的退订仍走 unsubscribe_urc）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    pm: VsimPortManager = svc.port_manager  # type: ignore[assignment]
    sub = svc.subscribe_urc(VSIM_PORT, None)["subscription_id"]
    svc.close_port(VSIM_PORT)
    svc.open_port(VSIM_EXPR)  # 重开但不再订阅 → 转发不应复活
    pm.emit_urc(VSIM_PORT, "+LATE")
    assert svc.poll_urc(sub)["events"] == []


# ---------------------------------------------------------------------------
# URC 监控
# ---------------------------------------------------------------------------
def test_urc_subscribe_requires_open(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    with pytest.raises(McpError) as ei:
        svc.subscribe_urc(VSIM_PORT, None)
    assert ei.value.kind == "INVALID_INPUT"


def test_urc_flow(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    pm: VsimPortManager = svc.port_manager  # type: ignore[assignment]
    sub_all = svc.subscribe_urc(VSIM_PORT, None)["subscription_id"]
    sub_cereg = svc.subscribe_urc(VSIM_PORT, r"\+CEREG")["subscription_id"]

    pm.emit_urc(VSIM_PORT, "\r\n+CEREG: 1\r\n")
    pm.emit_urc(VSIM_PORT, "\r\n+CSQ: 99,99\r\n")

    page_all = svc.poll_urc(sub_all)
    # 每端口只挂一次转发：若重复挂接，每订阅的事件数会翻倍
    assert [e["text"] for e in page_all["events"]] == ["\r\n+CEREG: 1\r\n", "\r\n+CSQ: 99,99\r\n"]
    assert page_all["next_cursor"] == 2

    page_cereg = svc.poll_urc(sub_cereg)
    assert len(page_cereg["events"]) == 1
    assert "+CEREG: 1" in page_cereg["events"][0]["text"]

    # 退订 → poll 该订阅 NOT_FOUND（pm 层转发保留，供同端口其他订阅）
    assert svc.unsubscribe_urc(sub_all) == {"unsubscribed": True}
    with pytest.raises(McpError) as ei:
        svc.poll_urc(sub_all)
    assert ei.value.kind == "NOT_FOUND"
    # 另一订阅不受影响
    assert svc.poll_urc(sub_cereg, cursor=2)["events"] == []


def test_poll_urc_limit_clamped(tmp_path):
    """契约：limit ≤ 0 一律钳制为 1（防负切片怪语义，Task 3 审查结论）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    pm: VsimPortManager = svc.port_manager  # type: ignore[assignment]
    sub = svc.subscribe_urc(VSIM_PORT, None)["subscription_id"]
    pm.emit_urc(VSIM_PORT, "+U1")
    pm.emit_urc(VSIM_PORT, "+U2")
    page = svc.poll_urc(sub, cursor=0, limit=0)
    assert len(page["events"]) == 1
    assert page["events"][0]["text"] == "+U1"
    assert page["next_cursor"] == 1


# ---------------------------------------------------------------------------
# 批量测试
# ---------------------------------------------------------------------------
def test_validate_run(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    result = svc.validate_run(paths=[str(case)], tags=["smoke"])
    assert result["case_count"] == 1
    assert result["cases"] == ["mini"]
    assert result["ports"] == [VSIM_PORT]
    # vsim 模式不做系统端口枚举
    assert "ports_available" not in result
    # 标签过滤后为空 → INVALID_INPUT
    with pytest.raises(McpError) as ei:
        svc.validate_run(paths=[str(case)], tags=["nonexistent"])
    assert ei.value.kind == "INVALID_INPUT"


def test_validate_run_no_cases(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(McpError) as ei:
        svc.validate_run(paths=[str(empty)], tags=[])
    assert ei.value.kind == "INVALID_INPUT"


def test_start_run_full_flow(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True, report_root=tmp_path / "reports")
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    job_id = svc.start_run(paths=[str(case)])["job_id"]
    snap = _wait_finished(svc, job_id)
    assert snap["status"] == "finished"
    assert snap["summary"]["passed"] == 1
    assert snap["summary"]["failed"] == 0
    assert snap["report_path"] and Path(snap["report_path"]).exists()

    # 互斥解除：作业结束（引擎关闭了自己打开的端口）→ 重开后手动通道恢复
    svc.open_port(VSIM_EXPR)
    assert "OK" in svc.send_at(VSIM_PORT, "AT")["text"]
    # 已结束的 job cancel → False（幂等）
    assert svc.cancel_job(job_id) == {"cancelled": False}


def test_send_at_busy_during_job(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True, report_root=tmp_path / "reports")
    many = tmp_path / "many"
    for i in range(100):
        _write_case(many, f"case{i:02d}", MINIMAL_CASE.replace("name: mini", f"name: case{i:02d}"))
    paths = [str(p) for p in sorted(many.glob("*.yaml"))]
    # 手动打开的端口：scheduler 复用不关闭 → 作业后 send_at 无需重开
    svc.open_port(VSIM_EXPR)
    job_id = svc.start_run(paths=paths)["job_id"]
    assert svc.get_job(job_id)["status"] == "running"
    with pytest.raises(McpError) as ei:
        svc.send_at(VSIM_PORT, "AT")
    assert ei.value.kind == "BUSY"
    assert ei.value.detail.get("job_id") == job_id
    assert svc.cancel_job(job_id) == {"cancelled": True}
    snap = _wait_finished(svc, job_id)
    assert snap["status"] != "running"
    # 互斥解除
    assert "OK" in svc.send_at(VSIM_PORT, "AT")["text"]


def test_start_run_resolve_inputs_errors(tmp_path):
    # 1) 坏用例 YAML → INVALID_INPUT
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    bad = _write_case(tmp_path / "bad", "bad", "name: [unclosed")
    with pytest.raises(McpError) as ei:
        svc.start_run(paths=[str(bad)])
    assert ei.value.kind == "INVALID_INPUT"

    # 2) vsim=False 且未配置端口 → INVALID_INPUT（未指定端口）
    real = McpService(_app_cfg(tmp_path, ports=()), vsim=False)
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    with pytest.raises(McpError) as ei:
        real.start_run(paths=[str(case)])
    assert ei.value.kind == "INVALID_INPUT"

    # 3) 端口表达式非法 → INVALID_INPUT
    with pytest.raises(McpError) as ei:
        real.start_run(paths=[str(case)], ports=["COM3:notanumber"])
    assert ei.value.kind == "INVALID_INPUT"


def test_get_job_unknown(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    with pytest.raises(McpError) as ei:
        svc.get_job("nope")
    assert ei.value.kind == "NOT_FOUND"
