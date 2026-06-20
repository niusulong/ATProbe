"""M5 CLI 主入口（REQ-M5 §2 子命令）."""

from __future__ import annotations

import typer

from atprobe import __version__

app = typer.Typer(
    name="atprobe",
    help="串口 AT 命令自动化测试工具",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="显示版本号"),
) -> None:
    if version:
        typer.echo(f"atprobe {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# 注册子命令
from atprobe.cli.commands import list as list_cmd  # noqa: E402
from atprobe.cli.commands import run as run_cmd  # noqa: E402
from atprobe.cli.commands.gui import gui_cmd  # noqa: E402

app.command()(run_cmd.run)
app.command(name="list")(list_cmd.list_cmd)
app.command(name="gui")(gui_cmd)
