"""GUI 主题与设计令牌（M6 §2.2/§10.5）.

按 **design-system** 技能的三层令牌架构实现：
    PRIMITIVE（原始值）→ SEMANTIC（语义别名）→ COMPONENT（组件令牌）→ QSS

来源：ui-ux-pro-max-skill / design-system（已下载安装到 ~/.agents/skills/design-system/）。
QSS 无 CSS 变量，因此由 ``_build_qss`` 这个唯一构建函数在构建期把语义/组件令牌
插值进 QSS 字符串。组件代码只引用语义令牌，不直接读原始值。

配色对标 GitHub / VS Code 现代风格（降饱和，非 Material 2014 高饱和）。
语义色与 M4 报告一致：PASS 绿 / FAIL 红 / SKIPPED 黄 / INTERRUPTED 灰。
"""

from __future__ import annotations

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

# 蓝（主色）
P_BLUE_000 = "#ddf4ff"
P_BLUE_500 = "#0969da"
P_BLUE_600 = "#0860ca"
P_BLUE_500_DK = "#2f81f7"  # 深色主题主色
P_BLUE_600_DK = "#388bfd"  # 深色主题悬停
P_BLUE_TINT_DK = "#1f6feb22"  # 深色主色浅底（带透明）

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
    "1": "4px", "2": "8px", "3": "12px", "4": "16px",
    "5": "20px", "6": "24px", "8": "32px",
}
# 圆角
RADIUS: dict[str, str] = {
    "none": "0", "sm": "4px", "md": "6px", "lg": "8px", "xl": "12px", "full": "9999px",
}
# 等宽字体栈（仅用于数据/日志/AT 指令区）
MONO_FONT = "'JetBrains Mono', 'Cascadia Code', 'Cascadia Mono', Consolas, 'Courier New', monospace"
# 比例字体栈（UI 文案）
UI_FONT = "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', 'Helvetica Neue', Arial, sans-serif"

# ===========================================================================
# 第 2 层：SEMANTIC TOKENS —— 语义别名（按用途命名），每个主题一份映射。
# 主题切换 = 换 dict。详见技能 semantic-tokens.md
# ===========================================================================

LIGHT_TOKENS: dict[str, str] = {
    # 背景（app 比卡片深一档，制造「卡片浮起」的层次感）
    "bg.app": "#e8ecf0",
    "bg.surface": P_WHITE,
    "bg.subtle": P_BG_SUBTLE_LIGHT,
    "bg.inset": P_BG_INSET_LIGHT,
    "bg.accent.subtle": P_BLUE_000,
    # 文字
    "text.primary": P_TEXT_PRIMARY_LIGHT,
    "text.secondary": P_TEXT_SECONDARY_LIGHT,
    "text.disabled": P_GRAY_300,
    "text.on.accent": P_WHITE,
    # 边框
    "border.default": P_GRAY_200,
    "border.muted": P_BORDER_MUTED_LIGHT,
    "border.subtle": P_BORDER_SUBTLE_LIGHT,
    # 主色
    "accent": P_BLUE_500,
    "accent.hover": P_BLUE_600,
    "accent.bg": P_BLUE_000,
    # 状态语义（降饱和）
    "success": P_GREEN_500,
    "success.bg": P_GREEN_000,
    "danger": P_RED_500,
    "danger.bg": P_RED_000,
    "warning": P_AMBER_500,
    "warning.bg": P_AMBER_000,
    "neutral": P_GRAY_500,
    "neutral.bg": P_GRAY_100,
    # 领域语义（串口数据方向）
    "data.tx": P_BLUE_500,
    "data.rx": P_TEXT_PRIMARY_LIGHT,
    # 侧栏品牌区（比 surface 更深的栏背景，制造「导航 vs 内容」分区）
    "sidebar.bg": "#1f2937",
    "sidebar.header.bg": "#111827",
    "sidebar.header.text": P_WHITE,
    "sidebar.item.text": "#cbd5e1",
    "sidebar.item.text.selected": P_WHITE,
    # 阴影
    "shadow.md": "rgba(31,35,40,0.08)",
    "shadow.lg": "rgba(31,35,40,0.12)",
}

