"""虚拟 AT 模组应答器测试（P0-2/P1-4 回归保护）.

重点：参数非法的指令必须返回 ERROR（而非 OK），区分「合法空响应」与「错误拒绝」。
"""

from __future__ import annotations

from atprobe.infra.serial.atresponder import AtResponder


def _frame(cmd: str) -> bytes:
    return AtResponder().respond(cmd)


class TestAtResponderErrorOnBadParam:
    """P0-2：格式错误的带参指令应返回 ERROR."""

    def test_cereg_non_numeric_returns_error(self) -> None:
        # AT+CEREG=abc 参数非数字 → ERROR（之前误返回 OK）
        assert b"ERROR" in _frame("AT+CEREG=abc")

    def test_cmgf_non_numeric_returns_error(self) -> None:
        assert b"ERROR" in _frame("AT+CMGF=xyz")

    def test_cereg_missing_param_returns_error(self) -> None:
        # AT+CEREG= 无参数 → 解析失败 → ERROR
        assert b"ERROR" in _frame("AT+CEREG=")


class TestAtResponderValidStillOk:
    """合法指令仍正常返回（含合法的空 body 仅 OK）."""

    def test_cereg_valid_returns_ok(self) -> None:
        r = AtResponder()
        out = r.respond("AT+CEREG=1")
        assert b"OK" in out
        assert b"ERROR" not in out
        assert r.cereg_n == 1  # 状态正确更新

    def test_cmgf_valid_returns_ok(self) -> None:
        r = AtResponder()
        out = r.respond("AT+CMGF=1")
        assert b"OK" in out
        assert b"ERROR" not in out
        assert r.cmgf == 1

    def test_plain_at_returns_ok(self) -> None:
        # 裸 AT 合法空 body → 仅 OK（不能因 None 改动误判为 ERROR）
        assert _frame("AT").endswith(b"AT\r\nOK\r\n")

    def test_unknown_command_returns_error(self) -> None:
        assert b"ERROR" in _frame("AT+UNKNOWN=1")


class TestAtResponderEchoControl:
    """ATE0/ATE1 控制回显：默认（ATE1）回显指令；ATE0 后不回显。

    对齐真实模组行为（3GPP TS 27.007 §5.1）：多数用例 setup 首步发 ATE0 关回显，
    随后断言不含回显前缀。vsim 遵循 ATE0 才能整条用例跑通（自动测试基础）。
    """

    def test_default_echo_on(self) -> None:
        # 默认 ATE1：响应回显收到的指令（回显行 + OK 行，每行 \r\n）
        r = AtResponder()
        out = r.respond("ATE1")
        assert out == b"\r\nATE1\r\nOK\r\n"

    def test_ate0_disables_echo(self) -> None:
        # ATE0 关回显：其自身的响应不再回显，后续指令也不回显
        r = AtResponder()
        assert r.respond("ATE0") == b"\r\nOK\r\n"
        # 后续指令不回显
        assert r.respond("AT+CSQ") == b"\r\n+CSQ: 23,99\r\nOK\r\n"
        assert r.respond("AT") == b"\r\nOK\r\n"

    def test_ate1_re_enables_echo(self) -> None:
        r = AtResponder()
        r.respond("ATE0")
        r.respond("ATE1")
        # ATE1 后回显恢复
        assert r.respond("AT+CSQ") == b"\r\nAT+CSQ\r\n+CSQ: 23,99\r\nOK\r\n"

    def test_ate0_no_echo_on_error(self) -> None:
        # ATE0 后，错误响应也不回显
        r = AtResponder()
        r.respond("ATE0")
        assert r.respond("AT+UNKNOWN=1") == b"\r\nERROR\r\n"
