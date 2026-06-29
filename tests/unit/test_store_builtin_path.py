"""store.py builtin_library_path 改造后的回归测试。"""

from __future__ import annotations

from atprobe.domain.quickcmd.store import builtin_library_path


def test_builtin_library_path_exists():
    """builtin_library_path() 返回真实存在的 quick_commands.yaml。"""
    p = builtin_library_path()
    assert p.exists()
    assert p.name == "quick_commands.yaml"


def test_builtin_library_path_is_not_module_dir():
    """不能返回模块自身目录（即不能用 parents[N] 错位）。"""
    p = builtin_library_path()
    # 必须指向 examples/ 下，而非 atprobe 包内
    assert "examples" in p.parts
