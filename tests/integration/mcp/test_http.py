"""HTTP serve 集成测试：进程内 uvicorn + Streamable HTTP + Bearer Token 全链路.

零 mock：真实 ASGI 栈（build_server → streamable_http_app → bearer_middleware
→ uvicorn 线程）+ mcp SDK 客户端（streamable_http_client + ClientSession），
端口管理为进程内 vsim 虚拟模组，不依赖真实串口。覆盖（M8 Task 8）：

1. 认证：正确 Token 走通手动调试主路径（list_tools 13 个 → open_port →
   send_at → URC 订阅/轮询/退订 → close_port）；错误 Token 中间件 401
   （裸 HTTP 直测契约）+ SDK 客户端初始化即失败（异常类型不钉死）。
2. 批量作业全链路：start_run → 运行中 send_at 被 BUSY 拒 → 轮询 get_job
   至 finished（summary/report_path 落盘）→ 互斥解除后手动通道恢复。
3. 错误通道：get_job 未知 id → is_error=True + kind=NOT_FOUND；send_at
   未开端口 → INVALID_INPUT（结构化 JSON，从首个 ``{`` 起解析剥 SDK 前缀）。

服务与临时目录（cases/reports/logs）模块级共享：BUSY 语义本身是被测对象，
测试按文件内定义顺序串行，跨测试共享无冲突。
"""

from __future__ import annotations

import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from atprobe.infra.config.appconfig import AppConfig
from atprobe.infra.serial.vsim import VSIM_PORT
from atprobe.mcp.auth import bearer_middleware
from atprobe.mcp.server import build_server
from atprobe.mcp.service import McpService
from conftest import make_case_yaml, payload, wait_finished

pytestmark = pytest.mark.anyio

TOKEN = "it-bearer-token"
HTTP_PORT = 18942  # 固定高位端口：被占即环境问题，不递增
BASE_URL = f"http://127.0.0.1:{HTTP_PORT}/mcp"
VSIM_EXPR = f"{VSIM_PORT}:115200:8N1"

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


