"""M8 Bearer Token 认证：加载（四级优先级）+ 纯 ASGI 中间件（常量时间比较）.

Token 来源优先级（M8 §7）：--token-file > --token > 环境变量 ATPROBE_MCP_TOKEN
> 配置 mcp.token_file（经 config_token_file 参数传入，由 CLI 层接线）。
Token 永不写日志（M8 §7）。
中间件挂在 MCPServer.streamable_http_app() 外层；非 http scope（如 lifespan）直通。
S-4 加固：Token 强度警告 + --token strip + 双侧 SHA-256 常量时间比较 + 失败指数退避。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from atprobe.infra.resources import resolve_workspace_path

ENV_TOKEN = "ATPROBE_MCP_TOKEN"

# 弱 Token 判定阈值（S-4）：<32 字符可被暴力枚举，记 WARNING（不阻断）
_MIN_TOKEN_LEN = 32


def load_token(
    token_file: str | None,
    token: str | None,
    config_token_file: str | None = None,
) -> str | None:
    """加载 Token（四级优先级）：token_file > token > 环境变量 > config_token_file.

    两个文件参数均 read_text().strip()，全空白 → None；
    文件不存在抛 FileNotFoundError（CLI 转为 exit 2）；路径是目录或读取失败
    抛 ValueError（CLI 同样转干净错误，不裸 traceback）。

    --token 同样 strip（S-4）：首尾空白剥离，strip 后全空白视为未提供、
    落到下一级（环境变量 ATPROBE_MCP_TOKEN）。

    路径解析（F-18）：config_token_file（来自配置文件，写相对路径时意图是
    工作区相对）经 resolve_workspace_path 锚定——打包态 CLI 从非 exe 目录
    启动时不再落到随机 cwd；显式 --token-file 保持用户原值（用户对 CLI
    参数的 cwd 语义有直觉）。

    强度（S-4）：任一级取到非 None Token 后，长度 <32 记 WARNING 提示
    换用 secrets.token_hex(32) 强随机——仅告警不阻断。
    """
    result: str | None
    if token_file:
        result = _read_token_file(Path(token_file))
    elif token and token.strip():
        result = token.strip()
    else:
        env = os.environ.get(ENV_TOKEN, "").strip()
        if env:
            result = env
        elif config_token_file:
            result = _read_token_file(Path(resolve_workspace_path(config_token_file)))
        else:
            result = None
    if result is not None and len(result) < _MIN_TOKEN_LEN:
        logging.getLogger("atprobe.mcp").warning(
            "MCP Token 长度 %d < 32，弱 Token 可被暴力枚举——建议强随机："
            'python -c "import secrets; print(secrets.token_hex(32))"',
            len(result),
        )
    return result


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


class _FailLimiter:
    """认证失败指数退避限速（S-4）：0.5s 起、×2、封顶 5s；成功重置."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails = 0

    def delay_for_failure(self) -> float:
        """记一次失败并返回应延迟的秒数."""
        with self._lock:
            self._fails += 1
            # float() 显式收窄：typeshed 对 int ** int 标注为 Any
            delay = min(0.5 * float(2 ** (self._fails - 1)), 5.0)
            return delay

    def reset(self) -> None:
        with self._lock:
            self._fails = 0


def bearer_middleware(
    app: Callable[[dict[str, Any], Any, Any], Awaitable[None]], expected_token: str
) -> Callable[[dict[str, Any], Any, Any], Awaitable[None]]:
    """纯 ASGI 中间件：非 http scope 直通；Authorization 不匹配 → 401 JSON.

    S-4 加固：Token 双侧 SHA-256 后 hmac.compare_digest（比较恒定 32 字节，
    消除长度信号）；认证失败先指数退避再回 401（_FailLimiter，每 app 实例
    独立——bearer_middleware 每次 serve 构建一次，limiter 在闭包内）。
    """

    limiter = _FailLimiter()
    expected_hash = hashlib.sha256(expected_token.encode("utf-8")).digest()

    async def middleware(
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        # header 名小写化做键、值保留原始 bytes；非 ASCII 原始字节哈希不报错 → 401
        # （旧实现对 str 比较要求纯 ASCII，bytes 哈希路径下无此约束）。
        headers_raw = {k.lower(): v for k, v in scope.get("headers", [])}
        auth_raw = headers_raw.get(b"authorization", b"")
        # S-4 消长度信号：剥 "Bearer " 后对凭据双侧 SHA-256 再比较——比较恒定
        # 32 字节，无任何与 Token 长度相关的分支/耗时差（hmac.compare_digest
        # 对不等长 bytes 本身安全，但"拼接+按长度比较"的路径仍有长度依赖）。
        # scheme 前缀是公开常量，startswith 检查不引入时序信号（审查修复：
        # 盲切 [7:] 会使任意 7 字节前缀 + 正确凭据通过）。
        if not auth_raw.startswith(b"Bearer "):
            await asyncio.sleep(limiter.delay_for_failure())
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
            return
        auth_token = auth_raw[7:]
        actual_hash = hashlib.sha256(auth_token).digest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            # 失败限速（S-4）：先退避（0.5s 起 ×2 封顶 5s）再回 401，压制暴力
            # 枚举；asyncio.sleep 在单事件循环内让出，锁仅防御跨线程并发。
            await asyncio.sleep(limiter.delay_for_failure())
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
            return
        limiter.reset()
        await app(scope, receive, send)

    return middleware
