"""报告查看选项卡（M6 §7）—— 单例容器，内部以子标签承载多个报告.

设计：报告查看是唯一的顶层选项卡；每打开一份 M4 生成的 HTML 报告，
就在内部新增一个子标签（文件名为标题，可关闭）。内嵌 WebView 渲染纯静态 HTML。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.tabs.registry import ITabView, TabBinding

# WebEngine 为可选依赖（CI/offscreen 环境可能不可用），延迟导入并降级。
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # type: ignore[import-not-found]

    _HAS_WEBENGINE = True
except Exception:  # noqa: BLE001
    _HAS_WEBENGINE = False


class ReportViewTab(ITabView):
    type_name = "report_view"
    display_name = "报告查看"
    _icon = "report"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return ReportViewWidget(binding, main_window)


class ReportViewWidget(QWidget):
    """报告查看视图（§7）—— 子标签式多报告容器."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._sub_tabs: QTabWidget | None = None
        self._has_web = _HAS_WEBENGINE
        self._init_ui()
        # 若 binding 带了 report_path，直接打开
        path = binding.params.get("report_path")
        if path:
            self.open_report(str(path))

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 工具栏：打开报告按钮 + 提示
        bar = QHBoxLayout()
        bar.setSpacing(8)
        open_btn = QPushButton("打开报告")
        open_btn.clicked.connect(self._open_dialog)
        bar.addWidget(open_btn)
        if not self._has_web:
            hint = QLabel("（WebEngine 不可用，请用浏览器打开报告文件）")
            hint.setObjectName("caption")
            bar.addWidget(hint)
        bar.addStretch()
        layout.addLayout(bar)

        # 子标签容器：每个报告一个子页
        self._sub_tabs = QTabWidget()
        self._sub_tabs.setTabsClosable(True)
        self._sub_tabs.tabCloseRequested.connect(self._close_sub_tab)
        self._sub_tabs.setDocumentMode(True)
        layout.addWidget(self._sub_tabs, 1)

    def _close_sub_tab(self, idx: int) -> None:
        """关闭一个报告子标签."""
        if self._sub_tabs is not None:
            w = self._sub_tabs.widget(idx)
            self._sub_tabs.removeTab(idx)
            if w is not None:
                w.deleteLater()

    def _open_dialog(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "打开报告", "", "HTML 报告 (*.html)")
        if f:
            self.open_report(f)

    def open_report(self, path: str) -> None:
        """在子标签中打开（或聚焦）一份报告。重复打开同一文件 → 聚焦已存在子页."""
        p = Path(path)
        if not p.exists():
            return
        if self._sub_tabs is None:
            return
        title = p.stem
        abs_path = str(p.absolute())
        # 若该报告已打开，直接聚焦
        for i in range(self._sub_tabs.count()):
            w = self._sub_tabs.widget(i)
            if isinstance(w, QWidget) and w.property("report_path") == abs_path:
                self._sub_tabs.setCurrentIndex(i)
                return
        # 新建子页
        if self._has_web:
            view = QWebEngineView()
            view.setUrl(QUrl.fromLocalFile(abs_path))
            view.setProperty("report_path", abs_path)
            idx = self._sub_tabs.addTab(view, title)
        else:
            placeholder = QLabel(f"报告：{p.name}\n（WebEngine 不可用，请用浏览器打开：{p}）")
            placeholder.setProperty("report_path", abs_path)
            idx = self._sub_tabs.addTab(placeholder, title)
        self._sub_tabs.setCurrentIndex(idx)
