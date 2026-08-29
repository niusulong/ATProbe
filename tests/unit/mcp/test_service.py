"""McpService 设备门面测试（M8 Task 6）：vsim 全链路、错误契约、URC 转发.

零 mock 原则：全部用真实对象（VsimPortManager 进程内应答；真 PortManager
只在不触碰硬件的错误路径上构造——DEVICE_ERROR 用真实不存在的端口名触发）。
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from atprobe.engine.config import EngineConfig
from atprobe.infra.config.appconfig import AppConfig
from atprobe.infra.resources import resolve_workspace_path
from atprobe.infra.serial.exceptions import InvalidArgumentError, PortBusyError
from atprobe.infra.serial.vsim import VSIM_PORT, VsimPortManager
from atprobe.mcp.errors import McpError
from atprobe.mcp.service import _CASE_CACHE_MAX, McpService

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


def test_list_cases_missing_path_invalid_input(tmp_path):
    """显式路径不存在 → INVALID_INPUT（不再静默空列表）；strict 与否一致."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    missing = tmp_path / "nope"
    with pytest.raises(McpError) as ei:
        svc.list_cases(path=str(missing))  # 非严格（list 语义）也报——用户显式给错路径
    assert ei.value.kind == "INVALID_INPUT"
    assert "路径不存在" in ei.value.message
    with pytest.raises(McpError) as ei:
        svc.validate_run(paths=[str(missing)], tags=[])
    assert ei.value.kind == "INVALID_INPUT"
    assert "路径不存在" in ei.value.message


