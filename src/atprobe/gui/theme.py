"""GUI 主题与设计令牌（M6 §2.2/§10.5）.

按 **design-system** 技能的三层令牌架构实现：
    PRIMITIVE（原始值）→ SEMANTIC（语义别名）→ COMPONENT（组件令牌）→ QSS

来源：ui-ux-pro-max-skill / design-system（已下载安装到 ~/.agents/skills/design-system/）。
QSS 无 CSS 变量，因此由 ``_build_qss`` 这个唯一构建函数在构建期把语义/组件令牌
插值进 QSS 字符串。组件代码只引用语义令牌，不直接读原始值。

配色为「精密仪器」主题（v0.7 视觉重塑）：深石板蓝面板 + 仪器青(P_CYAN)/信号
琥珀(P_AMBER) 双信号色（TX/RX = 示波器 CH1/CH2 隐喻）+ 柔和状态语义色。
致敬示波器/协议分析仪的硬件测试血统，替代原 GitHub Primer 蓝。
语义色与 M4 报告一致：PASS 绿 / FAIL 红 / SKIPPED 黄 / INTERRUPTED 灰。
"""

from __future__ import annotations

import base64


# ===========================================================================
# 内联图标（SVG → base64 data URI）—— 复选框三态的对勾/减号，白色，主题无关。
# 用 SVG 而非 QSS 描边，保证缩放锐利、跨主题统一（accent 色底配白色对勾）。
# ===========================================================================
def _svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


# 选中态：白色对勾（圆角线条，清晰锐利）
_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<path d="M3.5 8.5l3 3 6-7" stroke="#ffffff" stroke-width="2.4" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
# 部分选中态（目录三态）：白色短横线
_DASH_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<rect x="3.5" y="7.2" width="9" height="1.8" rx="0.9" fill="#ffffff"/></svg>'
)
CHECK_URL = _svg_data_uri(_CHECK_SVG)
DASH_URL = _svg_data_uri(_DASH_SVG)


# ===========================================================================
# 第 1 层：PRIMITIVE TOKENS —— 原始设计值，无语义含义，名称主题无关。
# 调色板对标 GitHub Primer / Tailwind v3（降饱和）。详见技能 primitive-tokens.md
# ===========================================================================

# 灰阶（中性）
P_GRAY_050 = "#f6f8fa"
P_GRAY_100 = "#eaeef2"
P_GRAY_200 = "#d0d7de"
P_GRAY_300 = "#afb8c1"
P_GRAY_400 = "#8c959f"
P_GRAY_500 = "#6e7781"
P_GRAY_600 = "#57606a"
P_GRAY_700 = "#424a53"
P_GRAY_800 = "#32383f"
P_GRAY_900 = "#24292f"
P_GRAY_950 = "#1c2128"
P_GRAY_1000 = "#0d1117"
P_WHITE = "#ffffff"
P_BLACK = "#010409"

# 蓝（历史主色，保留供浅色备选）
P_BLUE_000 = "#ddf4ff"
P_BLUE_500 = "#0969da"
P_BLUE_600 = "#0860ca"
P_BLUE_500_DK = "#2f81f7"  # 深色主题主色
P_BLUE_600_DK = "#388bfd"  # 深色主题悬停
P_BLUE_TINT_DK = "#1f6feb22"  # 深色主色浅底（带透明）

# 仪器青（signal cyan —— TX 通道/CH1/主操作，「精密仪器」主题主信号色）
P_CYAN_000 = "#cdf5f0"
P_CYAN_500 = "#1a9e92"  # 浅色主题主信号（深一档保对比）
P_CYAN_500_DK = "#4fd1c5"  # 深色主信号（CH1/TX/accent/品牌头）
P_CYAN_600_DK = "#5dd8cc"  # 深色悬停
P_CYAN_TINT_DK = "#4fd1c522"  # 深色主色浅底（带透明）

# 信号琥珀（signal amber —— RX 通道/CH2，与仪器青构成双信号色签名）
P_AMBER_600_DK = "#e8b465"  # 深色 RX/CH2（比 P_AMBER_500_DK 更亮的仪器琥珀）

# 语义色阶
P_GREEN_000 = "#dafbe1"
P_GREEN_500 = "#1a7f37"
P_GREEN_500_DK = "#3fb950"
P_GREEN_TINT_DK = "#23863622"