@asynccontextmanager
async def _session(base_url: str, token: str = TOKEN) -> AsyncIterator[ClientSession]:
    """带 Bearer Token 的已初始化客户端会话（http_client 由本方持有并关闭）."""
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        async with streamable_http_client(base_url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


@pytest.fixture(scope="module")
def many_case_paths(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    """100 个最小用例：保证 start_run 返回后作业可观测地运行（BUSY 断言窗口）."""
    d = tmp_path_factory.mktemp("cases")
    for i in range(100):
        make_case_yaml(d, f"it{i:02d}")
    return sorted(d.glob("*.yaml"))


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """进程内起 serve 形态：vsim 服务 + Bearer 中间件 + uvicorn 线程.

    用例/报告/日志目录全部锚定临时目录（绝对路径，report_path 可直接断言存在）。
    """
    tmp = tmp_path_factory.mktemp("mcp_http")
    app_cfg = AppConfig(
        cases_dir=str(tmp / "cases"),
        report_dir=str(tmp / "reports"),
        log_dir=str(tmp / "logs"),
        env_config=str(tmp / "noenv.yaml"),
    )
    service = McpService(app_cfg, vsim=True, report_root=tmp / "reports")
    app = bearer_middleware(build_server(service).streamable_http_app(), TOKEN)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=HTTP_PORT, log_level="error")
    )
    thread = threading.Thread(target=server.run, name="atprobe-it-uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15.0
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            server.should_exit = True
            raise RuntimeError(f"uvicorn 未在超时内启动（端口 {HTTP_PORT} 被占用？）")
        time.sleep(0.05)
    yield BASE_URL
    server.should_exit = True
    thread.join(timeout=15.0)
    if thread.is_alive():
        raise RuntimeError("uvicorn 线程未在 15s 内退出")


async def test_http_auth_and_manual_tools(base_url: str) -> None:
    # 错误 Token 之中间件契约：裸 HTTP 直测（401 + JSON 体，确定性断言）
    async with httpx2.AsyncClient() as raw:
        resp = await raw.get(base_url, headers={"Authorization": f"Bearer {TOKEN}wrong"})
        assert resp.status_code == 401
        assert resp.json() == {"error": "unauthorized"}
    # 错误 Token 之 SDK 客户端：401 表现为传输层异常（类型不钉死，非 is_error 语义）
    with pytest.raises(Exception):  # noqa: B017 - 传输层异常类型随 SDK 版本变化
        async with _session(base_url, token="wrong-token") as session:
            await session.list_tools()

    # 正确 Token：手动调试主路径
    async with _session(base_url) as session:
        listing = await session.list_tools()
        assert {t.name for t in listing.tools} == EXPECTED_TOOLS

        res = await session.call_tool("open_port", {"port_expr": VSIM_EXPR})
        assert res.is_error is not True
        assert payload(res)["name"] == VSIM_PORT

        res = await session.call_tool(
            "send_at", {"port": VSIM_PORT, "command": "AT", "timeout": 5.0}
        )
        assert res.is_error is not True
        assert "OK" in payload(res)["text"]

        res = await session.call_tool("subscribe_urc", {"port": VSIM_PORT})
        sub_id = payload(res)["subscription_id"]

        # vsim 默认不主动上报 → 空页（游标语义正常）
        res = await session.call_tool("poll_urc", {"subscription_id": sub_id})
        assert payload(res)["events"] == []

        res = await session.call_tool("unsubscribe_urc", {"subscription_id": sub_id})
        assert payload(res) == {"unsubscribed": True}

        res = await session.call_tool("close_port", {"port": VSIM_PORT})
        assert payload(res) == {"closed": True, "port": VSIM_PORT}


async def test_http_run_job_full_flow(base_url: str, many_case_paths: list[Path]) -> None:
    async with _session(base_url) as session:
        # 手动打开的端口：scheduler 只关闭自己新开的端口 → 作业后 send_at 无需重开
        await session.call_tool("open_port", {"port_expr": VSIM_EXPR})
        res = await session.call_tool("start_run", {"paths": [str(p) for p in many_case_paths]})
        job_id = payload(res)["job_id"]

        # BUSY 互斥：作业运行期间手动发送被拒（kind 枚举判定，detail 携带占用作业 id）
        busy = await session.call_tool("send_at", {"port": VSIM_PORT, "command": "AT"})
        assert busy.is_error is True
        data = payload(busy)
        assert data["kind"] == "BUSY"
        assert data["detail"]["job_id"] == job_id

        snap = await wait_finished(session, job_id)
        assert snap["status"] == "finished"
        assert snap["summary"]["passed"] == len(many_case_paths)
        assert snap["summary"]["failed"] == 0
        assert snap["report_path"]
        assert Path(snap["report_path"]).exists()

        # 互斥解除：作业结束后手动通道立即恢复
        res = await session.call_tool("send_at", {"port": VSIM_PORT, "command": "AT"})
        assert res.is_error is not True
        assert "OK" in payload(res)["text"]


async def test_http_error_channel(base_url: str) -> None:
    async with _session(base_url) as session:
        # get_job 未知 id → is_error=True + 结构化 JSON（kind 枚举判定，非文案匹配）
        res = await session.call_tool("get_job", {"job_id": "no-such-job"})
        assert res.is_error is True
        data = payload(res)
        assert data["kind"] == "NOT_FOUND"
        assert data["detail"]["job_id"] == "no-such-job"

        # send_at 端口未开（用从未打开的端口名，与其他测试顺序无关）→ INVALID_INPUT
        res = await session.call_tool("send_at", {"port": "VSIM_NEVER_OPENED", "command": "AT"})
        assert res.is_error is True
        assert payload(res)["kind"] == "INVALID_INPUT"
