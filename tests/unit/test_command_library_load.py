"""快捷命令管理对话框「加载」功能回归测试（issue: 加载后不生效）。

验证「加载」语义 = 导入到当前库：
- _on_load_file 只替换内存工作副本，不改提交目标 path（**真正调用 _on_load_file**）
- 确定后内容写入当前活动库文件（而非被加载的源文件）
- 取消则丢弃（对话框工作副本语义不变）

用 monkeypatch 绕开 QFileDialog，真正执行 _on_load_file 全流程。
用现有 qapp fixture（见 conftest.py），不依赖 pytest-qt。
"""

from __future__ import annotations

from pathlib import Path

from atprobe.domain.quickcmd import CommandLibrary
from atprobe.gui.widgets import command_library as cl_mod
from atprobe.gui.widgets.command_library import LibraryManagerDialog
from atprobe.infra.quickcmd import dump_library, load_library


def _make_library() -> CommandLibrary:
    """构造含一个命令的库."""
    lib = CommandLibrary.empty()
    lib.add_project("P1")
    grp = lib.add_group("P1", "G1")
    grp.commands.append("AT+OLD")
    return lib


def _patch_open_file_dialog(monkeypatch, path: Path) -> None:  # type: ignore[no-untyped-def]
    """让 QFileDialog.getOpenFileName 返回 path（绕开真实文件对话框）。"""
    monkeypatch.setattr(
        cl_mod.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(path), "")),
    )


def test_load_does_not_change_commit_target(qapp, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """_on_load_file 后 self._path 不变（提交目标仍是当前活动库）。

    这是修复的核心点：之前 _on_load_file 会把 self._path 改成源文件路径。
    本测试真正调用 _on_load_file（经 monkeypatch 绕开文件对话框）。
    """
    active = tmp_path / "quick_commands.yaml"
    lib = _make_library()
    dump_library(lib, active)

    src = tmp_path / "other.yaml"
    src_lib = CommandLibrary.empty()
    src_lib.add_project("Other")
    dump_library(src_lib, src)

    dlg = LibraryManagerDialog(lib, active)
    path_before = dlg.current_path()

    _patch_open_file_dialog(monkeypatch, src)
    dlg._on_load_file()  # noqa: SLF001

    # 提交目标未变（核心修复点）
    assert dlg.current_path() == path_before
    assert dlg.current_path() == active
    # 但内存库已导入新内容
    assert [p.name for p in dlg._library.projects] == ["Other"]  # noqa: SLF001


def test_load_then_accept_persists_to_active_not_source(qapp, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """加载 + 确定 → 内容写入当前活动库；源文件不被改写。"""
    active = tmp_path / "quick_commands.yaml"
    dump_library(_make_library(), active)

    src = tmp_path / "source.yaml"
    src_lib = CommandLibrary.empty()
    src_lib.add_project("Imported")
    src_lib.add_group("Imported", "G").commands.append("AT+NEW")
    dump_library(src_lib, src)
    src_mtime_before = src.stat().st_mtime_ns

    dlg = LibraryManagerDialog(_make_library(), active)
    _patch_open_file_dialog(monkeypatch, src)
    dlg._on_load_file()  # noqa: SLF001
    dlg._on_accept()  # noqa: SLF001

    # 活动库已更新为导入内容
    reloaded = load_library(active)
    assert [p.name for p in reloaded.projects] == ["Imported"]
    # 源文件未被改写（之前 bug：_on_accept 写回 self._path=源文件）
    assert src.stat().st_mtime_ns == src_mtime_before


def test_load_refreshes_dialog_tree(qapp, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """加载后对话框树立即显示新内容（视觉反馈，不能只改内存不刷 UI）。"""
    active = tmp_path / "quick_commands.yaml"
    dump_library(_make_library(), active)

    src = tmp_path / "src.yaml"
    src_lib = CommandLibrary.empty()
    src_lib.add_project("LoadedProj")
    dump_library(src_lib, src)

    dlg = LibraryManagerDialog(_make_library(), active)
    _patch_open_file_dialog(monkeypatch, src)
    dlg._on_load_file()  # noqa: SLF001

    # 对话框树已重建，显示导入的项目
    top_names = [dlg.tree.topLevelItem(i).text(0) for i in range(dlg.tree.topLevelItemCount())]
    assert "LoadedProj" in top_names


def test_load_cancel_discards(qapp, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """加载后取消（reject）→ 活动库文件不变（对话框工作副本语义）。"""
    active = tmp_path / "quick_commands.yaml"
    dump_library(_make_library(), active)
    active_mtime_before = active.stat().st_mtime_ns

    src = tmp_path / "src.yaml"
    src_lib = CommandLibrary.empty()
    src_lib.add_project("Discarded")
    dump_library(src_lib, src)

    dlg = LibraryManagerDialog(_make_library(), active)
    _patch_open_file_dialog(monkeypatch, src)
    dlg._on_load_file()  # noqa: SLF001
    dlg.reject()  # 取消，不提交

    # 活动库文件未被改写
    assert active.stat().st_mtime_ns == active_mtime_before
    assert "P1" in [p.name for p in load_library(active).projects]
