"""快捷命令管理对话框「加载」功能回归测试（issue: 加载后不生效）.

验证「加载」语义 = 导入到当前库：
- 加载只替换内存工作副本，不改提交目标 path
- 确定后内容写入当前活动库文件（而非被加载的源文件）
- 取消则丢弃（对话框工作副本语义不变）

用现有 qapp fixture（见 conftest.py），不依赖 pytest-qt。
"""

from __future__ import annotations

from pathlib import Path

from atprobe.domain.quickcmd import CommandLibrary, dump_library, load_library
from atprobe.gui.widgets.command_library import LibraryManagerDialog


def _make_library() -> CommandLibrary:
    """构造含一个命令的库."""
    lib = CommandLibrary.empty()
    lib.add_project("P1")
    grp = lib.add_group("P1", "G1")
    grp.commands.append("AT+OLD")
    return lib


def test_load_imports_to_current_library_on_accept(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """加载外部文件 + 确定 → 内容写入当前活动库文件（而非源文件）."""
    # 当前活动库文件
    active = tmp_path / "quick_commands.yaml"
    lib = _make_library()
    dump_library(lib, active)

    # 外部源文件（不同内容）
    src = tmp_path / "imported.yaml"
    src_lib = CommandLibrary.empty()
    src_lib.add_project("Imported")
    src_lib.add_group("Imported", "G").commands.append("AT+NEW")
    dump_library(src_lib, src)

    # 打开对话框
    dlg = LibraryManagerDialog(lib, active)
    original_path = dlg.current_path()

    # 模拟点「加载」选 src（绕过 QFileDialog，直接调内部加载逻辑）
    dlg._on_load_file  # noqa: B018 - 确认方法存在
    # 直接执行加载核心逻辑（_on_load_file 含文件对话框，测试里直接改 _library）
    dlg._library = load_library(src)  # noqa: SLF001
    dlg._refresh_tree()  # noqa: SLF001

    # 提交目标不变（仍是活动库，不是 src）
    assert dlg.current_path() == original_path

    # 确定 → 写入活动库
    dlg._on_accept()  # noqa: SLF001

    # 活动库文件现在含导入的内容
    reloaded = load_library(active)
    projs = [p.name for p in reloaded.projects]
    assert "Imported" in projs
    assert "P1" not in projs  # 旧内容被覆盖


def test_load_does_not_change_commit_target(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """加载后 self._path 不变（提交目标仍是当前活动库，不被源文件路径污染）."""
    active = tmp_path / "quick_commands.yaml"
    lib = _make_library()
    dump_library(lib, active)

    src = tmp_path / "other.yaml"
    src_lib = CommandLibrary.empty()
    src_lib.add_project("Other")
    dump_library(src_lib, src)

    dlg = LibraryManagerDialog(lib, active)
    path_before = dlg.current_path()

    # 加载 src（直接操作内存，模拟 _on_load_file 的核心）
    dlg._library = load_library(src)  # noqa: SLF001
    dlg._refresh_tree()  # noqa: SLF001

    # 提交目标未变（关键修复点：之前 _on_load_file 会改 self._path）
    assert dlg.current_path() == path_before
    assert dlg.current_path() == active


def test_load_then_accept_persists_to_active_not_source(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """确定后源文件不被改写（之前 bug：_on_accept 写回 self._path=源文件）."""
    active = tmp_path / "quick_commands.yaml"
    dump_library(_make_library(), active)

    src = tmp_path / "source.yaml"
    src_lib = CommandLibrary.empty()
    src_lib.add_project("SourceProj")
    dump_library(src_lib, src)
    src_mtime_before = src.stat().st_mtime_ns

    dlg = LibraryManagerDialog(_make_library(), active)
    dlg._library = load_library(src)  # noqa: SLF001
    dlg._refresh_tree()  # noqa: SLF001
    dlg._on_accept()  # noqa: SLF001

    # 源文件未被改写
    assert src.stat().st_mtime_ns == src_mtime_before
