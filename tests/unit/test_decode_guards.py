"""F-16 同型补漏：各文件读取入口对非 UTF-8 内容的解码守卫.

GBK 编码文件在 ``read_text(encoding="utf-8")`` 处抛 UnicodeDecodeError
（ValueError 子类，非 OSError），旧实现裸抛逃逸——契约要求各入口收敛为
领域错误（CaseParseError / SuiteParseError / QuickCmdStoreError /
ValueError），文案含文件路径与「非 UTF-8 编码」提示。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.domain.case.parser import CaseParseError, parse_case_file
from atprobe.domain.suite.parser import SuiteParseError, parse_suite_file
from atprobe.infra.quickcmd.store import QuickCmdStoreError, load_library
from atprobe.mcp.auth import load_token


def _write_gbk(path: Path) -> Path:
    """写入 GBK 编码文件（内容含中文，UTF-8 解码必失败）."""
    path.write_bytes("名称: 中文内容\n".encode("gbk"))
    return path


# ---------------------------------------------------------------------------
# parse_case_file / parse_suite_file
# ---------------------------------------------------------------------------
def test_parse_case_file_gbk_raises_case_parse_error(tmp_path: Path) -> None:
    p = _write_gbk(tmp_path / "case-gbk.yaml")
    with pytest.raises(CaseParseError, match="非 UTF-8") as exc_info:
        parse_case_file(p)
    assert str(p) in str(exc_info.value)


def test_parse_suite_file_gbk_raises_suite_parse_error(tmp_path: Path) -> None:
    p = _write_gbk(tmp_path / "suite-gbk.yaml")
    with pytest.raises(SuiteParseError, match="非 UTF-8") as exc_info:
        parse_suite_file(p)
    assert str(p) in str(exc_info.value)


def test_parse_case_file_utf8_still_works(tmp_path: Path) -> None:
    p = tmp_path / "case-ok.yaml"
    p.write_text("name: 正常用例\nsteps:\n- command: AT\n  expect: OK\n", encoding="utf-8")
    case = parse_case_file(p)
    assert case.steps[0].command == "AT"


# ---------------------------------------------------------------------------
# load_library（infra/quickcmd/store.py）
# ---------------------------------------------------------------------------
def test_load_library_gbk_raises_quickcmd_store_error(tmp_path: Path) -> None:
    p = _write_gbk(tmp_path / "quick_commands.yaml")
    with pytest.raises(QuickCmdStoreError, match="非 UTF-8") as exc_info:
        load_library(p)
    assert str(p) in str(exc_info.value)


def test_load_library_utf8_still_works(tmp_path: Path) -> None:
    p = tmp_path / "quick_commands.yaml"
    p.write_text(
        "projects:\n- name: 通用\n  groups:\n  - name: 基础\n    commands: [AT]\n",
        encoding="utf-8",
    )
    lib = load_library(p)
    assert lib.projects[0].name == "通用"


# ---------------------------------------------------------------------------
# load_token（mcp/auth.py：非 UTF-8 Token 文件 → ValueError，CLI 转 exit 2）
# ---------------------------------------------------------------------------
def test_load_token_file_gbk_raises_value_error(tmp_path: Path) -> None:
    p = _write_gbk(tmp_path / "token.txt")
    with pytest.raises(ValueError, match="非 UTF-8") as exc_info:
        load_token(token_file=str(p), token=None)
    assert str(p) in str(exc_info.value)
    # UnicodeDecodeError 本身是 ValueError 子类——须确认收敛后不是裸解码错误
    assert not isinstance(exc_info.value, UnicodeDecodeError)


def test_load_token_config_file_gbk_also_guarded(tmp_path: Path) -> None:
    """config_token_file（第 4 优先级）走同一 _read_token_file 入口."""
    p = _write_gbk(tmp_path / "token-cfg.txt")
    with pytest.raises(ValueError, match="非 UTF-8"):
        load_token(token_file=None, token=None, config_token_file=str(p))


def test_load_token_utf8_still_works(tmp_path: Path) -> None:
    p = tmp_path / "token-ok.txt"
    p.write_text("a" * 32 + "\n", encoding="utf-8")
    assert load_token(token_file=str(p), token=None) == "a" * 32


def test_load_app_config_file_gbk_raises_app_config_error(tmp_path: Path) -> None:
    """T7 审查 M-1：GBK 的 atprobe.yaml → AppConfigError（而非裸 UnicodeDecodeError
    穿透 CLI 的 exit 2 契约 / 使 GUI 启动即崩）."""
    from atprobe.infra.config.appconfig import AppConfigError, load_app_config_file

    p = _write_gbk(tmp_path / "atprobe.yaml")
    with pytest.raises(AppConfigError, match="非 UTF-8") as exc_info:
        load_app_config_file(p)
    assert not isinstance(exc_info.value, UnicodeDecodeError)


def test_load_env_config_file_gbk_raises_env_config_error(tmp_path: Path) -> None:
    """T7 审查 M-2：GBK 的 env.yaml → EnvConfigError（MCP 侧 McpError 契约依赖）."""
    from atprobe.infra.config.envconfig import EnvConfigError, load_env_config_file

    p = _write_gbk(tmp_path / "env.yaml")
    with pytest.raises(EnvConfigError, match="非 UTF-8") as exc_info:
        load_env_config_file(p)
    assert not isinstance(exc_info.value, UnicodeDecodeError)
