"""AppConfig mcp.* 键加载测试（M8）."""

from __future__ import annotations

from atprobe.infra.config.appconfig import load_app_config


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
    import pytest

    from atprobe.infra.config.appconfig import AppConfigError

    with pytest.raises(AppConfigError):
        load_app_config("mcp:\n  port: not-a-number\n")
