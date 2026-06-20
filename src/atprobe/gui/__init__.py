"""M6 UI 管理界面（REQ-M6）.

PySide6 (Qt6) 实现的桌面端 GUI，与 M5 CLI 共享同一引擎。
布局（§2.1）：侧边导航 + MDI 多文档选项卡工作区 + 右侧上下文栏 + 状态栏。
扩展机制（§2.3/§10.5）：选项卡类型注册表，新增功能 = 注册新类型 + 实现视图。
"""

from atprobe.gui.app import run_gui

__all__ = ["run_gui"]
