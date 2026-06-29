"""命令库 YAML 存储层单测（无 Qt 依赖）."""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.domain.quickcmd.models import CommandLibrary
from atprobe.domain.quickcmd.store import (
    QuickCmdStoreError,
    builtin_library_path,
    default_library,
    dump_library,
    load_library,
)


class TestLoad:
    def test_load_nested_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "lib.yaml"
        f.write_text(
            "projects:\n"
            "  - name: N58 项目\n"
            "    groups:\n"
            "      - name: 网络\n"
            "        commands:\n"
            "          - AT+CSQ\n"
            "          - AT+CEREG?\n",
            encoding="utf-8",
        )
        lib = load_library(f)
        grp = lib.find_group("N58 项目", "网络")
        assert grp is not None
        assert grp.commands == ["AT+CSQ", "AT+CEREG?"]

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """文件缺失 → 返回空库（不抛错，幂等）."""
        lib = load_library(tmp_path / "nope.yaml")
        assert lib.projects == []

    def test_load_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        lib = load_library(f)
        assert lib.projects == []

    def test_load_no_projects_key_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "x.yaml"
        f.write_text("foo: bar\n", encoding="utf-8")
        lib = load_library(f)
        assert lib.projects == []

    def test_load_invalid_structure_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("projects: \"不是列表\"\n", encoding="utf-8")
        with pytest.raises(QuickCmdStoreError):
            load_library(f)

    def test_load_missing_project_name_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("projects:\n  - groups: []\n", encoding="utf-8")
        with pytest.raises(QuickCmdStoreError):
            load_library(f)


class TestDumpRoundTrip:
    def test_dump_then_load_roundtrip(self, tmp_path: Path) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.add_command("P1", "G1", "ATZ")
        lib.add_project("P2")
        lib.add_group("P2", "G2")
        lib.add_command("P2", "G2", "ATI")

        f = tmp_path / "out.yaml"
        dump_library(lib, f)
        assert f.exists()  # 原子写后文件存在

        lib2 = load_library(f)
        assert lib2.find_group("P1", "G1").commands == ["AT", "ATZ"]
        assert lib2.find_group("P2", "G2").commands == ["ATI"]

    def test_dump_empty_library(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        dump_library(CommandLibrary.empty(), f)
        lib = load_library(f)
        assert lib.projects == []


class TestDefaults:
    def test_default_library_has_migrated_commands(self) -> None:
        """默认库含迁移的 5 条指令（AT/AT+CSQ/AT+CEREG?/AT+CPIN?/AT+CGDCONT?）."""
        lib = default_library()
        all_cmds = [
            c for p in lib.projects for g in p.groups for c in g.commands
        ]
        for expected in ("AT", "AT+CSQ", "AT+CEREG?", "AT+CPIN?", "AT+CGDCONT?"):
            assert expected in all_cmds, f"默认库缺少迁移指令 {expected}"

    def test_builtin_library_path_points_to_examples(self) -> None:
        p = builtin_library_path()
        assert p.name == "quick_commands.yaml"
        assert "examples" in p.parts