DARK_TOKENS: dict[str, str] = {
    "bg.app": "#060a10",
    "bg.surface": "#161b22",
    "bg.subtle": P_GRAY_950,
    "bg.inset": P_BLACK,
    "bg.accent.subtle": P_BLUE_TINT_DK,
    "text.primary": "#e6edf3",
    "text.secondary": "#8b949e",
    "text.disabled": "#484f58",
    "text.on.accent": P_WHITE,
    "border.default": "#30363d",
    "border.muted": "#21262d",
    "border.subtle": P_GRAY_950,
    "accent": P_BLUE_500_DK,
    "accent.hover": P_BLUE_600_DK,
    "accent.bg": P_BLUE_TINT_DK,
    "success": P_GREEN_500_DK,
    "success.bg": P_GREEN_TINT_DK,
    "danger": P_RED_500_DK,
    "danger.bg": P_RED_TINT_DK,
    "warning": P_AMBER_500_DK,
    "warning.bg": P_AMBER_TINT_DK,
    "neutral": "#8b949e",
    "neutral.bg": P_NEUTRAL_TINT_DK,
    "data.tx": "#58a6ff",
    "data.rx": "#e6edf3",
    "sidebar.bg": "#0b1117",
    "sidebar.header.bg": "#000000",
    "sidebar.header.text": "#f3f4f6",
    "sidebar.item.text": "#9ca3af",
    "sidebar.item.text.selected": P_WHITE,
    "shadow.md": "rgba(1,4,9,0.3)",
    "shadow.lg": "rgba(1,4,9,0.5)",
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
        font-size: 13px;
        color: {t['text.primary']};
    }}
    QMainWindow, QWidget {{
        background: {t['bg.app']};
    }}

    /* ===== 菜单栏 ===== */
    QMenuBar {{
        background: {t['bg.surface']};
        border: none;
        border-bottom: 1px solid {t['border.muted']};
        padding: 2px 4px;
    }}
    QMenuBar::item {{ padding: 6px 10px; border-radius: {btn_radius}; }}
    QMenuBar::item:selected {{ background: {t['bg.subtle']}; }}

    /* ===== 工具栏 ===== */
    QToolBar {{
        background: {t['bg.surface']};
        border: none;
        border-bottom: 1px solid {t['border.muted']};
        spacing: 6px;
        padding: 6px 10px;
    }}

    /* ===== 按钮：default / primary / danger 三变体（states-and-variants.md） ===== */
    QPushButton {{
        background: {t['bg.surface']};
        border: 1px solid {t['border.default']};
        border-radius: {btn_radius};
        padding: 6px 16px;
        color: {t['text.primary']};
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {t['bg.subtle']}; border-color: {t['text.secondary']}; }}
    QPushButton:pressed {{ background: {t['border.muted']}; }}
    QPushButton:disabled {{ color: {t['text.disabled']}; border-color: {t['border.muted']}; }}
    QPushButton:checked {{
        background: {t['accent']};
        color: {t['text.on.accent']};
        border-color: {t['accent']};
        font-weight: 600;
    }}
    QPushButton:checked:hover {{ background: {t['accent.hover']}; }}

    /* 主按钮变体（objectName="primary"） */
    QPushButton#primary {{
        background: {t['accent']};
        color: {t['text.on.accent']};
        border-color: {t['accent']};
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {t['accent.hover']}; border-color: {t['accent.hover']}; }}
    QPushButton#primary:pressed {{ background: {t['accent.hover']}; }}

    /* 危险按钮变体（objectName="danger"） */
    QPushButton#danger {{
        color: {t['danger']};
        border-color: {t['danger.bg']};
    }}
    QPushButton#danger:hover {{ background: {t['danger.bg']}; }}

    /* ===== 输入框 / 下拉 / 数值框（component-tokens.md: input.*） ===== */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {t['bg.surface']};
        border: 1px solid {t['border.default']};
        border-radius: {input_radius};
        padding: 5px 10px;
        selection-background-color: {t['accent']};
        selection-color: {t['text.on.accent']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {t['accent']};
    }}
    QLineEdit:disabled {{ color: {t['text.disabled']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {t['bg.surface']};
        border: 1px solid {t['border.default']};
        border-radius: {input_radius};
        selection-background-color: {t['accent.bg']};
        selection-color: {t['accent']};
        padding: 4px;
        outline: none;
    }}

    /* ===== 数据区（终端/日志：凹陷感 + 等宽，component-tokens.md: data.*） ===== */
    QTextEdit, QPlainTextEdit {{
        background: {t['bg.inset']};
        border: 1px solid {t['border.muted']};
        border-radius: {data_radius};
        padding: 8px;
        font-family: {MONO_FONT};
        font-size: 12px;
        selection-background-color: {t['accent.bg']};
        selection-color: {t['text.primary']};
    }}

    /* ===== 分组框（卡片：白底 + 柔和边框 + 轻阴影，在灰背景上浮起） ===== */
    QGroupBox {{
        background: {t['bg.surface']};
        border: 1px solid {t['border.muted']};
        border-radius: {card_radius};
        margin-top: 16px;
        padding: 18px 14px 14px 14px;
        font-weight: 600;
        color: {t['text.primary']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 14px;
        padding: 0 6px;
        background: {t['bg.app']};
        color: {t['text.secondary']};
    }}

    /* ===== 选项卡（内容面板：白底卡片，与 tab 栏无缝衔接） ===== */
    QTabWidget::pane {{
        border: 1px solid {t['border.muted']};
        border-top: none;
        border-radius: 0;
        top: -1px;
        background: {t['bg.app']};
    }}
    QTabWidget > QWidget {{
        background: {t['bg.app']};
    }}
    QTabBar {{
        background: {t['bg.app']};
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
        color: {t['text.secondary']};
        font-weight: 500;
    }}
    QTabBar::tab:hover:!selected {{ background: {t['bg.subtle']}; color: {t['text.primary']}; }}
    QTabBar::tab:selected {{
        background: {t['bg.surface']};
        color: {t['text.primary']};
        border-color: {t['border.muted']};
        border-bottom: 2px solid {t['accent']};
        font-weight: 600;
    }}
    QTabBar::close-button {{
        image: none;
        subcontrol-position: right;
        padding: 2px;
        border-radius: {RADIUS['sm']};
    }}
    QTabBar::close-button:hover {{ background: {t['danger.bg']}; }}

    /* ===== 表格（component-tokens.md: table.*） ===== */
    QTableWidget {{
        background: {t['bg.surface']};
        border: 1px solid {t['border.muted']};
        border-radius: {data_radius};
        gridline-color: {t['border.subtle']};
        alternate-background-color: {t['bg.subtle']};
        font-family: {UI_FONT};
        font-size: 13px;
        outline: none;
    }}
    QTableWidget::item {{ padding: 8px 10px; border: none; }}
    QTableWidget::item:hover {{ background: {t['bg.subtle']}; }}
    QTableWidget::item:selected {{ background: {t['accent.bg']}; color: {t['accent']}; }}
    QHeaderView::section {{
        background: {t['bg.subtle']};
        border: none;
        border-right: 1px solid {t['border.subtle']};
        border-bottom: 1px solid {t['border.muted']};
        padding: 8px 10px;
        font-weight: 600;
        color: {t['text.secondary']};
    }}

    /* ===== 普通列表（非导航，如报告列表）—— 卡片感 ===== */
    QListWidget, QListView {{
        background: {t['bg.surface']};
        border: 1px solid {t['border.muted']};
        border-radius: {data_radius};
        padding: 6px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 10px 14px;
        border-radius: {btn_radius};
        margin: 1px 0;
        color: {t['text.primary']};
    }}
    QListWidget::item:hover {{ background: {t['bg.subtle']}; }}
    QListWidget::item:selected {{
        background: {t['accent.bg']};
        color: {t['accent']};
        font-weight: 600;
    }}

    /* ===== 侧栏容器（深色品牌导航栏，制造「导航 vs 内容」强分区） ===== */
    QFrame#sidebar {{
        background: {t['sidebar.bg']};
        border: none;
        border-right: 1px solid {t['sidebar.header.bg']};
    }}
    /* 品牌头 */
    QLabel#sidebarHeader {{
        background: {t['sidebar.header.bg']};
        color: {t['sidebar.header.text']};
        padding: 18px 16px;
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 1px;
        border: none;
    }}
    /* 导航列表 —— 深色栏上的浅色项 */
    QListWidget#sidebarList {{
        background: {t['sidebar.bg']};
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
        color: {t['sidebar.item.text']};
        font-weight: 500;
    }}
    QListWidget#sidebarList::item:hover {{
        background: rgba(255,255,255,0.06);
        color: {t['sidebar.item.text.selected']};
    }}
    QListWidget#sidebarList::item:selected {{
        background: {t['accent']};
        color: {t['text.on.accent']};
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
        background: {t['bg.surface']};
        border-top: 1px solid {t['border.muted']};
        color: {t['text.secondary']};
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
        background: {t['border.default']};
        border-radius: {pill_radius};
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t['text.secondary']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['border.default']};
        border-radius: {pill_radius};
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {t['text.secondary']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ===== 复选框 / 单选 ===== */
    QCheckBox, QRadioButton {{ spacing: 6px; padding: 2px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {t['border.default']};
        border-radius: {RADIUS['sm']};
        background: {t['bg.surface']};
    }}
    QRadioButton::indicator {{ border-radius: {pill_radius}; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t['accent']}; }}
    QCheckBox::indicator:checked {{
        background: {t['accent']};
        border-color: {t['accent']};
    }}

    /* ===== 标签（弱化次要文字） ===== */
    QLabel {{ background: transparent; }}
    QLabel#hint, QLabel#caption {{ color: {t['text.secondary']}; font-size: 12px; }}

    /* ===== 滚动区域 ===== */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    /* ===== 提示：QToolTip ===== */
    QToolTip {{
        background: {t['text.primary']};
        color: {t['bg.surface']};
        border: none;
        border-radius: {RADIUS['sm']};
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
