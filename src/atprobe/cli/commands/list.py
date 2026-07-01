"""M5 `list` 子命令（REQ-M5 §4）."""

from __future__ import annotations

from pathlib import Path

import typer

from atprobe.domain.case.parser import CaseParseError, parse_case_file
from atprobe.infra.config.appconfig import load_app_config_file
from atprobe.infra.resources import resolve_workspace_path
from atprobe.infra.runtime import is_frozen


def list_cmd(
    target: str = typer.Argument("cases", help="cases / suites / ports"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="标签过滤"),
) -> None:
    """列出可用用例 / 套件 / 串口."""
    # 用户显式 --config 按其值；否则打包态优先 exe 同级 atprobe.yaml，回退 cwd
    if config is not None:
        cfg_path = config
    elif is_frozen() and resolve_workspace_path("atprobe.yaml").exists():
        cfg_path = resolve_workspace_path("atprobe.yaml")
    else:
        cfg_path = Path("atprobe.yaml")
    app_cfg = load_app_config_file(cfg_path)

    cases_dir = resolve_workspace_path(app_cfg.cases_dir)
    if target == "ports":
        _list_ports()
        return
    if target == "suites":
        _list_suites(cases_dir)
        return
    # 默认 cases
    _list_cases(cases_dir, tag)


def _list_cases(cases_dir: Path, tag: list[str]) -> None:
    if not cases_dir.exists():
        typer.echo(f"用例目录不存在: {cases_dir}")
        raise typer.Exit(1)
    typer.echo(f"可用用例 (扫描目录: {cases_dir}):")
    count = 0
    for f in sorted(cases_dir.rglob("*.yaml")):
        if f.name.startswith("suite-"):
            continue
        try:
            c = parse_case_file(f)
        except CaseParseError:
            continue
        if tag and not any(t in c.tags for t in tag):
            continue
        rel = f.relative_to(cases_dir).parent
        tags = f"[{', '.join(c.tags)}]" if c.tags else ""
        typer.echo(f"  {rel}/")
        typer.echo(f"    {tags:<20} {c.name:<24} {f.name}")
        count += 1
    typer.echo(f"共 {count} 个用例")


def _list_suites(cases_dir: Path) -> None:
    if not cases_dir.exists():
        typer.echo(f"用例目录不存在: {cases_dir}")
        raise typer.Exit(1)
    typer.echo("可用套件:")
    count = 0
    for f in sorted(cases_dir.rglob("suite-*.yaml")):
        name, desc, case_count, tags = _parse_suite_meta(f)
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


def _parse_suite_meta(path: Path) -> tuple[str | None, str | None, int | None, tuple[str, ...]]:
    """轻量解析套件文件的 name/description/cases 数量/tags（套件自有简单 schema，不走 Case 模型）."""
    from io import StringIO

    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    try:
        raw = YAML(typ="safe").load(StringIO(path.read_text(encoding="utf-8")))
    except (YAMLError, OSError):
        return None, None, None, ()
    if not isinstance(raw, dict):
        return None, None, None, ()
    name = raw.get("name")
    desc = raw.get("description")
    cases = raw.get("cases")
    case_count = len(cases) if isinstance(cases, list) else None
    raw_tags = raw.get("tags")
    tags = tuple(str(t) for t in raw_tags) if isinstance(raw_tags, list) else ()
    if isinstance(name, str) and name:
        name = name.strip() or None
    else:
        name = None
    if not (isinstance(desc, str) and desc.strip()):
        desc = None
    else:
        desc = desc.strip()
    return name, desc, case_count, tags


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
        status = "占用中" if p.in_use else "可用"
        typer.echo(f"  {p.name:<12} ({p.description}, {status})")
