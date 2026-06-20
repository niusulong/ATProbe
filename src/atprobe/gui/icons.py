"""侧栏 SVG 图标（线条风，24×24 viewBox，stroke 渲染）.

替代粗糙的 Unicode 符号，统一为精致的自绘线性图标（Lucide/Feather 风格）。
颜色由调用方传入，默认取侧栏项文字色，保证选中/未选中对比度。
通过 QSvgRenderer 把带颜色的 SVG 字符串渲染成 QPixmap → QIcon。
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 图标尺寸（逻辑像素，Qt 会按 DPR 缩放）
_ICON_SIZE = QSize(20, 20)

# ---------------------------------------------------------------------------
# SVG 模板：占位 {color} 由调用方填充 stroke 颜色。统一 stroke-width 1.8、圆角。
# 每个图标语义与功能对应：手动调试(终端光标)/用例执行(播放)/实时监控(波形)/
# 报告查看(文档)/环境配置(齿轮)。
# ---------------------------------------------------------------------------
_SVG_TPL = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" \
viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" \
stroke-linecap="round" stroke-linejoin="round">{body}</svg>"""

_ICONS: dict[str, str] = {
    # 手动调试：终端框 + 闪烁光标，呼应"敲 AT 指令"
    "manual_debug": (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<path d="M7 9l3 3-3 3"/>'
        '<path d="M13 15h4"/>'
    ),
    # 用例执行：播放三角
    "case_execute": '<polygon points="6 4 20 12 6 20 6 4"/>',
    # 实时监控：活动波形 + 边框，呼应"实时数据流"
    "monitor": (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<path d="M3 13h3l2-4 3 7 2-5 2 2h6"/>'
    ),
    # 报告查看：带横线的文档
    "report_view": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5"/>'
        '<path d="M9 13h6"/><path d="M9 17h4"/>'
    ),
    # 环境配置：齿轮
    "env_config": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>'
    ),
    # ===== 动作图标（供按钮使用，非导航）=====
    # 连接：电源/插头符号
    "connect": (
        '<path d="M9 2v8"/><path d="M15 2v8"/>'
        '<path d="M6 8h12v3a6 6 0 0 1-12 0z"/>'
        '<path d="M12 17v5"/>'
    ),
    # 断开连接：插头带斜杠
    "disconnect": (
        '<path d="M9 2v6"/><path d="M15 2v6"/>'
        '<path d="M6 8h12v2a6 6 0 0 1-4 5.66"/>'
        '<path d="M12 17v5"/>'
        '<path d="M3 3l18 18"/>'
    ),
    # 添加：加号
    "add": '<path d="M12 5v14M5 12h14"/>',
    # 删除：垃圾桶
    "remove": (
        '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/>'
        '<path d="M5 6l1 14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1l1-14"/>'
        '<path d="M10 11v6M14 11v6"/>'
    ),
    # 编辑：铅笔
    "edit": (
        '<path d="M12 20h9"/>'
        '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>'
    ),
    # 发送：纸飞机
    "send": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
}


def make_icon(name: str, color: str = "#cbd5e1") -> QIcon:
    """渲染指定名称的图标为 QIcon（按当前屏幕 DPR 输出清晰位图）."""
    body = _ICONS.get(name)
    if body is None:
        body = '<circle cx="12" cy="12" r="3"/>'  # 兜底：实心点
    svg = _SVG_TPL.format(color=color, body=body).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(svg))
    # 按 DPR 放大避免锯齿；QPixmap 用物理像素；透明背景
    pix = QPixmap(_ICON_SIZE * 2)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)