P_RED_000 = "#ffebe9"
P_RED_500 = "#cf222e"
P_RED_500_DK = "#f85149"
P_RED_TINT_DK = "#da363322"

P_AMBER_000 = "#fff8c5"
P_AMBER_500 = "#9a6700"
P_AMBER_500_DK = "#d29922"
P_AMBER_TINT_DK = "#bf870022"

P_NEUTRAL_TINT_DK = "#6e768122"

# 工程辅助：浅主题里次背景/凹陷区的微调值（Primer 里介于灰阶之间的实用值）
P_BG_SUBTLE_LIGHT = "#eef1f4"
P_BG_INSET_LIGHT = "#f0f3f6"
P_BORDER_MUTED_LIGHT = "#e1e4e8"
P_BORDER_SUBTLE_LIGHT = "#eaecef"
P_TEXT_PRIMARY_LIGHT = "#1f2328"
P_TEXT_SECONDARY_LIGHT = "#656d76"

# ===========================================================================
# 原始令牌：间距（4px 栅格）、圆角、字体栈 —— 跨主题共用，无需语义层。
# ===========================================================================

# 间距栅格（4 的倍数）
SPACE: dict[str, str] = {
    "1": "4px",
    "2": "8px",
    "3": "12px",
    "4": "16px",
    "5": "20px",
    "6": "24px",
    "8": "32px",
}
# 圆角
RADIUS: dict[str, str] = {
    "none": "0",
    "sm": "4px",
    "md": "6px",
    "lg": "8px",
    "xl": "12px",
    "full": "9999px",
}
# 等宽字体栈（数据/命令/响应终端 —— 工具视觉主角，仪器铭牌/终端美学）
# IBM Plex Mono 带工程仪器血统，作为 JetBrains Mono 的补充兜底
MONO_FONT = "'JetBrains Mono', 'IBM Plex Mono', 'Cascadia Code', 'Cascadia Mono', Consolas, 'Courier New', monospace"
# 比例字体栈（UI 文案）—— IBM Plex Sans 工程血统，区别于泛泛的 Segoe UI
UI_FONT = "'IBM Plex Sans', 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', 'Helvetica Neue', Arial, sans-serif"

# ===========================================================================
# 第 2 层：SEMANTIC TOKENS —— 语义别名（按用途命名），每个主题一份映射。
# 主题切换 = 换 dict。详见技能 semantic-tokens.md
# ===========================================================================

LIGHT_TOKENS: dict[str, str] = {
    # 背景（昼间仪器：冷灰白 + 卡片浮起）
    "bg.app": "#eef1f4",
    "bg.surface": P_WHITE,
    "bg.subtle": "#e6eaef",
    "bg.inset": "#f4f6f8",  # 数据屏（浅灰凹陷）
    "bg.accent.subtle": P_CYAN_000,
    # 文字（深石板墨，呼应深色主题的蓝灰血统）
    "text.primary": "#1a2530",
    "text.secondary": "#5d6b7a",
    "text.disabled": "#b0bac4",
    "text.on.accent": "#06140f",
    # 边框
    "border.default": "#d4dae1",
    "border.muted": "#e1e6ec",
    "border.subtle": "#eef1f4",
    # 主色 = 仪器青
    "accent": P_CYAN_500,
    "accent.hover": P_CYAN_600_DK,
    "accent.bg": P_CYAN_000,
    # 状态语义
    "success": "#2f9e6e",
    "success.bg": "#e3f5ec",
    "danger": "#d04545",
    "danger.bg": "#fce8e8",
    "warning": "#b07d2e",
    "warning.bg": "#fbeed4",
    "neutral": "#5d6b7a",
    "neutral.bg": "#e6eaef",
    # 领域语义（双信号色，浅底用深一档保证对比）
    "data.tx": "#1a9e92",
    "data.rx": "#b07d2e",
    # 侧栏（昼间仍偏深，保持「控制面板」分区）
    "sidebar.bg": "#1a2530",
    "sidebar.header.bg": "#0f1721",
    "sidebar.header.text": P_CYAN_500_DK,
    "sidebar.item.text": "#b0bac4",
    "sidebar.item.text.selected": "#cbd5dc",
    # 阴影
    "shadow.md": "rgba(26,37,48,0.08)",
    "shadow.lg": "rgba(26,37,48,0.12)",
}

