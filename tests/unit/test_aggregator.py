"""结果聚合器单测（M3 §8.2 / §4.6）."""

from __future__ import annotations

from atprobe.domain.report.aggregator import aggregate
from atprobe.domain.report.models import CaseResult, CaseStatus


def _cr(name: str, status: CaseStatus, tags: tuple[str, ...] = ()) -> CaseResult:
    return CaseResult(case_name=name, case_file="x.yaml", status=status, tags=tags)


class TestAggregate:
    def test_all_pass(self) -> None:
        s = aggregate([_cr("a", CaseStatus.PASS), _cr("b", CaseStatus.PASS)])
        assert s.total_cases == 2
        assert s.passed == 2
        assert s.pass_rate == 100.0

    def test_mixed(self) -> None:
        s = aggregate([
            _cr("a", CaseStatus.PASS),
            _cr("b", CaseStatus.FAIL),
            _cr("c", CaseStatus.SKIPPED),
        ])
        assert (s.passed, s.failed, s.skipped) == (1, 1, 1)
        # pass_rate 分母排除 skipped：1/(3-1-0) = 50%
        assert s.pass_rate == 50.0

    def test_pass_rate_excludes_interrupted(self) -> None:
        s = aggregate([
            _cr("a", CaseStatus.PASS),
            _cr("b", CaseStatus.INTERRUPTED),
        ])
        # 1/(2-0-1) = 100%
        assert s.pass_rate == 100.0

    def test_empty(self) -> None:
        s = aggregate([])
        assert s.total_cases == 0
        assert s.pass_rate == 0.0

    def test_all_skipped_zero_division(self) -> None:
        s = aggregate([_cr("a", CaseStatus.SKIPPED)])
        assert s.pass_rate == 0.0

    def test_by_tag(self) -> None:
        s = aggregate([
            _cr("a", CaseStatus.PASS, ("network",)),
            _cr("b", CaseStatus.FAIL, ("network",)),
            _cr("c", CaseStatus.PASS, ("sms",)),
        ])
        assert s.by_tag["network"] == {"total": 2, "passed": 1, "failed": 1}
        assert s.by_tag["sms"] == {"total": 1, "passed": 1, "failed": 0}

    def test_no_by_tag_when_disabled(self) -> None:
        s = aggregate([_cr("a", CaseStatus.PASS, ("t",))], by_tag=False)
        assert s.by_tag == {}
