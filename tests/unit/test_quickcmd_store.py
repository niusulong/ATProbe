"""命令库 YAML 存储层单测（无 Qt 依赖）."""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.domain.quickcmd.models import CommandLibrary
from atprobe.infra.quickcmd import (
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
        f.write_text('projects: "不是列表"\n', encoding="utf-8")
        with pytest.raises(QuickCmdStoreError):
            load_library(f)

    def test_load_missing_project_name_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("projects:\n  - groups: []\n", encoding="utf-8")
        with pytest.raises(QuickCmdStoreError):
            load_library(f)


class TestLoadNonStringCommand:
    """批 5 T6-9：非字符串标量命令硬拒（旧实现 str(c) 静默强转污染数据）."""

    def test_int_command_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text(
            "projects:\n"
            "  - name: P\n"
            "    groups:\n"
            "      - name: G\n"
            "        commands:\n"
            "          - 123\n",
            encoding="utf-8",
        )
        with pytest.raises(QuickCmdStoreError, match="第 1 条命令必须是字符串") as ei:
            load_library(f)
        assert "P" in str(ei.value) and "G" in str(ei.value), "报错应带项目/组定位"
        assert "123" in str(ei.value), "报错应带实际值"

    def test_bool_command_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text(
            "projects:\n  - name: P\n    groups:\n      - name: G\n        commands:\n          - true\n",
            encoding="utf-8",
        )
        with pytest.raises(QuickCmdStoreError, match="bool"):
            load_library(f)

    def test_none_command_skipped(self, tmp_path: Path) -> None:
        """None（YAML ~）跳过语义保留，其余命令照常加载."""
        f = tmp_path / "lib.yaml"
        f.write_text(
            "projects:\n"
            "  - name: P\n"
            "    groups:\n"
            "      - name: G\n"
            "        commands:\n"
            "          - ~\n"
            "          - AT\n",
            encoding="utf-8",
        )
        lib = load_library(f)
        grp = lib.find_group("P", "G")
        assert grp is not None
        assert grp.commands == ["AT"]


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


class TestDumpErrorWrapping:
    """批 5 T6-9：dump_library IO/序列化失败包装为 QuickCmdStoreError.

    旧实现裸抛 OSError——GUI 侧 ``except QuickCmdStoreError`` 捕不到，异常
    逃进 Qt 事件循环无提示。
    """

    @staticmethod
    def _lib() -> CommandLibrary:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        return lib

    def test_mkdir_failure_wrapped(self, tmp_path: Path) -> None:
        """父路径中段是普通文件 → mkdir 抛 OSError → 包装."""
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        target = blocker / "sub" / "lib.yaml"
        with pytest.raises(QuickCmdStoreError, match="无法写入命令库文件"):
            dump_library(self._lib(), target)

    def test_replace_failure_wrapped_and_tmp_cleaned(self, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
        """os.replace 失败 → 包装，且残留 .tmp 被清理（原子写卫生收尾）."""
        import atprobe.infra.quickcmd.store as store_mod

        def _boom(src: object, dst: object) -> None:
            raise OSError("replace boom")

        monkeypatch.setattr(store_mod.os, "replace", _boom)
        target = tmp_path / "out.yaml"
        with pytest.raises(QuickCmdStoreError, match="无法写入命令库文件"):
            dump_library(self._lib(), target)
        assert not (tmp_path / "out.yaml.tmp").exists(), "失败后应清理残留 .tmp"


class TestDefaults:
    def test_default_library_has_migrated_commands(self) -> None:
        """默认库含迁移的 5 条指令（AT/AT+CSQ/AT+CEREG?/AT+CPIN?/AT+CGDCONT?）."""
        lib = default_library()
        all_cmds = [c for p in lib.projects for g in p.groups for c in g.commands]
        for expected in ("AT", "AT+CSQ", "AT+CEREG?", "AT+CPIN?", "AT+CGDCONT?"):
            assert expected in all_cmds, f"默认库缺少迁移指令 {expected}"

    def test_builtin_library_path_points_to_examples(self) -> None:
        p = builtin_library_path()
        assert p.name == "quick_commands.yaml"
        assert "examples" in p.parts
