"""GUI 应用入口."""

from __future__ import annotations

import sys


def run_gui(argv: list[str] | None = None) -> int:
    """启动 GUI（延迟导入 PySide6，使 CLI 无 GUI 依赖时也能运行）."""
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication

    from atprobe.gui.mainwindow import MainWindow  # noqa: F401 (重定向)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ATProbe")
    # 显式设置组织名，使 QSettings() 默认路径稳定（Windows: HKCU\Software\ATProbe\ATProbe）
    app.setOrganizationName("ATProbe")

    # 应用窗口图标：从包内 resources/app_icon.png 加载（打包后经 spec collect_data_files 收集）
    try:
        from importlib import resources

        res_dir = resources.files("atprobe.resources")
        icon_path = res_dir / "app_icon.png"
        if icon_path.is_file():
            pix = QPixmap(str(icon_path))
            if not pix.isNull():
                app.setWindowIcon(QIcon(pix))
    except Exception:  # noqa: BLE001
        pass  # 图标缺失不影响功能

    from atprobe.gui.theme import apply_theme

    # 加载记忆的主题（默认浅色）
    dark = bool(QSettings("ATProbe", "ATProbe").value("theme/dark", False, type=bool))
    apply_theme(app, dark=dark)

    win = MainWindow()
    win.show()
    # 启动 3 秒后静默检查更新（后台线程，失败不打扰用户）
    from PySide6.QtCore import QTimer

    def _startup_check() -> None:
        win._check_update(manual=False)  # noqa: SLF001

    QTimer.singleShot(3000, _startup_check)
    return app.exec()
