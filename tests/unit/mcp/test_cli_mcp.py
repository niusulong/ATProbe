"""atprobe mcp 命令注册与参数处理测试（不真启动服务）.

覆盖（Task 7）：子命令组注册、serve 的 Token 校验层（四级优先级接线后的
缺失/文件不存在/环境变量兜底）、未装 MCP 依赖的友好守护（sys.modules 置
None 模拟）。不覆盖真实传输——stdio 会阻塞、serve 会真起 uvicorn，线上
行为由 Task 8 集成测试经真实 transport 验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from typer.testing import CliRunner  # noqa: E402

from atprobe.cli.main import app  # noqa: E402

runner = CliRunner()


def test_mcp_help_registered() -> None:
    """mcp 子命令组已注册：--help 列出 stdio 与 serve。"""
    res = runner.invoke(app, ["mcp", "--help"])
    assert res.exit_code == 0
    assert "serve" in res.output
    assert "stdio" in res.output


def test_stdio_help() -> None:
    """stdio 子命令存在且暴露 --config/--vsim。"""
    res = runner.invoke(app, ["mcp", "stdio", "--help"])
    assert res.exit_code == 0
    assert "--vsim" in res.output
    assert "--config" in res.output


def test_serve_requires_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无任何 Token 来源 → exit 2 且错误含 token。"""
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    res = runner.invoke(app, ["mcp", "serve", "--config", str(tmp_path / "absent.yaml")])
    assert res.exit_code == 2
    assert "token" in res.output.lower()


def test_serve_token_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--token-file 指向不存在文件 → exit 2（而非 traceback）。"""
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    res = runner.invoke(
        app,
        [
            "mcp",
            "serve",
            "--config",
            str(tmp_path / "absent.yaml"),
            "--token-file",
            str(tmp_path / "absent.txt"),
        ],
    )
    assert res.exit_code == 2
    assert res.exception is None or isinstance(res.exception, SystemExit)
    assert "token" in res.output.lower()


def test_serve_token_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量 Token 生效：不再因 Token 缺失退出（坏配置 → 配置层错误）。"""
    monkeypatch.setenv("ATPROBE_MCP_TOKEN", "x")
    bad = tmp_path / "bad.yaml"
    bad.write_text("mcp:\n  port: not_an_int\n", encoding="utf-8")
    res = runner.invoke(app, ["mcp", "serve", "--config", str(bad)])
    # Token 层已过（env 兜底），流程停在配置层：exit 2 且报「配置错误」而非 Token
    # （不断言 "token" 不在输出：tmp_path 路径含本测试函数名，会误伤）
    assert res.exit_code == 2
    assert "配置错误" in res.output
    assert "需要 Token" not in res.output


def test_serve_config_layer_before_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """顺序锁定：配置加载先于 Token 校验（无 Token + 坏配置 → 配置错误）。"""
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    bad = tmp_path / "bad.yaml"
    bad.write_text("mcp:\n  port: not_an_int\n", encoding="utf-8")
    res = runner.invoke(app, ["mcp", "serve", "--config", str(bad)])
    assert res.exit_code == 2
    assert "配置错误" in res.output


def test_serve_no_mcp_friendly_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟未装 mcp SDK：serve 最先快速失败 exit 2，提示 uv sync --extra mcp.

    ``sys.modules["mcp"]=None`` 使 import mcp 必败；_require_mcp 先于配置
    加载与 Token 校验，故无需任何 config。tools.py 顶层 SDK import 收敛后，
    命令体的延迟 import 不再抢先裸炸 ModuleNotFoundError。
    """
    monkeypatch.setitem(sys.modules, "mcp", None)
    res = runner.invoke(app, ["mcp", "serve", "--token", "x"])
    assert res.exit_code == 2
    assert "uv sync --extra mcp" in res.output
    assert res.exception is None or isinstance(res.exception, SystemExit)
