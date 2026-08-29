"""AT 命令凭据脱敏单测（批 5 T6-10）.

覆盖：前缀表全项、大小写不敏感、非敏感命令不变、查询形态不掩、APN 不掩、
幂等（已掩不再重复掩）、多行文本（响应中的命令回显）、ExecutionResult 副本
脱敏（统计/判定数据不动、入参不被修改）。
"""

from __future__ import annotations

from atprobe.domain.report.models import (
    CaseResult,
    ExecutionResult,
    InputType,
    PressureStats,
    StepPressureStats,
    StepResult,
    StepStatus,
    Summary,
)
from atprobe.infra.masking import mask_at_command, mask_execution_result


class TestMaskAtCommand:
    def test_prefix_table_full_coverage(self) -> None:
        """前缀表全项：参数段整体掩为 ****."""
        cases = {
            "AT+CPIN=1234": "AT+CPIN=****",
            "AT+CPIN=1234,5678": "AT+CPIN=****",  # 双参换 PIN 形态同样整段掩
            "AT+CPINW=1234": "AT+CPINW=****",
            'AT+CPWD="P","1234","5678"': "AT+CPWD=****",
            'AT+CLCK="SC",2,"1234"': "AT+CLCK=****",
        }
        for raw, want in cases.items():
            assert mask_at_command(raw) == want, f"{raw} 应掩码为 {want}"

    def test_case_insensitive(self) -> None:
        """小写命令形态同样掩码（设备接受小写 AT 命令）."""
        assert mask_at_command("at+cpin=1234") == "at+cpin=****"

    def test_non_sensitive_unchanged(self) -> None:
        """非敏感命令原样返回."""
        for cmd in (
            "AT",
            "AT+CSQ",
            'AT+CGDCONT=1,"IP","cmnet"',  # APN 不是凭据，明确不掩
            'AT+CMGS="10086"',
            "AT+CGMI? AT+CGMR? AT+CGSN",
        ):
            assert mask_at_command(cmd) == cmd

    def test_query_form_not_masked(self) -> None:
        """查询形态（AT+CPIN? 等）命令本身不含密钥，不掩."""
        assert mask_at_command("AT+CPIN?") == "AT+CPIN?"
        assert mask_at_command("AT+CLCK?") == "AT+CLCK?"

    def test_test_form_not_masked(self) -> None:
        """测试形态（AT+CPIN=? 仅枚举参数表）无密钥，不掩（T6 审查 m-1 钉子）."""
        assert mask_at_command("AT+CPIN=?") == "AT+CPIN=?"
        assert mask_at_command("AT+CPWD=?") == "AT+CPWD=?"

    def test_response_pin_status_not_masked(self) -> None:
        """响应正文中的 PIN 状态（+CPIN: READY）无密钥，不掩."""
        assert mask_at_command("\r\n+CPIN: READY\r\n") == "\r\n+CPIN: READY\r\n"

    def test_idempotent(self) -> None:
        """已掩文本再掩不变（**** 不重复叠加）."""
        once = mask_at_command("AT+CPIN=1234")
        assert mask_at_command(once) == once

    def test_multiline_echo_masked_per_line(self) -> None:
        """多行文本逐行行首匹配：响应中跟在换行后的命令回显被掩.

        典型响应形态（vsim echo）：``\\r\\nAT+CPIN=1234\\r\\nERROR\\r\\n``——回显
        不在字符串起点，靠 MULTILINE 行界命中；呈现层须在 <CR>/<LF> 转义
        **之前**掩码（转义后真实行界消失）。
        """
        text = "\r\nAT+CPIN=1234\r\nERROR\r\nAT+CPIN=1234\r\r\nOK\r\n"
        want = "\r\nAT+CPIN=****\r\nERROR\r\nAT+CPIN=****\r\r\nOK\r\n"
        assert mask_at_command(text) == want

    def test_mid_line_occurrence_not_masked(self) -> None:
        """行中段出现的同前缀字样不掩（避免误伤正文）."""
        text = "echo AT+CPIN=1234 in prose"
        assert mask_at_command(text) == text


def _step(command: str, request: str = "", response: str = "") -> StepResult:
    return StepResult(
        step_index=1,
        phase="steps",
        input_type=InputType.COMMAND,
        command=command,
        port="V0",
        status=StepStatus.PASS,
        request=request or command,
        response=response,
    )


class TestMaskExecutionResult:
    def _result(self) -> ExecutionResult:
        step = _step(
            command="AT+CPIN=1234",
            response="AT+CPIN=1234\r\r\nOK\r\n",
        )
        ps = PressureStats(step_stats=(StepPressureStats(step_index=1, command="AT+CPIN=1234"),))
        case = CaseResult(
            case_name="pin",
            case_file="pin.yaml",
            setup_results=(step,),
            step_results=(step,),
            teardown_results=(step,),
            pressure_stats=ps,
        )
        return ExecutionResult(
            summary=Summary(total_cases=1, passed=1),
            case_results=(case,),
            suite_setup_results=(step,),
            suite_teardown_results=(step,),
        )

    def test_all_phases_masked(self) -> None:
        masked = mask_execution_result(self._result())
        case = masked.case_results[0]
        assert case.setup_results[0].command == "AT+CPIN=****"
        assert case.step_results[0].request == "AT+CPIN=****"
        assert case.teardown_results[0].response == "AT+CPIN=****\r\r\nOK\r\n"
        assert masked.suite_setup_results[0].command == "AT+CPIN=****"
        assert masked.suite_teardown_results[0].command == "AT+CPIN=****"

    def test_pressure_stats_command_masked(self) -> None:
        masked = mask_execution_result(self._result())
        ps = masked.case_results[0].pressure_stats
        assert ps is not None
        assert ps.step_stats[0].command == "AT+CPIN=****"

    def test_input_not_mutated_and_stats_intact(self) -> None:
        """入参 result 不被修改；统计/判定数据保持原值."""
        result = self._result()
        masked = mask_execution_result(result)
        assert result.case_results[0].step_results[0].command == "AT+CPIN=1234", "入参不动"
        assert masked.case_results[0].step_results[0].status is StepStatus.PASS
        assert masked.case_results[0].pressure_stats is not None
        assert masked.summary.total_cases == 1 and masked.summary.passed == 1
