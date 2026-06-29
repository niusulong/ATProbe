# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec — ATProbe（GUI + CLI 双入口，Windows x64）。

构建入口：``uv run python packaging/build.py``（build.py 会动态注入版本号到
COLLECT name，替换下方 ATProbe-VERSION 占位符）。

关键点：
  - collect_all('PySide6'/'shiboken6')：Qt 插件全量收集，否则启动崩
  - collect_submodules('atprobe')：覆盖延迟导入
  - examples/ 打进 _internal/examples（resources.py 经此定位内置只读资源）
  - 双 EXE：GUI（console=False）+ CLI（console=True）共享同一 COLLECT 目录
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = []
binaries = []
hiddenimports = []

# Qt6 / PySide6 全量收集（plugins、translations、QML）—— 打包铁律
for pkg in ("PySide6", "shiboken6"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 内置只读资源 → _internal/examples（resources.py 经 importlib.resources / 文件路径读取）
datas += [
    ("../examples/env.yaml", "examples"),
    ("../examples/quick_commands.yaml", "examples"),
    ("../examples/testcases", "examples/testcases"),
]

# 源码全量收集（含延迟导入的子模块）
hiddenimports += collect_submodules("atprobe")

a = Analysis(
    ["entry_gui.py", "entry_cli.py"],
    pathex=[str(Path("..", "src").resolve())],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(Path("hooks").resolve())],
    excludes=["tkinter", "PyQt5", "PyQt6", "pytest", "_pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# GUI exe：取 Analysis scripts[0]（entry_gui.py 对应），console=False 不弹黑窗
gui_exe = EXE(
    pyz,
    a.scripts[:1],
    [],
    exclude_binaries=True,
    name="ATProbe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,  # 后续可加 packaging/atprobe.ico
)

# CLI exe：取 Analysis scripts[1]（entry_cli.py 对应），console=True 保留控制台
cli_exe = EXE(
    pyz,
    a.scripts[1:],
    [],
    exclude_binaries=True,
    name="atprobe-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

# COLLECT name 由 build.py 在调用前用字符串替换注入版本号（见 build.py 的 render_spec）
# 此处占位 ATProbe-VERSION，build.py 会替换为 ATProbe-<version>。
COLLECT(gui_exe, cli_exe, a.binaries, a.datas, name="ATProbe-VERSION")
