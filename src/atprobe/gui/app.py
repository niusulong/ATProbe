"""GUI 应用入口."""

from __future__ import annotations

import sys


def run_gui(argv: list[str] | None = None) -> int:
    """启动 GUI（延迟导入 PySide6，使 CLI 无 GUI 依赖时也能运行）."""
    from PySide6.QtWidgets import QApplication

    from atprobe.gui.mainwindow import MainWindow  # noqa: F401 (重定向)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ATProbe")
    # 显式设置组织名，使 QSettings() 默认路径稳定（Windows: HKCU\Software\ATProbe\ATProbe）
    app.setOrganizationName("ATProbe")

    from atprobe.gui.theme import apply_theme

    apply_theme(app, dark=False)

    win = MainWindow()
    win.show()
    return app.exec()
