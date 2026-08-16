"""M8 服务装配：构建 MCPServer 与两种传输（stdio / HTTP serve）.

传输细节全部收敛在本文件（SDK 升级只改这里，TSD §11）。
mcp/uvicorn 均为可选依赖（--extra mcp），全部延迟 import——本模块自身
可在未装 MCP 依赖的环境下被 import（CLI 层只在其内部延迟引用）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from atprobe.mcp.service import McpService
from atprobe.mcp.tools import INSTRUCTIONS, register

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def build_server(service: McpService) -> MCPServer[Any]:
    """构建 MCPServer 并注册 13 个工具."""
    from mcp.server.mcpserver import MCPServer

    server: MCPServer[Any] = MCPServer("atprobe", instructions=INSTRUCTIONS)
    register(server, service)
    return server


def run_stdio(service: McpService) -> int:
    """本地 stdio 形态：stdout 被协议独占，禁止任何 stdout 输出.

    日志由 SDK 经 anyio stdio 服务器接管（stderr 通道）；本函数自身
    不打印任何东西，返回码恒 0（Ctrl+C 等中断按 KeyboardInterrupt 传播）。
    """
    build_server(service).run()  # transport 默认 stdio
    return 0


def run_serve(service: McpService, host: str, port: int, token: str) -> int:
    """HTTP 形态：ASGI Bearer 中间件 + uvicorn（mcp 传递依赖，无需新增）."""
    import uvicorn

    from atprobe.mcp.auth import bearer_middleware

    app = bearer_middleware(build_server(service).streamable_http_app(), token)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0
