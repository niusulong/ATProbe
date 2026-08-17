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
    """构建 MCPServer 并注册 14 个工具."""
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


def build_http_app(service: McpService, token: str, host: str = "127.0.0.1") -> Any:
    """HTTP serve 的 ASGI 应用：Bearer 中间件 + Streamable HTTP（装配唯一路径）.

    host 透传 streamable_http_app（SDK 语义）：host 为回环地址时 SDK 自动启用
    DNS rebinding 防护（仅放行 localhost 系 Host 头，远程访问会 421）；host 为
    非回环（如远程部署的 0.0.0.0）时按 SDK 设计不启用——此时安全层为 Bearer
    Token。run_serve 与集成测试共用本函数，保证测试覆盖生产装配路径。
    """
    from atprobe.mcp.auth import bearer_middleware

    return bearer_middleware(build_server(service).streamable_http_app(host=host), token)


def run_serve(service: McpService, host: str, port: int, token: str) -> int:
    """HTTP 形态：ASGI Bearer 中间件 + uvicorn（mcp 传递依赖，无需新增）."""
    import uvicorn

    app = build_http_app(service, token, host)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0