def test_collect_default_cases_dir_missing(tmp_path):
    """缺省 cases_dir 不存在：strict（validate/start）→ INVALID_INPUT；
    非严格 list_cases → 空列表（发现式语义，tools 层文案足够）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)  # cases_dir 未创建
    assert svc.list_cases() == []
    with pytest.raises(McpError) as ei:
        svc.validate_run(tags=[])
    assert ei.value.kind == "INVALID_INPUT"
    assert "路径不存在" in ei.value.message


def test_collect_strict_parse_error_vs_skip(tmp_path):
    """同一坏文件：strict（validate_run）→ INVALID_INPUT；非 strict（list_cases）跳过."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    bad = _write_case(tmp_path / "cases" / "bad", "bad", "name: [unclosed")
    with pytest.raises(McpError) as ei:
        svc.validate_run(paths=[str(bad)], tags=[])
    assert ei.value.kind == "INVALID_INPUT"
    assert "用例解析失败" in ei.value.message
    assert svc.list_cases(path=str(bad)) == []  # 跳过坏文件 → 空列表（不抛）


def test_collect_suite_steps_through_cache(tmp_path):
    """显式 suite 文件经统一收集：suite 前后置带出（缓存粒度为单文件 Collected 整体）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    d = tmp_path / "cases"
    _write_case(d, "mini", MINIMAL_CASE)
    suite = d / "suite-all.yaml"
    suite.write_text(
        "name: 全\ncases:\n  - mini.yaml\n"
        "suite_setup:\n  - command: AT+SU\n    port: VSIM0\n"
        "suite_teardown:\n  - command: AT+TD\n    port: VSIM0\n",
        encoding="utf-8",
    )
    _cases, setup, teardown = svc._collect_cases([str(suite)], strict=True)
    assert [c.name for c in _cases] == ["mini"]
    assert [s.command for s in setup] == ["AT+SU"]
    assert [s.command for s in teardown] == ["AT+TD"]


def test_collect_cache_reuse_and_mtime_invalidation(tmp_path, monkeypatch):
    """缓存（§4.9/P3）：同文件二次收集（跨 list/validate 入口）不重复解析；
    mtime 变化（文件编辑）→ 失效重解析."""
    import atprobe.mcp.service as service_mod

    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    calls: list[Path] = []
    real_load = service_mod.load_cases

    def counting_load(paths):
        calls.extend(paths)
        return real_load(paths)

    monkeypatch.setattr(service_mod, "load_cases", counting_load)
    first = svc.list_cases(path=str(case))
    assert [c["name"] for c in first] == ["mini"]
    assert calls == [case]

    # 二次收集换入口（validate_run，strict）——同一文件命中缓存，不再解析
    svc.validate_run(paths=[str(case)], tags=[])
    assert calls == [case]

    # mtime 变化 → 缓存失效重解析（utime 显式 +5s，避开文件系统时间戳粒度）
    old_mtime = case.stat().st_mtime
    case.write_text(MINIMAL_CASE.replace("name: mini", "name: edited"), encoding="utf-8")
    os.utime(case, (old_mtime + 5, old_mtime + 5))
    second = svc.list_cases(path=str(case))
    assert [c["name"] for c in second] == ["edited"]
    assert calls == [case, case]


# ---------------------------------------------------------------------------
# S-3 路径白名单 + S-8 锚集扩展（批 4 T2，设计 §5/§7）
# ---------------------------------------------------------------------------
def test_allowed_roots_default_and_config(tmp_path):
    """_allowed_roots：默认仅 cases_dir；mcp.allowed_roots 追加且 cases_dir 恒在；
    重复项按 normcase 去重（复用 datasource.data_roots 口径）."""
    cfg = _app_cfg(tmp_path)
    svc = McpService(cfg, vsim=True)
    cases_dir = resolve_workspace_path(cfg.cases_dir)
    assert svc._allowed_roots() == [cases_dir]

    extra = tmp_path / "shared"
    cfg2 = replace(cfg, mcp_allowed_roots=(str(extra), str(cases_dir)))
    svc2 = McpService(cfg2, vsim=True)
    # 非空配置追加，cases_dir 恒在首；与 cases_dir 重复的额外根被去重
    assert svc2._allowed_roots() == [cases_dir, extra.resolve()]


def test_explicit_path_outside_whitelist_invalid_input(tmp_path):
    """显式 path 越出白名单 → INVALID_INPUT（文案含白名单列表）；四个入口一致."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    inside = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    assert [c["name"] for c in svc.list_cases(path=str(inside))] == ["mini"]

    outside = _write_case(tmp_path / "outside", "evil", MINIMAL_CASE)
    for call in (
        lambda: svc.list_cases(path=str(outside)),
        lambda: svc.validate_run(paths=[str(outside)], tags=[]),
        lambda: svc.list_suites(path=str(outside)),
        lambda: svc.start_run(paths=[str(outside)]),
    ):
        with pytest.raises(McpError) as ei:
            call()
        assert ei.value.kind == "INVALID_INPUT"
        assert "路径超出允许范围" in ei.value.message
        assert "白名单" in ei.value.message


def test_allowed_roots_config_extends_whitelist(tmp_path):
    """mcp.allowed_roots 配置生效：额外根内的路径可用；其余越界路径仍拒."""
    extra = tmp_path / "shared"
    case = _write_case(extra, "shared_case", MINIMAL_CASE)
    cfg = _app_cfg(tmp_path, mcp_allowed_roots=(str(extra),))
    svc = McpService(cfg, vsim=True)
    assert [c["name"] for c in svc.list_cases(path=str(case))] == ["mini"]

    outside = _write_case(tmp_path / "outside", "evil", MINIMAL_CASE)
    with pytest.raises(McpError) as ei:
        svc.list_cases(path=str(outside))
    assert ei.value.kind == "INVALID_INPUT"
    assert "路径超出允许范围" in ei.value.message


def test_server_info_contains_allowed_roots(tmp_path):
    """server_info.paths.allowed_roots 上报白名单（编码机可发现可用根）."""
    cfg = _app_cfg(tmp_path, mcp_allowed_roots=(str(tmp_path / "shared"),))
    svc = McpService(cfg, vsim=True)
    roots = svc.server_info()["paths"]["allowed_roots"]
    assert [Path(r) for r in roots] == [
        resolve_workspace_path(cfg.cases_dir),
        (tmp_path / "shared").resolve(),
    ]


def test_list_suites_missing_path_invalid_input(tmp_path):
    """list_suites 显式 path 不存在 → INVALID_INPUT（统一预检，批 3 终审⑨）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    with pytest.raises(McpError) as ei:
        svc.list_suites(path=str(tmp_path / "nope"))
    assert ei.value.kind == "INVALID_INPUT"
    assert "路径不存在" in ei.value.message


def test_list_suites_default_scans_cases_dir(tmp_path):
    """list_suites 缺省 path：锚定解析后的 cases_dir 扫描."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    cases_dir = tmp_path / "cases"
    (cases_dir).mkdir(parents=True, exist_ok=True)
    (cases_dir / "suite-x.yaml").write_text("name: x\ncases: []\n", encoding="utf-8")
    suites = svc.list_suites()
    assert [s["file"] for s in suites] == [str(cases_dir / "suite-x.yaml")]


def test_list_suites_deep_level_excluded(tmp_path):
    """批 5 T8（批 4 终审预备⑥）：list_suites 受限遍历与 list_cases 对称——
    深层（>4 层）suite 文件不被列出（旧 rglob 无界，两者不对称）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    cases_dir = tmp_path / "cases"
    d = cases_dir
    for i in range(1, 6):
        d = d / f"l{i}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"case{i}.yaml").write_text(MINIMAL_CASE, encoding="utf-8")
        (d / f"suite-{i}.yaml").write_text("name: s\ncases: []\n", encoding="utf-8")
    # 对称性双向钉住：1-4 层照收，第 5 层两者都不收
    assert len(svc.list_suites(path=str(cases_dir))) == 4
    assert len(svc.list_cases(path=str(cases_dir))) == 4


def test_case_cache_concurrent_smoke(tmp_path):
    """批 5 T1 并发冒烟：线程池并发 list_cases（文件数>512 强制走缓存淘汰）
    不抛 RuntimeError（旧实现 next(iter(dict)) 与并发写入交错可
    「字典迭代期间改变大小」）。"""
    from concurrent.futures import ThreadPoolExecutor

    svc = McpService(_app_cfg(tmp_path), vsim=True)
    cases_dir = tmp_path / "cases"
    for i in range(_CASE_CACHE_MAX + 8):  # 超过 512 封顶 → 必然触发淘汰路径
        _write_case(cases_dir, f"c{i:03d}", MINIMAL_CASE.replace("name: mini", f"name: c{i:03d}"))
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: svc.list_cases(path=str(cases_dir)), range(24)))
    assert all(len(r) == _CASE_CACHE_MAX + 8 for r in results)
    assert len(svc._case_cache) <= _CASE_CACHE_MAX  # 封顶不超限


def test_collect_cache_suite_reference_invalidation(tmp_path):
    """批 3 终审②：显式 suite 输入的缓存键级联被引用用例的 mtime——编辑
    被引用用例文件（suite 自身 mtime 不变）→ 缓存失效重解析（修复陈旧结果）。"""
    d = tmp_path / "cases"
    case = _write_case(d, "mini", MINIMAL_CASE)
    suite = d / "suite-all.yaml"
    suite.write_text("name: 全\ncases:\n  - mini.yaml\n", encoding="utf-8")
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    assert [c["name"] for c in svc.list_cases(path=str(suite))] == ["mini"]
    # 编辑被引用用例：case mtime 显式 +5s（避开文件系统时间戳粒度），suite 不动
    old = case.stat().st_mtime
    suite_mtime = suite.stat().st_mtime
    case.write_text(MINIMAL_CASE.replace("name: mini", "name: edited"), encoding="utf-8")
    os.utime(case, (old + 5, old + 5))
    assert suite.stat().st_mtime == suite_mtime  # 前置：suite 自身未变
    assert [c["name"] for c in svc.list_cases(path=str(suite))] == ["edited"]


def test_start_run_data_allowed_roots_from_whitelist(tmp_path, monkeypatch):
    """S-8 锚集扩展：start_run 的 EngineConfig.data_allowed_roots=S-3 白名单."""
    extra = tmp_path / "shared"
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    cfg = _app_cfg(tmp_path, mcp_allowed_roots=(str(extra),))
    svc = McpService(cfg, vsim=True)
    captured: dict[str, EngineConfig] = {}

    def fake_start(*, build_engine_cfg, sender_factory):  # noqa: ANN001, ANN002, ANN003
        captured["cfg"] = build_engine_cfg("job_s8")
        return "job_s8"

    monkeypatch.setattr(svc.jobs, "start", fake_start)
    assert svc.start_run(paths=[str(case)])["job_id"] == "job_s8"
    roots = [Path(p) for p in captured["cfg"].data_allowed_roots]
    assert roots == [resolve_workspace_path(cfg.cases_dir), extra.resolve()]


def test_start_run_data_file_in_extra_root(tmp_path):
    """S-8 端到端（vsim）：data.file 在 allowed_roots 内、case_dir 外 → 通过.

    两阶段 TCPSEND 形态（同 examples N58 tcp）：阶段一 {{file_size()}} 渲染
    （同锚集校验），阶段二 data.file 读额外根内文件——批 2b 预留点兑现后
    此类用例从 DataPathError 失败转为真实发送。
    """
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "p.bin").write_bytes(b"HELLO")  # 5 字节
    case = _write_case(
        tmp_path / "cases",
        "s8bin",
        "name: s8bin\n"
        "steps:\n"
        "  - command: 'AT+TCPSEND=0,{{file_size(\"../payloads/p.bin\")}}'\n"
        "    expect: '(\\r\\n>)'\n"
        "  - data: { file: ../payloads/p.bin }\n"
        "    wait_urc: '\\+TCPSEND: \\d+,\\d+'\n"
        "    assert: [{ matches: '\\+TCPSEND: 0,5' }]\n",
    )
    cfg = _app_cfg(tmp_path, mcp_allowed_roots=(str(payload_dir),))
    svc = McpService(cfg, vsim=True)
    job_id = svc.start_run(paths=[str(case)])["job_id"]
    snap = _wait_finished(svc, job_id)
    assert snap["status"] == "finished"
    assert snap["summary"]["passed"] == 1
    assert snap["summary"]["failed"] == 0

    # 反证锚集仍收紧：去掉 allowed_roots 后同一用例因 data 越界失败（S-8 生效）
    svc2 = McpService(_app_cfg(tmp_path), vsim=True)
    job2 = svc2.start_run(paths=[str(case)])["job_id"]
    snap2 = _wait_finished(svc2, job2)
    assert snap2["status"] == "finished"
    assert snap2["summary"]["failed"] == 1


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


def test_send_at_invalid_wait_urc(tmp_path):
    """wait_urc 非法正则 → INVALID_INPUT（服务层预校验；vsim 不校验也被拦）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    with pytest.raises(McpError) as ei:
        svc.send_at(VSIM_PORT, "AT", wait_urc="([unclosed")
    assert ei.value.kind == "INVALID_INPUT"
    assert "wait_urc" in ei.value.message


def test_send_at_invalid_argument_translated(tmp_path, monkeypatch):
    """连接层 InvalidArgumentError（SerialError 子类）→ INVALID_INPUT 而非 DEVICE_ERROR."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)

    def fake_send_command(port, command, **kwargs):
        raise InvalidArgumentError(f"[{port}] wait_urc 正则无效：boom")

    monkeypatch.setattr(svc.port_manager, "send_command", fake_send_command)
    with pytest.raises(McpError) as ei:
        svc.send_at(VSIM_PORT, "AT")
    assert ei.value.kind == "INVALID_INPUT"
    assert "参数错误" in ei.value.message


def test_send_at_port_busy_translated_to_busy(tmp_path, monkeypatch):
    """PortBusyError（撞端口命令锁）→ BUSY 而非 DEVICE_ERROR（批 3 终审①）.

    旧实现落入宽 catch (SerialError, OSError) → DEVICE_ERROR——编码机会把
    「稍后重试」误判为「设备异常」。转 BUSY 且 detail 携带冲突端口。
    """
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)

    def fake_send_command(port, command, **kwargs):
        raise PortBusyError(port, "端口正忙：并发发送不支持")

    monkeypatch.setattr(svc.port_manager, "send_command", fake_send_command)
    with pytest.raises(McpError) as ei:
        svc.send_at(VSIM_PORT, "AT")
    assert ei.value.kind == "BUSY"
    assert "端口被占用" in ei.value.message
    assert ei.value.detail.get("port") == VSIM_PORT


def test_send_at_busy_recheck_inside_pre_check(tmp_path, monkeypatch):
    """TOCTOU 收口（设计 §3.2）：BUSY 检查经 pre_check 在连接命令锁内执行.

    锁外不再预查（检查与发送间作业可启动）；pre_check 抛的 McpError 非
    SerialError/OSError 子类——穿透 PortManager（无兜底 except）与 send_at
    的 except 链直达调用方。模拟：进入 send_at 时无 running、到达连接层
    （pre_check）时作业已启动 → BUSY 且携带 job_id。
    """
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    monkeypatch.setattr(svc.jobs, "running_job_id", lambda: "job_window")
    seen: dict[str, object] = {}

    def fake_send_command(port, command, **kwargs):
        seen["pre_check"] = kwargs.get("pre_check")
        assert callable(kwargs["pre_check"])
        kwargs["pre_check"]()  # 连接层契约：命令锁内、发送前调用
        raise AssertionError("pre_check 未拦截，不应走到发送")

    monkeypatch.setattr(svc.port_manager, "send_command", fake_send_command)
    with pytest.raises(McpError) as ei:
        svc.send_at(VSIM_PORT, "AT")
    assert ei.value.kind == "BUSY"
    assert ei.value.detail.get("job_id") == "job_window"
    assert callable(seen["pre_check"])  # 占用检查确实传到了连接层（锁内重检）


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
    empty = tmp_path / "cases" / "empty"  # cases_dir 子目录（白名单内）→ 走"无用例"分支
    empty.mkdir(parents=True)
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
    # 本次作业的日志目录（get_job 直接给路径，不必从 server_info 根目录拼）：
    # 共享 PM 注入 RawLogger → 用例原始日志真实落盘于 log_dir/<job_id>/<端口>/
    log_dir = Path(snap["log_dir"])
    assert log_dir == tmp_path / "logs" / job_id
    assert (log_dir / VSIM_PORT / "mini.text.log").is_file()

    # 互斥解除：作业结束（引擎关闭了自己打开的端口）→ 重开后手动通道恢复
    svc.open_port(VSIM_EXPR)
    assert "OK" in svc.send_at(VSIM_PORT, "AT")["text"]
    # 已结束的 job cancel → False（幂等）
    assert svc.cancel_job(job_id) == {"cancelled": False}


def test_send_at_busy_during_job(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True, report_root=tmp_path / "reports")
    many = tmp_path / "cases" / "many"
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
    bad = _write_case(tmp_path / "cases" / "bad", "bad", "name: [unclosed")
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


def test_start_run_bad_env_config(tmp_path):
    """坏 env.yaml（YAML 语法错误）→ start_run INVALID_INPUT（EnvConfigError 转译）."""
    bad_env = tmp_path / "bad_env.yaml"
    bad_env.write_text("not: [valid", encoding="utf-8")
    svc = McpService(_app_cfg(tmp_path, env_config=str(bad_env)), vsim=True)
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    with pytest.raises(McpError) as ei:
        svc.start_run(paths=[str(case)])
    assert ei.value.kind == "INVALID_INPUT"


def test_resolve_run_inputs_urc_filter_injection(tmp_path):
    """urc_filter 注入：真实串口分支注入配置元组，vsim 分支跳过（对齐 run.py）."""
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    cfg = _app_cfg(tmp_path, ports=(), urc_filter=("^\\$X:",))
    inputs = {"paths": [str(case)], "ports": ["COM3:115200:8N1"], "tags": []}

    real = McpService(cfg, vsim=False)
    port_configs, *_ = real._resolve_run_inputs(**inputs)
    assert port_configs[0].urc_filter == ("^\\$X:",)

    # vsim=True 同输入：注入跳过（PortConfig 默认空元组）
    vsim = McpService(cfg, vsim=True)
    port_configs_v, *_ = vsim._resolve_run_inputs(**inputs)
    assert port_configs_v[0].urc_filter == ()


def test_get_job_unknown(tmp_path):
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    with pytest.raises(McpError) as ei:
        svc.get_job("nope")
    assert ei.value.kind == "NOT_FOUND"


# ---------------------------------------------------------------------------
# 原始日志（M8 修复：共享 PM 模式下作业/手动通道此前不落盘）
# ---------------------------------------------------------------------------
def _drain(svc: McpService) -> None:
    """测试收尾：stop RawLogger 确保异步队列落盘（实例生命周期结束）."""
    svc._raw_logger.stop()  # noqa: SLF001


def test_start_run_writes_raw_log(tmp_path):
    """作业日志：start_run 的用例收发落 logs/<job_id>/<端口>/<用例名>.text.log（与 CLI 同款）."""
    case = _write_case(tmp_path / "cases", "joblog", MINIMAL_CASE)
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    job_id = svc.start_run(paths=[str(case)])["job_id"]
    snap = _wait_finished(svc, job_id)
    assert snap["status"] == "finished"
    assert snap["summary"]["passed"] == 1
    _drain(svc)

    # 日志文件名按用例名（MINIMAL_CASE 的 name: mini），非用例文件名
    text_log = tmp_path / "logs" / job_id / VSIM_PORT / "mini.text.log"
    assert text_log.exists(), f"作业原始日志未生成: {text_log}"
    content = text_log.read_text(encoding="utf-8")
    assert "[TX] AT" in content
    assert "[RX]" in content and "OK" in content
    hex_log = tmp_path / "logs" / job_id / VSIM_PORT / "mini.hex.log"
    assert "41 54 0D 0A" in hex_log.read_text(encoding="utf-8")


def test_manual_channel_raw_log(tmp_path):
    """手动通道日志：open_port 后 send_at 的原始字节流落 manual 会话日志."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    resp = svc.send_at(VSIM_PORT, "AT")
    assert "OK" in resp["text"]
    _drain(svc)

    sessions = list((tmp_path / "logs").glob("manual_*"))
    assert len(sessions) == 1, "应恰好一个 manual 会话目录"
    text_log = sessions[0] / VSIM_PORT / "manual.text.log"
    assert text_log.exists()
    content = text_log.read_text(encoding="utf-8")
    assert "[TX] AT" in content
    assert "[RX]" in content and "OK" in content


def test_manual_log_detached_on_close(tmp_path):
    """close_port 拆除手动日志 observer：之后的底层写不再进入 manual 日志."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    svc.send_at(VSIM_PORT, "AT")
    svc.close_port(VSIM_PORT)
    # 直接驱动底层 TX 路径（observer 应已拆除，不产生新日志行）
    svc.port_manager.write_command(VSIM_PORT, "AT+CSQ")
    _drain(svc)

    sessions = list((tmp_path / "logs").glob("manual_*"))
    content = (sessions[0] / VSIM_PORT / "manual.text.log").read_text(encoding="utf-8")
    assert "AT+CSQ" not in content
    assert "[TX] AT" in content  # close 前的记录仍在


def test_manual_log_reopen_appends_same_session(tmp_path):
    """close 后重开同端口：追加同一 manual 会话（进程生命周期一个手动会话）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    svc.send_at(VSIM_PORT, "AT")
    svc.close_port(VSIM_PORT)
    svc.open_port(VSIM_EXPR)
    svc.send_at(VSIM_PORT, "AT+CSQ")
    _drain(svc)

    sessions = list((tmp_path / "logs").glob("manual_*"))
    assert len(sessions) == 1
    content = (sessions[0] / VSIM_PORT / "manual.text.log").read_text(encoding="utf-8")
    assert "[TX] AT" in content
    assert "[TX] AT+CSQ" in content


def test_job_end_clears_case_log_binding(tmp_path):
    """C1 回归：作业结束后用例日志绑定被清除——手动 send_at 不再污染最后用例日志.

    场景：手动 open_port（外部连接，scheduler 复用不关闭）→ start_run 复用该
    端口 → 作业结束。旧实现引擎不清 _log_files，共享 PM 常驻 RawLogger 下
    手动 send_at 的流量会追加进最后一个用例的日志文件。
    """
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    svc.open_port(VSIM_EXPR)  # 外部手动开的端口：作业结束后仍连着
    job_id = svc.start_run(paths=[str(case)])["job_id"]
    snap = _wait_finished(svc, job_id)
    assert snap["status"] == "finished"

    # 作业结束后手动发送；send_at 同步返回，stop logger 时排空队列落盘
    svc.send_at(VSIM_PORT, "AT+CSQ")
    _drain(svc)

    # 用例日志：作业流量在，作业后的手动流量不在（绑定已被 start finally 清除）
    case_log = tmp_path / "logs" / job_id / VSIM_PORT / "mini.text.log"
    content = case_log.read_text(encoding="utf-8")
    assert "[TX] AT" in content  # 作业期间的用例流量仍完整
    assert "AT+CSQ" not in content  # 手动流量未泄漏进用例日志

    # 手动通道日志正常记录（同一发送双视角，manual 会话不受影响）
    sessions = list((tmp_path / "logs").glob("manual_*"))
    manual = (sessions[0] / VSIM_PORT / "manual.text.log").read_text(encoding="utf-8")
    assert "[TX] AT+CSQ" in manual


def test_job_traffic_also_in_manual_log(tmp_path):
    """双视角设计钉进测试：作业流量也进 manual 日志（手动开的端口 observer 全程生效）.

    手动 open_port 挂的 rx/tx observer 在作业期间持续派发——manual 会话记录
    引擎执行流量（含噪声的完整字节流），与用例级日志（按用例分文件）互补。
    """
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    case = _write_case(tmp_path / "cases", "mini", MINIMAL_CASE)
    svc.open_port(VSIM_EXPR)
    job_id = svc.start_run(paths=[str(case)])["job_id"]
    snap = _wait_finished(svc, job_id)
    assert snap["status"] == "finished"
    _drain(svc)

    sessions = list((tmp_path / "logs").glob("manual_*"))
    assert len(sessions) == 1
    manual = (sessions[0] / VSIM_PORT / "manual.text.log").read_text(encoding="utf-8")
    assert "[TX] AT" in manual  # 作业期间的引擎流量也进 manual 会话
    # 用例级日志同样完整（两条通道各自成篇，互不替代）
    assert (tmp_path / "logs" / job_id / VSIM_PORT / "mini.text.log").exists()


def test_send_at_wait_urc_redos_rejected(tmp_path):
    """批 4 终审 Important：send_at 的 wait_urc 嵌套量词硬拒（对齐 urcbuffer/模型层）."""
    svc = McpService(_app_cfg(tmp_path), vsim=True)
    svc.open_port(VSIM_EXPR)
    with pytest.raises(McpError) as ei:
        svc.send_at(VSIM_PORT, "AT", wait_urc=r"(a+)+$")
    assert ei.value.kind == "INVALID_INPUT"
    assert "灾难性回溯" in str(ei.value)
    # 合法 wait_urc 不受影响
    resp = svc.send_at(VSIM_PORT, "AT", wait_urc=r"\+CSQ: \d+")
    assert resp["status"] == "complete"
