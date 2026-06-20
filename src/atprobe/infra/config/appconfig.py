"""M5 atprobe.yaml 应用配置加载（REQ-M5 §3.5）.

集中所有可变参数的默认值，命令行参数覆盖之（M5 §3.2 优先级）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from atprobe.infra.serial.config import FrameFormat, PortConfig

_yaml = YAML(typ="safe")


class AppConfigError(ValueError):
    """配置文件加载错误."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}" if source else message)


@dataclass
class AppConfig:
    """atprobe.yaml 配置（M5 §3.5）."""

    ports: list[PortConfig] = field(default_factory=list)
    step_timeout: float = 5.0
    baud: int = 115200
    log_level: str = "progress"
    cases_dir: str = "./testcases"
    report_dir: str = "./reports"
    env_config: str = "./env.yaml"
    console_color: bool = True
    command_truncate: int = 40
    log_dir: str = "./logs"
    log_keep: int = 0
    pressure_pass_rate_threshold: float = 95.0


def load_app_config(data: str | bytes | None, *, source: str | None = None) -> AppConfig:
    """从 YAML 文本加载配置；data 为 None 或空 → 默认值（M5 §3.5 不报错）."""
    cfg = AppConfig()
    if not data:
        return cfg
    try:
        raw = _yaml.load(StringIO(data) if isinstance(data, str) else StringIO(data.decode("utf-8")))
    except YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        loc = f"第 {line + 1} 行" if line is not None else "未知行"
        raise AppConfigError(f"YAML 语法错误（{loc}）：{exc}", source=source) from exc
    if raw is None:
        return cfg
    if not isinstance(raw, dict):
        raise AppConfigError(f"配置根节点必须是映射，实际为 {type(raw).__name__}", source=source)

    if "ports" in raw:
        cfg.ports = [_parse_port_expr(p) for p in raw["ports"]]
    default = raw.get("default") or {}
    if isinstance(default, dict):
        cfg.step_timeout = float(default.get("step_timeout", cfg.step_timeout))
        cfg.baud = int(default.get("baud", cfg.baud))
        cfg.log_level = str(default.get("log_level", cfg.log_level))
    cfg.cases_dir = str(raw.get("cases_dir", cfg.cases_dir))
    cfg.report_dir = str(raw.get("report_dir", cfg.report_dir))
    cfg.env_config = str(raw.get("env_config", cfg.env_config))
    console = raw.get("console") or {}
    if isinstance(console, dict):
        cfg.console_color = bool(console.get("color", cfg.console_color))
        cfg.command_truncate = int(console.get("command_truncate", cfg.command_truncate))
    log = raw.get("log") or {}
    if isinstance(log, dict):
        cfg.log_dir = str(log.get("dir", cfg.log_dir))
        cfg.log_keep = int(log.get("keep", cfg.log_keep))
    pressure = raw.get("pressure") or {}
    if isinstance(pressure, dict):
        cfg.pressure_pass_rate_threshold = float(
            pressure.get("pass_rate_threshold", cfg.pressure_pass_rate_threshold)
        )
    return cfg


def load_app_config_file(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        return AppConfig()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise AppConfigError(f"无法读取配置文件：{exc.strerror or exc}", source=str(p)) from exc
    return load_app_config(text, source=str(p))


# ---------------------------------------------------------------------------
# §3.3 --port 复合表达式解析（也用于配置文件 ports 列表）
# ---------------------------------------------------------------------------
def parse_port_expr(expr: str) -> PortConfig:
    """解析复合端口表达式 ``COM3:115200:8N1``（M5 §3.3 BNF）."""
    parts = expr.split(":")
    name = parts[0].strip()
    if not name:
        raise AppConfigError(f"端口表达式无效：{expr!r}")
    baud = 115200
    frame = FrameFormat()
    if len(parts) >= 2 and parts[1].strip():
        try:
            baud = int(parts[1].strip())
        except ValueError as exc:
            raise AppConfigError(f"波特率无效：{parts[1]!r}") from exc
    if len(parts) >= 3 and parts[2].strip():
        frame = FrameFormat.parse(parts[2].strip())
    return PortConfig(name=name, baudrate=baud, frame=frame)


_parse_port_expr = parse_port_expr  # 别名用于内部
