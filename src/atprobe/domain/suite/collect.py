"""M2/M8 用例收集共享逻辑（从 cli/commands/run.py 抽取，CLI 与 MCP 共用）.

纯函数：目录展开、套件/用例加载、参数化展开、标签过滤。副作用（警告打印）
由调用方处理——本模块返回 warnings 列表；解析失败原样上抛
（CaseParseError / SuiteParseError），呈现方式由调用方决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from atprobe.domain.case.models import Case, Step
from atprobe.domain.case.parser import parse_case_file
from atprobe.domain.suite import parse_suite_file


@dataclass(frozen=True)
class Collected:
    """一次收集的完整结果：展开参数化后的用例 + 套件级前后置步骤."""

    cases: list[Case] = field(default_factory=list)
    suite_setup: list[Step] = field(default_factory=list)
    suite_teardown: list[Step] = field(default_factory=list)


def collect_case_paths(paths: list[Path] | None, cases_dir: Path) -> tuple[list[Path], list[str]]:
    """展开位置参数为用例文件列表（目录递归、去重、目录扫描跳过 suite- 前缀）.

    返回 (文件列表, 警告列表)。paths 为 None/空 → 扫 cases_dir。
    显式指定的单个 suite- 文件保留（走套件执行路径，REQ-M2 §12）。
    """
    if not paths:
        # 无位置参数时用配置的 cases_dir（调用方负责锚定到工作区）
        paths = [cases_dir]
    result: list[Path] = []
    seen: set[Path] = set()
    warnings: list[str] = []
    for p in paths:
        if p.is_dir():
            # 同时覆盖 .yaml 与 .yml 两种后缀，与单文件分支接受的后缀保持一致
            # （否则目录下的 .yml 用例与 suite-*.yml 会被静默漏扫）
            for f in sorted(
                [*p.rglob("*.yaml"), *p.rglob("*.yml")],
                key=lambda x: str(x),
            ):
                # 目录扫描排除套件文件避免与显式指定重复
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
            warnings.append(f"路径不存在 {p}")
    return result, warnings


def load_cases(case_paths: list[Path]) -> Collected:
    """解析用例与套件文件（suite- 前缀走套件路径），展开参数化.

    顺序与原 CLI 行为一致：先按 case_paths 顺序处理全部套件，再处理散用例。
    Raises:
        SuiteParseError: 套件文件解析失败（原样上抛）。
        CaseParseError: 用例文件解析失败（原样上抛）。
    """
    suite_files = [p for p in case_paths if p.name.startswith("suite-")]
    case_files = [p for p in case_paths if not p.name.startswith("suite-")]

    collected = Collected()
    # 套件：解析 suite，按 cases 列表载入用例（相对套件文件所在目录）
    for sf in suite_files:
        suite = parse_suite_file(sf)
        collected.suite_setup.extend(suite.suite_setup)
        collected.suite_teardown.extend(suite.suite_teardown)
        for crel in suite.cases:
            cpath = (sf.parent / crel).resolve()
            collected.cases.extend(expand_parameters(parse_case_file(cpath)))

    # 普通用例文件
    for cp in case_files:
        collected.cases.extend(expand_parameters(parse_case_file(cp)))
    return collected


def expand_parameters(case: Case) -> list[Case]:
    """参数化展开：把 parameters 矩阵的每行展开为独立 Case 实例（REQ-M2 §10.2）.

    每个实例的 parameters 缩为单行，并带 param_index 序号（1-based）。
    非参数化用例（parameters 为空）返回单元素列表（原样）。
    """
    if not case.parameters:
        return [case]
    return [
        case.model_copy(update={"parameters": (row,), "param_index": idx})
        for idx, row in enumerate(case.parameters, start=1)
    ]


def filter_by_tags(cases: list[Case], tags: list[str], exclude_tags: list[str]) -> list[Case]:
    """标签过滤（REQ-M5 §3.4：多 --tag 并集；--exclude-tag 排除）.

    tags 为空表示不过滤（全保留）；命中任一排除标签即剔除。
    """
    return [
        c
        for c in cases
        if (not tags or any(t in c.tags for t in tags))
        and not any(t in c.tags for t in exclude_tags)
    ]
