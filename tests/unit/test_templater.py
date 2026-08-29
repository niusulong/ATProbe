"""模板替换器单测（M2 §5.2 / M7 §4）."""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.domain.case.errors import UndefinedReferenceError
from atprobe.domain.case.templater import (
    TemplateRenderError,
    find_references,
    render,
)


class TestRender:
    def test_simple_var(self) -> None:
        assert render("AT+CSQ={{x}}", {"x": 23}) == "AT+CSQ=23"

    def test_multiple_vars(self) -> None:
        assert render("{{a}}{{b}}", {"a": 1, "b": 2}) == "12"

    def test_string_value(self) -> None:
        assert render("ATD{{num}};", {"num": "13800138000"}) == "ATD13800138000;"

    def test_bool_value(self) -> None:
        assert render("{{flag}}", {"flag": True}) == "true"
        assert render("{{flag}}", {"flag": False}) == "false"

    def test_float_value(self) -> None:
        assert render("{{v}}", {"v": 1.5}) == "1.5"
        assert render("{{v}}", {"v": 2.0}) == "2"  # 整数值 float 用整数形式

    def test_no_placeholders(self) -> None:
        assert render("plain text", {}) == "plain text"

    def test_whitespace_around_name(self) -> None:
        assert render("{{  x  }}", {"x": 1}) == "1"

    def test_undefined_raises(self) -> None:
        with pytest.raises(UndefinedReferenceError):
            render("{{missing}}", {})

    def test_allow_partial_keeps_undefined(self) -> None:
        out = render("{{defined}}-{{missing}}", {"defined": "ok"}, allow_partial=True)
        assert out == "ok-{{missing}}"


class TestEnvResolution:
    def test_dot_ref_resolves_env(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{ftp.host}}", {}, env=env) == "192.168.1.100"
        assert render("{{ftp.port}}", {}, env=env) == "21"

    def test_dot_ref_cross_group(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{fota.version_a}}", {}, env=env) == "V1.0.0"

    def test_dot_ref_not_overridable_by_case_var(self, env) -> None:  # type: ignore[no-untyped-def]
        # 点号名边界（M7 §4.4）：点号名只查环境配置，不被用例级变量覆盖
        out = render("{{ftp.host}}", {"ftp.host": "fake"}, env=env)
        assert out == "192.168.1.100"

    def test_simple_name_fallback_to_env_default_group(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{apn}}", {}, env=env) == "cmnet"

    def test_simple_name_case_var_overrides_env(self, env) -> None:  # type: ignore[no-untyped-def]
        assert render("{{apn}}", {"apn": "custom"}, env=env) == "custom"

    def test_dot_ref_undefined_raises(self, env) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(UndefinedReferenceError):
            render("{{fota.missing}}", {}, env=env)

    def test_no_env_dot_ref_raises(self) -> None:
        with pytest.raises(UndefinedReferenceError):
            render("{{ftp.host}}", {}, env=None)

    def test_three_level_ref_rejected(self, env) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(UndefinedReferenceError):
            render("{{a.b.c}}", {}, env=env)


class TestFindReferences:
    def test_finds_all(self) -> None:
        refs = find_references("{{a}} {{b}} {{a}} {{c.d}}")
        assert refs == ["a", "b", "c.d"]

    def test_no_refs(self) -> None:
        assert find_references("plain") == []

    def test_distinguishes_dot_and_simple(self) -> None:
        refs = find_references("{{x}} {{group.param}}")
        assert refs == ["x", "group.param"]

    def test_skips_function_form(self) -> None:
        # 函数形态不是变量引用，UI 校验引用不应报未定义
        refs = find_references('{{a}} {{file_size("x.bin")}} {{group.param}}')
        assert refs == ["a", "group.param"]


class TestBuiltinFunctions:
    """{{file_size("path")}} 内置函数（S-8 路径锚定，设计 §5）."""

    def test_file_size_double_quoted(self, tmp_path: Path) -> None:
        (tmp_path / "x.bin").write_bytes(b"abc")
        assert render('{{file_size("./x.bin")}}', {}, case_dir=tmp_path) == "3"

    def test_file_size_single_quoted(self, tmp_path: Path) -> None:
        (tmp_path / "x.bin").write_bytes(b"abc")
        assert render("{{file_size('./x.bin')}}", {}, case_dir=tmp_path) == "3"

    def test_file_size_mixed_with_vars(self, tmp_path: Path) -> None:
        (tmp_path / "fw.bin").write_bytes(b"abcd")
        out = render(
            'AT+UPD={{file_size("fw.bin")}},name={{n}}',
            {"n": "fw"},
            case_dir=tmp_path,
        )
        assert out == "AT+UPD=4,name=fw"

    def test_file_size_escape_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(TemplateRenderError):
            render('{{file_size("../out.bin")}}', {}, case_dir=tmp_path)

    def test_file_size_absolute_outside_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "secret.bin"
        with pytest.raises(TemplateRenderError):
            render(f'{{{{file_size("{outside}")}}}}', {}, case_dir=tmp_path)

    def test_unknown_function(self) -> None:
        with pytest.raises(TemplateRenderError, match="未知内置"):
            render('{{nope("x")}}', {})

    def test_non_quoted_argument(self, tmp_path: Path) -> None:
        with pytest.raises(TemplateRenderError, match="引号"):
            render("{{file_size(x.bin)}}", {}, case_dir=tmp_path)

    def test_missing_file_inside_raises(self, tmp_path: Path) -> None:
        with pytest.raises(TemplateRenderError, match="file_size"):
            render('{{file_size("./missing.bin")}}', {}, case_dir=tmp_path)

    def test_allow_partial_does_not_swallow_function_errors(self, tmp_path: Path) -> None:
        # 函数求值失败不是「未定义变量」——allow_partial 下照抛
        with pytest.raises(TemplateRenderError):
            render(
                '{{file_size("./missing.bin")}}',
                {},
                case_dir=tmp_path,
                allow_partial=True,
            )

    def test_data_allowed_roots_extra_root(self, tmp_path: Path) -> None:
        # 文件在额外根内、case_dir 外（绝对路径）→ 通过
        case_dir = tmp_path / "case"
        case_dir.mkdir()
        extra = tmp_path / "extra"
        extra.mkdir()
        (extra / "y.bin").write_bytes(b"abcd")
        out = render(
            f'{{{{file_size("{extra / "y.bin"}")}}}}',
            {},
            case_dir=case_dir,
            data_allowed_roots=(extra,),
        )
        assert out == "4"

    def test_no_case_dir_no_roots_rejects(self, tmp_path: Path) -> None:
        # 锚集为空：相对路径按 CWD 解析后无锚根可比 → 拒绝
        with pytest.raises(TemplateRenderError):
            render("{{file_size('x.bin')}}", {})

    def test_default_params_keep_legacy_behavior(self, tmp_path: Path) -> None:
        # 不传新参数：占位符解析与既有行为完全一致
        assert render("{{a}}", {"a": 1}) == "1"
        assert render("plain", {}) == "plain"
