"""M5 `list` 子命令（REQ-M5 §4）.

顶层只留 typer/stdlib（parser/collect 的 pydantic+ruamel 下沉到命令体，
其它子命令不为 list 的解析链买单）。
"""

from __future__ import annotations

from pathlib import Path

import typer

# 损坏用例展示封顶（路径 + 错误摘要，超出折叠为一行计数）
_BROKEN_SHOW_LIMIT = 10
# 单条错误摘要截断宽度（解析错误可能带整段 YAML 上下文，防刷屏）
_ERR_SUMMARY_LIMIT = 120

_VALID_TARGETS = ("cases", "suites", "ports")


def list_cmd(
    target: str = typer.Argument("cases", help="cases / suites / ports"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="标签过滤"),
) -> None:
    """列出可用用例 / 套件 / 串口."""
    # 重型依赖下沉到命令体（见模块 docstring）
    from atprobe.infra.config.appconfig import (
        AppConfigError,
        load_app_config_file,
        resolve_config_path,
    )
    from atprobe.infra.resources import resolve_workspace_path

    # 配置定位规则收敛 resolve_config_path 单点（与 run/mcp/GUI 一致）
    try:
        app_cfg = load_app_config_file(resolve_config_path(config))
    except AppConfigError as exc:
        typer.secho(f"配置错误：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    cases_dir = resolve_workspace_path(app_cfg.cases_dir)
    if target == "ports":
        _list_ports()
        return
    if target == "suites":
        _list_suites(cases_dir)
        return
    if target == "cases":
        _list_cases(cases_dir, tag)
        return
    # 未知 target：明确报错 exit 2（旧实现静默落回用例列表，打错字如
    # "suite"/"port" 看似成功实则列表驴唇不对马嘴）
    typer.secho(
        f"未知的目标：{target}（可用：{' / '.join(_VALID_TARGETS)}）",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(2)


def _list_cases(cases_dir: Path, tag: list[str]) -> None:
    from atprobe.domain.case.parser import CaseParseError, parse_case_file

    if not cases_dir.exists():
        # 输入问题（目录不存在）→ exit 2（与 run 未找到用例同口径，非执行失败 1）
        typer.secho(f"用例目录不存在: {cases_dir}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    typer.echo(f"可用用例 (扫描目录: {cases_dir}):")
    count = 0
    # 损坏用例（解析失败）：路径 + 错误摘要，随计数汇总可见（旧实现 except 后
    # continue 静默吞掉，用户不知道自己的用例根本没列出来）
    broken: list[tuple[Path, str]] = []
    # M5 修复：同时扫 .yaml 与 .yml，与 run.py 一致（否则 .yml 用例被静默漏掉）
    # 后缀大小写不敏感（对齐 run/MCP 的 suffix.lower()——Linux 上 rglob 模式
    # 匹配大小写敏感会漏 .YAML/.Yml，批 5 终审 M-3）
    yaml_files = sorted(f for f in cases_dir.rglob("*") if f.suffix.lower() in (".yaml", ".yml"))
    for f in yaml_files:
        if f.name.startswith("suite-"):
            continue
        try:
            c = parse_case_file(f)
        except CaseParseError as exc:
            broken.append((f, _err_summary(str(exc))))
            continue
        if tag and not any(t in c.tags for t in tag):
            continue
        rel = f.relative_to(cases_dir).parent
        tags = f"[{', '.join(c.tags)}]" if c.tags else ""
        typer.echo(f"  {rel}/")
        typer.echo(f"    {tags:<20} {c.name:<24} {f.name}")
        count += 1
    if broken:
        typer.secho(
            f"解析失败 {len(broken)} 个（修复后才会被执行）：", fg=typer.colors.YELLOW, err=True
        )
        for f, err in broken[:_BROKEN_SHOW_LIMIT]:
            typer.secho(f"  {f}: {err}", fg=typer.colors.YELLOW, err=True)
        if len(broken) > _BROKEN_SHOW_LIMIT:
            typer.secho(
                f"  ……其余 {len(broken) - _BROKEN_SHOW_LIMIT} 个解析失败略",
                fg=typer.colors.YELLOW,
                err=True,
            )
    # 计数汇总：正常 N 个 + 解析失败 M 个并列（旧实现只报 N，M 不可见）
    summary = f"共 {count} 个用例"
    if broken:
        summary += f"，{len(broken)} 个解析失败"
    typer.echo(summary)


def _err_summary(err: str) -> str:
    """解析错误摘要：剥掉冗余的 ``[来源路径]`` 前缀（路径已单列展示）后取首行截断.

    解析错误可能带整段 YAML 上下文，不截断会刷屏；CaseParseError 文案自带
    ``[source]`` 前缀，与单列的路径重复，先剥再截。
    """
    text = err.strip()
    if text.startswith("[") and "] " in text:
        text = text.split("] ", 1)[1]
    first_line = text.splitlines()[0] if text else ""
    if len(first_line) > _ERR_SUMMARY_LIMIT:
        return first_line[: _ERR_SUMMARY_LIMIT - 1] + "…"
    return first_line


def _list_suites(cases_dir: Path) -> None:
    from atprobe.domain.suite.collect import read_suite_meta

    if not cases_dir.exists():
        # 输入问题 → exit 2（同 _list_cases 口径）
        typer.secho(f"用例目录不存在: {cases_dir}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    typer.echo("可用套件:")
    count = 0
    # M5 修复：同时扫 suite-*.yaml 与 suite-*.yml，与 run.py 一致
    suite_files = sorted(
        f for f in cases_dir.rglob("suite-*") if f.suffix.lower() in (".yaml", ".yml")
    )
    for f in suite_files:
        name, desc, case_count, tags = read_suite_meta(f)
        rel = f.relative_to(cases_dir)
        display_name = name or f.stem
        parts = [f"  {rel}", display_name]
        if tags:
            parts.append(f"[{', '.join(tags)}]")
        if desc:
            parts.append(f"({desc})")
        if case_count is not None:
            parts.append(f"({case_count} 用例)")
        typer.echo("  ".join(parts))
        count += 1
    typer.echo(f"共 {count} 个套件")


def _list_ports() -> None:
    try:
        from atprobe.infra.serial.portmanager import PortManager

        pm = PortManager()
        ports = pm.enumerate_ports()
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"端口枚举失败：{exc}", err=True)
        raise typer.Exit(2) from exc
    if not ports:
        typer.echo("未发现可用串口")
        return
    typer.echo("可用串口:")
    for p in ports:
        # 注：系统级占用检测已移除（旧实现对每个端口试探性独占打开，侵入他人
        # 进程）；in_use 仅反映本程序内连接状态，CLI 一次性进程恒为 False，
        # 不再展示误导性的「占用中」标注。
        typer.echo(f"  {p.name:<12} ({p.description})")
