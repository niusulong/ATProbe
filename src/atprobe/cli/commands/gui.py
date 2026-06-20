"""M5 `gui` 子命令 —— 启动桌面 GUI（M6）.

延迟导入 PySide6，使 CLI 无 GUI 依赖时也能正常运行其他子命令。
"""

from __future__ import annotations

import typer


def gui_cmd() -> None:
    """启动桌面端 GUI 应用."""
    try:
        from atprobe.gui.app import run_gui
    except ImportError as exc:
        typer.secho(
            "GUI 依赖未安装，请运行: uv sync --extra gui",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2) from exc
    raise typer.Exit(run_gui())
