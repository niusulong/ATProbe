"""AT 命令凭据脱敏（呈现层专用，批 5 T6-10）.

范围界定：
    - 掩的是「呈现文本」——控制台实时输出/汇总、HTML 报告的 command/request/
      response 字段；**rawlog 原始字节日志不掩**（功能预期：原始日志用于发送
      前后的字节级核对，T9 文档明示）。
    - 首版前缀表只收 PIN/密码类写形态（GSM 07.07）：``AT+CPIN=``（输入 PIN/PUK，
      含双参换 PIN 形态）、``AT+CPINW=``（写 PIN 计数，部分模组扩展）、
      ``AT+CPWD=``（修改设施密码，如 "P","1234","5678"）、``AT+CLCK=``（设施锁
      写形态，密码在参数段）。= 后参数段整体掩为 ``****``。
    - 明确**不掩**：``AT+CGDCONT=``（APN 不是凭据）、查询形态（如 ``AT+CPIN?``
      命令本身不含密钥）、测试形态（``AT+CPIN=?`` 仅枚举参数表）、响应正文
      （如 ``+CPIN: READY`` 无密钥——响应中仅命令回显经行首匹配被掩）。

mask_at_command 幂等：已掩文本（参数段已是 ****）再掩不变。
"""

from __future__ import annotations

import re
from dataclasses import replace as _dc_replace

from atprobe.domain.report.models import ExecutionResult, StepResult

# 敏感命令前缀表（大小写不敏感；= 后至行尾的参数段整体替换为 ****）。
# 新增前缀须先评估「参数段是否真含凭据」——APN/IP/端口等配置项不算。
# (?!\\?)：测试形态 ``AT+CPIN=?`` 不掩（T6 审查 m-1：无密钥，纯枚举参数表；
# 与查询形态 ``AT+CPIN?`` 同为无凭据呈现）。
_CREDENTIAL_PREFIX_RE = re.compile(
    r"(?im)^(AT\+(?:CPIN|CPINW|CPWD|CLCK)=(?!\?))[^\r\n]*",
)

_MASK = "****"


def mask_at_command(text: str) -> str:
    """掩码文本中的凭据类 AT 命令参数段（``AT+CPIN=1234`` → ``AT+CPIN=****``）.

    逐行行首匹配（MULTILINE）：命令文本与响应中的命令回显均出现在行首；
    行中段出现的同前缀字样不掩（避免误伤含该字样的正文）。幂等：已掩不再
    重复掩。非敏感命令原样返回。
    """
    return _CREDENTIAL_PREFIX_RE.sub(lambda m: m.group(1) + _MASK, text)


# ---------------------------------------------------------------------------
# ExecutionResult 呈现层脱敏（CLI run 单点接线：console 汇总 + HTML 报告共用）
# ---------------------------------------------------------------------------
def _mask_step(sr: StepResult) -> StepResult:
    """步骤结果脱敏：command/request（展示命令）/response（含命令回显）."""
    return _dc_replace(
        sr,
        command=mask_at_command(sr.command),
        request=mask_at_command(sr.request),
        response=mask_at_command(sr.response),
    )


def mask_execution_result(result: ExecutionResult) -> ExecutionResult:
    """返回命令文本已脱敏的执行结果副本（控制台汇总与 HTML 报告呈现用）.

    只改呈现字段（command/request/response 与压测 step_stats.command），
    不动统计与判定数据；入参 result 本身不被修改（frozen，全量重建副本）。
    """
    cases = tuple(
        _dc_replace(
            cr,
            setup_results=tuple(_mask_step(s) for s in cr.setup_results),
            step_results=tuple(_mask_step(s) for s in cr.step_results),
            teardown_results=tuple(_mask_step(s) for s in cr.teardown_results),
            pressure_stats=(
                _dc_replace(
                    cr.pressure_stats,
                    step_stats=tuple(
                        _dc_replace(ss, command=mask_at_command(ss.command))
                        for ss in cr.pressure_stats.step_stats
                    ),
                )
                if cr.pressure_stats is not None
                else None
            ),
        )
        for cr in result.case_results
    )
    return _dc_replace(
        result,
        case_results=cases,
        suite_setup_results=tuple(_mask_step(s) for s in result.suite_setup_results),
        suite_teardown_results=tuple(_mask_step(s) for s in result.suite_teardown_results),
    )
