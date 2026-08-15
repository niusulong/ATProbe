"""AppConfig mcp.* 键加载测试（M8）."""

from __future__ import annotations

import pytest

from atprobe.infra.config.appconfig import (
    AppConfigError,
    load_app_config,
)


def test_mcp_defaults():
    cfg = load_app_config(None)
    assert cfg.mcp_host == "127.0.0.1"
    assert cfg.mcp_port == 8470
    assert cfg.mcp_token_file is None


def test_mcp_keys_loaded():
    cfg = load_app_config("mcp:\n  host: 0.0.0.0\n  port: 9000\n  token_file: ./secret.txt\n")
    assert cfg.mcp_host == "0.0.0.0"
    assert cfg.mcp_port == 9000
    assert cfg.mcp_token_file == "./secret.txt"


def test_mcp_bad_port_rejected():
    with pytest.raises(AppConfigError, match=r"mcp\.port"):
        load_app_config("mcp:\n  port: not-a-number\n")


def test_mcp_bool_port_rejected():
    # bool 是 int 子类：YAML 的 true 不能溜进 _to_int
    with pytest.raises(AppConfigError, match=r"mcp\.port"):
        load_app_config("mcp:\n  port: true\n")


def test_mcp_null_token_file_stays_none():
    # 显式置空（~）保持 None，不变成字符串 'None'
    cfg = load_app_config("mcp:\n  token_file: ~\n")
    assert cfg.mcp_token_file is None
