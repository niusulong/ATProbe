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

# Qt6 / PySide6 收集。collect_all 拿 Qt plugins（platforms/styles 等运行时铁律），
# 但会顺带拉入大量未用的大块二进制（WebEngine/Chromium ~270MB、Qml/Quick/3D 等）。
# 策略：先 collect_all，再从 datas/binaries 里剔除明确未用的大块，保留 plugins。
_EXCLUDE_BIN_PATTERNS = (
    # WebEngine（Chromium，~270MB；report_view.py 已 try/except 降级为"浏览器打开"）
    "QtWebEngine", "qtwebengine", "WebEngineCore", "webengine",
    # QtQml/Quick（无 QML 代码）
    "Qt6Qml", "Qt6Quick", "Qt6Quick3D", "Qt6QuickControls2", "Qt6QuickTemplates2",
    "Qt6QuickWidgets", "Qt6ShaderTools", "Qt6Pdf", "Qt6Designer",
    "/qml/", "\\qml\\", "qmlls", "qmlscene",
    # 其他未用大块
    "Qt6Charts", "Qt6DataVis", "Qt63D", "Qt6Bluetooth", "Qt6Multimedia",
    "Qt6SerialPort", "Qt6WebSockets", "Qt6Location", "Qt6Sensors", "Qt6Nfc",
    "Qt6RemoteObjects", "Qt6Scxml", "Qt6TextToSpeech", "Qt6VirtualKeyboard",
    "Qt6SpatialAudio", "Qt6Quick3D",
    "avcodec", "avformat", "avutil", "swscale", "swresample",  # QtMultimedia FFmpeg
    "opengl32sw",  # 软件渲染兜底（有硬件 OpenGL 足够）
)
# 仍需保留的 Qt 模块（Core/Gui/Widgets/Svg/Network?）—— 只保留代码实际用的
_KEEP_HINTS = ("Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Svg", "Qt6OpenGL",
               "Qt6Network", "Qt6DBus", "Qt6PrintSupport", "Qt6Concurrent",
               "Qt6Test")  # 这些体积小，保留以防隐式依赖

# 过滤掉未用的大块二进制（按文件名匹配）；匹配 collect_all 收集到的 dest 路径名
def _excluded(name: str) -> bool:
    n = name.replace("\\", "/").lower()
    return any(p.lower() in n for p in _EXCLUDE_BIN_PATTERNS)

for pkg in ("PySide6", "shiboken6"):
    d, b, h = collect_all(pkg)
    binaries += [item for item in b if not _excluded(item[1])]
    datas += [item for item in d if not _excluded(item[1])]
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

# 排除未使用的模块以瘦身。
# ATProbe 实际只用 QtCore/QtGui/QtWidgets/QtSvg + shiboken6（图标渲染用 QSvgRenderer）。
# QtWebEngine（Chromium，~150-200MB）仅用于 GUI 内嵌 HTML 报告查看，代码已 try/except 降级
# （report_view.py 排除后显示"用浏览器打开报告"），故整体排除以换取最大体积收益。
excludes = [
    # 非 Qt
    "tkinter", "PyQt5", "PyQt6", "pytest", "_pytest",
    # PySide6 未用大块（按代码证据，src/atprobe 仅用 QtCore/QtGui/QtWidgets/QtSvg）
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickTemplates2",
    "PySide6.QtNetwork",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSql",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtTest",
    "PySide6.QtSvgWidgets",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtDBus",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtTextToSpeech",
    "PySide6.QtOpenGL",
    "PySide6.QtPrintSupport",
    "PySide6.QtConcurrent",
    "PySide6.QtAxContainer",
]

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
    icon=str(SPEC_DIR / "atprobe.ico"),
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
#
# Analysis 阶段 Qt hook 会把 WebEngine/Qml/Quick 等大块二进制加回 a.binaries/a.datas
# （即使前面 collect_all 过滤了，hook 仍按 import 图加入）。此处对 Analysis 产物再次
# 清理：从 gui_a.binaries/gui_a.datas（COLLECT 实际用的）删除未用大块。
_gui_bins = [(d, s, k) for (d, s, k) in gui_a.binaries if not _excluded(d)]
_gui_datas = [(d, s, k) for (d, s, k) in gui_a.datas if not _excluded(d)]
print(f"[spec] binaries: {len(gui_a.binaries)} -> {len(_gui_bins)}, "
      f"datas: {len(gui_a.datas)} -> {len(_gui_datas)}")

COLLECT(gui_exe, cli_exe, _gui_bins, _gui_datas, name="ATProbe-VERSION")
