"""tools.register 进程内验证：14 工具注册、inputSchema、JSON 出参与结构化错误.

SDK 行为实测（mcp 2.0.0）：进程内 ``server.call_tool`` 对工具错误直接抛
ToolError；``is_error=True`` 的转换发生在 lowlevel ``_handle_call_tool``（仅
真实传输路径生效）——线上行为由 Task 8 集成测试经真实 transport 验证。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from atprobe.infra.config.appconfig import AppConfig
from atprobe.infra.serial.vsim import VSIM_PORT
from atprobe.mcp.service import McpService
from atprobe.mcp.tools import INSTRUCTIONS, _wrap, register

EXPECTED_TOOLS = {
    "server_info",
    "list_ports",
    "list_cases",
    "list_suites",
    "validate_run",
    "start_run",
    "get_job",
    "cancel_job",
    "open_port",
    "close_port",
    "send_at",
    "subscribe_urc",
    "poll_urc",
    "unsubscribe_urc",
}


def _app_cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        cases_dir=str(tmp_path / "cases"),
        report_dir=str(tmp_path / "reports"),
        log_dir=str(tmp_path / "logs"),
        env_config=str(tmp_path / "noenv.yaml"),
    )


@pytest.fixture
def server(tmp_path: Path) -> MCPServer:  # type: ignore[no-any-unimported]
    srv = MCPServer(name="atprobe-test", instructions=INSTRUCTIONS)
    register(srv, McpService(_app_cfg(tmp_path), vsim=True, report_root=tmp_path / "reports"))
    return srv


@pytest.mark.anyio
async def test_register_13_tools_with_schema(server):  # type: ignore[no-untyped-def]
    tools = await server.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    # 每个工具都有中文描述（LLM 可见的工具说明）
    assert all(t.name and t.description for t in tools)
    # structured_output=False：无 output_schema，出参为纯 JSON 文本
    assert all(t.output_schema is None for t in tools)
    # schema 抽查：send_at 必填 port/command，可选 timeout/wait_urc
    send_at = next(t for t in tools if t.name == "send_at")
    assert set(send_at.input_schema["properties"]) == {"port", "command", "timeout", "wait_urc"}
    assert set(send_at.input_schema["required"]) == {"port", "command"}
    poll = next(t for t in tools if t.name == "poll_urc")
    assert poll.input_schema["properties"]["limit"]["default"] == 100


@pytest.mark.anyio
async def test_call_tool_ok_returns_json_text(server):  # type: ignore[no-untyped-def]
    result = await server.call_tool("open_port", {"port_expr": f"{VSIM_PORT}:115200:8N1"})
    assert result.is_error is not True
    assert result.structured_content is None
    payload = json.loads(result.content[0].text)
    assert payload["name"] == VSIM_PORT
    assert payload["frame"] == "8N1"

    resp = await server.call_tool("send_at", {"port": VSIM_PORT, "command": "AT", "timeout": 2.0})
    assert "OK" in json.loads(resp.content[0].text)["text"]


@pytest.mark.anyio
async def test_server_info_paths(tmp_path: Path):  # type: ignore[no-untyped-def]
    """server_info：工作区/用例/日志/报告的绝对路径（编码机配合文件传输工具用）.

    相对配置 → 锚定 user_workspace() 后的绝对路径；vsim 标志如实上报。
    """
    from atprobe.mcp.service import McpService

    svc = McpService(_app_cfg(tmp_path), vsim=True, report_root=tmp_path / "reports")
    info = svc.server_info()

    assert info["vsim"] is True
    assert Path(info["workspace"]).is_absolute()
    # _app_cfg 的三个目录都是 tmp 绝对路径（resolve_workspace_path 原样返回）
    assert Path(info["paths"]["cases_dir"]) == tmp_path / "cases"
    assert Path(info["paths"]["log_dir"]) == tmp_path / "logs"
    assert Path(info["paths"]["report_dir"]) == tmp_path / "reports"
    assert isinstance(info["version"], str) and info["version"]


@pytest.mark.anyio
async def test_server_info_relative_anchored(tmp_path: Path):  # type: ignore[no-untyped-def]
    """相对路径配置 → 锚定到工作区根的绝对路径（与 CLI/GUI 同一解析规则）."""
    from dataclasses import replace

    from atprobe.mcp.service import McpService

    cfg = replace(_app_cfg(tmp_path), cases_dir="cases", log_dir="logs")
    svc = McpService(cfg, vsim=False, report_root=tmp_path / "reports")
    info = svc.server_info()

    assert info["vsim"] is False
    from atprobe.infra.resources import user_workspace

    assert Path(info["paths"]["cases_dir"]) == user_workspace() / "cases"
    assert Path(info["paths"]["log_dir"]) == user_workspace() / "logs"


@pytest.mark.anyio
async def test_server_info_report_dir_follows_report_root(tmp_path: Path):  # type: ignore[no-untyped-def]
    """report_dir 上报 JobManager 实际根目录（构造 report_root 优先于 app_cfg.report_dir）.

    M3 修复：旧实现报 app_cfg.report_dir 的解析值——report_root 注入到别处
    （自定义部署/独立锚点）时，编码机按 server_info 指引去取报告会扑空。
    """
    from atprobe.mcp.service import McpService

    svc = McpService(_app_cfg(tmp_path), vsim=True, report_root=tmp_path / "custom_reports")
    info = svc.server_info()

    assert Path(info["paths"]["report_dir"]) == tmp_path / "custom_reports"


@pytest.mark.anyio
async def test_call_tool_error_structured_json(server):  # type: ignore[no-untyped-def]
    with pytest.raises(ToolError) as ei:
        await server.call_tool("send_at", {"port": "NOPE", "command": "AT"})
    text = str(ei.value)
    payload = json.loads(text[text.index("{") :])
    assert payload["kind"] == "INVALID_INPUT"
    assert payload["detail"] == {"port": "NOPE"}


def test_wrap_internal_fallback():
    """非 McpError 逃逸 → 同构 INTERNAL 结构化 JSON ToolError（errors.py INTERNAL 枚举的生产者）.

    直接调 _wrap 包装后的函数（不经 SDK call_tool）：ToolError 消息即纯 JSON，
    无 ``"Error executing tool <name>: "`` 前缀（该前缀由 Tool.run 添加）。
    """

    @_wrap
    def boom() -> dict[str, str]:
        raise ValueError("意外逃逸")

    with pytest.raises(ToolError) as ei:
        boom()
    payload = json.loads(str(ei.value))
    assert payload["kind"] == "INTERNAL"
    assert "ValueError" in payload["message"]
    assert payload["detail"] == {}