DARK_TOKENS: dict[str, str] = {
    # 背景（仪器面板层次：app 外壳 → 卡片浮起 → inset 屏幕凹陷最深）
    "bg.app": "#0d141b",  # 深石板蓝（仪器外壳）
    "bg.surface": "#161e27",  # 卡片/面板
    "bg.subtle": "#1c2530",  # 次表面
    "bg.inset": "#0a1016",  # 数据屏凹陷（比外壳更深）
    "bg.accent.subtle": P_CYAN_TINT_DK,
    # 文字（冷白系，不刺眼）
    "text.primary": "#d4dde6",
    "text.secondary": "#7d8a99",
    "text.disabled": "#4a5563",
    "text.on.accent": "#06140f",  # 青底用深墨（仪器感）
    # 边框
    "border.default": "#2a3441",
    "border.muted": "#1f2832",
    "border.subtle": "#161e27",
    # 主色 = 仪器青（CH1/TX/选中/主操作，统一「主动信号」语言）
    "accent": P_CYAN_500_DK,
    "accent.hover": P_CYAN_600_DK,
    "accent.bg": P_CYAN_TINT_DK,
    # 状态语义（柔和，不刺眼）
    "success": "#5ec98a",
    "success.bg": "#5ec98a22",
    "danger": "#ef6b6b",
    "danger.bg": "#ef6b6b22",
    "warning": P_AMBER_600_DK,
    "warning.bg": "#e8b46522",
    "neutral": "#7d8a99",
    "neutral.bg": "#7d8a9922",
    # 领域语义（双信号色签名：CH1 青 / CH2 琥珀）
    "data.tx": P_CYAN_500_DK,
    "data.rx": P_AMBER_600_DK,
    # 侧栏（仪器暗区控制面板，比内容区更深）
    "sidebar.bg": "#0a0f15",
    "sidebar.header.bg": "#060a0e",
    "sidebar.header.text": P_CYAN_500_DK,  # 品牌头仪器青，像铭牌发光字
    "sidebar.item.text": "#7d8a99",
    "sidebar.item.text.selected": "#cbd5dc",  # 侧栏图标色（深底/青底均可见）
    # 阴影
    "shadow.md": "rgba(0,0,0,0.35)",
    "shadow.lg": "rgba(0,0,0,0.5)",
}


# ===========================================================================
# 第 3 层：COMPONENT TOKENS —— 组件令牌，绑定语义令牌到具体控件子部位。
# 这是「用途→控件」的桥梁。详见技能 component-tokens.md
# QSS 无变量，故此处以 Python 闭包形式在 _build_qss 内消费，保证单一事实源。
# ===========================================================================


