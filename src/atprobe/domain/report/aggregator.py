"""结果聚合器（M3 §8.2 / §4.6 汇总规则）.

纯函数：从一组 CaseResult 聚合出 Summary。供引擎结束与报告使用。
"""

from __future__ import annotations

from atprobe.domain.report.models import CaseResult, CaseStatus, Summary


def aggregate(
    case_results: list[CaseResult] | tuple[CaseResult, ...],
    *,
    start_time: str = "",
    end_time: str = "",
    duration_ms: float = 0.0,
    by_tag: bool = True,
) -> Summary:
    """聚合用例结果为概览（M3 §8.2）.

    pass_rate 分母排除 SKIPPED 和 INTERRUPTED（§8.2 备注）。
    """
    total = len(case_results)
    passed = sum(1 for c in case_results if c.status is CaseStatus.PASS)
    failed = sum(1 for c in case_results if c.status is CaseStatus.FAIL)
    skipped = sum(1 for c in case_results if c.status is CaseStatus.SKIPPED)
    interrupted = sum(1 for c in case_results if c.status is CaseStatus.INTERRUPTED)

    denom = total - skipped - interrupted
    pass_rate = (passed / denom * 100.0) if denom > 0 else 0.0

    tag_stats: dict[str, dict[str, int]] = {}
    if by_tag:
        for c in case_results:
            for tag in c.tags:
                bucket = tag_stats.setdefault(tag, {"total": 0, "passed": 0, "failed": 0})
                bucket["total"] += 1
                if c.status is CaseStatus.PASS:
                    bucket["passed"] += 1
                elif c.status is CaseStatus.FAIL:
                    bucket["failed"] += 1

    return Summary(
        start_time=start_time,
        end_time=end_time,
        duration_ms=duration_ms,
        total_cases=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        interrupted=interrupted,
        pass_rate=pass_rate,
        by_tag=tag_stats,
    )
