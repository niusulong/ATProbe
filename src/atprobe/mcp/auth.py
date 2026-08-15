"""M8 Bearer Token 认证：加载（四级优先级）+ 纯 ASGI 中间件（常量时间比较）.

Token 来源优先级（设计 §7.1）：--token-file > --token > 环境变量 ATPROBE_MCP_TOKEN
（第四级「配置 mcp.token_file」由 CLI 层在调用 load_token 前合并进 token_file 参数，
本模块不重复实现）。Token 永不写日志（设计 §7.3）。
中间件挂在 MCPServer.streamable_http_app() 外层；非 http scope（如 lifespan）直通。
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

ENV_TOKEN = "ATPROBE_MCP_TOKEN"


def load_token(token_file: str | None, token: str | None) -> str | None:
    """加载 Token：文件（首尾空白剥离）> 显式值 > 环境变量；全无 → None.

    文件不存在抛 FileNotFoundError（CLI 转为 exit 2）。
    """
    if token_file:
        return Path(token_file).read_text(encoding="utf-8").strip()
    if token:
        return token
    env = os.environ.get(ENV_TOKEN, "").strip()
    return env or None


def bearer_middleware(
    app: Callable[[dict[str, Any], Any, Any], Awaitable[None]], expected_token: str
) -> Callable[[dict[str, Any], Any, Any], Awaitable[None]]:
    """纯 ASGI 中间件：非 http scope 直通；Authorization 不匹配 → 401 JSON."""

    async def middleware(
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {expected_token}"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
            return
        await app(scope, receive, send)

    return middleware
