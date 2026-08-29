"""M2/M8 用例收集共享逻辑（从 cli/commands/run.py 抽取，CLI 与 MCP 共用）.

纯函数：目录展开、套件/用例加载、参数化展开、标签过滤，以及套件文件
元信息的轻量读取（read_suite_meta，供 CLI list 与 MCP list_suites 展示）。
副作用（警告打印）由调用方处理——本模块返回 warnings 列表；解析失败
原样上抛（CaseParseError / SuiteParseError），呈现方式由调用方决定。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from atprobe.domain.case.models import Case, Step
from atprobe.domain.case.parser import parse_case_file
from atprobe.domain.suite.parser import SuiteParseError, parse_suite_file


def _normcase(p: Path) -> Path:
    """比较用规范化：normcase 折叠 Windows 大小写与斜杠方向.

    与 datasource._norm 同口径（S-7 越界判定与 S-8 锚定判定行为一致）；
    不 import 私有名，本地复刻。
    """
    return Path(os.path.normcase(str(p)))


def _within_dir(path: Path, directory: Path) -> bool:
    """S-7 判定：path（已 resolve）是否位于 directory（已 resolve）内.

    两侧 normcase 后 is_relative_to——Windows 大小写/斜杠差异不误判越界。
    """
    return _normcase(path).is_relative_to(_normcase(directory))


class SuiteMeta(NamedTuple):
    """套件文件轻量元信息（list 展示与 MCP list_suites 共用）.

    字段全可空：文件不可读/结构异常时返回全空值，调用方以文件名兜底展示。
    """

    name: str | None
    description: str | None
    case_count: int | None
    tags: tuple[str, ...]


def read_suite_meta(path: Path) -> SuiteMeta:
    """轻量解析套件文件的 name/description/cases 数量/tags.

    套件自有简单 schema，不走 Suite 模型完整解析（引用的用例文件不打开，
    cases 仅计数）——CLI list 与 MCP list_suites 共享（M8 Task 6 抽取）。
    """
    from io import StringIO

    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    try:
        raw = YAML(typ="safe").load(StringIO(path.read_text(encoding="utf-8")))
    # F-16：GBK 等非 UTF-8 文件抛 UnicodeDecodeError（ValueError 子类，
    # 非 OSError）。parse_case_file/parse_suite_file 文件包装层已同口径收敛
    # （F-16 同型补漏）；此处 read_suite_meta 是独立读文件入口，同样兜住
    # （list 展示容错语义：读不出元信息返回空值，不裸崩）
    except (YAMLError, OSError, UnicodeDecodeError):
        return SuiteMeta(None, None, None, ())
    if not isinstance(raw, dict):
        return SuiteMeta(None, None, None, ())
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
    return SuiteMeta(name, desc, case_count, tags)


@dataclass(frozen=True)
class Collected:
    """一次收集的完整结果：展开参数化后的用例 + 套件级前后置步骤.

    字段用 tuple（而非 list）：frozen dataclass 持 list 防不住 append()，
    tuple 化保证实例真正不可变，可安全跨线程传递（TSD §5.1，MCP 异步 job）。
    """

    cases: tuple[Case, ...] = ()
    suite_setup: tuple[Step, ...] = ()
    suite_teardown: tuple[Step, ...] = ()


def collect_case_paths(
    paths: list[Path] | None,
    cases_dir: Path,
    *,
    max_depth: int | None = None,
    max_files: int | None = None,
) -> tuple[list[Path], list[str]]:
    """展开位置参数为用例文件列表（目录递归、去重、目录扫描跳过 suite- 前缀）.

    返回 (文件列表, 警告列表)。paths 为 None/空 → 扫 cases_dir。
    显式指定的单个 suite- 文件保留（走套件执行路径，REQ-M2 §12）。

    S-3 扫描上限（MCP 传入，CLI 不传=行为不变）：max_depth 限相对起始目录的
    下潜深度（起始目录自身为 0 层，max_depth=4 即收 1-4 层子目录内文件，
    5 层起不收——防止 ``list_cases(path="C:\\")`` 之类全盘扫）；max_files 限
    收集总数，达到即停止收集并在 warnings 附截断提示。目录扫描用 os.walk
    手控深度（rglob 无法限制下潜），单路径内按路径字符串排序（保留 rglob
    sorted 的确定性语义），跨路径保持参数顺序（CLI 多参数执行序）。
    """
    if not paths:
        # 无位置参数时用配置的 cases_dir（调用方负责锚定到工作区）
        paths = [cases_dir]
    result: list[Path] = []
    seen: set[Path] = set()
    warnings: list[str] = []
    truncated = False
    for p in paths:
        if p.is_dir():
            # 单路径内先全量收集再按路径字符串排序（对齐旧 rglob+sorted 的确定性），
            # 跨路径保持参数顺序（CLI 多参数的执行序，T2 审查修复——不做全局排序）
            found: list[Path] = []
            for dirpath, dirnames, filenames in os.walk(p):
                cur = Path(dirpath)
                # 相对起始目录的深度（起始目录为 0）：到达上限即剪枝不再下潜
                # （当前层文件照收，下一层起不收）
                if max_depth is not None and len(cur.relative_to(p).parts) >= max_depth:
                    dirnames[:] = []
                for name in filenames:
                    # 同时覆盖 .yaml 与 .yml 两种后缀（大小写不敏感，对齐 Windows
                    # pathlib glob 行为——否则 .YAML 在目录扫描中被静默漏收）
                    f = cur / name
                    if f.suffix.lower() not in (".yaml", ".yml"):
                        continue
                    # 目录扫描排除套件文件避免与显式指定重复
                    if f.name.startswith("suite-"):
                        continue
                    found.append(f)
            found.sort(key=str)
            for f in found:
                key = f.resolve()
                if key in seen:
                    continue
                if max_files is not None and len(result) >= max_files:
                    truncated = True
                    break
                seen.add(key)
                result.append(f)
        elif p.is_file() and p.suffix.lower() in (".yaml", ".yml"):
            key = p.resolve()
            if key not in seen:
                if max_files is not None and len(result) >= max_files:
                    truncated = True
                else:
                    seen.add(key)
                    result.append(p)
        else:
            warnings.append(f"路径不存在 {p}")
        if truncated:
            break
    if truncated:
        warnings.append(f"文件数超过上限 {max_files}，已截断")
    return result, warnings


def load_cases(case_paths: list[Path]) -> Collected:
    """解析用例与套件文件（suite- 前缀走套件路径），展开参数化.

    顺序与原 CLI 行为一致：先按 case_paths 顺序处理全部套件，再处理散用例。
    S-7：套件引用的用例路径（相对套件目录）resolve 后越出套件目录 →
    SuiteParseError（../.. 与绝对路径不可借套件读取任意 YAML）。
    Raises:
        SuiteParseError: 套件文件解析失败或用例路径越界（原样上抛）。
        CaseParseError: 用例文件解析失败（原样上抛）。
    """
    suite_files = [p for p in case_paths if p.name.startswith("suite-")]
    case_files = [p for p in case_paths if not p.name.startswith("suite-")]

    # 内部用局部 list 累积，末尾一次性构造不可变 Collected（见类 docstring）
    cases: list[Case] = []
    suite_setup: list[Step] = []
    suite_teardown: list[Step] = []
    # 套件：解析 suite，按 cases 列表载入用例（相对套件文件所在目录）
    for sf in suite_files:
        suite = parse_suite_file(sf)
        suite_setup.extend(suite.suite_setup)
        suite_teardown.extend(suite.suite_teardown)
        suite_dir = sf.parent.resolve()
        for crel in suite.cases:
            cpath = (sf.parent / crel).resolve()
            # S-7：套件引用的用例必须在套件目录内（防 ../.. 与绝对路径读取任意 YAML）
            if not _within_dir(cpath, suite_dir):
                raise SuiteParseError(
                    f"套件用例路径越界：{crel!r}（须在套件目录内）", source=str(sf)
                )
            cases.extend(expand_parameters(parse_case_file(cpath)))

    # 普通用例文件
    for cp in case_files:
        cases.extend(expand_parameters(parse_case_file(cp)))
    return Collected(
        cases=tuple(cases),
        suite_setup=tuple(suite_setup),
        suite_teardown=tuple(suite_teardown),
    )


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


def filter_by_tags(cases: Sequence[Case], tags: list[str], exclude_tags: list[str]) -> list[Case]:
    """标签过滤（REQ-M5 §3.4：多 --tag 并集；--exclude-tag 排除）.

    tags 为空表示不过滤（全保留）；命中任一排除标签即剔除。
    """
    return [
        c
        for c in cases
        if (not tags or any(t in c.tags for t in tags))
        and not any(t in c.tags for t in exclude_tags)
    ]
