"""命令库数据模型单测（无 Qt 依赖）."""

from __future__ import annotations

import pytest

from atprobe.domain.quickcmd.models import (
    CommandLibrary,
)


class TestAddFind:
    def test_add_project_group_command(self) -> None:
        lib = CommandLibrary.empty()
        proj = lib.add_project("N58 项目")
        grp = lib.add_group("N58 项目", "网络")
        lib.add_command("N58 项目", "网络", "AT+CSQ")
        assert proj.name == "N58 项目"
        assert grp.name == "网络"
        assert lib.find_project("N58 项目") is proj
        assert lib.find_group("N58 项目", "网络") is grp
        assert "AT+CSQ" in lib.find_group("N58 项目", "网络").commands

    def test_find_missing_returns_none(self) -> None:
        lib = CommandLibrary.empty()
        assert lib.find_project("不存在") is None
        assert lib.find_group("N58 项目", "网络") is None


class TestDuplicateValidation:
    def test_duplicate_project_raises(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        with pytest.raises(ValueError):
            lib.add_project("P1")

    def test_duplicate_group_in_same_project_raises(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        with pytest.raises(ValueError):
            lib.add_group("P1", "G1")

    def test_same_group_name_in_different_project_ok(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_project("P2")
        lib.add_group("P1", "通用")
        lib.add_group("P2", "通用")  # 不同项目下同名功能组，允许

    def test_duplicate_command_allowed(self) -> None:
        """同功能组下命令允许重复（不去重）."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.add_command("P1", "G1", "AT")  # 允许重复
        assert lib.find_group("P1", "G1").commands == ["AT", "AT"]

    def test_empty_name_raises(self) -> None:
        lib = CommandLibrary.empty()
        with pytest.raises(ValueError):
            lib.add_project("")
        lib.add_project("P1")
        with pytest.raises(ValueError):
            lib.add_group("P1", "")
        with pytest.raises(ValueError):
            lib.add_command("P1", "G1", "")


class TestRename:
    def test_rename_project_to_new_name(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.rename_project("P1", "P2")
        assert lib.find_project("P1") is None
        assert lib.find_project("P2") is not None

    def test_rename_project_duplicate_raises(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_project("P2")
        with pytest.raises(ValueError):
            lib.rename_project("P1", "P2")

    def test_rename_project_to_self_idempotent(self) -> None:
        """重命名为自身原名应幂等成功."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.rename_project("P1", "P1")  # 不报错
        assert lib.find_project("P1") is not None


class TestRemove:
    def test_remove_project_cascades(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.remove_project("P1")
        assert lib.find_project("P1") is None

    def test_remove_group(self) -> None:
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.remove_group("P1", "G1")
        assert lib.find_group("P1", "G1") is None

    def test_remove_command_at(self) -> None:
        """按索引删命令：只删点中的那一条（批 5 T6-9，替代按文本删除）."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.add_command("P1", "G1", "ATZ")
        lib.remove_command_at("P1", "G1", 0)
        assert lib.find_group("P1", "G1").commands == ["ATZ"]

    def test_remove_command_at_duplicate_only_removes_that_one(self) -> None:
        """同文重复命令：按索引删除只删一条（旧 remove_command 按文本会全删）."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        lib.add_command("P1", "G1", "AT")
        lib.remove_command_at("P1", "G1", 1)
        assert lib.find_group("P1", "G1").commands == ["AT"]

    def test_remove_command_at_out_of_range_raises(self) -> None:
        """索引越界 → IndexError（友好文案附组内命令数与有效范围）."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        with pytest.raises(IndexError, match="越界"):
            lib.remove_command_at("P1", "G1", 5)
        with pytest.raises(IndexError, match="越界"):
            lib.remove_command_at("P1", "G1", -1)

    def test_remove_command_at_missing_group_raises(self) -> None:
        """组不存在 → ValueError（与 add_command 同款文案）."""
        lib = CommandLibrary.empty()
        with pytest.raises(ValueError, match="不存在"):
            lib.remove_command_at("P", "G", 0)

    def test_replace_command_at_keeps_position(self) -> None:
        """按索引原位修改：保持组内顺序（旧 add+remove 会把命令挪到末尾）."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        for c in ("AT", "AT+CSQ", "ATZ"):
            lib.add_command("P1", "G1", c)
        lib.replace_command_at("P1", "G1", 1, "AT+CGMR")
        assert lib.find_group("P1", "G1").commands == ["AT", "AT+CGMR", "ATZ"]

    def test_replace_command_at_validates_and_raises(self) -> None:
        """空命令/越界/组不存在分别报 ValueError/IndexError."""
        lib = CommandLibrary.empty()
        lib.add_project("P1")
        lib.add_group("P1", "G1")
        lib.add_command("P1", "G1", "AT")
        with pytest.raises(ValueError, match="不能为空"):
            lib.replace_command_at("P1", "G1", 0, "  ")
        with pytest.raises(IndexError, match="越界"):
            lib.replace_command_at("P1", "G1", 3, "AT+X")
        with pytest.raises(ValueError, match="不存在"):
            lib.replace_command_at("P", "G", 0, "AT")

    def test_remove_missing_is_idempotent(self) -> None:
        """删除不存在的项不抛错（幂等；命令删除不在此列——按索引，越界即报）."""
        lib = CommandLibrary.empty()
        lib.remove_project("不存在")  # 不抛错
        lib.remove_group("P", "G")
