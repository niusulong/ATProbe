"""数据源路径信任边界单测（S-8，设计 §5）."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atprobe.domain.case.datasource import (
    DataPathError,
    data_roots,
    ensure_within,
    read_data_file,
    resolve_case_path,
)


def _flip_drive_case(path: Path) -> Path:
    """Windows 盘符大小写翻转（C:\\... ↔ c:\\...），用于大小写不敏感比较测试."""
    text = str(path)
    return Path(text[0].swapcase() + text[1:])


class TestResolveCasePath:
    def test_relative_anchored_to_case_dir(self, tmp_path: Path) -> None:
        assert resolve_case_path("data/x.bin", tmp_path) == tmp_path / "data" / "x.bin"

    def test_absolute_passthrough(self, tmp_path: Path) -> None:
        absolute = tmp_path / "a.bin"
        assert resolve_case_path(str(absolute), tmp_path) == absolute

    def test_case_dir_none_cwd_semantics(self) -> None:
        # case_dir=None：Path(raw) 原语义（相对 CWD），不做锚定拼接
        assert resolve_case_path("x.bin", None) == Path("x.bin")


class TestEnsureWithin:
    def test_within_passes_returns_resolved(self, tmp_path: Path) -> None:
        target = tmp_path / "ok.bin"
        target.write_bytes(b"abc")
        result = ensure_within(tmp_path / "ok.bin", [tmp_path])
        assert result == target.resolve()
        assert result.is_absolute()

    def test_escape_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DataPathError) as excinfo:
            ensure_within(tmp_path / ".." / "out.bin", [tmp_path])
        # 错误信息含渲染后路径与锚集
        message = str(excinfo.value)
        assert "out.bin" in message
        assert str(tmp_path) in message

    def test_empty_roots_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DataPathError, match="data_allowed_roots"):
            ensure_within(tmp_path / "x.bin", [])

    def test_symbolic_dotdot_still_inside_passes(self, tmp_path: Path) -> None:
        # sub/../ok.bin resolve 后仍在锚内——符号性路径不应误拒
        (tmp_path / "sub").mkdir()
        result = ensure_within(tmp_path / "sub" / ".." / "ok.bin", [tmp_path])
        assert result == (tmp_path / "ok.bin").resolve()

    @pytest.mark.skipif(sys.platform != "win32", reason="盘符大小写仅 Windows 有意义")
    def test_windows_mixed_drive_case_within_passes(self, tmp_path: Path) -> None:
        # pathlib is_relative_to 大小写敏感，须 normcase 后比较：C:\... vs c:\...
        # （PureWindowsPath 相等本身不区分大小写，故用字符串断言翻转生效）
        flipped = _flip_drive_case(tmp_path)
        assert str(flipped) != str(tmp_path)
        result = ensure_within(flipped / "ok.bin", [tmp_path])
        assert result == (tmp_path / "ok.bin").resolve()

    def test_multiple_roots_any_match(self, tmp_path: Path) -> None:
        other = tmp_path / "other"
        other.mkdir()
        result = ensure_within(other / "y.bin", [tmp_path, other])
        assert result == (other / "y.bin").resolve()


class TestDataRoots:
    def test_dedup(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        roots = data_roots(tmp_path, (tmp_path, sub))
        assert roots == [tmp_path.resolve(), sub.resolve()]

    def test_dedup_case_insensitive_windows(self, tmp_path: Path) -> None:
        flipped = _flip_drive_case(tmp_path)
        assert data_roots(tmp_path, (flipped,)) == [tmp_path.resolve()]

    def test_none_case_dir_skipped(self, tmp_path: Path) -> None:
        assert data_roots(None, (tmp_path,)) == [tmp_path.resolve()]
        assert data_roots(None) == []


class TestReadDataFile:
    def test_read_bytes_success(self, tmp_path: Path) -> None:
        (tmp_path / "x.bin").write_bytes(b"abc")
        assert read_data_file("x.bin", tmp_path) == b"abc"

    def test_outside_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DataPathError):
            read_data_file("../secret.bin", tmp_path)

    def test_missing_file_inside_wraps_oserror(self, tmp_path: Path) -> None:
        with pytest.raises(DataPathError) as excinfo:
            read_data_file("missing.bin", tmp_path)
        # 包装含底层原因与渲染后路径
        message = str(excinfo.value)
        assert "missing.bin" in message
        assert "WinError" in message or "No such file" in message or "Errno" in message

    def test_extra_roots_allow_reading_outside_case_dir(self, tmp_path: Path) -> None:
        # 相对路径锚定 case_dir；额外根内、case_dir 外的文件须走绝对路径
        case_dir = tmp_path / "case"
        case_dir.mkdir()
        extra = tmp_path / "extra"
        extra.mkdir()
        (extra / "y.bin").write_bytes(b"xyz")
        assert read_data_file(str(extra / "y.bin"), case_dir, (extra,)) == b"xyz"
