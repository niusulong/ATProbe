"""M8 MCP 工具定义：把 McpService 门面经官方 SDK ``@server.tool()`` 暴露.

14 个工具（资源发现 4 + 批量测试 4 + 手动调试 3 + URC 监控 3；设计文档
「12 个」为笔误，以名单为准）。统一约定：

- 入参：SDK 从函数签名生成 inputSchema（snake_case 参数名即 LLM 的 JSON 键）；
  出参：service 返回的 dict/list 序列化为 JSON 文本（``ensure_ascii=False``）。
- 错误：McpError → 结构化 JSON ``{"kind", "message", "detail"}`` 包在
  ToolError 里抛出 → SDK 转 ``is_error=True``（文本含该 JSON，LLM 可按
  kind 枚举判定，禁止文案匹配——对齐 errors.py 契约）。非 McpError 的
  逃逸异常由 ``_wrap`` 兜底转同构 INTERNAL（errors.py 该枚举的生产者）。
  注意 SDK 在
  ``Tool.run`` 会再包一层前缀 ``"Error executing tool <name>: "``（对
  ToolError 亦然，mcp 2.0.0 base.py），JSON 不在消息最前——客户端解析
  应从首个 ``{`` 起取（Task 8 err_payload 同此约定），该前缀无法在
  tools 层去除。
- ``structured_output=False``：实测 mcp 2.0.0 对 ``-> str`` 返回注解默认
  开启结构化输出（包成 ``{"result": "<json 文本>"}`` 的 structured_content，
  客户端需二次解析），故显式关闭，纯文本出参。
- 同步函数由 SDK 自动入线程池（anyio.to_thread），不阻塞事件循环。
- 顶层零 SDK 依赖（可选性）：``MCPServer`` 仅作注解（TYPE_CHECKING 延迟），
  ``ToolError`` 在 ``_wrap`` 调用时局部 import——未装 MCP extra 也能 import
  本模块与 server.py（server.py docstring「无 MCP 依赖可 import」的根因保障）。
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from atprobe.mcp.errors import McpError
from atprobe.mcp.service import McpService

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

INSTRUCTIONS = (
    "ATProbe 串口 AT 命令测试工具。工作流：list_ports 发现设备 → open_port 连接 → "
    "send_at 手动调试 / subscribe_urc 监控上报 → start_run 批量执行 → get_job 轮询结果。"
    "同一时刻只能有一个测试作业（BUSY）；作业运行期间不可手动发送指令。"
)


def _wrap(fn: Callable[..., Any]) -> Callable[..., str]:
    """工具函数统一包装：service 调用 → JSON 文本；McpError → 结构化 JSON ToolError.

    functools.wraps 保留 ``__name__``/``__doc__``/``__annotations__``，且
    ``inspect.signature`` 沿 ``__wrapped__`` 取原函数签名 → SDK 据此生成
    每个工具的 inputSchema 与描述。
    """

    @functools.wraps(fn)
    def _inner(*args: Any, **kwargs: Any) -> str:
        from mcp.server.mcpserver.exceptions import ToolError  # 延迟：顶层保持零 SDK 依赖

        try:
            return json.dumps(fn(*args, **kwargs), ensure_ascii=False)
        except McpError as exc:
            raise ToolError(
                json.dumps(
                    {"kind": exc.kind, "message": exc.message, "detail": exc.detail},
                    ensure_ascii=False,
                )
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 兜底：非 McpError 逃逸也走结构化 JSON 通道
            raise ToolError(
                json.dumps(
                    {
                        "kind": "INTERNAL",
                        "message": f"{type(exc).__name__}: {exc}",
                        "detail": {},
                    },
                    ensure_ascii=False,
                )
            ) from exc

    return _inner


def register(server: MCPServer[Any], service: McpService) -> None:
    """在 MCPServer 上注册全部 14 个工具（幂等：SDK 对重名仅告警并保留首个）."""

    def server_info() -> dict[str, Any]:
        """获取服务端信息：工作区根、用例/日志/报告目录的绝对路径、版本、vsim 标志。

        编码机配合文件传输工具使用：把用例文件放到 cases_dir、从 log_dir/report_dir
        取回测试产物（用例与日志的传输由外部工具负责，本服务只按路径引用）。
        """
        return service.server_info()

    def list_ports() -> list[dict[str, Any]]:
        """列出系统可用串口（name、描述、是否已连接），作为设备发现入口。"""
        return service.list_ports()

    def list_cases(path: str | None = None, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """列出可执行测试用例（参数化已展开，name 带 #N；tags 按并集过滤）；path 省略时用配置目录。"""
        return service.list_cases(path, tags)

    def list_suites(path: str | None = None) -> list[dict[str, Any]]:
        """列出可用测试套件（suite- 前缀文件：名称、描述、用例数、标签）。"""
        return service.list_suites(path)

    def validate_run(
        paths: list[str] | None = None,
        ports: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """校验一次批量执行的输入（dry-run）：用例数/用例名/端口，不实际执行。"""
        return service.validate_run(paths, ports, tags)

    def start_run(
        paths: list[str] | None = None,
        ports: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """启动异步批量测试作业并立即返回 job_id；用 get_job 轮询进度与结果。"""
        return service.start_run(paths, ports, tags)

    def get_job(job_id: str) -> dict[str, Any]:
        """查询作业快照：status（running/finished/failed）、进度、summary 与最近事件。"""
        return service.get_job(job_id)

    def cancel_job(job_id: str) -> dict[str, Any]:
        """取消 running 中的测试作业（幂等：已结束返回 cancelled=false）。"""
        return service.cancel_job(job_id)

    def open_port(port_expr: str) -> dict[str, Any]:
        """打开串口用于手动调试，port_expr 形如 COM3:115200:8N1（波特率/帧格式可省略）。"""
        return service.open_port(port_expr)

    def close_port(port: str) -> dict[str, Any]:
        """关闭手动调试打开的串口（幂等；同时拆除该端口的 URC 转发）。"""
        return service.close_port(port)

    def send_at(
        port: str,
        command: str,
        timeout: float | None = None,
        wait_urc: str | None = None,
    ) -> dict[str, Any]:
        """向已打开端口发送单条 AT 命令并等待响应；timeout 秒可选，wait_urc 为 URC 终结正则。"""
        return service.send_at(port, command, timeout=timeout, wait_urc=wait_urc)

    def subscribe_urc(port: str, pattern: str | None = None) -> dict[str, Any]:
        """订阅端口 URC 上报（pattern 为可选正则），返回 subscription_id 供 poll_urc 增量拉取。"""
        return service.subscribe_urc(port, pattern)

    def poll_urc(subscription_id: str, cursor: int = 0, limit: int = 100) -> dict[str, Any]:
        """按游标增量拉取订阅的 URC 事件（next_cursor 回传作下次 cursor）。"""
        return service.poll_urc(subscription_id, cursor=cursor, limit=limit)

    def unsubscribe_urc(subscription_id: str) -> dict[str, Any]:
        """退订 URC（幂等；端口级转发保留至 close_port）。"""
        return service.unsubscribe_urc(subscription_id)

    for fn in (
        server_info,
        list_ports,
        list_cases,
        list_suites,
        validate_run,
        start_run,
        get_job,
        cancel_job,
        open_port,
        close_port,
        send_at,
        subscribe_urc,
        poll_urc,
        unsubscribe_urc,
    ):
        server.tool(structured_output=False)(_wrap(fn))
