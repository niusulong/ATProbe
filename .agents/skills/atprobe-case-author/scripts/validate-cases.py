#!/usr/bin/env python3
"""ATProbe 测试用例批量验证脚本（skill bundled script，可在任意工作区运行）.

扫描目录下所有用例 YAML（跳过 suite- 前缀），逐个校验：
  1. YAML 解析 + schema 校验（复用框架 parse_case）
  2. 正则编译校验（extract / assert.matches / wait_urc 的正则都能编译）
  3. env 引用存在性（{{group.param}} 在指定 env.yaml 中有定义）
  4. 文件名四段规范（<功能块>-<指令>-<类型>-<变体>.yaml，全大写）
  5. 条件表达式语法（when / poll.until 能被 evaluator 解析，含括号分组）

并对所有 suite-*.yaml 套件文件做：
  6. 套件解析（复用 parse_suite_file）
  7. 引用用例文件存在性（cases 列表里的相对路径文件确实存在）

用法（在任意工作区，用相对/绝对路径指向本脚本）：
  uv run python <skill所在>/scripts/validate-cases.py <用例目录> [--env <env.yaml>]
  或 atprobe 已 pip 安装：python <skill>/scripts/validate-cases.py <用例目录> --env env.yaml

环境要求：
  - 完整校验（schema + env）：当前 Python 环境需能 import atprobe（pip install / uv tool install）。
  - atprobe 未安装时自动降级为基础校验（YAML 语法 + 正则编译 + 文件名），并提示安装。

退出码：0 全部通过；1 有错误；2 环境错误。

设计原则：复用框架已有 API（parse_case / find_references / load_env_config），不重新实现校验；
不假设脚本所在路径与 atprobe 仓库的关系（可在任意工作区/任意安装方式下运行）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 优先用已安装的 atprobe（不假设仓库路径——本 skill 可在任意工作区运行）。
# 导入失败说明当前 Python 环境没装 atprobe，给清晰的安装指引后退出。
try:
    from atprobe.domain.case.parser import CaseParseError, parse_case
    from atprobe.domain.case.templater import find_references
    from atprobe.domain.case.evaluator import ExpressionError, evaluate
    from atprobe.domain.suite import SuiteParseError, parse_suite_file
    from atprobe.infra.config.envconfig import EnvConfig, load_env_config_file

    _HAS_ATPROBE = True
except ImportError:
    _HAS_ATPROBE = False
    CaseParseError = None  # type: ignore[assignment,misc]
    parse_case = None  # type: ignore[assignment]
    find_references = None  # type: ignore[assignment]
    ExpressionError = None  # type: ignore[assignment,misc]
    evaluate = None  # type: ignore[assignment]
    SuiteParseError = None  # type: ignore[assignment,misc]
    parse_suite_file = None  # type: ignore[assignment]
    EnvConfig = None  # type: ignore[assignment,misc]
    load_env_config_file = None  # type: ignore[assignment]


# 文件名四段规范：<功能块>-<指令>-<类型>-<变体>.yaml，全大写字母/数字/下划线
# 类型段：FUNC/RESP/PARA（指令中心用例）或 REGRESS（bug 回归用例，变体段放 BUGID）
_FILENAME_RE = re.compile(r"^([A-Z][A-Z0-9_]*)-([A-Z][A-Z0-9_]*)-(FUNC|RESP|PARA|REGRESS)-([A-Z][A-Z0-9_]*)\.yaml$")
# 合法类型
_VALID_TYPES = {"FUNC", "RESP", "PARA", "REGRESS"}


def _check_filename(path: Path, block_name: str | None) -> list[str]:
    """校验文件名四段规范。block_name 为从 cases 所在目录名推断的功能块名（可选比对）。"""
    errs: list[str] = []
    m = _FILENAME_RE.match(path.name)
    if not m:
        errs.append(
            f"文件名不符四段规范 <功能块>-<指令>-<类型>-<变体>.yaml（全大写，类型 FUNC/RESP/PARA/REGRESS）: {path.name}"
        )
        return errs
    fb, _cmd, typ, _var = m.group(1), m.group(2), m.group(3), m.group(4)
    if typ not in _VALID_TYPES:
        errs.append(f"类型段非法 '{typ}'，应为 FUNC/RESP/PARA/REGRESS 之一")
    # 若目录名是功能块大写，比对文件名第一段是否一致
    if block_name and fb != block_name:
        errs.append(f"文件名功能块段 '{fb}' 与所在目录名 '{block_name}' 不一致")
    return errs


def _iter_regexes(case) -> list[tuple[str, str]]:
    """从 Case 模型提取所有正则字符串（来源标注, 正则）。只收集，不编译。"""
    out: list[tuple[str, str]] = []
    for phase_name, steps in (("setup", case.setup), ("steps", case.steps), ("teardown", case.teardown or ())):
        for i, step in enumerate(steps):
            prefix = f"{phase_name}[{i}]"
            if step.extract:
                for k, pat in step.extract.items():
                    out.append((f"{prefix} extract.{k}", pat))
            if step.wait_urc:
                out.append((f"{prefix} wait_urc", step.wait_urc))
            for j, a in enumerate(step.assertions):
                if a.matches is not None:
                    out.append((f"{prefix} assert[{j}].matches", a.matches))
                if a.var is not None and a.op is not None and a.op.value == "matches":
                    # 变量断言的 matches（value 字段是正则）
                    if a.expected:
                        out.append((f"{prefix} assert[{j}].var.matches", a.expected))
    return out


def _check_regexes(case) -> list[str]:
    """编译所有正则，报告编译失败的。"""
    errs: list[str] = []
    for src, pat in _iter_regexes(case):
        try:
            re.compile(pat)
        except re.error as exc:
            errs.append(f"正则编译失败 [{src}]: {pat!r} → {exc}")
    return errs


def _check_condition_exprs(case) -> list[str]:
    """校验 when / poll.until 条件表达式语法（能被 evaluator 解析）。

    用空作用域求值：语法错误（缺运算符、括号不闭合等）会被 evaluator 拒绝；
    语义判定（变量未定义→null）不影响解析校验。
    """
    errs: list[str] = []
    for phase_name, steps in (("setup", case.setup), ("steps", case.steps), ("teardown", case.teardown or ())):
        for i, step in enumerate(steps):
            prefix = f"{phase_name}[{i}]"
            exprs: list[tuple[str, str]] = []
            if step.when:
                exprs.append((f"{prefix} when", step.when))
            if step.poll:
                exprs.append((f"{prefix} poll.until", step.poll.until))
            for src, expr in exprs:
                try:
                    evaluate(expr, {})
                except ExpressionError as exc:
                    errs.append(f"条件表达式语法错误 [{src}]: {expr!r} → {exc}")
                except Exception:
                    # 旧写法 {{var}} 在空作用域求值会因变量未定义抛错（引用错，非语法错），跳过。
                    # 新用例 when/poll.until 用裸名，未定义→null 不影响解析校验。
                    pass
    return errs


def _collect_command_templates(case) -> list[str]:
    """收集所有含 {{...}} 的 command 模板（用于 env 引用检查）。"""
    out: list[str] = []
    for steps in (case.setup, case.steps, case.teardown or ()):
        for step in steps:
            if step.command:
                out.append(step.command)
    return out


def _check_env_refs(case, env: EnvConfig | None) -> tuple[list[str], list[str]]:
    """校验 {{group.param}} env 引用是否存在。返回 (errors, missing_list)。

    简单名 {{var}}（extract 变量）不校验（运行时动态赋值）。只校验点号名 {{group.param}}。
    """
    errs: list[str] = []
    missing: list[str] = []
    if env is None:
        return errs, missing  # 未提供 env.yaml 则跳过此项
    for tpl in _collect_command_templates(case):
        for ref in find_references(tpl):
            if "." not in ref:
                continue  # 简单名（extract 变量），跳过
            parts = ref.split(".")
            if len(parts) != 2:
                errs.append(f"env 引用格式非法（仅支持两级 group.param）: {{{{{ref}}}}}")
                continue
            group, param = parts
            if group not in env.groups():
                missing.append(f"{ref}  # 组 '{group}' 不存在")
            elif param not in env.groups()[group]:
                missing.append(f"{ref}  # 组 '{group}' 缺字段 '{param}'")
    return errs, list(dict.fromkeys(missing))  # 去重保序


def validate_file(path: Path, env: EnvConfig | None, block_name: str | None) -> tuple[list[str], list[str]]:
    """验证单个用例文件。返回 (errors, env_missing)。"""
    errs: list[str] = []
    text = path.read_text(encoding="utf-8")
    # 1. YAML 解析 + schema
    try:
        case = parse_case(text, source=str(path))
    except CaseParseError as exc:
        errs.append(f"解析失败: {exc}")
        return errs, []
    # 2. 文件名
    errs.extend(_check_filename(path, block_name))
    # 3. 正则编译
    errs.extend(_check_regexes(case))
    # 4. 条件表达式语法（when / poll.until）
    errs.extend(_check_condition_exprs(case))
    # 5. env 引用
    env_errs, env_missing = _check_env_refs(case, env)
    errs.extend(env_errs)
    return errs, env_missing


def validate_suite(path: Path) -> list[str]:
    """验证单个套件文件。返回 errors。

    检查：套件能解析；cases 列表里的相对路径文件确实存在（相对套件文件所在目录）。
    """
    errs: list[str] = []
    try:
        suite = parse_suite_file(path)
    except SuiteParseError as exc:
        errs.append(f"套件解析失败: {exc}")
        return errs
    # 引用用例文件存在性（相对套件文件所在目录，与 CLI run.py 解析逻辑一致）
    for crel in suite.cases:
        cpath = (path.parent / crel).resolve()
        if not cpath.is_file():
            errs.append(f"套件引用的用例文件不存在: {crel}（相对套件目录 {path.parent}）")
    return errs


# ---------------------------------------------------------------------------
# 降级模式：atprobe 未安装时，纯标准库做基础校验（不依赖框架 schema）
# ---------------------------------------------------------------------------
def _run_basic_only(case_dir: Path) -> int:
    """无 atprobe 时的基础校验：YAML 语法 + 文件名规范 + 所有字符串值里的正则编译检查。

    较粗糙（不能解析 Case 模型，靠遍历 YAML dict 找正则字段），但能拦住大部分低级错误。
    """
    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError
    except ImportError:
        print("错误：降级校验需要 ruamel.yaml（atprobe 的依赖），请先安装 atprobe。", file=sys.stderr)
        return 2

    yaml_loader = YAML(typ="safe")
    # 用正则匹配 YAML 值里的正则特征（含 \+ \d \r \n 等）——粗筛，可能漏报但不误报
    re_value = re.compile(r"[\\\.()\[\]\d\*]")

    yaml_files = sorted(p for p in case_dir.rglob("*.yaml") if not p.name.startswith("suite-"))
    total_errs = 0
    for path in yaml_files:
        file_errs: list[str] = []
        # 文件名
        file_errs.extend(_check_filename(path, path.parent.name.upper() if path.parent.name else None))
        # YAML 语法
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml_loader.load(text)
        except YAMLError as exc:
            file_errs.append(f"YAML 语法错误: {exc}")
            data = None
        # 正则编译（粗筛：遍历 extract/wait_urc/matches 的值尝试编译）
        if isinstance(data, dict):
            _basic_check_regexes_in_dict(data, file_errs)
        if file_errs:
            total_errs += len(file_errs)
            try:
                rel = path.relative_to(Path.cwd())
            except ValueError:
                rel = path
            print(f"\n✗ {rel}")
            for e in file_errs:
                print(f"    - {e}")

    print(f"\n{'=' * 40}")
    if total_errs == 0:
        print(f"✓ 基础校验通过（降级模式，未做 schema/env 校验）")
        return 0
    print(f"✗ 失败: {total_errs} 个错误（降级模式）")
    return 1


def _basic_check_regexes_in_dict(data: dict, errs: list[str]) -> None:
    """遍历 YAML dict，对 extract/wait_urc/matches 字段值尝试正则编译。"""
    if not isinstance(data, dict):
        return
    for step_phase in ("setup", "steps", "teardown"):
        steps = data.get(step_phase)
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            # extract
            ext = step.get("extract")
            if isinstance(ext, dict):
                for k, v in ext.items():
                    if isinstance(v, str) and "\\" in v:
                        try:
                            re.compile(v)
                        except re.error as exc:
                            errs.append(f"{step_phase}[{i}] extract.{k} 正则无效: {exc}")
            # wait_urc
            wu = step.get("wait_urc")
            if isinstance(wu, str):
                try:
                    re.compile(wu)
                except re.error as exc:
                    errs.append(f"{step_phase}[{i}] wait_urc 正则无效: {exc}")
            # assert (列表或单条)
            ast = step.get("assert")
            _basic_check_assert_regex(ast, f"{step_phase}[{i}]", errs)


def _basic_check_assert_regex(ast, prefix: str, errs: list[str]) -> None:
    if isinstance(ast, dict):
        ast = [ast]
    if not isinstance(ast, list):
        return
    for j, a in enumerate(ast):
        if not isinstance(a, dict):
            continue
        m = a.get("matches")
        if isinstance(m, str):
            try:
                re.compile(m)
            except re.error as exc:
                errs.append(f"{prefix} assert[{j}].matches 正则无效: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="ATProbe 测试用例批量验证")
    ap.add_argument("directory", help="用例目录（递归扫描 *.yaml，跳过 suite- 前缀）")
    ap.add_argument("--env", help="env.yaml 路径（校验 {{group.param}} 引用存在性）", default=None)
    args = ap.parse_args()

    case_dir = Path(args.directory)
    if not case_dir.is_dir():
        print(f"错误：目录不存在: {case_dir}", file=sys.stderr)
        return 2

    # atprobe 未安装时降级：只能做不依赖框架的校验（文件名/正则/YAML 语法），
    # 跳过 schema 校验与 env 引用校验，并提示安装。
    if not _HAS_ATPROBE:
        print(
            "⚠ 未安装 atprobe，降级为基础校验（文件名/正则/YAML 语法），"
            "跳过 schema 与 env 引用校验。\n"
            "  完整校验请安装：uv tool install atprobe 或 pip install atprobe，"
            "或用 uv run python <脚本>",
            file=sys.stderr,
        )
        return _run_basic_only(case_dir)

    env: EnvConfig | None = None
    if args.env:
        env_path = Path(args.env)
        if not env_path.is_file():
            print(f"警告：env 文件不存在，跳过 env 引用校验: {env_path}", file=sys.stderr)
        else:
            try:
                env = load_env_config_file(str(env_path))
            except Exception as exc:  # noqa: BLE001
                print(f"警告：env 加载失败，跳过 env 引用校验: {exc}", file=sys.stderr)

    yaml_files = sorted(p for p in case_dir.rglob("*.yaml") if not p.name.startswith("suite-"))
    suite_files = sorted(p for p in case_dir.rglob("*.yaml") if p.name.startswith("suite-"))
    if not yaml_files and not suite_files:
        print(f"未找到用例文件（{case_dir} 下无 *.yaml）", file=sys.stderr)
        return 2

    total_errs = 0
    total_files = 0
    all_missing: dict[str, list[str]] = {}

    for path in yaml_files:
        total_files += 1
        # 推断功能块名：用例文件所在目录名（若是功能块目录）
        block_name = path.parent.name.upper() if path.parent.name else None
        errs, missing = validate_file(path, env, block_name)
        if errs:
            total_errs += len(errs)
            # 显示相对当前工作目录的路径（更短更清晰），不可相对则用绝对路径
            try:
                rel = path.relative_to(Path.cwd())
            except ValueError:
                rel = path
            print(f"\n✗ {rel}")
            for e in errs:
                print(f"    - {e}")
        if missing:
            all_missing[str(path)] = missing

    # 套件文件校验（解析 + 引用文件存在性）
    total_suites = 0
    for path in suite_files:
        total_suites += 1
        errs = validate_suite(path)
        if errs:
            total_errs += len(errs)
            try:
                rel = path.relative_to(Path.cwd())
            except ValueError:
                rel = path
            print(f"\n✗ {rel}")
            for e in errs:
                print(f"    - {e}")

    # 汇总 env 缺失项（跨文件去重）
    if all_missing:
        seen: set[str] = set()
        uniq_missing: list[str] = []
        for miss_list in all_missing.values():
            for m in miss_list:
                if m not in seen:
                    seen.add(m)
                    uniq_missing.append(m)
        print("\n⚠ env.yaml 待补充项（用例引用了但 env.yaml 未定义）:")
        for m in uniq_missing:
            print(f"    - {m}")

    print(f"\n{'=' * 40}")
    if total_errs == 0:
        suite_note = f"，{total_suites} 个套件文件" if total_suites else ""
        print(f"✓ 全部通过: {total_files} 个用例文件{suite_note}校验无误")
        if all_missing:
            print(f"  （{len(all_missing)} 个文件有 env 待补充项，见上）")
        return 0
    print(f"✗ 失败: {total_errs} 个错误，涉及文件见上（共扫描 {total_files} 个用例 + {total_suites} 个套件）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
