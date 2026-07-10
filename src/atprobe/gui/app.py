"""GUI 应用入口."""

from __future__ import annotations

import sys


def run_gui(argv: list[str] | None = None) -> int:
    """启动 GUI（延迟导入 PySide6，使 CLI 无 GUI 依赖时也能运行）."""
    # 最早接入日志：确保后续所有 import 与启动流程的异常都被记录
    # （诊断 Win10 分发后卡住的关键——异常落盘而非静默消失）
    import logging

    from atprobe.infra.logging_config import install_excepthook, setup_logging

    log_path = setup_logging(level=logging.INFO)
    logger = logging.getLogger("atprobe.app")
    install_excepthook()
    logger.info("ATProbe GUI 启动，日志: %s", log_path)

    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication

    from atprobe.gui.mainwindow import MainWindow  # noqa: F401 (重定向)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ATProbe")
    # 显式设置组织名，使 QSettings() 默认路径稳定（Windows: HKCU\Software\ATProbe\ATProbe）
    app.setOrganizationName("ATProbe")

    # 应用窗口图标：AT 字母标（矢量 SVG，任意尺寸清晰，主题色统一）
    # 失败回退包内静态 PNG（打包后经 spec collect_data_files 收集）
    try:
        from atprobe.gui.icons import make_logo

        app.setWindowIcon(make_logo(64))
    except Exception:  # noqa: BLE001
        try:
            from importlib import resources

            icon_path = resources.files("atprobe.resources") / "app_icon.png"
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
