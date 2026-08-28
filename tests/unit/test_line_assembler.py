"""LineAssembler 纯逻辑单元测试（批 2a Task 3）.

语义来源 = SerialConnection._process_incoming（迁移前行为快照）：空闲派发 /
等待态终结交付 / wait_urc 双交付 / 偏移去重 / 孤儿续行逐条锁定——Task 4
接线时以本文件 + 既有 test_connection_* 行为锁共同验收。

新增能力（设计 §2.1/§2.3，connection 接线见 Task 4/5）单独成组：
  - expect 检测：新增字节区间命中即 COMPLETE（命中点前完整行双交付），
    优先于终结行判定；
  - 错误码行（ERROR/+CME ERROR/+CMS ERROR）在任何**等待**模式（含 wait_urc）
    下立即终结。空闲态无终结概念（无在途命令），错误行仍按主动上报派发。
"""

from __future__ import annotations

import re

from atprobe.infra.serial.line_assembler import LineAssembler, RxEvent, RxEventKind


def _asm(
    *,
    echo: bytes | None = None,
    wait_urc: bytes | None = None,
    expect: bytes | None = None,
    waiting: bool = False,
) -> LineAssembler:
    """构造已注入周期参数的 assembler（正则参数传 bytes 原文）."""
    asm = LineAssembler()
    asm.set_cycle(
        echo_line=echo,
        wait_urc_re=re.compile(wait_urc) if wait_urc is not None else None,
        expect_re=re.compile(expect) if expect is not None else None,
        waiting=waiting,
    )
    return asm


def _urc(text: str) -> RxEvent:
    return RxEvent(kind=RxEventKind.URC_LINE, text=text)


def _complete(data: bytes) -> RxEvent:
    return RxEvent(kind=RxEventKind.RESPONSE_COMPLETE, data=data)


def _wurc(data: bytes, keep: re.Pattern[bytes] | None = None) -> RxEvent:
    """期望的 wait_urc 终结事件——keep 传注入 assembler 的同一正则对象（Task 4
    起事件携带 keep_re，re.Pattern 相等性按 identity 比较）."""
    return RxEvent(kind=RxEventKind.RESPONSE_URC_TERMINATED, data=data, keep_re=keep)


def _truncate() -> RxEvent:
    return RxEvent(kind=RxEventKind.TRUNCATED_IDLE)


class TestIdleMode:
    """空闲态：所有完整非空行 = 主动上报，已处理行截断（connection :769-784）."""

    def test_urc_line_dispatched(self) -> None:
        asm = _asm()
        assert asm.feed(b"\r\n$MYURC: 1\r\n") == [_urc("$MYURC: 1"), _truncate()]

    def test_multiple_lines_in_one_chunk(self) -> None:
        asm = _asm()
        assert asm.feed(b"+A: 1\r\n$B: 2\r\n") == [_urc("+A: 1"), _urc("$B: 2"), _truncate()]

    def test_half_line_across_chunks(self) -> None:
        asm = _asm()
        assert asm.feed(b"+A: ") == []
        assert asm.has_pending_half_line is True
        assert asm.feed(b"1\r\n") == [_urc("+A: 1"), _truncate()]
        assert asm.has_pending_half_line is False

    def test_half_line_only_emits_no_truncate(self) -> None:
        """无完整行被处理时不发 TRUNCATED_IDLE（截断事件=已处理行被丢弃）."""
        asm = _asm()
        assert asm.feed(b"+A: ") == []

    def test_empty_lines_skipped(self) -> None:
        asm = _asm()
        assert asm.feed(b"\r\n\r\n") == [_truncate()]

    def test_idle_truncation_no_redispatch_across_chunks(self) -> None:
        """空闲截断（防 OOM）：已派发行移出 buffer，下个 chunk 不重复派发."""
        asm = _asm()
        assert asm.feed(b"+A\r\n") == [_urc("+A"), _truncate()]
        assert asm.feed(b"+B\r\n") == [_urc("+B"), _truncate()]

    def test_empty_chunk_idempotent(self) -> None:
        """空 chunk：无事件、无状态变化（代次/半行标记/缓冲内容均不变）."""
        asm = _asm()
        asm.feed(b"+A\r\n")
        gen = asm.generation
        assert asm.feed(b"") == []
        assert asm.generation == gen
        half = _asm()
        half.feed(b"+HALF")
        gen_half = half.generation
        assert half.feed(b"") == []
        assert half.generation == gen_half
        assert half.has_pending_half_line is True
        assert half.snapshot_and_reset() == b"+HALF"

    def test_terminator_line_still_urc_when_idle(self) -> None:
        """空闲态终结行（OK）也是完整非空行——照常派发（无在途命令无终结概念）."""
        asm = _asm()
        assert asm.feed(b"\r\nOK\r\n") == [_urc("OK"), _truncate()]


