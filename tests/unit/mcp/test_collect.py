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

    def test_empty_paths_scan_cases_dir(self, tmp_path: Path) -> None:
        # paths 为 None/空 → 扫 cases_dir（CLI 省略位置参数、MCP start_run 缺省）
        _write(tmp_path / "a.yaml", MINIMAL_CASE)
        files, warnings = collect_case_paths(None, cases_dir=tmp_path)
        assert [f.name for f in files] == ["a.yaml"]
        assert warnings == []

    def test_skips_suite_prefix_in_dir_scan(self, tmp_path: Path) -> None:
        _write(tmp_path / "suite-x.yaml", "name: s\n")
        _write(tmp_path / "b.yaml", MINIMAL_CASE)
        files, _ = collect_case_paths([tmp_path], cases_dir=tmp_path)
        assert [f.name for f in files] == ["b.yaml"]

    def test_explicit_suite_file_kept(self, tmp_path: Path) -> None:
        # 显式指定的 suite- 文件不跳过（单文件分支不走目录扫描的排除规则）
        sf = _write(tmp_path / "suite-x.yaml", "name: s\n")
        files, _ = collect_case_paths([sf], cases_dir=tmp_path)
        assert files == [sf]


class TestLoadCases:
    def test_plain_case(self, tmp_path: Path) -> None:
        _write(tmp_path / "c.yaml", MINIMAL_CASE)
        collected = load_cases([tmp_path / "c.yaml"])
        assert len(collected.cases) == 1
        assert collected.cases[0].name == "mini"
        assert collected.suite_setup == []
        assert collected.suite_teardown == []

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
