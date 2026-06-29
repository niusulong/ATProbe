"""ATProbe GUI 入口（打包用）。

双击 ATProbe.exe 直接进 GUI，跳过 Typer CLI 层，对非技术用户友好。
PyInstaller 把本文件作为 Analysis 第一个脚本，生成 console=False 的 ATProbe.exe。
"""

from __future__ import annotations

import sys

from atprobe.gui.app import run_gui

if __name__ == "__main__":
    sys.exit(run_gui())
