"""PyInstaller hook：收集 atprobe 全部子模块（覆盖延迟导入）。"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("atprobe")