class TestWaitingMode:
    """等待态：回显排除 / 终结交付全量 / 余行派发 / 双交付（connection :731-767）."""

    def test_echo_line_excluded_from_urc(self) -> None:
        asm = _asm(echo=b"AT", waiting=True)
        assert asm.feed(b"AT\r\r\nOK\r\n") == [_complete(b"AT\r\r\nOK\r\n")]

    def test_terminator_delivery_full_bytes_from_cycle_start(self) -> None:
        """交付字节 = 发送起（含前导 CRLF/回显）至终结行含——精确切分."""
        asm = _asm(echo=b"AT+CSQ", waiting=True)
        assert asm.feed(b"AT+CSQ\r\r\n+CSQ: 10,99\r\nOK\r\n") == [
            _urc("+CSQ: 10,99"),
            _complete(b"AT+CSQ\r\r\n+CSQ: 10,99\r\nOK\r\n"),
        ]

    def test_rest_lines_after_terminator_dispatched_as_urc(self) -> None:
        asm = _asm(waiting=True)
        assert asm.feed(b"\r\nOK\r\n+CSQ: 20,0\r\n") == [
            _complete(b"\r\nOK\r\n"),
            _urc("+CSQ: 20,0"),
        ]

    def test_urc_before_terminator_dual_delivery(self) -> None:
        """双交付：终结前行既派发事件又保留在交付文本（无法区分载荷/插队 URC）."""
        asm = _asm(echo=b"AT", waiting=True)
        assert asm.feed(b"\r\n+CREG: 2\r\nOK\r\n") == [
            _urc("+CREG: 2"),
            _complete(b"\r\n+CREG: 2\r\nOK\r\n"),
        ]

    def test_cross_chunk_dispatched_offset_dedup(self) -> None:
        """等待中 buffer 不截断、逐 chunk 全量重拆——历史行不得重复派发."""
        asm = _asm(waiting=True)
        assert asm.feed(b"+A\r\n") == [_urc("+A")]
        # 第二 chunk 触发全缓冲重拆："+A" 行偏移已派发，不得二次派发
        assert asm.feed(b"OK\r\n") == [_complete(b"+A\r\nOK\r\n")]


