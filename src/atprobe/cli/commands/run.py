"""M5 `run` 子命令（REQ-M5 §3）.

把命令行参数 + 配置文件翻译成 M3 engine.start(配置) 调用，订阅进度事件渲染控制台，
结束后触发 M4 生成 HTML 报告。

顶层只留 typer/stdlib（engine/jinja2/ruamel 等重型依赖全部下沉到命令体内——
`atprobe --version` / `gui` / `mcp` 等其它子命令不为 run 的执行链买单）。
"""

from __future__ import annotations

import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from atprobe.infra.serial.config import PortConfig

if TYPE_CHECKING:
    from atprobe.domain.report.models import ExecutionResult


def run(
    paths: list[Path] = typer.Argument(None, help="用例/套件/目录路径（省略则用配置 cases_dir）"),
    port: list[str] = typer.Option(
        [], "--port", "-p", help="端口复合表达式 COM3:115200:8N1，可重复"
    ),
    tag: list[str] = typer.Option([], "--tag", "-t", help="标签过滤（并集），可重复"),
    exclude_tag: list[str] = typer.Option([], "--exclude-tag", help="排除标签"),
    config: Path | None = typer.Option(None, "--config", "-c", help="配置文件路径"),
    env_config: Path | None = typer.Option(None, "--env-config", help="环境配置文件（M7）"),
    no_color: bool = typer.Option(False, "--no-color", help="关闭控制台颜色"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只校验不实际执行"),
    no_report: bool = typer.Option(False, "--no-report", help="不生成 HTML 报告"),
    report_dir: Path | None = typer.Option(None, "--report-dir", help="报告输出目录"),
    log_level: str | None = typer.Option(
        None, "--log-level", help="progress / debug（缺省用配置文件 default.log_level）"
    ),
    vsim: bool = typer.Option(
        False,
        "--vsim",
        help="进程内虚拟模组模式（无需开发板/虚拟串口，用例直接驱动内置 AT 应答器）",
    ),
    vsim_rssi: int = typer.Option(
        23, "--vsim-rssi", help="虚拟模组 CSQ 信号 0..31（--vsim 时生效）"
    ),
    vsim_cereg: int = typer.Option(
        1, "--vsim-cereg", help="虚拟模组 CEREG 状态 0..5（--vsim 时生效）"
    ),
    baud: int | None = typer.Option(
        None, "--baud", help="覆盖所有端口的波特率（默认 115200 或配置文件 default.baud）"
    ),
    debug: bool = typer.Option(
        False, "--debug", help="开启详细日志（DEBUG 级，记录串口/引擎细节）"
    ),
) -> None:
    """执行测试用例/套件/目录."""
    # 日志初始化（CLI 最早接入；--debug 提到 DEBUG 级，记录串口/引擎细节）
    import logging

    from atprobe.infra.logging_config import setup_logging

    setup_logging(level=logging.DEBUG if debug else logging.INFO)
    if debug:
        logging.getLogger("atprobe").info("--debug 模式：详细日志已开启")

    # 重型依赖集中下沉到命令体（见模块 docstring）
    from atprobe.domain.case.parser import CaseParseError
    from atprobe.domain.suite import SuiteParseError
    from atprobe.domain.suite.collect import collect_case_paths, filter_by_tags, load_cases
    from atprobe.engine import Engine, EngineConfig
    from atprobe.infra.config.appconfig import (
        AppConfigError,
        load_app_config_file,
        parse_port_expr,
        resolve_config_path,
    )
    from atprobe.infra.config.envconfig import EnvConfigError, load_env_config_file
    from atprobe.infra.resources import resolve_workspace_path
    from atprobe.reporting.console import (
        format_case_result,
        format_case_start,
        format_step_line,
    )
    from atprobe.reporting.html import HtmlReporter
    from atprobe.reporting.interfaces import ReportOutput

    # 1. 加载配置（定位规则收敛 resolve_config_path 单点，与 list/mcp/GUI 一致）
    cfg_path = resolve_config_path(config)
    # P2 修复：配置加载错误收敛为 exit 2（旧实现 AppConfigError 直面 traceback）
    try:
        app_cfg = load_app_config_file(cfg_path)
    except AppConfigError as exc:
        typer.secho(f"配置错误：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    # P2 修复（覆盖链补全）：--log-level 未给时用配置文件 default.log_level
    # （旧实现该配置字段无消费者）
    if log_level is None:
        log_level = app_cfg.log_level
    # 复审修复：大小写归一——YAML 写 DEBUG/Debug 曾静默退化为 progress 行为
    log_level = log_level.strip().lower()

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
        typer.secho(
            "错误：未指定端口（--port 或配置文件 ports，或用 --vsim）",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    if not ports:
        typer.secho("错误：端口列表为空", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    # --baud 覆盖所有端口波特率（REQ-M5 §3.2）；urc_filter（噪声 URC 剥离）
    # 来自配置文件，注入所有端口（SerialConnection 构造时编译正则）
    if not vsim:
        from dataclasses import replace as _replace

        ports = [_replace(p, urc_filter=app_cfg.urc_filter) for p in ports]
        if baud is not None:
            ports = [_replace(p, baudrate=baud) for p in ports]

    # 3. 加载用例（展开目录）——共享收集逻辑（domain/suite/collect，MCP 复用）
    case_paths, path_warnings = collect_case_paths(paths, resolve_workspace_path(app_cfg.cases_dir))
    for w in path_warnings:
        typer.secho(f"警告：{w}", fg=typer.colors.YELLOW, err=True)
    if not case_paths:
        typer.secho("错误：未找到任何用例文件", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    # 套件文件识别（suite- 前缀）与解析在 load_cases 内完成；错误文案按异常
    # 类型区分，与抽取前的 CLI 输出保持一致
    try:
        collected = load_cases(case_paths)
    except SuiteParseError as exc:
        typer.secho(f"套件解析失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    except CaseParseError as exc:
        typer.secho(f"用例解析失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    # Collected 字段已 tuple 化（跨线程安全）；cases 后续要经 filter_by_tags
    # 重新赋值为 list，故先拷贝为局部 list（tuple(...) 进 EngineConfig 不变）
    cases = list(collected.cases)
    suite_setups = collected.suite_setup
    suite_teardowns = collected.suite_teardown

    # 4. 标签过滤（§3.4：多 --tag 并集；--exclude-tag 排除）
    cases = filter_by_tags(cases, tag, exclude_tag)
    if not cases:
        # 退出码口径：过滤条件把用例集清空是输入/用法问题 → 2（旧实现 1，
        # 与真实执行失败混淆，脚本无法区分重试价值）
        typer.secho("过滤后无可用用例", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(2)

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
            # 参数化实例显示 #N 后缀（与实际执行/报告一致）
            disp = c.name if c.param_index is None else f"{c.name}#{c.param_index}"
            typer.echo(f"  - {disp}  [{', '.join(c.tags)}]")
        typer.echo(f"端口：{', '.join(p.name for p in ports)}")
        typer.echo(f"用例数：{len(cases)}")
        # 端口可用性检查（REQ-M5 §3.2/§3.6）：vsim 跳过（虚拟端口不枚举）
        if not vsim:
            _check_ports_available(ports)
        return

    # 7. 构造引擎配置并执行
    # session_id 加 4 位随机后缀，避免连续快速运行时按秒生成的 id 冲突覆盖报告
    import secrets

    from atprobe.engine.config import StopMode
    from atprobe.engine.interfaces import (
        CaseResultEvent,
        CaseStartEvent,
        PressureProgressEvent,
        StepResultEvent,
    )

    session = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    # 用户显式 --report-dir 按 cwd；否则锚定工作区
    rdir = report_dir or resolve_workspace_path(app_cfg.report_dir)
    engine_cfg = EngineConfig(
        ports=tuple(ports),
        cases=tuple(cases),
        suite_setup=tuple(suite_setups),
        suite_teardown=tuple(suite_teardowns),
        step_timeout_default=app_cfg.step_timeout,
        pressure_pass_threshold=app_cfg.pressure_pass_rate_threshold,
        env_config=env_cfg,
        session_id=session,
        log_dir=str(resolve_workspace_path(app_cfg.log_dir)),
        # S-8 额外数据根：cases_dir 绝对路径（各用例自身目录由 case.source_file
        # 派生，此根覆盖「数据文件统一放 cases_dir、用例从别处单文件跑」的布局）
        data_allowed_roots=(str(resolve_workspace_path(app_cfg.cases_dir).resolve()),),
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
                        phase=ev.phase,
                        port=ev.port,
                        command=ev.command,
                        status=ev.status,
                        duration_ms=ev.duration_ms,
                        truncate=app_cfg.command_truncate,
                        color=color,
                        error_msg=ev.error_msg,
                    )
                )
                # 原始响应文本（\r\n 转义为可见 <CR><LF>，便于核对字节格式）：
                # debug 级打印所有步骤的响应；progress 级打印**非 PASS** 步骤的响应
                # （失败时必须能看到实际响应，否则无法定位文档与实测的差异——这是断言校准的前提）。
                show_resp = ev.response and (log_level == "debug" or ev.status != "PASS")
                if show_resp:
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

    # 启动级错误（如端口全部打开失败）：输出原因到 stderr，否则用户只能看到退出码 1 却不知为何
    if result.error:
        typer.secho(f"执行失败：{result.error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # 8. 控制台汇总 + 报告
    from atprobe.reporting.console import ConsoleReporter

    ConsoleReporter().render(result, ReportOutput(to_console=True, color=color))

    if not no_report:
        html_path = rdir / session / "report.html"
        HtmlReporter().render(result, ReportOutput(html_path=html_path, to_console=False))
        typer.echo(f"报告已生成: {html_path}")

    # 9. 退出码（§9）。口径（单一决策点 run_exit_code，与 HTML 报告徽标共用）：
    # 失败/跳过/suite_setup 失败 → 1（真实问题）；仅用户中断（Ctrl+C，无失败无
    # 跳过）→ 0（用户主动取消不是错误，与 update 取消下载同口径）；成功 0
    raise typer.Exit(_exit_code(result))


def _exit_code(result: ExecutionResult) -> int:
    """run 退出码（委托 domain/report.run_exit_code 单一决策点，特征测试直测）."""
    from atprobe.domain.report.models import run_exit_code

    return run_exit_code(result)


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
