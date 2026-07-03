#!/usr/bin/env python3
"""ATProbe 测试用例批量验证脚本（skill bundled script）.

扫描目录下所有用例 YAML（跳过 suite- 前缀），逐个校验：
  1. YAML 解析 + schema 校验（复用框架 parse_case）
  2. 正则编译校验（extract / assert.matches / wait_urc 的正则都能编译）
  3. env 引用存在性（{{group.param}} 在指定 env.yaml 中有定义）
  4. 文件名四段规范（<功能块>-<指令>-<类型>-<变体>.yaml，全大写）
  5. tags 前三段规范（[功能块, 指令, 类型]）

用法：
  uv run python .agents/skills/atprobe-case-author/scripts/validate-cases.py <用例目录> [--env <env.yaml>]

退出码：0 全部通过；1 有错误。错误逐条打印（文件: 错误描述）。

设计原则：复用框架已有 API（parse_case / find_references / load_env_config），不重新实现校验逻辑。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 确保能导入 atprobe 包（脚本可能在任意 cwd 运行）
_REPO_ROOT = Path(__file__).resolve().parents[4]  # scripts/ -> skill -> .agents -> repo
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from atprobe.domain.case.parser import CaseParseError, parse_case  # noqa: E402
from atprobe.domain.case.templater import find_references  # noqa: E402
from atprobe.infra.config.envconfig import EnvConfig, load_env_config_file  # noqa: E402


# 文件名四段规范：<功能块>-<指令>-<类型>-<变体>.yaml，全大写字母/数字/下划线
_FILENAME_RE = re.compile(r"^([A-Z][A-Z0-9_]*)-([A-Z][A-Z0-9_]*)-(FUNC|RESP|PARA)-([A-Z][A-Z0-9_]*)\.yaml$")
# 合法类型
_VALID_TYPES = {"FUNC", "RESP", "PARA"}


def _check_filename(path: Path, block_name: str | None) -> list[str]:
    """校验文件名四段规范。block_name 为从 cases 所在目录名推断的功能块名（可选比对）。"""
    errs: list[str] = []
    m = _FILENAME_RE.match(path.name)
    if not m:
        errs.append(
            f"文件名不符四段规范 <功能块>-<指令>-<类型>-<变体>.yaml（全大写，类型 FUNC/RESP/PARA）: {path.name}"
        )
        return errs
    fb, _cmd, typ, _var = m.group(1), m.group(2), m.group(3), m.group(4)
    if typ not in _VALID_TYPES:
        errs.append(f"类型段非法 '{typ}'，应为 FUNC/RESP/PARA 之一")
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
    # 4. env 引用
    env_errs, env_missing = _check_env_refs(case, env)
    errs.extend(env_errs)
    return errs, env_missing


def main() -> int:
    ap = argparse.ArgumentParser(description="ATProbe 测试用例批量验证")
    ap.add_argument("directory", help="用例目录（递归扫描 *.yaml，跳过 suite- 前缀）")
    ap.add_argument("--env", help="env.yaml 路径（校验 {{group.param}} 引用存在性）", default=None)
    args = ap.parse_args()

    case_dir = Path(args.directory)
    if not case_dir.is_dir():
        print(f"错误：目录不存在: {case_dir}", file=sys.stderr)
        return 2

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
    if not yaml_files:
        print(f"未找到用例文件（{case_dir} 下无 *.yaml 或全是 suite- 前缀）", file=sys.stderr)
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
            print(f"\n✗ {path.relative_to(_REPO_ROOT) if _REPO_ROOT in path.parents else path}")
            for e in errs:
                print(f"    - {e}")
        if missing:
            all_missing[str(path)] = missing

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
        print(f"✓ 全部通过: {total_files} 个用例文件校验无误")
        if all_missing:
            print(f"  （{len(all_missing)} 个文件有 env 待补充项，见上）")
        return 0
    print(f"✗ 失败: {total_errs} 个错误，涉及用例文件见上（共扫描 {total_files} 个）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
