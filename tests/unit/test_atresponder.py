"""虚拟 AT 模组应答器测试（P0-2/P1-4 回归保护 + 批 2b Task 5 两阶段状态机）.

重点：参数非法的指令必须返回 ERROR（而非 OK），区分「合法空响应」与「错误拒绝」；
两阶段发送（TCPSEND/UDPSEND/FSWF）与 FS 家族（FSRF/FSFS/FSDF）帧格式逐字对齐
手册（docs/at-ref/ ch06 §6.4/§6.10、ch28 §28.1-28.6）。
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


def _mute(r: AtResponder) -> AtResponder:
    """关回显，便于对整帧字节做精确断言."""
    r.respond("ATE0")
    return r


def _write_file(r: AtResponder, name: str, payload: bytes, mode: int = 0) -> None:
    """经 FSWF 两阶段写入 FS 存储（测试前置）."""
    r.respond(f'AT+FSWF="{name}",{mode},{len(payload)},10000')
    r.receive_data(payload)


class TestBareCommandPrefixExclusion:
    """设计 §2.4 随批修复：裸指令不作前缀匹配，ATE0X 等无效变体应 ERROR."""

    def test_ate0x_returns_error_not_ok(self) -> None:
        r = AtResponder()
        assert r.respond("ATE0X") == b"\r\nATE0X\r\nERROR\r\n"
        # 且不误触回显切换（ATE0X 非合法 ATE0）
        assert r.echo is True

    def test_at_prefix_still_exact_only(self) -> None:
        # 回归：AT 精确匹配仍 OK，不被前缀逻辑影响
        assert _mute(AtResponder()).respond("AT") == b"\r\nOK\r\n"


class TestTcpSendTwoPhase:
    """AT+TCPSEND=<n>,<length> 两阶段发送（手册 §6.4）."""

    def test_prompt_frame_with_echo(self) -> None:
        # 阶段一：\r\n + 回显行 + \r\n + 提示符（无尾 CRLF、无 OK、无尾空格）
        r = AtResponder()
        assert r.respond("AT+TCPSEND=0,5") == b"\r\nAT+TCPSEND=0,5\r\n>"

    def test_prompt_frame_after_ate0(self) -> None:
        assert _mute(AtResponder()).respond("AT+TCPSEND=0,5") == b"\r\n>"

    def test_data_completes_session_with_result_frame(self) -> None:
        r = _mute(AtResponder())
        r.respond("AT+TCPSEND=0,5")
        assert r.receive_data(b"hello") == b"\r\nOK\r\n\r\n+TCPSEND: 0,5\r\n"
        assert r._pending is None  # 会话已清

    def test_partial_data_silent_then_complete(self) -> None:
        r = _mute(AtResponder())
        r.respond("AT+TCPSEND=0,5")
        assert r.receive_data(b"he") == b""  # 未收满静默
        assert r.receive_data(b"llo") == b"\r\nOK\r\n\r\n+TCPSEND: 0,5\r\n"

    def test_link_out_of_range_raw_frame_no_session(self) -> None:
        r = _mute(AtResponder())
        assert r.respond("AT+TCPSEND=6,5") == b"\r\n+TCPSEND: SOCKET ID OPEN FAILED\r\n"
        assert r._pending is None  # 失败不挂会话

    def test_length_zero_data_length_error(self) -> None:
        assert _mute(AtResponder()).respond("AT+TCPSEND=0,0") == (
            b"\r\n+TCPSEND: DATA LENGTH ERROR\r\n"
        )

    def test_length_over_4096_data_length_error(self) -> None:
        assert _mute(AtResponder()).respond("AT+TCPSEND=0,4097") == (
            b"\r\n+TCPSEND: DATA LENGTH ERROR\r\n"
        )

    def test_length_4096_accepted(self) -> None:
        r = _mute(AtResponder())
        assert r.respond("AT+TCPSEND=5,4096") == b"\r\n>"

    def test_three_params_error(self) -> None:
        # 参数恰两个：命令模式第三参数不模拟，多数 → ERROR
        assert _mute(AtResponder()).respond("AT+TCPSEND=0,5,1") == b"\r\nERROR\r\n"

    def test_one_param_error(self) -> None:
        assert _mute(AtResponder()).respond("AT+TCPSEND=0") == b"\r\nERROR\r\n"

    def test_non_integer_error(self) -> None:
        assert _mute(AtResponder()).respond("AT+TCPSEND=0,abc") == b"\r\nERROR\r\n"

    def test_expire_pending_operation_expired(self) -> None:
        r = _mute(AtResponder())
        r.respond("AT+TCPSEND=0,10")
        r.receive_data(b"abc")
        assert r.expire_pending() == b"\r\n+TCPSEND: 0,OPERATION EXPIRED\r\n"
        assert r._pending is None


class TestUdpSendTwoPhase:
    """AT+UDPSEND=<n>,<length> 两阶段发送（手册 §6.10，提示符带尾空格）."""

    def test_prompt_has_trailing_space(self) -> None:
        r = AtResponder()
        assert r.respond("AT+UDPSEND=0,7") == b"\r\nAT+UDPSEND=0,7\r\n> "

    def test_prompt_after_ate0(self) -> None:
        assert _mute(AtResponder()).respond("AT+UDPSEND=0,7") == b"\r\n> "

    def test_success_frame(self) -> None:
        r = _mute(AtResponder())
        r.respond("AT+UDPSEND=0,7")
        assert r.receive_data(b"0123456") == b"\r\nOK\r\n\r\n+UDPSEND: 0,7\r\n"

    def test_link_out_of_range_raw_frame(self) -> None:
        assert _mute(AtResponder()).respond("AT+UDPSEND=9,1") == (
            b"\r\n+UDPSEND: SOCKET ID OPEN FAILED\r\n"
        )

    def test_length_error_family(self) -> None:
        assert _mute(AtResponder()).respond("AT+UDPSEND=0,0") == (
            b"\r\n+UDPSEND: DATA LENGTH ERROR\r\n"
        )

    def test_expire_pending_operation_expired(self) -> None:
        r = _mute(AtResponder())
        r.respond("AT+UDPSEND=1,4")
        assert r.expire_pending() == b"\r\n+UDPSEND: 1,OPERATION EXPIRED\r\n"


class TestFswfTwoPhase:
    """AT+FSWF="<file>",<mode>,<size>,<time> 写文件（手册 §28.1）."""

    def test_write_ok_and_stored(self) -> None:
        r = _mute(AtResponder())
        assert r.respond('AT+FSWF="test.txt",0,10,10000') == b"\r\n>"
        assert r.receive_data(b"0123456789") == b"\r\nOK\r\n"
        assert r._fs["test.txt"] == bytearray(b"0123456789")

    def test_mode1_appends(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "f.txt", b"hello")
        r.respond('AT+FSWF="f.txt",1,5,1000')
        assert r.receive_data(b"world") == b"\r\nOK\r\n"
        assert bytes(r._fs["f.txt"]) == b"helloworld"

    def test_mode0_overwrites_start_keeps_tail(self) -> None:
        # 覆写起始段、保超出段（bytearray 切片赋值语义）
        r = _mute(AtResponder())
        _write_file(r, "f.txt", b"0123456789")
        r.respond('AT+FSWF="f.txt",0,4,1000')
        assert r.receive_data(b"ABCD") == b"\r\nOK\r\n"
        assert bytes(r._fs["f.txt"]) == b"ABCD456789"

    def test_partial_chunks_write_sequentially(self) -> None:
        # 分块到达按序写入（mode 0 游标前进，不重复覆写起点）
        r = _mute(AtResponder())
        r.respond('AT+FSWF="f.txt",0,6,1000')
        assert r.receive_data(b"abc") == b""
        assert r.receive_data(b"def") == b"\r\nOK\r\n"
        assert bytes(r._fs["f.txt"]) == b"abcdef"

    def test_time_60001_error(self) -> None:
        # 手册示例：time=60001 即 ERROR（参数表 0~240000 与示例矛盾，按示例模拟）
        assert _mute(AtResponder()).respond('AT+FSWF="t.txt",1,1024,60001') == b"\r\nERROR\r\n"

    def test_time_60000_accepted(self) -> None:
        assert _mute(AtResponder()).respond('AT+FSWF="t.txt",0,0,60000') == b"\r\n>"

    def test_size_over_limit_error(self) -> None:
        assert _mute(AtResponder()).respond('AT+FSWF="t.txt",0,1048577,1000') == b"\r\nERROR\r\n"

    def test_mode_out_of_range_error(self) -> None:
        assert _mute(AtResponder()).respond('AT+FSWF="t.txt",2,10,1000') == b"\r\nERROR\r\n"

    def test_filename_without_double_quotes_error(self) -> None:
        # 只接受双引号文件名（手册如此；SD/flash 路径示例的无引号形态不模拟）
        assert _mute(AtResponder()).respond("AT+FSWF=test.txt,0,10,1000") == b"\r\nERROR\r\n"

    def test_param_count_error(self) -> None:
        assert _mute(AtResponder()).respond('AT+FSWF="t.txt",0,10') == b"\r\nERROR\r\n"
        assert _mute(AtResponder()).respond('AT+FSWF="t.txt",0,10,1000,1') == b"\r\nERROR\r\n"

    def test_insufficient_data_then_expire(self) -> None:
        r = _mute(AtResponder())
        r.respond('AT+FSWF="test.txt",0,10,10000')
        assert r.receive_data(b"abc") == b""  # 数据不足：静默
        assert r.expire_pending() == b"\r\n+FSWF: Timeout!\r\n"
        assert r._pending is None
        # 会话已清：后续数据走无会话污染路径（当命令解析）
        assert r.receive_data(b"AT\r\n") == b"\r\nOK\r\n"

    def test_expire_without_pending_returns_empty(self) -> None:
        assert AtResponder().expire_pending() == b""


class TestFsrf:
    """AT+FSRF="<file>",<mode>,<size>[,<position>] 读文件（手册 §28.2）."""

    def test_read_from_start(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"start0123456789")
        assert r.respond('AT+FSRF="test.txt",0,10') == b"\r\n+FSRF: 10,start01234\r\nOK\r\n"

    def test_read_size_zero(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"start0123456789")
        assert r.respond('AT+FSRF="test.txt",0,0') == b"\r\n+FSRF: 0,\r\nOK\r\n"

    def test_read_with_position(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"start0123456789")
        assert r.respond('AT+FSRF="test.txt",1,5,2') == b"\r\n+FSRF: 5,art01\r\nOK\r\n"

    def test_read_size_zero_with_position(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"start0123456789")
        assert r.respond('AT+FSRF="test.txt",1,0,2') == b"\r\n+FSRF: 0,\r\nOK\r\n"

    def test_file_missing_error(self) -> None:
        assert _mute(AtResponder()).respond('AT+FSRF="nope.txt",0,10') == b"\r\nERROR\r\n"

    def test_size_over_file_length_error(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"0123456789")
        assert r.respond('AT+FSRF="test.txt",0,11') == b"\r\nERROR\r\n"

    def test_position_over_file_length_error(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"0123456789")
        assert r.respond('AT+FSRF="test.txt",1,0,11') == b"\r\nERROR\r\n"

    def test_position_plus_size_over_file_length_error(self) -> None:
        # 从 position 起可读字节数不足 size：从严 ERROR（不生成声明长于实发的说谎帧）
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"0123456789")
        assert r.respond('AT+FSRF="test.txt",1,5,8') == b"\r\nERROR\r\n"

    def test_mode1_without_position_error(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"0123456789")
        assert r.respond('AT+FSRF="test.txt",1,5') == b"\r\nERROR\r\n"

    def test_non_integer_params_error(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"0123456789")
        assert r.respond('AT+FSRF="test.txt",x,5') == b"\r\nERROR\r\n"


class TestFsfsAndFsdf:
    """AT+FSFS（文件大小）/ AT+FSDF（删除）（手册 §28.6/§28.4）."""

    def test_fsfs_reports_byte_size(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"0123456789")
        assert r.respond('AT+FSFS="test.txt"') == b"\r\n+FSFS: 10\r\nOK\r\n"

    def test_fsfs_missing_error(self) -> None:
        assert _mute(AtResponder()).respond('AT+FSFS="123.txt"') == b"\r\nERROR\r\n"

    def test_fsfs_extra_params_error(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "t.txt", b"x")
        assert r.respond('AT+FSFS="t.txt",0') == b"\r\nERROR\r\n"

    def test_fsdf_deletes_then_read_errors(self) -> None:
        r = _mute(AtResponder())
        _write_file(r, "test.txt", b"0123456789")
        assert r.respond('AT+FSDF="test.txt"') == b"\r\nOK\r\n"
        assert "test.txt" not in r._fs
        assert r.respond('AT+FSRF="test.txt",0,10') == b"\r\nERROR\r\n"

    def test_fsdf_missing_error(self) -> None:
        assert _mute(AtResponder()).respond('AT+FSDF="123.txt"') == b"\r\nERROR\r\n"

    def test_fsdf_without_quotes_error(self) -> None:
        assert _mute(AtResponder()).respond("AT+FSDF=test.txt") == b"\r\nERROR\r\n"


class TestReceiveDataNoSessionPollution:
    """无会话时 receive_data 的污染语义：意外数据被当 AT 指令解析."""

    def test_unexpected_data_parsed_as_command(self) -> None:
        r = AtResponder()
        assert r.receive_data(b"AT\r\n") == r.respond("AT")  # 与直接 respond 等价

    def test_pollution_after_ate0(self) -> None:
        r = _mute(AtResponder())
        assert r.receive_data(b"AT\r\n") == b"\r\nOK\r\n"

    def test_garbage_data_yields_error_frame(self) -> None:
        assert _mute(AtResponder()).receive_data(b"\x00\x01") == b"\r\nERROR\r\n"


class TestLeftoverContinuation:
    """收满出帧后 leftover 继续按命令解析（同一到达流里命令紧跟数据尾）."""

    def test_leftover_appended_as_command_response(self) -> None:
        r = _mute(AtResponder())
        r.respond("AT+TCPSEND=0,3")
        out = r.receive_data(b"abcAT\r\n")
        assert out == b"\r\nOK\r\n\r\n+TCPSEND: 0,3\r\n" + b"\r\nOK\r\n"

    def test_leftover_with_echo_includes_echo_line(self) -> None:
        r = AtResponder()  # 回显开
        r.respond("AT+UDPSEND=0,2")
        out = r.receive_data(b"hiAT\r\n")
        assert out == b"\r\nOK\r\n\r\n+UDPSEND: 0,2\r\n" + b"\r\nAT\r\nOK\r\n"
