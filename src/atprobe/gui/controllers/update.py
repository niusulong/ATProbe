"""GUI 更新流程控制器（D-1 拆分，自 MainWindow 迁出）.

检查（worker 线程）→ 结果呈现（弹窗）→ 下载（UpdateSession）→ 完成回调
（安装确认/执行）。MainWindow 只保留实例化与菜单入口
``controller.check(manual=...)``——弹窗呈现随迁本控制器（持宿主窗口引用
作弹窗父级，构造传 ``parent``）。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from PySide6.QtWidgets import QProgressDialog, QWidget

# check_result 信号的哨兵：版本未知（VERSION 缺失，current_version 回退 0.0.0）。
# 与 None（已是最新）/ Exception（检查失败）区分——主线程据此给特殊文案而非升级框。
_VERSION_UNKNOWN = object()


class UpdateController(QObject):
    """GUI 更新流程控制器（D-1 拆分,自 MainWindow 迁出 ~200 行）。

    信号:check_result(object)  # ReleaseInfo | _VERSION_UNKNOWN | None | Exception
          download_progress(int, int)
          download_done(object)  # Path | Exception
    职责:检查(worker 线程)→ 结果呈现(弹窗)→ 下载(UpdateSession)→ 完成回调;
    MainWindow 保留:实例化、信号连接(→主线程槽)、菜单入口 `controller.check(manual=...)`。
    """

    # 跨线程事件投递信号（工作线程 → 主线程槽；自连接在 __init__，弹窗呈现在本类）
    # check_result 哨兵：_VERSION_UNKNOWN=版本未知（模块顶部常量，特殊文案路径）
    check_result = Signal(object)  # ReleaseInfo | None(无新版/失败) | Exception
    download_progress = Signal(int, int)  # (done, total)
    download_done = Signal(object)  # Path | Exception

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 弹窗父级：宿主窗口（MainWindow）——QMessageBox/QDialog 以其为父居中
        self._host = parent
        self._update_in_progress = False
        self._cancelled = False
        self._check_manual = False
        self._progress_dlg: QProgressDialog | None = None
        # 信号自连接：worker 线程 emit → queued → 主线程呈现槽
        # （MainWindow 时代的 update_check_result 等三信号连接随方法整体迁入）
        self.check_result.connect(self._on_check_result)
        self.download_progress.connect(self._on_download_progress)
        self.download_done.connect(self._on_download_done)

    # ------------------------------------------------------------------
    # 检查更新
    # ------------------------------------------------------------------
    def check(self, manual: bool = True) -> None:
        """后台检查更新（工作线程做 HTTP，结果经信号回主线程）。

        manual=False（启动自动）：失败/无新版静默；manual=True（手动）：弹提示。
        下载进行中（_update_in_progress）时忽略重复请求。
        """
        if self._update_in_progress:
            return
        self._check_manual = manual
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        from atprobe.infra.update.checker import fetch_latest, is_newer
        from atprobe.infra.version import current_version, is_version_known

        try:
            info = fetch_latest()
            local = current_version()
            if not is_version_known(local):
                # VERSION 缺失时 local 是回退 '0.0.0'——不能参与 semver 比较
                # （任何远端版本都"更新"，恒弹升级框误导）。未知走特殊呈现。
                self.check_result.emit(_VERSION_UNKNOWN)
                return
            self.check_result.emit(info if is_newer(info.version, local) else None)
        except Exception as exc:  # noqa: BLE001 - P3：网络失败等统一经信号回主线程呈现
            self.check_result.emit(exc)

    def _on_check_result(self, result: object) -> None:
        """主线程：处理检查结果。"""
        from PySide6.QtWidgets import QMessageBox

        from atprobe.infra.version import current_version

        # 异常：失败
        if isinstance(result, Exception):
            if self._check_manual:
                QMessageBox.warning(self._host, "检查更新", f"检查失败：{result}")
            return
        # 版本未知（VERSION 缺失）：不进入升级流程，提示从 Release 页确认
        if result is _VERSION_UNKNOWN:
            if self._check_manual:
                QMessageBox.warning(
                    self._host,
                    "检查更新",
                    "无法确定当前版本（VERSION 文件缺失），请从 Release 页确认。",
                )
            return
        # None：已是最新
        if result is None:
            if self._check_manual:
                QMessageBox.information(
                    self._host, "检查更新", f"当前已是最新版本 {current_version()}"
                )
            return
        # ReleaseInfo：有新版 → 弹升级对话框
        self._show_update_dialog(result)

    def _show_update_dialog(self, info: object) -> None:
        """有新版时弹升级对话框（版本号 + changelog + 立即更新/稍后）。"""
        import html as _html

        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QTextEdit,
            QVBoxLayout,
        )

        from atprobe.infra.version import current_version

        dlg = QDialog(self._host)
        # P3：预发布版本在弹窗标题标注（info.prerelease 由 checker 按 tag 后缀解析）
        dlg.setWindowTitle(
            "发现新版本（预发布）" if getattr(info, "prerelease", False) else "发现新版本"
        )
        dlg.setMinimumWidth(480)
        layout = QVBoxLayout(dlg)
        layout.addWidget(
            QLabel(
                f"<b>发现新版本 {info.version}</b>（当前 {current_version()}）"  # type: ignore[attr-defined]
            )
        )
        notes = QTextEdit()
        notes.setReadOnly(True)
        # HTML 转义 changelog，避免含 <,>,& 的 release body 破坏渲染
        safe_notes = _html.escape(str(getattr(info, "release_notes", "")))
        notes.setHtml(f"<pre>{safe_notes}</pre>")
        layout.addWidget(QLabel("更新内容："))
        layout.addWidget(notes, 1)
        size_mb = getattr(info, "zip_size", 0) / (1024 * 1024)
        layout.addWidget(QLabel(f"下载大小：约 {size_mb:.1f} MB"))
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("立即更新")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("稍后")
        btns.accepted.connect(lambda: self._start_download(info, dlg))
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.exec()

    # ------------------------------------------------------------------
    # 下载 + 安装
    # ------------------------------------------------------------------
    def _start_download(self, info: object, dlg: object) -> None:
        """用户点立即更新：关闭对话框，启动下载（工作线程 + 进度对话框）。"""
        from PySide6.QtWidgets import QProgressDialog

        dlg.accept()  # type: ignore[attr-defined]
        self._update_in_progress = True

        self._progress_dlg = QProgressDialog(
            f"正在更新到 {info.version}...",  # type: ignore[attr-defined]
            "取消",
            0,
            100,
            self._host,
        )
        self._progress_dlg.setWindowTitle("更新")
        self._progress_dlg.setMinimumDuration(0)
        self._progress_dlg.setValue(0)
        self._progress_dlg.canceled.connect(self._cancel_download)
        self._cancelled = False

        threading.Thread(target=self._download_worker, args=(info,), daemon=True).start()

    def _download_worker(self, info: object) -> None:
        from atprobe.infra.update.session import UpdateSession

        try:
            # D-3/P1-9 结构修：下载编排收敛 UpdateSession（此前 GUI 此处硬编码
            # 文件名、漏传校验参数，与 CLI 两处拼装各自漂移——单点后天然一致）
            result = UpdateSession().download(
                info,  # type: ignore[arg-type]
                progress_cb=lambda d, t: self.download_progress.emit(d, t),
                cancel_token=lambda: self._cancelled,
            )
            self.download_done.emit(result.path)
        except Exception as exc:  # noqa: BLE001 - P3：取消/失败统一经信号回主线程呈现
            self.download_done.emit(exc)

    def _on_download_progress(self, done: int, total: int) -> None:
        if self._progress_dlg is not None and total > 0:
            self._progress_dlg.setValue(done * 100 // total)

    def _cancel_download(self) -> None:
        self._cancelled = True

    def _on_download_done(self, result: object) -> None:
        """下载完成（Path）或失败（Exception）→ 安装确认/执行。"""
        from pathlib import Path

        from PySide6.QtWidgets import QApplication, QMessageBox

        from atprobe.infra.runtime import app_root
        from atprobe.infra.update import DownloadCancelled, UpdateError
        from atprobe.infra.update.installer import apply_update

        if self._progress_dlg is not None:
            self._progress_dlg.close()
        self._update_in_progress = False

        if isinstance(result, Exception):
            if not isinstance(result, DownloadCancelled):
                QMessageBox.critical(self._host, "更新失败", f"下载失败：{result}")
            return
        # 下载成功 → 最终确认安装
        zip_path = Path(result)  # type: ignore[arg-type]
        choice = QMessageBox.question(
            self._host,
            "开始安装",
            "更新已就绪。点击「是」后程序将关闭并自动完成升级（约 5 秒）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            apply_update(zip_path, app_root())
        except UpdateError as exc:
            QMessageBox.critical(self._host, "安装失败", str(exc))
            return
        # 脚本已 detached 启动，主动退出
        QApplication.quit()
