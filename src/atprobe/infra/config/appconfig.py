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
from atprobe.infra.resources import resolve_workspace_path
from atprobe.infra.runtime import is_frozen
from atprobe.infra.serial.config import FrameFormat, PortConfig
from atprobe.infra.update.config import UpdateConfig

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
    # 呈现层凭据脱敏开关（批 5 T6-10）：True 时控制台/HTML 报告/事件流中的
    # 凭据类 AT 命令（AT+CPIN=/AT+CPWD= 等）参数段掩为 ****；rawlog 原始字节
    # 日志不掩（字节级核对用）。默认 False，行为零变化。
    mask_credentials: bool = False
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
    # S-5 升级链路用户追加的下载主机（批 5 T8，批 4 终审预备⑨）：镜像/自建
    # 发布源主机名。空元组=仅内置 GitHub 白名单（默认，零变化）；经
    # update_config() 并入 UpdateConfig，与内置白名单**合并**生效（只能追加
    # 不能收窄内置项）。完整文档（update 段）见 docs/user/config-reference.md。
    update_allowed_hosts: tuple[str, ...] = ()

    def update_config(self) -> UpdateConfig:
        """构造升级链 UpdateConfig（CLI update / GUI UpdateController 接线单点）.

        用户 update.allowed_hosts 并入（其余 UpdateConfig 字段维持生产默认——
        api_base/repo/超时等不属于用户配置面）；返回 frozen 实例可直接传
        fetch_latest / UpdateSession。
        """
        return UpdateConfig(allowed_hosts=self.update_allowed_hosts)


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


def _to_bool(value: object, *, what: str, source: str | None) -> bool:
    """bool 配置项严格解析：值必须是 bool 类型（YAML true/false）.

    旧实现 ``bool(value)`` 把字符串 "false" 强转为 True（任何非空串都真值），
    用户写 ``color: "false"`` 会得到与字面相反的行为且无任何提示。此处按
    类型硬校验：非 bool（带引号字符串/数字等）即 AppConfigError，报错带键
    定位与去引号提示。与 _to_int/_to_float 同款口径（P2 异常收敛家族）。
    """
    if not isinstance(value, bool):
        raise AppConfigError(
            f"{what} 须为 true/false 布尔值（YAML 裸写，不要加引号），实际为 {value!r}",
            source=source,
        )
    return value


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
            # T6-2：严格 bool——旧实现 bool(console["color"]) 把字符串 "false"
            # 强转 True，行为与字面相反且无提示（详见 _to_bool docstring）。
            cfg = _replace(
                cfg, console_color=_to_bool(console["color"], what="console.color", source=source)
            )
        if "mask_credentials" in console:
            cfg = _replace(
                cfg,
                mask_credentials=_to_bool(
                    console["mask_credentials"], what="console.mask_credentials", source=source
                ),
            )
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
    # S-5 升级链白名单追加项（批 5 T8）：字符串列表（空列表/显式 ~ 保持默认空
    # 元组=仅内置 GitHub 白名单）；主机存在性不在配置层校验（downloader 触网
    # 时按 effective_allowed_hosts 判定，报错文案自带白名单列表）。
    update = raw.get("update") or {}
    if isinstance(update, dict):
        if "allowed_hosts" in update and update["allowed_hosts"] is not None:
            hosts_raw = update["allowed_hosts"]
            if not isinstance(hosts_raw, list) or not all(isinstance(x, str) for x in hosts_raw):
                raise AppConfigError(
                    f"'update.allowed_hosts' 必须是字符串列表（下载主机白名单追加项），实际：{hosts_raw!r}",
                    source=source,
                )
            cfg = _replace(cfg, update_allowed_hosts=tuple(hosts_raw))
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
    except UnicodeDecodeError as exc:
        # F-16 同型守卫（T7 审查 M-1）：GBK 等非 UTF-8 配置裸抛 UnicodeDecodeError
        # 会穿透 CLI（traceback+exit 1，违反 AppConfigError→exit 2 契约）并使
        # GUI 启动即崩（MainWindow.__init__ 无包裹）
        raise AppConfigError(
            f"配置文件非 UTF-8 编码，请转存为 UTF-8：{exc}", source=str(p)
        ) from exc
    return load_app_config(text, source=str(p))


def resolve_config_path(config: Path | None = None) -> Path:
    """定位 atprobe.yaml：显式 --config > 打包态 exe 同级 > cwd.

    CLI run/list/mcp 与 GUI MainWindow 四处共用的单点（此前各自复制粘贴
    同一三分支，漂移风险高）。用户显式 ``--config`` 按其原值（相对 cwd）；
    打包态优先 exe 同级 atprobe.yaml，找不到回退 cwd（开发态 cwd=仓库根，
    与 exe 同级等价）。仅定位路径，存在性/合法性由 load_app_config_file 判定
    （不存在 → 默认配置，不报错）。
    """
    if config is not None:
        return config
    if is_frozen():
        beside_exe = resolve_workspace_path("atprobe.yaml")
        if beside_exe.exists():
            return beside_exe
    return Path("atprobe.yaml")


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
