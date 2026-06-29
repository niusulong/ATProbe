"""ATProbe CLI 入口（打包用）。

暴露完整 run/list/gui 子命令，供会命令行的工程师使用：
    atprobe-cli.exe run examples/testcases/ntp/x.yaml --port COM5:115200
    atprobe-cli.exe list cases
PyInstaller 把本文件作为 Analysis 第二个脚本，生成 console=True 的 atprobe-cli.exe。
"""

from __future__ import annotations

from atprobe.cli.main import app

if __name__ == "__main__":
    app()