class TestWaitUrcMode:
    """wait_urc 模式：OK 仅受理不终结 / 目标行整段交付（connection :682-726）."""

    def test_ok_accepted_without_termination(self) -> None:
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"\r\nOK\r\n") == []
        assert asm.snapshot_and_reset() == b"\r\nOK\r\n"  # OK 段留在缓冲

    def test_target_line_delivers_whole_segment(self) -> None:
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"\r\nOK\r\n") == []
        # 目标行命中：目标行先派发，随后整段（OK+目标行）交付，buffer 清尾
        assert asm.feed(b"+X: done\r\n") == [
            _urc("+X: done"),
            _wurc(b"\r\nOK\r\n+X: done\r\n", keep=asm._wait_urc_re),
        ]
        assert asm.has_pending_half_line is False

    def test_strip_anchored_regex_matches(self) -> None:
        """正则作用在 strip 后的行上——含 $ 锚点的合法正则可命中（P1 修复语义）."""
        asm = _asm(wait_urc=rb"\+X: done$", waiting=True)
        assert asm.feed(b"\r\n+X: done\r\n") == [
            _urc("+X: done"),
            _wurc(b"\r\n+X: done\r\n", keep=asm._wait_urc_re),
        ]

    def test_non_target_urc_dispatched_and_kept_in_text(self) -> None:
        asm = _asm(wait_urc=rb"\+T:", waiting=True)
        assert asm.feed(b"+INSERT\r\n") == [_urc("+INSERT")]
        # 非目标行双交付：派发 + 留文本；OK 行跨 chunk 不重复处理
        assert asm.feed(b"OK\r\n+T: v\r\n") == [
            _urc("+T: v"),
            _wurc(b"+INSERT\r\nOK\r\n+T: v\r\n", keep=asm._wait_urc_re),
        ]

    def test_echo_line_excluded_in_wait_urc(self) -> None:
        asm = _asm(echo=b"AT+X", wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"AT+X\r\r\nOK\r\n") == []

    def test_rest_lines_after_target_dispatched(self) -> None:
        """匹配行之后的完整行不丢弃——按 URC 分流补派发（P3 修复语义）."""
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"+X: hit\r\n$AFTER: u\r\n") == [
            _urc("+X: hit"),
            _wurc(b"+X: hit\r\n$AFTER: u\r\n", keep=asm._wait_urc_re),
            _urc("$AFTER: u"),
        ]

    def test_urc_terminated_event_carries_keep_re(self) -> None:
        """RESPONSE_URC_TERMINATED 附带 keep_re=注入的 wait_urc 正则（Task 4 接线）.

        连接层锁外分发事件（含用户回调）时经 ev.keep_re 取剥离豁免正则——
        零读自身 _wait_urc_re（读线程分发/引擎线程 reset 的竞态面消除）。
        其余事件（含常规终结 COMPLETE）恒 None，与迁移前 keep_re 口径一致。
        """
        keep = re.compile(rb"\+X:")
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        events = asm.feed(b"\r\nOK\r\n+X: done\r\n")
        assert [ev.kind for ev in events] == [
            RxEventKind.URC_LINE,
            RxEventKind.RESPONSE_URC_TERMINATED,
        ]
        assert events[0].text == "+X: done"
        assert events[1].data == b"\r\nOK\r\n+X: done\r\n"
        assert events[1].keep_re is keep  # 注入正则本身（identity）
        assert events[0].keep_re is None
        # 常规终结 COMPLETE 不携带（连接层传 None，与迁移前一致）
        asm2 = _asm(waiting=True)
        assert asm2.feed(b"\r\nOK\r\n")[0].keep_re is None


