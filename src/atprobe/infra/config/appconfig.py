"""M5 atprobe.yaml 应用配置加载（REQ-M5 §3.5）.

集中所有可变参数的默认值，命令行参数覆盖之（M5 §3.2 优先级）。

P2 修复（异常收敛）：所有「配置值非法」路径统一抛 AppConfigError（旧实现
FrameFormat 帧格式错误/非字符串端口项/数值转换失败裸抛 ValueError/
AttributeError/TypeError，CLI 直面 traceback）。CLI 入口对 AppConfigError
统一 exit 2。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from atprobe.domain.case.redos import check_pattern
from atprobe.infra.serial.config import FrameFormat, PortConfig

_yaml = YAML(typ="safe")
_log = logging.getLogger("atprobe.config")


class AppConfigError(ValueError):
    """配置文件加载错误."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}" if source else message)


@dataclass(frozen=True)
class AppConfig:
    """atprobe.yaml 配置（M5 §3.5）.

    P3 修复：frozen（与 EnvConfig/UpdateConfig 一致）——跨模块共享的可变配置
    对象任何一处误改会全局生效；需要覆盖时用 dataclasses.replace（run.py 已有
    此用法）。

    注：log.keep 保留份数字段已移除（从未接入任何清理逻辑，静默无效误导用户）；
    日志目录按会话留存，手动清理。
    """

    ports: tuple[PortConfig, ...] = ()
    step_timeout: float = 5.0
    baud: int = 115200
    log_level: str = "progress"
    # 默认指向 <app_root>/examples/ 下（与打包外露布局、build.py expose_user_assets 一致）。
    # 用户未提供 atprobe.yaml 时，这些默认值仍能命中用户可写的 examples 副本，
    # 而非回退到 _internal 只读副本。
    cases_dir: str = "./examples/testcases"
    report_dir: str = "./reports"
    env_config: str = "./examples/env.yaml"
    console_color: bool = True
    command_truncate: int = 40
    log_dir: str = "./logs"
    pressure_pass_rate_threshold: float = 95.0
    # 噪声 URC 过滤（正则字符串元组，作用于所有端口）：匹配的行照常派发给 URC
    # 订阅者（不丢失），但从交付给断言的响应文本中整段剥离（含紧邻空行）。
    # 用于设备存在持续性主动上报的场景（如 N58 开启 GPS 循环输出后的
    # $MYGPSPOS 行每秒到达）。正则对 strip 后的整行内容 search。
    urc_filter: tuple[str, ...] = ()
    # M8 MCP 服务（本地 stdio 无认证；HTTP serve 用 token_file 认证）。
    # host 默认故意回环——对外开放需显式设 0.0.0.0（最小暴露面）。
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8470
    mcp_token_file: str | None = None
    # S-3 MCP 路径白名单（设计 §5）：list_cases/list_suites/start_run 等显式
    # 路径的信任边界。解析后的 cases_dir 恒在锚集内，本字段追加额外根
    # （编码机可放用例的共享目录等）；空元组=仅 cases_dir。
    mcp_allowed_roots: tuple[str, ...] = ()


def _to_int(value: object, *, what: str, source: str | None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str, float)):
        raise AppConfigError(f"{what} 必须是整数，实际为 {value!r}", source=source)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AppConfigError(f"{what} 必须是整数，实际为 {value!r}", source=source) from exc


