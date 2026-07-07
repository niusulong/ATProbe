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