class TestExpectDetection:
    """expect 检测（批 2a 新增，设计 §2.3）：新增字节命中即完成，优先于终结行."""

    def test_half_line_prompt_hit_without_newline(self) -> None:
        asm = _asm(expect=rb"\r\n>", waiting=True)
        assert asm.feed(b"\r\n>") == [_complete(b"\r\n>")]
        assert asm.has_pending_half_line is False

    def test_expect_priority_over_terminator(self) -> None:
        asm = _asm(expect=rb"\r\n>", waiting=True)
        # 同 chunk 含 OK 终结行：expect 先命中，OK 不再触发终结交付
        assert asm.feed(b"\r\n> \r\nOK\r\n") == [_complete(b"\r\n>")]

    def test_remainder_stays_in_buffer(self) -> None:
        asm = _asm(expect=rb"\r\n>", waiting=True)
        asm.feed(b"\r\n> \r\nOK\r\n")
        assert asm.snapshot_and_reset() == b" \r\nOK\r\n"

    def test_lines_before_hit_dual_delivered(self) -> None:
        """命中点之前的完整行按双交付派发（URC 永不丢失），并同时含于 data 内."""
        asm = _asm(expect=rb"\r\n>", waiting=True)
        events = asm.feed(b"\r\n+CREG: 2\r\n> ")
        assert events == [_urc("+CREG: 2"), _complete(b"\r\n+CREG: 2\r\n>")]
        assert asm.snapshot_and_reset() == b" "

    def test_dual_delivery_before_hit_excludes_echo_and_terminator(self) -> None:
        """双交付与终结前同款结构性排除：回显行/终结行不派发为 URC."""
        asm = _asm(echo=b"AT+X", expect=rb"\r\n>", waiting=True)
        assert asm.feed(b"AT+X\r\r\nOK\r\n> ") == [_complete(b"AT+X\r\r\nOK\r\n>")]

    def test_cross_chunk_anchor_hit(self) -> None:
        """终审复现：锚前缀（\\r\\n）已在早先 chunk 构成完整行使 dispatched 推进——
        扫描区域须为周期全量缓冲（自发送起），否则锚字节跨 chunk 永不命中等到超时."""
        asm = _asm(echo=b"AT+TCPSEND=0,5", expect=rb"\r\n>", waiting=True)
        assert asm.feed(b"AT+TCPSEND=0,5\r\r\n\r\n") == []
        assert asm.feed(b">") == [_complete(b"AT+TCPSEND=0,5\r\r\n\r\n>")]

    def test_cross_chunk_anchor_after_urc_line(self) -> None:
        """变体：dispatched 推进源自 URC 行——URC 事件照常先派发，COMPLETE 含该行."""
        asm = _asm(expect=rb"\r\n>", waiting=True)
        assert asm.feed(b"\r\n+EVT: 1\r\n") == [_urc("+EVT: 1")]
        assert asm.feed(b"\r\n>") == [_complete(b"\r\n+EVT: 1\r\n\r\n>")]

    def test_scan_region_is_whole_cycle_buffer(self) -> None:
        """expect 激活时扫描周期全量缓冲；已派发历史行不重复派发 URC."""
        asm = _asm(waiting=True)
        assert asm.feed(b"DATA1\r\n") == [_urc("DATA1")]  # 等待中未终结，偏移推进
        asm.set_cycle(
            echo_line=None, wait_urc_re=None, expect_re=re.compile(rb"EXPECT>"), waiting=True
        )
        assert asm.feed(b"EXPECT> tail") == [_complete(b"DATA1\r\nEXPECT>")]
        assert asm.snapshot_and_reset() == b" tail"

    def test_expect_ignored_when_not_waiting(self) -> None:
        """expect 是发送周期的附加完成条件——空闲态不触发（终结概念不存在）."""
        asm = _asm(expect=rb"\r\n>", waiting=False)
        # expect 未命中：">" 行按空闲语义派发为主动上报
        assert asm.feed(b"\r\n> \r\n") == [_urc(">"), _truncate()]