def _build_qss(t: dict[str, str]) -> str:
    """根据语义令牌字典生成完整 QSS（组件令牌在此处就地解析并插值）.

    这是唯一的 QSS 构建函数：组件令牌 → 语义令牌 → QSS 字符串。
    组件代码永远只引用语义令牌，不直接读原始值。
    """
    # 组件令牌在此处就地绑定到语义令牌（component-tokens.md 的实现）
    btn_radius = RADIUS["md"]
    input_radius = RADIUS["md"]
    data_radius = RADIUS["md"]
    card_radius = RADIUS["lg"]
    pill_radius = RADIUS["full"]
    return f"""
    /* ===== 全局 ===== */
    * {{
        font-family: {UI_FONT};
        font-size: 14px;
        color: {t["text.primary"]};
    }}
    QMainWindow, QWidget {{
        background: {t["bg.app"]};
    }}

    /* ===== 菜单栏 ===== */
    QMenuBar {{
        background: {t["bg.surface"]};
        border: none;
        border-bottom: 1px solid {t["border.muted"]};
        padding: 2px 4px;
    }}
    QMenuBar::item {{ padding: 6px 10px; border-radius: {btn_radius}; }}
    QMenuBar::item:selected {{ background: {t["bg.subtle"]}; }}

    /* ===== 工具栏 ===== */
    QToolBar {{
        background: {t["bg.surface"]};
        border: none;
        border-bottom: 1px solid {t["border.muted"]};
        spacing: 6px;
        padding: 6px 10px;
    }}

    /* ===== 按钮：default / primary / danger 三变体（states-and-variants.md） ===== */
    QPushButton {{
        background: {t["bg.surface"]};
        border: 1px solid {t["border.default"]};
        border-radius: {btn_radius};
        padding: 6px 16px;
        color: {t["text.primary"]};
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {t["bg.subtle"]}; border-color: {t["text.secondary"]}; }}
    QPushButton:pressed {{ background: {t["border.muted"]}; }}
    QPushButton:disabled {{ color: {t["text.disabled"]}; border-color: {t["border.muted"]}; }}
    QPushButton:checked {{
        background: {t["accent"]};
        color: {t["text.on.accent"]};
        border-color: {t["accent"]};
        font-weight: 600;
    }}
    QPushButton:checked:hover {{ background: {t["accent.hover"]}; }}

    /* 主按钮变体（objectName="primary"） */
    QPushButton#primary {{
        background: {t["accent"]};
        color: {t["text.on.accent"]};
        border-color: {t["accent"]};
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {t["accent.hover"]}; border-color: {t["accent.hover"]}; }}
    QPushButton#primary:pressed {{ background: {t["accent.hover"]}; }}

    /* 危险按钮变体（objectName="danger"） */
    QPushButton#danger {{
        color: {t["danger"]};
        border-color: {t["danger.bg"]};
    }}
    QPushButton#danger:hover {{ background: {t["danger.bg"]}; }}

    /* ===== 输入框 / 下拉 / 数值框（component-tokens.md: input.*） ===== */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {t["bg.surface"]};
        border: 1px solid {t["border.default"]};
        border-radius: {input_radius};
        padding: 5px 10px;
        selection-background-color: {t["accent"]};
        selection-color: {t["text.on.accent"]};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {t["accent"]};
    }}
    QLineEdit:disabled {{ color: {t["text.disabled"]}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {t["bg.surface"]};
        border: 1px solid {t["border.default"]};
        border-radius: {input_radius};
        selection-background-color: {t["accent.bg"]};
        selection-color: {t["accent"]};
        padding: 4px;
        outline: none;
    }}

    /* ===== 数据区（终端/日志：凹陷感 + 等宽，component-tokens.md: data.*） ===== */
    QTextEdit, QPlainTextEdit {{
        background: {t["bg.inset"]};
        border: 1px solid {t["border.muted"]};
        border-radius: {data_radius};
        padding: 8px;
        font-family: {MONO_FONT};
        font-size: 12px;
        selection-background-color: {t["accent.bg"]};
        selection-color: {t["text.primary"]};
    }}

    /* ===== 分组框（卡片：白底 + 柔和边框 + 轻阴影，在灰背景上浮起） ===== */
    QGroupBox {{
        background: {t["bg.surface"]};
        border: 1px solid {t["border.muted"]};
        border-radius: {card_radius};
        margin-top: 16px;
        padding: 18px 14px 14px 14px;
        font-weight: 600;
        color: {t["text.primary"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 14px;
        padding: 0 6px;
        background: {t["bg.app"]};
        color: {t["text.secondary"]};
    }}

    /* ===== 选项卡（内容面板：白底卡片，与 tab 栏无缝衔接） ===== */
    QTabWidget::pane {{
        border: 1px solid {t["border.muted"]};
        border-top: none;
        border-radius: 0;
        top: -1px;
        background: {t["bg.app"]};
    }}
    QTabWidget > QWidget {{
        background: {t["bg.app"]};
    }}
    QTabBar {{
        background: {t["bg.app"]};
        qproperty-drawBase: 0;
    }}
    QTabBar::tab {{
        background: transparent;
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
        border-top-left-radius: {btn_radius};
        border-top-right-radius: {btn_radius};
        padding: 9px 20px;
        margin-right: 2px;
        color: {t["text.secondary"]};
        font-weight: 500;
    }}
    QTabBar::tab:hover:!selected {{ background: {t["bg.subtle"]}; color: {t["text.primary"]}; }}
    QTabBar::tab:selected {{
        background: {t["bg.surface"]};
        color: {t["text.primary"]};
        border-color: {t["border.muted"]};
        border-bottom: 2px solid {t["accent"]};
        font-weight: 600;
    }}
    QTabBar::close-button {{
        image: none;
        subcontrol-position: right;
        padding: 2px;
        border-radius: {RADIUS["sm"]};
    }}
    QTabBar::close-button:hover {{ background: {t["danger.bg"]}; }}

    /* ===== 表格（component-tokens.md: table.*） ===== */
    QTableWidget {{
        background: {t["bg.surface"]};
        border: 1px solid {t["border.muted"]};
        border-radius: {data_radius};
        gridline-color: {t["border.subtle"]};
        alternate-background-color: {t["bg.subtle"]};
        font-family: {UI_FONT};
        font-size: 13px;
        outline: none;
    }}
    QTableWidget::item {{ padding: 8px 10px; border: none; }}
    QTableWidget::item:hover {{ background: {t["bg.subtle"]}; }}
    QTableWidget::item:selected {{ background: {t["accent.bg"]}; color: {t["accent"]}; }}

    /* ===== 树（component-tokens.md: table.* 复用——目录层级树，卡片感） ===== */
    QTreeWidget, QTreeView {{
        background: {t["bg.surface"]};
        border: 1px solid {t["border.muted"]};
        border-radius: {data_radius};
        alternate-background-color: {t["bg.subtle"]};
        font-family: {UI_FONT};
        font-size: 13px;
        outline: none;
    }}
    QTreeWidget::item, QTreeView::item {{ padding: 6px 4px; border: none; }}
    QTreeWidget::item:hover, QTreeView::item:hover {{ background: {t["accent.bg"]}; }}
    QTreeWidget::item:selected, QTreeView::item:selected {{
        background: {t["accent.bg"]};
        color: {t["accent"]};
        font-weight: 600;
    }}
    /* 分支线（连接父子的虚线）：低对比，不喧宾夺主 */
    QTreeView::branch {{
        background: transparent;
    }}
    QTreeView::branch:has-siblings:!adjoins-item {{
        background: {t["bg.subtle"]};
    }}
    /* 树内置复选框（三态）—— 与 QCheckBox::indicator 视觉统一，覆盖 Qt 原生丑样式 */
    QTreeView::indicator, QTreeWidget::indicator {{
        width: 16px; height: 16px;
        border: 1.5px solid {t["border.default"]};
        border-radius: {RADIUS["sm"]};
        background: {t["bg.surface"]};
    }}
    QTreeView::indicator:hover, QTreeWidget::indicator:hover, QTreeView::indicator:focus {{
        border-color: {t["accent"]};
    }}
    QTreeView::indicator:checked, QTreeWidget::indicator:checked {{
        background: {t["accent"]};
        border-color: {t["accent"]};
        image: url("{CHECK_URL}");
    }}
    QTreeView::indicator:indeterminate, QTreeWidget::indicator:indeterminate {{
        background: {t["accent"]};
        border-color: {t["accent"]};
        image: url("{DASH_URL}");
    }}
    QHeaderView::section {{
        background: {t["bg.subtle"]};
        border: none;
        border-right: 1px solid {t["border.subtle"]};
        border-bottom: 1px solid {t["border.muted"]};
        padding: 8px 10px;
        font-weight: 600;
        color: {t["text.secondary"]};
    }}

    /* ===== 普通列表（非导航，如报告列表）—— 卡片感 ===== */
    QListWidget, QListView {{
        background: {t["bg.surface"]};
        border: 1px solid {t["border.muted"]};
        border-radius: {data_radius};
        padding: 6px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 10px 14px;
        border-radius: {btn_radius};
        margin: 1px 0;
        color: {t["text.primary"]};
    }}
    QListWidget::item:hover {{ background: {t["bg.subtle"]}; }}
    QListWidget::item:selected {{
        background: {t["accent.bg"]};
        color: {t["accent"]};
        font-weight: 600;
    }}

    /* ===== 侧栏容器（深色品牌导航栏，制造「导航 vs 内容」强分区） ===== */
    QFrame#sidebar {{
        background: {t["sidebar.bg"]};
        border: none;
        border-right: 1px solid {t["sidebar.header.bg"]};
    }}
    /* 品牌头 */
    QLabel#sidebarHeader {{
        background: {t["sidebar.header.bg"]};
        color: {t["sidebar.header.text"]};
        padding: 18px 16px;
        font-family: {MONO_FONT};
        font-size: 16px;
        font-weight: 700;
        letter-spacing: 2px;
        border: none;
    }}
    /* 导航列表 —— 深色栏上的浅色项 */
    QListWidget#sidebarList {{
        background: {t["sidebar.bg"]};
        border: none;
        border-radius: 0;
        padding: 10px 8px;
        outline: none;
        font-size: 13px;
    }}
    QListWidget#sidebarList::item {{
        padding: 11px 14px;
        border-radius: {btn_radius};
        margin: 2px 0;
        color: {t["sidebar.item.text"]};
        font-weight: 500;
    }}
    QListWidget#sidebarList::item:hover {{
        background: rgba(255,255,255,0.06);
        color: {t["sidebar.item.text.selected"]};
    }}
    QListWidget#sidebarList::item:selected {{
        background: {t["accent"]};
        color: {t["text.on.accent"]};
        font-weight: 600;
    }}

    /* ===== 停靠部件（侧栏容器：移除原生标题栏，无装饰） ===== */
    QDockWidget {{
        border: none;
        padding: 0;
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget::title {{
        background: transparent;
        border: none;
        padding: 0;
    }}

    /* ===== 状态栏（component-tokens.md: statusbar.*，语义点而非彩色文字） ===== */
    QStatusBar {{
        background: {t["bg.surface"]};
        border-top: 1px solid {t["border.muted"]};
        color: {t["text.secondary"]};
        padding: 2px 8px;
    }}
    QStatusBar::item {{ border: none; }}

    /* ===== 滚动条（细、圆润、低对比） ===== */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["border.default"]};
        border-radius: {pill_radius};
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t["text.secondary"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t["border.default"]};
        border-radius: {pill_radius};
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {t["text.secondary"]}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ===== 复选框 / 单选 ===== */
    QCheckBox, QRadioButton {{ spacing: 6px; padding: 2px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px;
        border: 1.5px solid {t["border.default"]};
        border-radius: {RADIUS["sm"]};
        background: {t["bg.surface"]};
    }}
    QRadioButton::indicator {{ border-radius: {pill_radius}; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t["accent"]}; }}
    QCheckBox::indicator:checked {{
        background: {t["accent"]};
        border-color: {t["accent"]};
        image: url("{CHECK_URL}");
    }}

    /* ===== 标签（弱化次要文字） ===== */
    QLabel {{ background: transparent; }}
    QLabel#hint, QLabel#caption {{ color: {t["text.secondary"]}; font-size: 12px; }}

    /* ===== 滚动区域 ===== */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    /* ===== 提示：QToolTip ===== */
    QToolTip {{
        background: {t["text.primary"]};
        color: {t["bg.surface"]};
        border: none;
        border-radius: {RADIUS["sm"]};
        padding: 4px 8px;
    }}
    """


