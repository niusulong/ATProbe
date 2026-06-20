"""M7 环境配置单测."""

from __future__ import annotations

import pytest

from atprobe.domain.case.templater import UndefinedReferenceError
from atprobe.infra.config.envconfig import (
    EnvConfigError,
    dump_env_config,
    empty_env_config,
    load_env_config,
)


class TestLoad:
    def test_basic(self) -> None:
        env = load_env_config("ftp:\n  host: 1.2.3.4\n  port: 21\n")
        assert env.resolve_str("ftp.host") == "1.2.3.4"
        assert env.resolve_str("ftp.port") == "21"

    def test_empty_file(self) -> None:
        env = load_env_config("")
        assert env.is_empty() is True

    def test_null_file(self) -> None:
        env = load_env_config("---\n")
        assert env.is_empty() is True

    def test_string_values_preserved(self) -> None:
        # 号码类用字符串避免精度丢失
        env = load_env_config('device:\n  number: "13800138000"\n')
        assert env.resolve_str("device.number") == "13800138000"

    def test_bool_value(self) -> None:
        env = load_env_config("flag:\n  on: true\n")
        assert env.resolve_str("flag.on") == "true"

    def test_round_trip_dump(self) -> None:
        env = load_env_config("ftp:\n  host: 1.2.3.4\n  port: 21\n")
        dumped = dump_env_config(env)
        env2 = load_env_config(dumped)
        assert env2.resolve_str("ftp.host") == "1.2.3.4"


class TestErrors:
    def test_non_dict_root_rejected(self) -> None:
        with pytest.raises(EnvConfigError):
            load_env_config("- a\n- b\n")

    def test_non_dict_group_rejected(self) -> None:
        with pytest.raises(EnvConfigError):
            load_env_config("ftp: not-a-map\n")

    def test_nested_structure_rejected(self) -> None:
        with pytest.raises(EnvConfigError):
            load_env_config("ftp:\n  server:\n    host: x\n")

    def test_list_value_rejected(self) -> None:
        with pytest.raises(EnvConfigError):
            load_env_config("ftp:\n  ports:\n    - 1\n    - 2\n")

    def test_undefined_ref_raises(self) -> None:
        env = load_env_config("ftp:\n  host: x\n")
        with pytest.raises(UndefinedReferenceError):
            env.resolve_str("ftp.missing")

    def test_simple_name_not_in_default_group(self) -> None:
        env = load_env_config("ftp:\n  host: x\n")
        # apn 不在 default 组 → 简单名查找失败
        assert env.has("apn") is False


class TestItems:
    def test_iterate_items(self) -> None:
        env = load_env_config("ftp:\n  host: a\n  port: 1\nhttp:\n  host: b\n")
        items = sorted(env.items())
        assert ("ftp", "host", "a") in items
        assert ("ftp", "port", 1) in items
        assert ("http", "host", "b") in items

    def test_empty_env(self) -> None:
        env = empty_env_config()
        assert env.is_empty()
        assert list(env.items()) == []
