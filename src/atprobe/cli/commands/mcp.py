"""M8 `atprobe mcp` 子命令组：本地 stdio / HTTP serve.

模块顶层只依赖核心包（typer/infra）；mcp SDK 与传输装配全部延迟 import
（gui.py 同款模式），未装 MCP 依赖时其余子命令不受影响。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from atprobe.infra.config.appconfig import AppConfig
    from atprobe.mcp.service import McpService

mcp_app = typer.Typer(help="MCP 服务（向大模型开放 ATProbe 能力）", no_args_is_help=True)


def _load_app_config(config: Path | None) -> AppConfig:
    """加载配置：定位规则收敛 resolve_config_path 单点（与 run/list/GUI 同规则）."""
    from atprobe.infra.config.appconfig import (
        AppConfigError,
        load_app_config_file,
        resolve_config_path,
    )

    try:
        return load_app_config_file(resolve_config_path(config))
    except AppConfigError as exc:
        typer.secho(f"配置错误：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _require_mcp() -> None:
    """MCP 依赖守护：缺失时红字提示并 exit 2（gui.py 同款）.

    必须在命令体最先调用（先于配置加载与任何延迟 import）——无 mcp 环境的
    真实失败点是 ``from atprobe.mcp.server import ...`` 拉起的 mcp SDK，
    此处先行探测才能把裸 ModuleNotFoundError 转成友好提示。
    """
    try:
        import mcp  # noqa: F401
    except ImportError as exc:
        typer.secho(
            f"MCP 依赖未安装（{exc}）：uv sync --extra mcp",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2) from exc


def _build_service(app_cfg: AppConfig, vsim: bool) -> McpService:
    """构建 McpService（配置由调用方加载一次后传入，避免 serve 双载）."""
    from atprobe.mcp.service import McpService

    return McpService(app_cfg=app_cfg, vsim=vsim)


@mcp_app.command("stdio")
def stdio(
    config: Path | None = typer.Option(None, "--config", "-c", help="配置文件路径"),
    vsim: bool = typer.Option(False, "--vsim", help="进程内虚拟模组模式（无需真实串口）"),
) -> None:
    """本地 stdio 形态（标准输入输出归 MCP 协议，本命令不打印任何提示）."""
    _require_mcp()
    from atprobe.mcp.server import run_stdio

    # stdout 独占协议：进入 run_stdio 前后都不打印任何东西
    # （错误路径的 stderr 提示发生在协议启动前，见 _require_mcp）。
    raise typer.Exit(run_stdio(_build_service(_load_app_config(config), vsim)))


@mcp_app.command("serve")
def serve(
    host: str | None = typer.Option(
        None, "--host", help="监听地址（缺省 127.0.0.1 或配置 mcp.host）"
    ),
    port: int | None = typer.Option(None, "--port", help="监听端口（缺省 8470 或配置 mcp.port）"),
    token: str | None = typer.Option(
        None, "--token", help="Bearer Token 值（优先级低于 --token-file）"
    ),
    token_file: str | None = typer.Option(
        None, "--token-file", help="Token 文件路径（最高优先级）"
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="配置文件路径"),
    vsim: bool = typer.Option(False, "--vsim", help="进程内虚拟模组模式（无需真实串口）"),
) -> None:
    """HTTP serve 形态（Streamable HTTP + Bearer Token）."""
    _require_mcp()
    from atprobe.mcp.auth import ENV_TOKEN, load_token
    from atprobe.mcp.server import run_serve

    # 顺序：MCP 依赖 → 配置 → Token → 服务（后三者的先后顺序被 test_cli_mcp 钉住）
    app_cfg = _load_app_config(config)
    try:
        tok = load_token(
            token_file=token_file, token=token, config_token_file=app_cfg.mcp_token_file
        )
    except FileNotFoundError as exc:
        typer.secho(f"Token 文件不存在：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    except ValueError as exc:
        # config 路径工作区锚定后仍不可读（目录/权限等，F-18 呈现层）
        typer.secho(f"Token 加载失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    if not tok:
        typer.secho(
            f"serve 需要 Token（--token-file / --token / 环境变量 {ENV_TOKEN} / 配置 mcp.token_file）",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    service = _build_service(app_cfg, vsim)
    bind_host = host or app_cfg.mcp_host
    bind_port = port if port is not None else app_cfg.mcp_port
    typer.secho(
        f"atprobe mcp serve → http://{bind_host}:{bind_port}/mcp",
        fg=typer.colors.CYAN,
        err=True,
    )
    raise typer.Exit(run_serve(service, bind_host, bind_port, tok))
