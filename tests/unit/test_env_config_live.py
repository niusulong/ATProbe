"""环境配置页「改完即生效」回归测试（issue: UI 编辑值与用例执行脱节）.

验证 EnvConfigWidget 的内存 EnvConfig 随文本编辑实时更新，以及 dirty/save_if_dirty
保证内存=磁盘单一数据源。用现有 qapp fixture（见 tests/integration/test_gui.py），
不依赖 pytest-qt。

注意：不直接测 Qt 信号连接（脆弱），测公共方法契约（current_env/is_dirty/save_if_dirty）。
"""

from __future__ import annotations

from pathlib import Path

from atprobe.gui.tabs.env_config import EnvConfigWidget
from atprobe.gui.tabs.registry import TabBinding


def _make_widget(qapp, main_window) -> EnvConfigWidget:  # type: ignore[no-untyped-def]
    return EnvConfigWidget(TabBinding(type_name="env_config", params={}), main_window)


class _FakeMain:
    """最小 MainWindow 替身：只提供 env_config_path（EnvConfigWidget 初始化会调）."""

    def __init__(self, env_path: str | None = None) -> None:
        self._env_path = env_path

    def env_config_path(self) -> str | None:
        return self._env_path


def test_current_env_reflects_text_edit_without_save(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """编辑文本框后，current_env() 立即反映新值，无需点保存（所见即所跑核心契约）."""
    env_file = tmp_path / "env.yaml"
    env_file.write_text("http:\n  url: old.com\n", encoding="utf-8")
    w = _make_widget(qapp, _FakeMain(str(env_file)))

    # 初始值
    assert w.current_env().resolve_str("http.url") == "old.com"

    # 改文本框（不点保存）
    w._group_widgets["http"]["url"].setText("new.com")

    # current_env 立即反映新值
    assert w.current_env().resolve_str("http.url") == "new.com"


def test_is_dirty_true_after_edit_and_false_after_save(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """编辑后 is_dirty()==True；save_if_dirty 后 False 且磁盘更新."""
    env_file = tmp_path / "env.yaml"
    env_file.write_text("http:\n  url: old.com\n", encoding="utf-8")
    w = _make_widget(qapp, _FakeMain(str(env_file)))

    assert w.is_dirty() is False  # 初始与磁盘一致

    w._group_widgets["http"]["url"].setText("edited.com")
    assert w.is_dirty() is True

    w.save_if_dirty()
    assert w.is_dirty() is False
    # 磁盘已更新
    assert "edited.com" in env_file.read_text(encoding="utf-8")


def test_save_if_dirty_noop_when_clean(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """无改动时 save_if_dirty 不写盘（mtime 不变）."""
    env_file = tmp_path / "env.yaml"
    env_file.write_text("http:\n  url: a.com\n", encoding="utf-8")
    w = _make_widget(qapp, _FakeMain(str(env_file)))
    mtime_before = env_file.stat().st_mtime_ns

    w.save_if_dirty()

    assert env_file.stat().st_mtime_ns == mtime_before


def test_current_env_empty_not_none(qapp) -> None:  # type: ignore[no-untyped-def]
    """空表单 current_env() 返回空 EnvConfig（非 None），保证 run_cases 不中断."""
    w = _make_widget(qapp, _FakeMain(None))
    env = w.current_env()
    assert env is not None
    assert env.is_empty()


def test_save_if_dirty_skips_when_no_path(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """从未保存过（path=None）时 save_if_dirty 不抛异常、不写盘；run_cases 仍用内存值."""
    w = _make_widget(qapp, _FakeMain(None))
    # 触发一次 collect
    w._group_widgets.setdefault("http", {})
    # path 为 None → save_if_dirty 直接返回（不报错）
    w.save_if_dirty()  # 不抛异常即可
    assert w.current_env().is_empty()
