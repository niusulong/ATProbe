"""M5 `run` 子命令（REQ-M5 §3）.

把命令行参数 + 配置文件翻译成 M3 engine.start(配置) 调用，订阅进度事件渲染控制台，
结束后触发 M4 生成 HTML 报告。
"""

from __future__ import annotations

import signal
import sys
from datetime import datetime
from pathlib import Path

import typer

from atprobe.domain.case.parser import CaseParseError, parse_case_file
from atprobe.engine import Engine, EngineConfig
from atprobe.engine.config import StopMode
from atprobe.engine.interfaces import (
    CaseResultEvent,
    CaseStartEvent,
    PressureProgressEvent,
    StepResultEvent,
)
from atprobe.infra.config.appconfig import AppConfig, load_app_config_file, parse_port_expr
from atprobe.infra.config.envconfig import EnvConfigError, load_env_config_file
from atprobe.infra.resources import resolve_workspace_path
from atprobe.infra.runtime import is_frozen
from atprobe.infra.serial.config import PortConfig
from atprobe.reporting.console import (
    format_case_result,
    format_case_start,
    format_step_line,
)
from atprobe.reporting.html import HtmlReporter
from atprobe.reporting.interfaces import ReportOutput


def run(
    paths: list[Path] = typer.Argument(None, help="用例/套件/目录路径（省略则用配置 cases_dir）"),
    port: list[str] = typer.Option([], "--port", "-p", help="端口复合表达式 COM3:115200:8N1，可重复"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="标签过滤（并集），可重复"),
    exclude_tag: list[str] = typer.Option([], "--exclude-tag", help="排除标签"),
    config: Path | None = typer.Option(None, "--config", "-c", help="配置文件路径"),
    env_config: Path | None = typer.Option(None, "--env-config", help="环境配置文件（M7）"),
    no_color: bool = typer.Option(False, "--no-color", help="关闭控制台颜色"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只校验不实际执行"),
    no_report: bool = typer.Option(False, "--no-report", help="不生成 HTML 报告"),
    report_dir: Path | None = typer.Option(None, "--report-dir", help="报告输出目录"),
    log_level: str = typer.Option("progress", "--log-level", help="progress / debug"),
    vsim: bool = typer.Option(
        False, "--vsim",
        help="进程内虚拟模组模式（无需开发板/虚拟串口，用例直接驱动内置 AT 应答器）",
    ),
    vsim_rssi: int = typer.Option(23, "--vsim-rssi", help="虚拟模组 CSQ 信号 0..31（--vsim 时生效）"),
    vsim_cereg: int = typer.Option(1, "--vsim-cereg", help="虚拟模组 CEREG 状态 0..5（--vsim 时生效）"),
    baud: int | None = typer.Option(
        None, "--baud", help="覆盖所有端口的波特率（默认 115200 或配置文件 default.baud）"
    ),
) -> None:
    """执行测试用例/套件/目录."""
    # 1. 加载配置
    # 用户显式 --config 按其值（相对 cwd）；否则打包态优先找 exe 同级 atprobe.yaml，
    # 找不到回退 cwd（开发态 cwd=仓库根，与 exe 同级等价）。
    if config is not None:
        cfg_path = config
    elif is_frozen() and (resolve_workspace_path("atprobe.yaml")).exists():
        cfg_path = resolve_workspace_path("atprobe.yaml")
    else:
        cfg_path = Path("atprobe.yaml")
    app_cfg = load_app_config_file(cfg_path)

    # 2. 解析端口（§3.3）。--vsim 模式忽略端口参数，统一用虚拟端口
    if vsim:
        from atprobe.infra.serial.vsim import VSIM_PORT

        ports = [parse_port_expr(f"{VSIM_PORT}:115200:8N1")]
        typer.secho(
            f"[vsim] 进程内虚拟模组模式：rssi={vsim_rssi} cereg={vsim_cereg}，端口 {VSIM_PORT}",
            fg=typer.colors.CYAN,
        )
    elif port:
        ports = [parse_port_expr(p) for p in port]
    elif app_cfg.ports:
        ports = list(app_cfg.ports)
    else:
        typer.secho("错误：未指定端口（--port 或配置文件 ports，或用 --vsim）", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    if not ports:
        typer.secho("错误：端口列表为空", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    # --baud 覆盖所有端口波特率（REQ-M5 §3.2）
    if baud is not None and not vsim:
        from dataclasses import replace as _replace

        ports = [_replace(p, baudrate=baud) for p in ports]

    # 3. 加载用例（展开目录）
    case_paths = _resolve_case_paths(paths, app_cfg)
    if not case_paths:
        typer.secho("错误：未找到任何用例文件", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    cases = []
    for cp in case_paths:
        try:
            cases.append(parse_case_file(cp))
        except CaseParseError as exc:
            typer.secho(f"用例解析失败：{exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc

    # 4. 标签过滤（§3.4：多 --tag 并集；--exclude-tag 排除）
    if tag or exclude_tag:
        cases = [
            c for c in cases
            if (not tag or any(t in c.tags for t in tag))
            and not any(t in c.tags for t in exclude_tag)
        ]
    if not cases:
        typer.secho("过滤后无可用用例", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    # 5. 环境配置（M7）。用户显式 --env-config 按 cwd；否则锚定工作区
    env_path = env_config or resolve_workspace_path(app_cfg.env_config)
    env_cfg = None
    if env_path.exists():
        try:
            env_cfg = load_env_config_file(env_path)
        except EnvConfigError as exc:
            typer.secho(f"环境配置加载失败：{exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc

    color = (not no_color) and app_cfg.console_color and sys.stdout.isatty()

    # 6. dry-run（§3.6）
    if dry_run:
        typer.echo("Dry Run — 将执行的用例：")
        for c in cases:
            typer.echo(f"  - {c.name}  [{', '.join(c.tags)}]")
        typer.echo(f"端口：{', '.join(p.name for p in ports)}")
        typer.echo(f"用例数：{len(cases)}")
        # 端口可用性检查（REQ-M5 §3.2/§3.6）：vsim 跳过（虚拟端口不枚举）
        if not vsim:
            _check_ports_available(ports)
        return

    # 7. 构造引擎配置并执行
    # session_id 加 4 位随机后缀，避免连续快速运行时按秒生成的 id 冲突覆盖报告
    import secrets

    session = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    # 用户显式 --report-dir 按 cwd；否则锚定工作区
    rdir = report_dir or resolve_workspace_path(app_cfg.report_dir)
    engine_cfg = EngineConfig(
        ports=tuple(ports),
        cases=tuple(cases),
        step_timeout_default=app_cfg.step_timeout,
        pressure_pass_threshold=app_cfg.pressure_pass_rate_threshold,
        env_config=env_cfg,
        session_id=session,
        log_dir=str(resolve_workspace_path(app_cfg.log_dir)),
    )

    # --vsim：注入进程内虚拟模组作为 sender，引擎不连任何真实硬件
    if vsim:
        from atprobe.infra.serial.vsim import VsimPortManager

        _vsim_pm = VsimPortManager(rssi=vsim_rssi, cereg=vsim_cereg, echo=(log_level == "debug"))
        # 预连虚拟端口，引擎运行时无需真实 open
        from atprobe.infra.serial.config import PortConfig

        _vsim_pm.open(PortConfig(name=ports[0].name))
        engine = Engine(sender_factory=lambda: _vsim_pm)
    else:
        engine = Engine()

    # Ctrl+C 交互（§5.2）
    def _sigint(_sig, _frame):  # type: ignore[no-untyped-def]
        typer.echo("\n[Ctrl+C] 中断信号")
        engine.stop(mode=StopMode.ALL)

    signal.signal(signal.SIGINT, _sigint)

    # 事件渲染
    def handler(ev):  # type: ignore[no-untyped-def]
        if isinstance(ev, CaseStartEvent):
            typer.echo(format_case_start(ev.case_name, ev.case_index, ev.total_cases, color=color))
        elif isinstance(ev, StepResultEvent):
            # debug 级打印所有步骤；progress 级打印非 PASS 步骤
            if log_level == "debug" or ev.status != "PASS":
                typer.echo(
                    format_step_line(
                        phase=ev.phase, port=ev.port, command=ev.command,
                        status=ev.status, duration_ms=ev.duration_ms,
                        truncate=app_cfg.command_truncate, color=color, error_msg=ev.error_msg,
                    )
                )
                # debug 级额外打印原始响应文本（\r\n 转义为可见 <CR><LF>，便于核对字节格式）
                if log_level == "debug" and ev.response:
                    vis = ev.response.replace("\r", "<CR>").replace("\n", "<LF>")
                    typer.echo(f"           resp: {vis}")
        elif isinstance(ev, PressureProgressEvent):
            typer.echo(
                f"  进度: {ev.current_round}/{ev.total_rounds}轮 | 成功 {ev.success} | "
                f"失败 {ev.fail} | 平均 {ev.avg_ms:.0f}ms"
            )
        elif isinstance(ev, CaseResultEvent):
            typer.echo(format_case_result(ev.case_name, ev.status, ev.duration_ms, color=color))
            typer.echo("")

    result = engine.start(engine_cfg, handler=handler)

    # 8. 控制台汇总 + 报告
    from atprobe.reporting.console import ConsoleReporter

    ConsoleReporter().render(result, ReportOutput(to_console=True, color=color))

    if not no_report:
        html_path = rdir / session / "report.html"
        HtmlReporter().render(result, ReportOutput(html_path=html_path, to_console=False))
        typer.echo(f"报告已生成: {html_path}")

    # 9. 退出码（§9）
    s = result.summary
    if s.failed or s.skipped or s.interrupted:
        raise typer.Exit(1)
    raise typer.Exit(0)


def _resolve_case_paths(paths: list[Path], app_cfg: AppConfig) -> list[Path]:
    """展开位置参数为用例文件列表（目录递归，排除套件文件避免重复）."""
    if not paths:
        # 无位置参数时用配置的 cases_dir，锚定到工作区
        paths = [resolve_workspace_path(app_cfg.cases_dir)]
    result: list[Path] = []
    seen: set[Path] = set()
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*.yaml")):
                if f.name.startswith("suite-"):
                    continue
                if f.resolve() not in seen:
                    seen.add(f.resolve())
                    result.append(f)
        elif p.is_file() and p.suffix in (".yaml", ".yml"):
            if p.resolve() not in seen:
                seen.add(p.resolve())
                result.append(p)
        else:
            typer.secho(f"警告：路径不存在 {p}", fg=typer.colors.YELLOW, err=True)
    return result


def _check_ports_available(ports: list[PortConfig]) -> None:
    """dry-run 端口可用性检查：列出实际可枚举端口，提示哪些请求端口不存在/被占用（REQ-M5 §3.2）."""
    try:
        from atprobe.infra.serial.portmanager import PortManager

        available = {p.name for p in PortManager().enumerate_ports()}
    except Exception as exc:  # noqa: BLE001 - 枚举失败不阻断 dry-run，仅警告
        typer.secho(f"（端口枚举失败，跳过可用性检查：{exc}）", fg=typer.colors.YELLOW)
        return
    if not available:
        typer.secho("（系统未发现任何串口；执行时将尝试直接打开指定端口）", fg=typer.colors.YELLOW)
        return
    missing = [p.name for p in ports if p.name not in available]
    if missing:
        typer.secho(
            f"警告：以下端口在系统中未发现：{', '.join(missing)}（可用：{', '.join(sorted(available))}）",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(f"端口可用性检查：通过（可用端口：{', '.join(sorted(available))}）")
