"""domain/suite/collect.py 用例收集测试（M8，从 run.py 抽取）.

覆盖共享收集契约：目录展开（去重/跳过 suite- 前缀/缺失路径警告）、套件与用例
加载、参数化展开、标签并集过滤。CLI 与 MCP 共用此模块，故断言钉住纯函数语义
（不打印、异常上抛由调用方呈现）。

注：MINIMAL_CASE 的断言键为 ``assert``（AssertElement.contains），与
examples/testcases/3gpp 及 tests/integration/test_cli.py 的 schema 一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.domain.case.models import Case, Step
from atprobe.domain.case.parser import CaseParseError
from atprobe.domain.suite import SuiteParseError
from atprobe.domain.suite.collect import (
    collect_case_paths,
    expand_parameters,
    filter_by_tags,
    load_cases,
)

MINIMAL_CASE = """\
name: mini
tags: [smoke]
steps:
  - command: "AT"
    assert:
      - contains: "OK"
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _mk_case(name: str, tags: tuple[str, ...] = ()) -> Case:
    # Case.steps 必填（min_length=1），与 tags 无关的测试统一用最小步骤
    return Case(name=name, tags=tags, steps=(Step(command="AT"),))


class TestCollectCasePaths:
    def test_dir_and_missing(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.yaml", MINIMAL_CASE)
        files, warnings = collect_case_paths([tmp_path], cases_dir=tmp_path)
        assert [f.name for f in files] == ["a.yaml"]
        assert warnings == []

        files2, warnings2 = collect_case_paths([tmp_path / "nope"], cases_dir=tmp_path)
        assert files2 == []
        assert len(warnings2) == 1  # 路径不存在 → 警告（CLI 打印、MCP 记日志）

    def test_dir_scan_covers_yml_suffix(self, tmp_path: Path) -> None:
        # 历史坑钉住：目录扫描必须同时覆盖 .yml（否则会被静默漏扫）
        _write(tmp_path / "a.yaml", MINIMAL_CASE)
        _write(tmp_path / "b.yml", MINIMAL_CASE)
        files, _ = collect_case_paths([tmp_path], cases_dir=tmp_path)
        assert sorted(f.name for f in files) == ["a.yaml", "b.yml"]

    def test_skips_suite_prefix_in_dir_scan(self, tmp_path: Path) -> None:
        # suite- 前缀对两种后缀一致排除（.yml 同样不能漏）
        _write(tmp_path / "suite-x.yaml", "name: s\n")
        _write(tmp_path / "suite-y.yml", "name: s\n")
        _write(tmp_path / "b.yaml", MINIMAL_CASE)
        files, _ = collect_case_paths([tmp_path], cases_dir=tmp_path)
        assert [f.name for f in files] == ["b.yaml"]

    def test_dir_scan_recurses_into_subdirs(self, tmp_path: Path) -> None:
        # 嵌套目录递归：子目录里的用例也要被扫到（rglob 而非 iterdir）
        _write(tmp_path / "sub" / "nested.yaml", MINIMAL_CASE)
        _write(tmp_path / "top.yaml", MINIMAL_CASE)
        files, _ = collect_case_paths([tmp_path], cases_dir=tmp_path)
        assert sorted(f.name for f in files) == ["nested.yaml", "top.yaml"]

    def test_dir_and_explicit_file_overlap_dedups_by_resolve(self, tmp_path: Path) -> None:
        # 目录 + 显式文件重叠：resolve 去重后 a.yaml 只出现一次
        a = _write(tmp_path / "a.yaml", MINIMAL_CASE)
        _write(tmp_path / "b.yaml", MINIMAL_CASE)
        files, _ = collect_case_paths([tmp_path, a], cases_dir=tmp_path)
        assert sorted(f.name for f in files) == ["a.yaml", "b.yaml"]
        assert sum(1 for f in files if f.name == "a.yaml") == 1

    def test_empty_paths_scan_cases_dir(self, tmp_path: Path) -> None:
        # paths 为 None/空 → 扫 cases_dir（CLI 省略位置参数、MCP start_run 缺省）
        _write(tmp_path / "a.yaml", MINIMAL_CASE)
        files, warnings = collect_case_paths(None, cases_dir=tmp_path)
        assert [f.name for f in files] == ["a.yaml"]
        assert warnings == []

    def test_explicit_suite_file_kept(self, tmp_path: Path) -> None:
        # 显式指定的 suite- 文件不跳过（单文件分支不走目录扫描的排除规则）；
        # .yml 后缀同样保留（与 .yaml 一致）
        sf_yaml = _write(tmp_path / "suite-x.yaml", "name: s\n")
        sf_yml = _write(tmp_path / "suite-y.yml", "name: s\n")
        files, _ = collect_case_paths([sf_yaml, sf_yml], cases_dir=tmp_path)
        assert files == [sf_yaml, sf_yml]


class TestCollectCasePathsLimits:
    """S-3 扫描上限（MCP 传入 max_depth/max_files；CLI 不传=行为不变）."""

    def test_max_depth_excludes_fifth_level(self, tmp_path: Path) -> None:
        # 嵌套 5 层链：max_depth=4 收 1-4 层，第 5 层不收（防全盘扫）
        d = tmp_path
        for i in range(1, 6):
            d = d / f"l{i}"
            _write(d / f"a{i}.yaml", MINIMAL_CASE)
        files, warnings = collect_case_paths([tmp_path], cases_dir=tmp_path, max_depth=4)
        assert [f.name for f in files] == ["a1.yaml", "a2.yaml", "a3.yaml", "a4.yaml"]
        assert warnings == []

    def test_max_depth_top_level_always_scanned(self, tmp_path: Path) -> None:
        # max_depth=0：仅起始目录自身（不下潜任何子目录）
        _write(tmp_path / "top.yaml", MINIMAL_CASE)
        _write(tmp_path / "sub" / "nested.yaml", MINIMAL_CASE)
        files, _ = collect_case_paths([tmp_path], cases_dir=tmp_path, max_depth=0)
        assert [f.name for f in files] == ["top.yaml"]

    def test_max_files_truncates_with_warning(self, tmp_path: Path) -> None:
        # 文件数超上限：停止收集 + 截断警告（截断后保留排序在前的确定性子集）
        for i in range(5):
            _write(tmp_path / f"c{i}.yaml", MINIMAL_CASE)
        files, warnings = collect_case_paths([tmp_path], cases_dir=tmp_path, max_files=3)
        assert [f.name for f in files] == ["c0.yaml", "c1.yaml", "c2.yaml"]
        assert warnings == ["文件数超过上限 3，已截断"]

    def test_max_files_stops_across_paths(self, tmp_path: Path) -> None:
        # 上限跨 paths 计数：首个目录已满 → 后续路径不再收集（也不再有警告）
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        for i in range(2):
            _write(d1 / f"a{i}.yaml", MINIMAL_CASE)
        _write(d2 / "b.yaml", MINIMAL_CASE)
        files, warnings = collect_case_paths([d1, d2], cases_dir=tmp_path, max_files=2)
        assert [f.name for f in files] == ["a0.yaml", "a1.yaml"]
        assert warnings == ["文件数超过上限 2，已截断"]

    def test_no_limits_by_default(self, tmp_path: Path) -> None:
        # 缺省不设限（CLI 调用点行为不变）：深嵌套照收
        d = tmp_path
        for i in range(6):
            d = d / f"l{i}"
            _write(d / f"a{i}.yaml", MINIMAL_CASE)
        files, warnings = collect_case_paths([tmp_path], cases_dir=tmp_path)
        assert len(files) == 6
        assert warnings == []

    def test_sorted_order_preserved_with_walk(self, tmp_path: Path) -> None:
        # os.walk 改造后仍统一按路径排序（rglob sorted 的确定性语义保留）
        _write(tmp_path / "b" / "z.yaml", MINIMAL_CASE)
        _write(tmp_path / "a" / "y.yaml", MINIMAL_CASE)
        _write(tmp_path / "m.yaml", MINIMAL_CASE)
        files, _ = collect_case_paths([tmp_path], cases_dir=tmp_path)
        assert files == sorted(files, key=str)


class TestLoadCases:
    def test_plain_case(self, tmp_path: Path) -> None:
        _write(tmp_path / "c.yaml", MINIMAL_CASE)
        collected = load_cases([tmp_path / "c.yaml"])
        assert len(collected.cases) == 1
        assert collected.cases[0].name == "mini"
        # Collected tuple 化（TSD §5.1 跨线程安全）：空值为 ()
        assert collected.suite_setup == ()
        assert collected.suite_teardown == ()

    def test_collected_fields_are_tuples(self, tmp_path: Path) -> None:
        # 钉住不可变形态：frozen + tuple 字段，append 被类型系统挡住
        _write(tmp_path / "c.yaml", MINIMAL_CASE)
        collected = load_cases([tmp_path / "c.yaml"])
        assert isinstance(collected.cases, tuple)
        assert isinstance(collected.suite_setup, tuple)
        assert isinstance(collected.suite_teardown, tuple)

    def test_suite_references_and_setup_teardown(self, tmp_path: Path) -> None:
        # suite- 前缀走套件路径：setup/teardown 汇入，用例相对套件目录载入
        _write(tmp_path / "d.yaml", MINIMAL_CASE)
        _write(
            tmp_path / "suite-all.yaml",
            "name: s\n"
            "suite_setup:\n"
            "  - command: AT\n"
            "suite_teardown:\n"
            "  - command: AT\n"
            "cases:\n"
            "  - d.yaml\n",
        )
        collected = load_cases([tmp_path / "suite-all.yaml"])
        assert [c.name for c in collected.cases] == ["mini"]
        assert len(collected.suite_setup) == 1
        assert len(collected.suite_teardown) == 1

    def test_bad_case_raises_parse_error(self, tmp_path: Path) -> None:
        # 解析失败原样上抛（CLI 打印文案、MCP 记日志由调用方决定）
        _write(
            tmp_path / "bad.yaml",
            "name: x\nsteps:\n  - command: AT\n    bogus_key: 1\n",
        )
        with pytest.raises(CaseParseError):
            load_cases([tmp_path / "bad.yaml"])

    def test_bad_suite_raises_suite_parse_error(self, tmp_path: Path) -> None:
        # 套件文件解析失败同样原样上抛（与 CaseParseError 对称）
        _write(tmp_path / "suite-bad.yaml", "- not\n- a mapping\n")
        with pytest.raises(SuiteParseError):
            load_cases([tmp_path / "suite-bad.yaml"])

    # -- S-7：套件用例路径越界拒绝（防 ../.. 与绝对路径读取任意 YAML） -----------
    def test_suite_case_parent_escape_rejected(self, tmp_path: Path) -> None:
        outside = _write(tmp_path / "outside.yaml", MINIMAL_CASE)
        assert outside.exists()
        sf = _write(tmp_path / "sd" / "suite-esc.yaml", "name: esc\ncases:\n  - ../outside.yaml\n")
        with pytest.raises(SuiteParseError, match="越界"):
            load_cases([sf])

    def test_suite_case_absolute_path_rejected(self, tmp_path: Path) -> None:
        # 绝对路径引用：resolve 后不在套件目录内 → 拒（目标文件存在也不行）
        target = _write(tmp_path / "outside.yaml", MINIMAL_CASE)
        sf = _write(tmp_path / "sd" / "suite-abs.yaml", f"name: abs\ncases:\n  - {target}\n")
        with pytest.raises(SuiteParseError, match="越界"):
            load_cases([sf])

    def test_suite_case_subdir_relative_allowed(self, tmp_path: Path) -> None:
        # 合法相对路径：套件目录内的子目录引用通过（越界≠禁止子目录）
        _write(tmp_path / "sd" / "sub" / "d.yaml", MINIMAL_CASE)
        sf = _write(tmp_path / "sd" / "suite-sub.yaml", "name: sub\ncases:\n  - sub/d.yaml\n")
        collected = load_cases([sf])
        assert [c.name for c in collected.cases] == ["mini"]


class TestFilterByTags:
    def test_union_and_exclude(self) -> None:
        cases = [_mk_case("a", ("t1",)), _mk_case("b", ("t2",)), _mk_case("c", ("t3",))]
        assert [c.name for c in filter_by_tags(cases, ["t1", "t2"], [])] == ["a", "b"]
        assert [c.name for c in filter_by_tags(cases, [], ["t3"])] == ["a", "b"]

    def test_no_filters_returns_all(self) -> None:
        cases = [_mk_case("a", ("t1",)), _mk_case("b", ("t2",))]
        assert [c.name for c in filter_by_tags(cases, [], [])] == ["a", "b"]


class TestExpandParameters:
    def test_expands_to_indexed_instances(self) -> None:
        c = Case(
            name="p",
            steps=(Step(command="AT"),),
            parameters=[{"v": "1"}, {"v": "2"}],
        )
        out = expand_parameters(c)
        assert len(out) == 2
        assert out[0].param_index == 1
        assert out[1].param_index == 2
        # 每实例 parameters 缩为单行（REQ-M2 §10.2）
        assert out[0].parameters == ({"v": "1"},)
        assert out[1].parameters == ({"v": "2"},)

    def test_plain_case_returned_as_is(self) -> None:
        plain = _mk_case("q")
        assert expand_parameters(plain) == [plain]
        assert plain.param_index is None
