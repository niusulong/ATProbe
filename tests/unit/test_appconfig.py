"""AppConfig 加载与端口表达式解析测试（补测试缺口——本轮 P2 修复配套）.

覆盖：
    - 默认值（空数据）
    - 各配置段加载
    - default.baud 填充无冒号端口表达式（P2 修复：旧实现死字段）
    - 值类型错误收敛 AppConfigError（P2 修复：旧实现裸 ValueError/TypeError）
    - ports 非字符串项 / 帧格式错误收敛
    - frozen 语义（赋值报错）
    - log.keep 死键已移除（不再接受但也不报错？——实际：extra 键被忽略，字段不存在）
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from atprobe.infra.config.appconfig import (
    AppConfigError,
    load_app_config,
    parse_port_expr,
)


class TestDefaults:
    def test_empty_data_returns_defaults(self) -> None:
        cfg = load_app_config(None)
        assert cfg.baud == 115200
        assert cfg.log_level == "progress"
        assert cfg.ports == ()
        assert cfg.step_timeout == 5.0

    def test_empty_string_defaults(self) -> None:
        assert load_app_config("").cases_dir == "./examples/testcases"

    def test_frozen(self) -> None:
        cfg = load_app_config(None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.baud = 9600  # type: ignore[misc]


class TestSections:
    def test_full_config(self) -> None:
        cfg = load_app_config(
            """
ports: ["COM3:9600:8N1"]
default:
  step_timeout: 10
  baud: 9600
  log_level: debug
cases_dir: ./tc
report_dir: ./r
console:
  color: false
  command_truncate: 20
log:
  dir: ./lg
pressure:
  pass_rate_threshold: 90
""",
            source="test.yaml",
        )
        assert cfg.ports[0].name == "COM3"
        assert cfg.ports[0].baudrate == 9600  # 显式冒号段，不被 default.baud 覆盖
        assert cfg.step_timeout == 10.0
        assert cfg.baud == 9600
        assert cfg.log_level == "debug"
        assert cfg.cases_dir == "./tc"
        assert cfg.console_color is False
        assert cfg.command_truncate == 20
        assert cfg.log_dir == "./lg"
        assert cfg.pressure_pass_rate_threshold == 90.0


class TestDefaultBaudFill:
    """P2 修复：default.baud 填充未显式给波特率的端口表达式."""

    def test_bare_port_gets_default_baud(self) -> None:
        cfg = load_app_config(
            """
ports: ["COM3"]
default:
  baud: 9600
"""
        )
        assert cfg.ports[0].baudrate == 9600

    def test_explicit_baud_not_overridden(self) -> None:
        cfg = load_app_config(
            """
ports: ["COM3:115200"]
default:
  baud: 9600
"""
        )
        assert cfg.ports[0].baudrate == 115200

    def test_no_default_baud_bare_port_keeps_115200(self) -> None:
        cfg = load_app_config('ports: ["COM3"]')
        assert cfg.ports[0].baudrate == 115200

    def test_trailing_colon_counts_as_explicit_default(self) -> None:
        # "COM3:"（空波特率段）——parse_port_expr 走默认 115200；含冒号不填充
        cfg = load_app_config(
            """
ports: ["COM3:"]
default:
  baud: 9600
"""
        )
        assert cfg.ports[0].baudrate == 115200


class TestErrorConvergence:
    """P2 修复：值错误全部收敛 AppConfigError（旧实现裸抛）."""

    def test_bad_step_timeout(self) -> None:
        with pytest.raises(AppConfigError, match="step_timeout"):
            load_app_config("default:\n  step_timeout: abc")

    def test_bad_baud(self) -> None:
        with pytest.raises(AppConfigError, match=r"default\.baud"):
            load_app_config("default:\n  baud: xyz")

    def test_bad_command_truncate(self) -> None:
        with pytest.raises(AppConfigError, match="command_truncate"):
            load_app_config("console:\n  command_truncate: xyz")

    def test_non_string_port_item(self) -> None:
        with pytest.raises(AppConfigError, match="ports"):
            load_app_config("ports: [115200]")

    def test_bad_frame_converged(self) -> None:
        with pytest.raises(AppConfigError, match="帧格式无效"):
            load_app_config('ports: ["COM3:115200:XYZ"]')

    def test_bad_baud_in_expr(self) -> None:
        with pytest.raises(AppConfigError, match="波特率无效"):
            load_app_config('ports: ["COM3:abc"]')

    def test_yaml_syntax_error(self) -> None:
        with pytest.raises(AppConfigError, match="YAML 语法错误"):
            load_app_config("ports: [unclosed")

    def test_non_dict_root(self) -> None:
        with pytest.raises(AppConfigError, match="根节点"):
            load_app_config("- a\n- b\n")

    def test_non_list_ports(self) -> None:
        with pytest.raises(AppConfigError, match="'ports' 必须是列表"):
            load_app_config("ports: COM3")


class TestParsePortExpr:
    def test_full_expr(self) -> None:
        p = parse_port_expr("COM3:115200:8N1")
        assert p.name == "COM3"
        assert p.baudrate == 115200
        assert p.frame.databits == 8

    def test_name_only(self) -> None:
        p = parse_port_expr("COM3")
        assert p.name == "COM3"
        assert p.baudrate == 115200

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(AppConfigError, match="端口表达式无效"):
            parse_port_expr("  ")


class TestLogKeepRemoved:
    def test_log_keep_ignored_not_stored(self) -> None:
        # log.keep 死键已移除：配置里写了被忽略（不报错），字段不存在
        cfg = load_app_config("log:\n  dir: ./x\n  keep: 3")
        assert cfg.log_dir == "./x"
        assert not hasattr(cfg, "log_keep")


class TestResolveConfigPath:
    """配置定位单点（批 5 收敛）：显式 --config > 打包态 exe 同级 > cwd.

    旧实现 run/list/mcp/GUI 四处复制同一三分支，此处钉单点行为。
    """

    def test_explicit_config_wins(self, tmp_path, monkeypatch) -> None:  # noqa: ANN001, no-untyped-def
        from atprobe.infra.config import appconfig

        explicit = tmp_path / "my.yaml"
        monkeypatch.setattr(appconfig, "is_frozen", lambda: True)  # 打包态也不越权
        assert appconfig.resolve_config_path(explicit) == explicit

    def test_dev_falls_back_to_cwd(self, monkeypatch) -> None:  # noqa: ANN001, no-untyped-def
        from atprobe.infra.config import appconfig

        monkeypatch.setattr(appconfig, "is_frozen", lambda: False)
        assert appconfig.resolve_config_path() == Path("atprobe.yaml")

    def test_frozen_picks_beside_exe_when_exists(self, tmp_path, monkeypatch) -> None:  # noqa: ANN001, no-untyped-def
        from atprobe.infra.config import appconfig

        exe_level = tmp_path / "atprobe.yaml"
        exe_level.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(appconfig, "is_frozen", lambda: True)
        monkeypatch.setattr(appconfig, "resolve_workspace_path", lambda raw: tmp_path / raw)
        assert appconfig.resolve_config_path() == exe_level

    def test_frozen_missing_beside_exe_falls_back_to_cwd(self, tmp_path, monkeypatch) -> None:  # noqa: ANN001, no-untyped-def
        from atprobe.infra.config import appconfig

        monkeypatch.setattr(appconfig, "is_frozen", lambda: True)
        monkeypatch.setattr(appconfig, "resolve_workspace_path", lambda raw: tmp_path / raw)
        assert appconfig.resolve_config_path() == Path("atprobe.yaml")
