"""选项卡类型注册表（M6 §2.3/§10.5 插件化扩展机制）.

新增功能 = 注册一个新选项卡类型 + 实现其内容视图，无需改动主框架。
侧边栏、状态栏、选项卡栏作为稳定外壳。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class TabBinding:
    """选项卡实例的绑定参数（如绑定的端口、用例集、报告文件等）."""

    type_name: str
    # 各类型自定义参数，放 kwargs
    params: dict[str, object]


class ITabView(Protocol):
    """选项卡视图接口（§2.3 选项卡类型注册表契约）."""

    type_name: str
    display_name: str  # 侧边栏/菜单显示名

    def create_widget(self, binding: TabBinding, main_window: object) -> "QWidget":
        """创建选项卡内容 widget（返回 QWidget）。main_window 用于访问引擎等共享资源."""
        ...

    def icon_name(self) -> str:
        """图标标识（主题图标库中的键）."""
        ...


class TabTypeRegistry:
    """选项卡类型注册表（§2.3）."""

    def __init__(self) -> None:
        self._types: dict[str, ITabView] = {}

    def register(self, view: ITabView) -> None:
        self._types[view.type_name] = view

    def get(self, type_name: str) -> ITabView | None:
        return self._types.get(type_name)

    def types(self) -> list[str]:
        return list(self._types.keys())

    def display_names(self) -> dict[str, str]:
        return {name: view.display_name for name, view in self._types.items()}


def default_registry() -> TabTypeRegistry:
    """构造默认注册表（注册第一阶段选项卡类型）."""
    from atprobe.gui.tabs.case_execute import CaseExecuteTab
    from atprobe.gui.tabs.env_config import EnvConfigTab
    from atprobe.gui.tabs.manual_debug import ManualDebugTab
    from atprobe.gui.tabs.monitor import MonitorTab
    from atprobe.gui.tabs.report_view import ReportViewTab

    reg = TabTypeRegistry()
    reg.register(ManualDebugTab())
    reg.register(CaseExecuteTab())
    reg.register(MonitorTab())
    reg.register(ReportViewTab())
    reg.register(EnvConfigTab())
    return reg
