"""M8 Bearer Token 认证：加载（四级优先级）+ 纯 ASGI 中间件（常量时间比较）.

Token 来源优先级（M8 §7）：--token-file > --token > 环境变量 ATPROBE_MCP_TOKEN
> 配置 mcp.token_file（经 config_token_file 参数传入，由 CLI 层接线）。
Token 永不写日志（M8 §7）。
中间件挂在 MCPServer.streamable_http_app() 外层；非 http scope（如 lifespan）直通。
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from atprobe.infra.resources import resolve_workspace_path

ENV_TOKEN = "ATPROBE_MCP_TOKEN"


def load_token(
    token_file: str | None,
    token: str | None,
    config_token_file: str | None = None,
) -> str | None:
    """加载 Token（四级优先级）：token_file > token > 环境变量 > config_token_file.

    两个文件参数均 read_text().strip()，全空白 → None；
    文件不存在抛 FileNotFoundError（CLI 转为 exit 2）；路径是目录或读取失败
    抛 ValueError（CLI 同样转干净错误，不裸 traceback）。

    路径解析（F-18）：config_token_file（来自配置文件，写相对路径时意图是
    工作区相对）经 resolve_workspace_path 锚定——打包态 CLI 从非 exe 目录
    启动时不再落到随机 cwd；显式 --token-file 保持用户原值（用户对 CLI
    参数的 cwd 语义有直觉）。
    """
    if token_file:
        return _read_token_file(Path(token_file))
    if token:
        return token
    env = os.environ.get(ENV_TOKEN, "").strip()
    if env:
        return env
    if config_token_file:
        return _read_token_file(Path(resolve_workspace_path(config_token_file)))
    return None


def _read_token_file(p: Path) -> str | None:
    """读 Token 文件并剥离首尾空白；全空白 → None.

    失败分类（CLI 统一转干净错误）：目录 → ValueError（Windows 下 read_text
    对目录抛 PermissionError、POSIX 抛 IsADirectoryError，故先判 is_dir 统一
    文案）；文件不存在 → FileNotFoundError 原样上抛（CLI 有专门呈现）；
    其余 OSError → ValueError。
    """
    if p.is_dir():
        raise ValueError(f"Token 文件路径是目录：{p}")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise  # 保持原异常类型：CLI 现有"Token 文件不存在"专门呈现依赖它
        raise ValueError(f"Token 文件读取失败（{p}）：{exc}") from exc
    return text.strip() or None


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
        # header 名小写化做键、值保留原始 bytes：hmac.compare_digest 对 str 要求纯
        # ASCII（非 ASCII 头会 TypeError → 500），bytes 比较则恒定返回 False → 401。
        headers_raw = {k.lower(): v for k, v in scope.get("headers", [])}
        auth_raw = headers_raw.get(b"authorization", b"")
        if not hmac.compare_digest(auth_raw, b"Bearer " + expected_token.encode("utf-8")):
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
