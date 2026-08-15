"""M8 MCP 结构化错误（对齐 TSD §5.4：按枚举判定，禁止文案匹配）.

tools.py 捕获 McpError 后序列化为 JSON 文本抛出 → SDK 转 is_error=True。
kind 枚举：INVALID_INPUT / NOT_FOUND / BUSY / DEVICE_ERROR / INTERNAL。
"""

from __future__ import annotations

from typing import Any


class McpError(Exception):
    """MCP 工具业务错误（结构化，可序列化）."""

    def __init__(self, kind: str, message: str, detail: dict[str, Any] | None = None):
        self.kind = kind
        self.message = message
        self.detail = detail or {}
        super().__init__(f"[{kind}] {message}")


def invalid_input(message: str, **detail: Any) -> McpError:
    return McpError("INVALID_INPUT", message, detail)


def not_found(message: str, **detail: Any) -> McpError:
    return McpError("NOT_FOUND", message, detail)


def busy(message: str, **detail: Any) -> McpError:
    return McpError("BUSY", message, detail)


def device_error(message: str, **detail: Any) -> McpError:
    return McpError("DEVICE_ERROR", message, detail)