class TestErrorTermination:
    """错误码行在任何等待模式下终结（设计 §2.1 行为变更，wait_urc 不再等超时）."""

    def test_error_terminates_regular_waiting(self) -> None:
        asm = _asm(waiting=True)
        assert asm.feed(b"\r\nERROR\r\n") == [_complete(b"\r\nERROR\r\n")]

    def test_error_terminates_wait_urc_mode(self) -> None:
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"\r\nOK\r\n") == []
        # 行为变更点：修前 ERROR 在 wait_urc 模式仅受理，须等目标 URC 到超时。
        # 交付与 wait_urc 整段同口径：含先前累积的 OK 段（发送起至错误行含）。
        assert asm.feed(b"\r\nERROR\r\n") == [_complete(b"\r\nOK\r\n\r\nERROR\r\n")]

    def test_cme_error_terminates_wait_urc_mode(self) -> None:
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"\r\n+CME ERROR: 10\r\n") == [_complete(b"\r\n+CME ERROR: 10\r\n")]

    def test_cms_error_terminates_wait_urc_mode(self) -> None:
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"\r\n+CMS ERROR: 500\r\n") == [_complete(b"\r\n+CMS ERROR: 500\r\n")]

    def test_error_wait_urc_rest_lines_dispatched(self) -> None:
        """错误码终结与常规终结同口径：其后完整行按主动上报补派发."""
        asm = _asm(wait_urc=rb"\+X:", waiting=True)
        assert asm.feed(b"\r\nERROR\r\n$AFTER: u\r\n") == [
            _complete(b"\r\nERROR\r\n"),
            _urc("$AFTER: u"),
        ]

    def test_error_in_idle_dispatched_as_urc(self) -> None:
        """空闲态无在途命令：错误行仍是完整非空行——按主动上报派发（现状语义）."""
        asm = _asm()
        assert asm.feed(b"\r\nERROR\r\n") == [_urc("ERROR"), _truncate()]


class TestOrphanContinuation:
    """孤儿续行：reset 于半行后，续行（至下一个 \n 含）字节级丢弃（connection :637-644）."""

    def test_continuation_dropped_until_newline(self) -> None:
        asm = _asm(waiting=True)
        asm.feed(b"+PART")  # 半行滞留缓冲
        asm.reset()  # 周期结束清缓冲 → 按缓冲重算 orphan 标记（半行 → True）
        asm.set_cycle(echo_line=None, wait_urc_re=None, expect_re=None, waiting=True)
        # "TAIL\r\n" 是被截断半行的续行——静默丢弃，OK 不受污染
        assert asm.feed(b"TAIL\r\nOK\r\n") == [_complete(b"OK\r\n")]

    def test_whole_chunk_without_newline_dropped(self) -> None:
        asm = _asm(waiting=True)
        asm.feed(b"+PART")
        asm.reset()
        assert asm.feed(b"abcdef") == []  # 无 \n：整 chunk 均为续行内容，继续等行尾
        asm.set_cycle(echo_line=None, wait_urc_re=None, expect_re=None, waiting=False)
        assert asm.feed(b"gh\r\n+U: 1\r\n") == [_urc("+U: 1"), _truncate()]


class TestResetAndSnapshot:
    """reset / snapshot_and_reset / generation（connection _reset_buffer_locked 语义）."""

    def test_reset_bumps_generation_and_sets_orphan(self) -> None:
        asm = _asm(waiting=True)
        asm.feed(b"+HALF")
        gen = asm.generation
        asm.reset()
        assert asm.generation == gen + 1
        assert asm.has_pending_half_line is False
        # 半行滞留时 reset → orphan 已置位：续行被丢弃
        asm.set_cycle(echo_line=None, wait_urc_re=None, expect_re=None, waiting=True)
        assert asm.feed(b"xx\r\nOK\r\n") == [_complete(b"OK\r\n")]

    def test_snapshot_and_reset_returns_then_clears(self) -> None:
        asm = _asm(waiting=True)
        asm.feed(b"\r\nPART")
        gen = asm.generation
        assert asm.snapshot_and_reset() == b"\r\nPART"
        assert asm.has_pending_half_line is False
        assert asm.generation == gen + 1
        # 快照时缓冲不以 \n 结尾 → orphan 置位，收割期续行被丢弃
        asm.set_cycle(echo_line=None, wait_urc_re=None, expect_re=None, waiting=True)
        assert asm.feed(b"IAL\r\nOK\r\n") == [_complete(b"OK\r\n")]

    def test_delivery_bumps_generation(self) -> None:
        """buffer 每次清/换自增代次——终结交付（buffer 替换为 tail）同样生效."""
        asm = _asm(waiting=True)
        gen = asm.generation
        asm.feed(b"\r\nOK\r\n")
        assert asm.generation == gen + 1
