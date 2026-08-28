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
    # S-3：默认空元组=仅 cases_dir 在白名单
    assert cfg.mcp_allowed_roots == ()


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


# ---------------------------------------------------------------------------
# S-3：mcp.allowed_roots 路径白名单（批 4 T2）
# ---------------------------------------------------------------------------
def test_mcp_allowed_roots_loaded():
    # 字符串列表原样收敛为 tuple（路径合法性由服务层 resolve 口径统一处理）
    cfg = load_app_config("mcp:\n  allowed_roots:\n    - D:/shared\n    - ./rel\n")
    assert cfg.mcp_allowed_roots == ("D:/shared", "./rel")


def test_mcp_allowed_roots_empty_list_ok():
    cfg = load_app_config("mcp:\n  allowed_roots: []\n")
    assert cfg.mcp_allowed_roots == ()


def test_mcp_null_allowed_roots_stays_empty():
    # 显式置空（~）保持默认空元组（与 token_file 同口径）
    cfg = load_app_config("mcp:\n  allowed_roots: ~\n")
    assert cfg.mcp_allowed_roots == ()


def test_mcp_allowed_roots_not_list_rejected():
    with pytest.raises(AppConfigError, match=r"mcp\.allowed_roots"):
        load_app_config("mcp:\n  allowed_roots: D:/shared\n")


def test_mcp_allowed_roots_non_str_item_rejected():
    with pytest.raises(AppConfigError, match=r"mcp\.allowed_roots"):
        load_app_config("mcp:\n  allowed_roots: [D:/shared, 42]\n")