# 预生成的 QSS（供 apply_theme 使用）
LIGHT_QSS = _build_qss(LIGHT_TOKENS)
DARK_QSS = _build_qss(DARK_TOKENS)

# ===========================================================================
# 全局主题状态（运行时单一事实源）
# ===========================================================================
# 各视图调 get_tokens()（无参）取当前主题令牌；set_theme() 切换并重应用 QSS。
# 这样主题切换不需逐视图传参，也不依赖 QApplication 单例的反查。
_THEME_DARK: bool = False


def current_theme_is_dark() -> bool:
    """当前是否深色主题."""
    return _THEME_DARK


def get_tokens(dark: bool | None = None) -> dict[str, str]:
    """获取主题的语义令牌字典.

    dark=None（默认）取当前全局主题；显式传 bool 取指定主题。
    供视图内联配色使用（如 TX/RX 方向色、状态点颜色）。返回语义令牌，
    调用方应引用语义键（``t['data.tx']`` / ``t['success']`` 等），不直接读原始值。
    """
    use_dark = _THEME_DARK if dark is None else dark
    return DARK_TOKENS if use_dark else LIGHT_TOKENS


def apply_theme(app: object, dark: bool = False) -> None:
    """应用主题到 QApplication，并更新全局主题状态."""
    global _THEME_DARK  # noqa: PLW0603
    _THEME_DARK = dark
    app.setStyleSheet(DARK_QSS if dark else LIGHT_QSS)  # type: ignore[attr-defined]