def _to_float(value: object, *, what: str, source: str | None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AppConfigError(f"{what} 必须是数值，实际为 {value!r}", source=source)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AppConfigError(f"{what} 必须是数值，实际为 {value!r}", source=source) from exc


def load_app_config(data: str | bytes | None, *, source: str | None = None) -> AppConfig:
    """从 YAML 文本加载配置；data 为 None 或空 → 默认值（M5 §3.5 不报错）."""
    cfg = AppConfig()
    if not data:
        return cfg
    try:
        raw = _yaml.load(
            StringIO(data) if isinstance(data, str) else StringIO(data.decode("utf-8"))
        )
    except YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        loc = f"第 {line + 1} 行" if line is not None else "未知行"
        raise AppConfigError(f"YAML 语法错误（{loc}）：{exc}", source=source) from exc
    except UnicodeDecodeError as exc:
        raise AppConfigError(f"配置文件不是有效 UTF-8：{exc}", source=source) from exc
    if raw is None:
        return cfg
    if not isinstance(raw, dict):
        raise AppConfigError(f"配置根节点必须是映射，实际为 {type(raw).__name__}", source=source)

    # P2 修复（default.baud 覆盖链）：端口表达式未显式给波特率（无冒号段）时，
    # 用 default.baud 填充——旧实现 default.baud 是死字段（配置 9600 实际仍按
    # 115200 连接）。显式写了波特率的端口不受影响。
    default_baud: int | None = None

    if "ports" in raw:
        raw_ports = raw["ports"]
        if not isinstance(raw_ports, list):
            raise AppConfigError(
                f"'ports' 必须是列表，实际为 {type(raw_ports).__name__}", source=source
            )
        ports: list[PortConfig] = []
        for i, p in enumerate(raw_ports):
            if not isinstance(p, str):
                raise AppConfigError(
                    f"ports 第 {i + 1} 项必须是字符串（如 'COM3:115200:8N1'），实际为 {p!r}",
                    source=source,
                )
            ports.append(parse_port_expr(p, source=source))
        cfg = _replace(cfg, ports=tuple(ports))

    default = raw.get("default") or {}
    if isinstance(default, dict):
        if "step_timeout" in default:
            cfg = _replace(
                cfg,
                step_timeout=_to_float(default["step_timeout"], what="step_timeout", source=source),
            )
        if "baud" in default:
            default_baud = _to_int(default["baud"], what="default.baud", source=source)
            cfg = _replace(cfg, baud=default_baud)
        if "log_level" in default:
            cfg = _replace(cfg, log_level=str(default["log_level"]))
    if default_baud is not None and cfg.ports:
        filled = tuple(
            _replace_port_baud_if_absent(p, raw_expr, default_baud)
            for p, raw_expr in zip(cfg.ports, raw["ports"], strict=False)
        )
        cfg = _replace(cfg, ports=filled)

    cfg = _replace(
        cfg,
        cases_dir=str(raw.get("cases_dir", cfg.cases_dir)),
        report_dir=str(raw.get("report_dir", cfg.report_dir)),
        env_config=str(raw.get("env_config", cfg.env_config)),
    )
    console = raw.get("console") or {}
    if isinstance(console, dict):
        if "color" in console:
            cfg = _replace(cfg, console_color=bool(console["color"]))
        if "command_truncate" in console:
            cfg = _replace(
                cfg,
                command_truncate=_to_int(
                    console["command_truncate"], what="command_truncate", source=source
                ),
            )
    log = raw.get("log") or {}
    if isinstance(log, dict):
        if "dir" in log:
            cfg = _replace(cfg, log_dir=str(log["dir"]))
        # log.keep 已移除（从未生效的死配置，见 AppConfig docstring）
    pressure = raw.get("pressure") or {}
    if isinstance(pressure, dict):
        if "pass_rate_threshold" in pressure:
            cfg = _replace(
                cfg,
                pressure_pass_rate_threshold=_to_float(
                    pressure["pass_rate_threshold"], what="pass_rate_threshold", source=source
                ),
            )
    # 噪声 URC 过滤（列表项须为字符串；编译合法性由 SerialConnection 构造时
    # re.compile 校验——此处做类型收敛 + S-2 ReDoS 分级检测）
    urc_filter_raw = raw.get("urc_filter")
    if urc_filter_raw is not None:
        if not isinstance(urc_filter_raw, list) or not all(
            isinstance(x, str) for x in urc_filter_raw
        ):
            raise AppConfigError(
                f"'urc_filter' 必须是字符串列表（正则，匹配整行内容），实际：{urc_filter_raw!r}",
                source=source,
            )
        # S-2（设计 §5）：urc_filter 在串口读线程对每行噪声文本反复匹配，
        # 嵌套量词会被设备持续上报触发灾难性回溯卡死读线程——解析期硬拒。
        # 存量 N58 模式（如 ^\$MYGPSPOS:）不含嵌套量词，零误拒。
        for pat in urc_filter_raw:
            hard, warns = check_pattern(pat)
            if hard is not None:
                raise AppConfigError(
                    f"urc_filter 模式 {pat!r} 存在灾难性回溯风险（{hard}）——请改写为非嵌套量词形式",
                    source=source,
                )
            for w in warns:
                _log.warning("urc_filter 模式 %r：%s（静态提示，不阻断）", pat, w)
        cfg = _replace(cfg, urc_filter=tuple(urc_filter_raw))
    mcp = raw.get("mcp") or {}
    if isinstance(mcp, dict):
        if "host" in mcp:
            cfg = _replace(cfg, mcp_host=str(mcp["host"]))
        if "port" in mcp:
            cfg = _replace(cfg, mcp_port=_to_int(mcp["port"], what="mcp.port", source=source))
        if "token_file" in mcp and mcp["token_file"] is not None:
            cfg = _replace(cfg, mcp_token_file=str(mcp["token_file"]))
        # S-3 路径白名单（设计 §5）：字符串列表（空列表/显式 ~ 保持默认空元组，
        # 即仅 cases_dir）；路径本身的存在性/可读性不在配置层校验（服务层
        # _allowed_roots 统一 resolve 去重，越界提示由 MCP 错误契约给出）。
        if "allowed_roots" in mcp and mcp["allowed_roots"] is not None:
            roots_raw = mcp["allowed_roots"]
            if not isinstance(roots_raw, list) or not all(isinstance(x, str) for x in roots_raw):
                raise AppConfigError(
                    f"'mcp.allowed_roots' 必须是字符串列表（路径白名单），实际：{roots_raw!r}",
                    source=source,
                )
            cfg = _replace(cfg, mcp_allowed_roots=tuple(roots_raw))
    return cfg


def _replace(cfg: AppConfig, **changes: Any) -> AppConfig:
    from dataclasses import replace as _dc_replace

    return _dc_replace(cfg, **changes)


def _replace_port_baud_if_absent(p: PortConfig, raw_expr: object, default_baud: int) -> PortConfig:
    """端口表达式未显式给波特率（无任何冒号段）时填充 default.baud."""
    if isinstance(raw_expr, str) and ":" not in raw_expr.strip() and p.baudrate == 115200:
        from dataclasses import replace as _dc_replace

        return _dc_replace(p, baudrate=default_baud)
    return p


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
def parse_port_expr(expr: str, *, source: str | None = None) -> PortConfig:
    """解析复合端口表达式 ``COM3:115200:8N1``（M5 §3.3 BNF）."""
    parts = expr.split(":")
    name = parts[0].strip()
    if not name:
        raise AppConfigError(f"端口表达式无效：{expr!r}", source=source)
    baud = 115200
    frame = FrameFormat()
    if len(parts) >= 2 and parts[1].strip():
        try:
            baud = int(parts[1].strip())
        except ValueError as exc:
            raise AppConfigError(f"波特率无效：{parts[1]!r}", source=source) from exc
    if len(parts) >= 3 and parts[2].strip():
        try:
            frame = FrameFormat.parse(parts[2].strip())
        except ValueError as exc:
            # P2 修复：帧格式错误收敛为 AppConfigError（旧实现裸 ValueError 逃逸）
            raise AppConfigError(f"帧格式无效：{parts[2]!r}（{exc}）", source=source) from exc
    return PortConfig(name=name, baudrate=baud, frame=frame)


_parse_port_expr = parse_port_expr  # 别名用于内部
