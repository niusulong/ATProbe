# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec — ATProbe（GUI + CLI 双入口，Windows x64）。

构建入口：``uv run python packaging/build.py``（build.py 注入版本号到 COLLECT name，
并通过 --distpath 指定输出目录）。

多入口策略：每个 exe 用独立 Analysis（PyInstaller 官方推荐的多入口做法），
共享同一份 datas/binaries/hiddenimports 计算结果。COLLECT 把两个 exe +
共用运行时收集到一个目录（_internal 共享，体积不重复）。

关键点：
  - collect_all('PySide6'/'shiboken6')：Qt 插件全量收集，否则启动崩
  - collect_submodules('atprobe')：覆盖延迟导入
  - examples/ 打进 _internal/examples（resources.py 经此定位内置只读资源）
  - 所有路径基于 spec 所在目录（PyInstaller 全局 SPECPATH），不依赖 cwd
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# PyInstaller exec spec 时不设置 __file__，但提供全局变量 SPECPATH（spec 所在目录）
SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

block_cipher = None

# 共享的依赖计算（两个 exe 用同一份）
datas = []
binaries = []
hiddenimports = []

# Qt6 / PySide6 全量收集（plugins、translations、QML）—— 打包铁律
for pkg in ("PySide6", "shiboken6"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 内置只读资源 → _internal/examples（resources.py 经此定位）
datas += [
    (str(REPO_ROOT / "examples" / "env.yaml"), "examples"),
    (str(REPO_ROOT / "examples" / "quick_commands.yaml"), "examples"),
    (str(REPO_ROOT / "examples" / "testcases"), "examples/testcases"),
]

# 包内数据文件 → _internal/atprobe/...（PackageLoader/importlib.resources 经此定位）
# collect_data_files 自动收集 atprobe 包内所有非 .py 数据文件（如 reporting/templates/*.j2），
# 避免逐个手写、漏报（之前漏 templates 导致 HtmlReporter 崩）
from PyInstaller.utils.hooks import collect_data_files

datas += collect_data_files("atprobe")

# 源码全量收集（含延迟导入的子模块）
hiddenimports += collect_submodules("atprobe")

pathex = [str(REPO_ROOT / "src")]
hookspath = [str(SPEC_DIR / "hooks")]
excludes = ["tkinter", "PyQt5", "PyQt6", "pytest", "_pytest"]

# --- GUI exe：独立 Analysis（console=False）---
gui_a = Analysis(
    [str(SPEC_DIR / "entry_gui.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=hookspath,
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)
gui_pyz = PYZ(gui_a.pure, gui_a.zipped_data, cipher=block_cipher)
gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
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

# --- CLI exe：独立 Analysis（console=True）---
cli_a = Analysis(
    [str(SPEC_DIR / "entry_cli.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=hookspath,
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data, cipher=block_cipher)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name="atprobe-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

# COLLECT 把两个 exe + 共用运行时收集到一个目录（_internal 共享）
# COLLECT name 由 build.py 在调用前替换 ATProbe-VERSION → ATProbe-<version>
COLLECT(gui_exe, cli_exe, gui_a.binaries, gui_a.datas, name="ATProbe-VERSION")
