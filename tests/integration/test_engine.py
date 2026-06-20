"""集成测试：引擎 + FakeSerial（TSD §8.3）.

验证 M3 引擎与 M1（Fake）、M2（用例）、M7（环境配置）、M4（结果）的协作。
"""

from __future__ import annotations

from atprobe.domain.case import parse_case
from atprobe.domain.report.models import CaseStatus, StepStatus
from atprobe.engine import Engine, EngineConfig
from atprobe.infra.config.envconfig import load_env_config
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import Response


def _engine_with_fake(fake: FakePortManager) -> Engine:
    return Engine(sender_factory=lambda: fake, sleep=lambda s: None)


def _cfg(cases, env=None) -> EngineConfig:  # type: ignore[no-untyped-def]
    return EngineConfig(
        ports=(PortConfig(name="COM3"),),
        cases=tuple(cases),
        step_timeout_default=5.0,
        env_config=env,
    )


class TestBasicExecution:
    def test_single_pass(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "OK\r\n")
        fake_port.script_text("COM3", "+CSQ: 23\r\nOK\r\n", match="AT+CSQ")
        case = parse_case("""
name: 信号查询
port: COM3
steps:
  - command: AT
    assert: { contains: "OK" }
  - command: AT+CSQ
    extract: { rssi: 'CSQ: (\\d+)' }
    assert: [{ var: rssi, op: ge, value: 10 }]
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        assert result.summary.passed == 1
        cr = result.case_results[0]
        assert cr.status is CaseStatus.PASS
        assert cr.step_results[1].extracted_vars == {"rssi": "23"}

    def test_assertion_fail_aborts(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "ERROR\r\n")
        fake_port.script_text("COM3", "OK\r\n")  # 第二步不应执行（默认 abort）
        case = parse_case("""
name: fail-test
port: COM3
steps:
  - command: AT
    assert: { contains: "OK" }
  - command: AT+SECOND
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.FAIL
        assert len(cr.step_results) == 1  # 第二步未执行


class TestRetry:
    def test_retry_succeeds_eventually(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        # 前 2 次 ERROR，第 3 次 OK
        fake_port.script("COM3", Response(text="ERROR\r\n"))
        fake_port.script("COM3", Response(text="ERROR\r\n"))
        fake_port.script("COM3", Response(text="OK\r\n"))
        case = parse_case("""
name: retry
port: COM3
steps:
  - command: AT+X
    retry: { count: 3, interval: 0 }
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.PASS
        assert cr.step_results[0].retry_count == 2

    def test_retry_exhausted_fails(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        for _ in range(5):
            fake_port.script("COM3", Response(text="ERROR\r\n"))
        case = parse_case("""
name: retry-fail
port: COM3
steps:
  - command: AT+X
    retry: { count: 2, interval: 0 }
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.FAIL
        assert cr.step_results[0].retry_count == 2


class TestOnFailure:
    def test_continue_runs_subsequent_steps(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script("COM3", Response(text="ERROR\r\n"))
        fake_port.script("COM3", Response(text="OK\r\n"))
        case = parse_case("""
name: continue
port: COM3
on_failure: continue
steps:
  - command: AT+BAD
    assert: { contains: "OK" }
  - command: AT+GOOD
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.FAIL  # 有失败步骤
        assert len(cr.step_results) == 2  # 两步都执行了

    def test_skip(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script("COM3", Response(text="ERROR\r\n"))
        fake_port.script("COM3", Response(text="OK\r\n"))
        case = parse_case("""
name: skip
port: COM3
steps:
  - command: AT+BAD
    on_failure: skip
    assert: { contains: "OK" }
  - command: AT+GOOD
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        # on_failure=skip：失败步状态仍为 FAIL（M3 §4.6），但执行继续到下一步
        # 存在 FAIL 但无 abort → 用例 = FAIL（§4.6 规则 2）
        assert cr.status is CaseStatus.FAIL
        assert cr.step_results[0].status is StepStatus.FAIL
        assert cr.step_results[1].status is StepStatus.PASS  # 后续步骤仍执行


class TestPoll:
    def test_poll_satisfied(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script("COM3", Response(text="+CEREG: 0,2\r\nOK\r\n"))
        fake_port.script("COM3", Response(text="+CEREG: 0,1\r\nOK\r\n"))
        case = parse_case("""
name: poll
port: COM3
steps:
  - command: AT+CEREG?
    extract: { stat: 'CEREG: 0,(\\d+)' }
    poll: { until: 'stat == "1"', timeout: 5, interval: 1 }
    on_failure: continue
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.PASS
        assert cr.step_results[0].poll_iterations == 2

    def test_poll_timeout_fails(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        # 永远不满足
        for _ in range(50):
            fake_port.script("COM3", Response(text="+CEREG: 0,2\r\nOK\r\n"))
        case = parse_case("""
name: poll-timeout
port: COM3
steps:
  - command: AT+CEREG?
    extract: { stat: 'CEREG: 0,(\\d+)' }
    poll: { until: 'stat == "1"', timeout: 0.3, interval: 10 }
    on_failure: continue
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.FAIL


class TestWhen:
    def test_when_false_skips(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "+CSQ: 5\r\nOK\r\n", match="AT+CSQ")
        fake_port.script_text("COM3", "OK\r\n")  # 第二步因 when 跳过，不应消费
        case = parse_case("""
name: when-test
port: COM3
steps:
  - command: AT+CSQ
    extract: { rssi: 'CSQ: (\\d+)' }
  - command: AT+RICH
    when: 'rssi > 20'
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.step_results[0].status is StepStatus.PASS
        assert cr.step_results[1].status is StepStatus.SKIPPED


class TestSetupTeardown:
    def test_setup_fail_skips_case(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script("COM3", Response(text="ERROR\r\n"))  # setup 失败
        fake_port.script("COM3", Response(text="OK\r\n"))  # teardown
        case = parse_case("""
name: setup-fail
port: COM3
setup:
  - command: AT
    assert: { contains: "READY" }
steps:
  - command: AT+BODY
    assert: { contains: "OK" }
teardown:
  - command: AT
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.SKIPPED
        assert len(cr.step_results) == 0  # steps 未执行
        assert len(cr.teardown_results) == 1  # teardown 仍执行

    def test_teardown_always_runs(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script("COM3", Response(text="ERROR\r\n"))  # step 失败
        fake_port.script("COM3", Response(text="OK\r\n"))  # teardown
        case = parse_case("""
name: teardown-test
port: COM3
steps:
  - command: AT
    assert: { contains: "OK" }
teardown:
  - command: AT+RESET
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.FAIL
        assert len(cr.teardown_results) == 1


class TestEnvConfig:
    def test_env_dot_ref_filled(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        env = load_env_config('ftp:\n  host: 192.168.1.100\n  port: 21\n')
        fake_port.script_text("COM3", "OK\r\n")
        case = parse_case("""
name: env-test
port: COM3
steps:
  - command: 'AT+QFTPURL={{ftp.host}},{{ftp.port}}'
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case], env=env))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.PASS
        assert cr.step_results[0].request == "AT+QFTPURL=192.168.1.100,21"


class TestPressure:
    def test_pressure_pass(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        for _ in range(10):
            fake_port.script("COM3", Response(text="OK\r\n"))
        case = parse_case("""
name: pressure
port: COM3
loop: { count: 10, interval: 1 }
steps:
  - command: AT
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.PASS
        assert cr.pressure_stats is not None
        assert cr.pressure_stats.success_rate == 100.0
        assert cr.pressure_stats.counted_rounds == 10
        assert cr.pressure_stats.step_stats[0].success_count == 10

    def test_pressure_fail_below_threshold(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        for _ in range(5):
            fake_port.script("COM3", Response(text="OK\r\n"))
        for _ in range(5):
            fake_port.script("COM3", Response(text="ERROR\r\n"))
        case = parse_case("""
name: pressure-fail
port: COM3
loop: { count: 10, interval: 1 }
steps:
  - command: AT
    assert: { contains: "OK" }
""")
        cfg = EngineConfig(
            ports=(PortConfig(name="COM3"),),
            cases=(case,),
            pressure_pass_threshold=95.0,
        )
        result = _engine_with_fake(fake_port).start(cfg)
        cr = result.case_results[0]
        assert cr.status is CaseStatus.FAIL
        assert cr.pressure_stats.success_rate == 50.0


class TestVariableFlow:
    def test_extract_then_reference(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        fake_port.script_text("COM3", "192.168.1.100\r\nOK\r\n", match="AT+GETIP")
        fake_port.script_text("COM3", "OK\r\n", match="AT+CONNECT")
        case = parse_case("""
name: var-flow
port: COM3
steps:
  - command: AT+GETIP
    extract: { ip: '(\\d+\\.\\d+\\.\\d+\\.\\d+)' }
  - command: 'AT+CONNECT="{{ip}}"'
    assert: { contains: "OK" }
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        assert cr.status is CaseStatus.PASS
        assert cr.step_results[1].request == 'AT+CONNECT="192.168.1.100"'


class TestMultipleCases:
    def test_sequential_cases_isolated(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        # 两个用例，变量不跨用例共享
        fake_port.script_text("COM3", "100\r\nOK\r\n", match="AT+A")
        fake_port.script_text("COM3", "200\r\nOK\r\n", match="AT+B")
        case1 = parse_case("""
name: case-a
port: COM3
steps:
  - command: AT+A
    extract: { v: '(\\d+)' }
""")
        case2 = parse_case("""
name: case-b
port: COM3
steps:
  - command: AT+B
    extract: { v: '(\\d+)' }
    assert: [{ var: v, op: eq, value: "200" }]
""")
        result = _engine_with_fake(fake_port).start(_cfg([case1, case2]))
        assert result.summary.passed == 2


class TestDisconnectSafety:
    """§4.2 连续断连安全阀：同用例连续断连达到阈值（默认 3）则放弃用例."""

    def test_safety_valve_aborts_case(self, fake_port) -> None:  # type: ignore[no-untyped-def]
        from atprobe.infra.serial.interfaces import ResponseStatus

        # 5 步都返回断连错误（error 含「断连」）→ 第 3 步触发安全阀放弃用例
        for _ in range(5):
            fake_port.script(
                "COM3",
                Response(text="", status=ResponseStatus.ERROR, error="端口断连"),
                match="AT",
                persistent=True,
            )
        case = parse_case("""
name: disconnect-test
port: COM3
on_failure: continue
steps:
  - command: AT1
  - command: AT2
  - command: AT3
  - command: AT4
  - command: AT5
""")
        result = _engine_with_fake(fake_port).start(_cfg([case]))
        cr = result.case_results[0]
        # 安全阀在第 3 次连续断连时触发，应放弃用例（status=FAIL，且未执行到第 5 步）
        assert cr.status is CaseStatus.FAIL
        assert "安全阀" in cr.error_msg
        # 连续断连 3 次即放弃 → 执行的步骤数应 < 5
        assert len(cr.step_results) < 5
