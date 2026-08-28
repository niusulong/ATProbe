"""RX 行组装器（纯逻辑，无锁无 IO）——SerialConnection 读路径的行协议核心.

从 SerialConnection._process_incoming 抽取（批 2a §3.1）：输入字节增量，
输出结构化事件。所有状态由本类持有，SerialConnection 仅持锁调用——
竞态关键路径变为可穷举单测的纯函数。禁止 import threading/queue。

语义来源 = 迁移前的 connection._process_incoming（行拆分 / URC 结构分类 /
终结判定 / 偏移去重 / 孤儿续行逐条等价，见各方法注释的行号对照）。本模块
新增两点能力（connection 接线见 Task 4/5）：
  - expect 检测（设计 §2.3）：对新增字节命中即 COMPLETE，优先于终结行判定；
  - 错误码行任何**等待**模式下立即终结（设计 §2.1）：wait_urc 模式收到
    ERROR/+CME ERROR/+CMS ERROR 不再等目标 URC 到超时。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# AT 响应终结标志行：OK / ERROR / +CME ERROR / +CMS ERROR 等（按行匹配）。
# 与 connection._TERMINATOR_RE 同款自带副本（不 import connection，避免环）。
_TERMINATOR_RE = re.compile(rb"^(OK|ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)\s*$")

# 错误码行（终结行去掉 OK）：设计 §2.1——wait_urc 模式下设备已明确拒绝，
# 继续等目标 URC 只会烧掉整个超时预算，故任何等待模式下均立即按终结交付。
_ERROR_RE = re.compile(rb"^(ERROR|\+CME ERROR:.*|\+CMS ERROR:.*)\s*$")


class RxEventKind(Enum):
    URC_LINE = "urc"  # 结构位置判定为主动上报的完整行
    RESPONSE_COMPLETE = "complete"  # 终结行交付（bytes=发送起至终结行含）
    RESPONSE_URC_TERMINATED = "complete_wait_urc"  # wait_urc 目标行命中（同上）
    TRUNCATED_IDLE = "truncate"  # 空闲态已处理行截断（状态推进，无交付）


@dataclass(frozen=True)
class RxEvent:
    kind: RxEventKind
    text: str = ""  # URC_LINE：已解码行文本
    data: bytes = b""  # COMPLETE/URC_TERMINATED：响应原始字节


class LineAssembler:
    """行组装 + URC 结构分类 + expect/终结检测的状态机.

    自有状态（对应 connection 迁移前的缓冲族字段）：``_buffer``（累积字节）、
    ``_dispatched``（已拆行派发偏移，原 _urc_dispatched）、``_generation``
    （代次——buffer 每次清/换自增，调用方据此检测跨调用重置）、
    ``_orphan_pending``（孤儿续行标记）。周期判定参数
    ``_echo_line/_wait_urc_re/_expect_re/_waiting`` 由调用方经 set_cycle 逐周期
    注入（线程语义归 connection，本类不持有）。
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._dispatched = 0
        self._generation = 0
        self._orphan_pending = False
        # 周期参数（set_cycle 注入；默认空闲态）
        self._echo_line: bytes | None = None
        self._wait_urc_re: re.Pattern[bytes] | None = None
        self._expect_re: re.Pattern[bytes] | None = None
        self._waiting = False

    # ------------------------------------------------------------------
    # 周期参数注入
    # ------------------------------------------------------------------
    def set_cycle(
        self,
        *,
        echo_line: bytes | None,
        wait_urc_re: re.Pattern[bytes] | None,
        expect_re: re.Pattern[bytes] | None,
        waiting: bool,
    ) -> None:
        """设置当前发送周期的判定参数（send_command/数据周期入口调用）.

        echo_line：在途命令回显行（strip 后 bytes）——与其逐字相等的行
        结构上是回显，不派发 URC；wait_urc_re：异步指令目标 URC 正则
        （OK 仅受理不终结，目标行命中交付整段）；expect_re：本批新增的附加
        完成条件（新增字节命中即 COMPLETE，优先于终结行判定）；waiting：
        是否处于等待响应态（False = 空闲态，所有完整非空行按 URC 派发）。
        expect 与 wait_urc 的互斥由调用方保证（connection 层校验），本类不检查。
        """
        self._echo_line = echo_line
        self._wait_urc_re = wait_urc_re
        self._expect_re = expect_re
        self._waiting = waiting

    # ------------------------------------------------------------------
    # 状态操作（等价 connection 的 _reset_buffer_locked / 超时快照路径）
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """清缓冲、偏移归零、代次+1（等价 connection._reset_buffer_locked）.

        孤儿续行标记为**赋值语义**（非只置位）：按当前缓冲状态重算——存在
        未完结半行（不以 \\n 结尾）则 True，否则 False。只置位不清位的旧写法
        有两个 bug：超时后续行 150ms 内未到时 stale 标记穿过收割尾部与下条
        命令入口存活，吞掉下一命令响应的首个 \\n（\\r\\nOK\\r\\n 变 OK\\r\\n）；
        重连路径对死链半行置位后吞掉新会话首行。赋值语义下各调用点天然正确。
        """
        self._orphan_pending = bool(self._buffer) and not self._buffer.endswith(b"\n")
        self._buffer.clear()
        self._dispatched = 0
        self._generation += 1

    @property
    def generation(self) -> int:
        """buffer 代次：每次清/换自增（调用方据此检测跨调用缓冲重置）."""
        return self._generation

    def snapshot_and_reset(self) -> bytes:
        """超时快照：返回当前缓冲并 reset（供超时交付）.

        等价 connection 超时路径的 ``partial = bytes(self._buffer)`` +
        ``_reset_buffer_locked()``——reset 按快照时缓冲状态重算 orphan 标记
        （半行尚在缓冲 → True，收割窗口内到达的续行由后续 feed 字节级丢弃）。
        """
        snapshot = bytes(self._buffer)
        self.reset()
        return snapshot

    @property
    def has_pending_half_line(self) -> bool:
        """缓冲是否存在未完结半行（非空且不以 \\n 结尾）——诊断/测试用."""
        return bool(self._buffer) and not self._buffer.endswith(b"\n")

    # ------------------------------------------------------------------
    # 核心：字节增量 → 事件序列
    # ------------------------------------------------------------------
    def feed(self, chunk: bytes) -> list[RxEvent]:
        """处理一个 RX chunk：孤儿丢弃、累积、行拆分、结构分类、终结判定.

        返回本次产生的事件（顺序即发生顺序）。事件携带的字节/文本均派生自
        进入本函数时的缓冲快照——feed 是同步纯函数，执行期间不存在并发
        reset，connection 原实现的三处"锁外交付读当前 buffer"竞态路径
        （P1-1）在此结构性消除。
        """
        events: list[RxEvent] = []

        # 孤儿续行丢弃（原 :637-644）：入口清缓冲截断的在途半行，其续行
        # （至下一个 \n 含）属命令前数据——字节级静默丢弃，不派发、不累积
        # （残缺行内容不可信，行级规则无法识别）。
        if self._orphan_pending and chunk:
            nl = chunk.find(b"\n")
            if nl < 0:
                return events  # 整个 chunk 都是续行内容，继续等行尾
            chunk = chunk[nl + 1 :]
            self._orphan_pending = False
            if not chunk:
                return events  # 续行恰好在本 chunk 结束，其余处理留给下个 chunk

        self._buffer.extend(chunk)
        data = bytes(self._buffer)  # 本次处理的快照（交付一律派生自它）
        dispatched_offset = self._dispatched
        awaiting = self._waiting

        # ------------------------------------------------------------------
        # expect 检测（批 2a 新增，设计 §2.3）：对**新增字节**（buffer[dispatched:]
        # 起——历史行已处理不重扫，增量扫描）做 expect_re.search。命中即完成
        # 且优先于终结行判定（命中点即响应终点，其后余量留 buffer 待下轮处理）。
        # 仅等待态生效：expect 是发送周期的附加完成条件，空闲态无终结概念。
        # 与 wait_urc 的互斥由调用方保证，此处不检查（都设置时 expect 先判）。
        # ------------------------------------------------------------------
        if self._expect_re is not None and awaiting:
            region = data[dispatched_offset:]
            m = self._expect_re.search(region)
            if m is not None:
                hit_end = dispatched_offset + m.end()
                events.append(RxEvent(kind=RxEventKind.RESPONSE_COMPLETE, data=data[:hit_end]))
                self._buffer = bytearray(data[hit_end:])  # 命中点后余量留 buffer
                self._dispatched = 0
                self._generation += 1
                return events

        lines = data.split(b"\n")
        # 最后一行可能不完整
        *complete_lines, tail = lines

        # 预计算每个完整行的字节跨度 [start, end)（end 含换行符），
        # end <= dispatched_offset 的行是历史 chunk 已处理过的，跳过派发。
        spans: list[tuple[int, int]] = []
        _pos = 0
        for _line in complete_lines:
            spans.append((_pos, _pos + len(_line) + 1))
            _pos += len(_line) + 1

        def _urc_candidate(stripped: bytes) -> bool:
            """结构位置排除后的 URC 候选行（无前缀判断）."""
            if not stripped:
                return False
            if _TERMINATOR_RE.match(stripped):
                return False
            # 在途命令的回显行（与刚发送命令逐字相等）不是 URC
            return not (self._echo_line is not None and stripped == self._echo_line)

        def _decode(b: bytes) -> str:
            return b.decode("utf-8", errors="replace")

        def _emit_urc(stripped: bytes) -> None:
            events.append(RxEvent(kind=RxEventKind.URC_LINE, text=_decode(stripped)))

        # ------------------------------------------------------------------
        # wait_urc 模式（异步指令，原 :682-726）：OK 仅受理不终结，须等匹配
        # wait_urc_re 的 URC 才把整段响应（OK+URC）交付终结；错误码行例外
        # （§2.1 行为变更，见 _ERROR_RE 注释）。
        # ------------------------------------------------------------------
        if self._wait_urc_re is not None and awaiting:
            for mi, (line, (_ls, le)) in enumerate(zip(complete_lines, spans, strict=True)):
                if le <= dispatched_offset:
                    continue  # 历史 chunk 已处理过的行（去重）
                stripped = line.strip()
                if not stripped:
                    continue
                # 目标 URC 匹配：整段响应（含 OK）交付终结。
                # 正则作用在 strip 后的行上——split(b"\n") 保留行尾 \r，
                # 含 $ 锚点的合法正则（如 \+X:ok$）须对 strip 后行匹配。
                if self._wait_urc_re.search(stripped):
                    _emit_urc(stripped)  # 目标行也按常规分流（§6.4）
                    # 交付 = 全量缓冲快照（发送起至目标行含，含其间 OK 段）
                    events.append(RxEvent(kind=RxEventKind.RESPONSE_URC_TERMINATED, data=data))
                    self._buffer = bytearray(tail)
                    self._dispatched = 0  # buffer 已替换，偏移归零
                    self._generation += 1
                    # 匹配行之后的完整行不丢弃（buffer 重置为 tail 后它们既不在
                    # 缓冲也未被派发）——按 URC 分流补派发一次。
                    for rest in complete_lines[mi + 1 :]:
                        s2 = rest.strip()
                        if s2:
                            _emit_urc(s2)
                    return events
                # 错误码行（ERROR/+CME/+CMS）：任何等待模式立即按终结交付
                # （§2.1 行为变更——修前 wait_urc 模式仅受理，等目标 URC 到超时）。
                if _ERROR_RE.match(stripped):
                    events.append(RxEvent(kind=RxEventKind.RESPONSE_COMPLETE, data=data[:le]))
                    self._buffer = bytearray(tail)
                    self._dispatched = 0
                    self._generation += 1
                    # 错误终结与常规终结同口径：其后完整行按主动上报补派发
                    for rest, (_rls, rle) in zip(complete_lines, spans, strict=True):
                        if rle <= le:
                            continue
                        s2 = rest.strip()
                        if s2:
                            _emit_urc(s2)
                    return events
                # OK 等非错误终结行：仅受理不终结，继续等 URC（已累积进 buffer）
                if _TERMINATOR_RE.match(stripped):
                    continue
                # 其它行：可能是插队的 URC（如 $ 前缀厂商上报）也可能是载荷——
                # 双交付：派发事件 + 留在文本（结构性排除回显/空行/终结行）
                if _urc_candidate(stripped):
                    _emit_urc(stripped)
            # 推进已处理偏移（下个 chunk 不再重复派发历史行）。原实现的代次
            # 校验（锁外派发期间 buffer 被引擎清/换）在此不需要：feed 是同步
            # 纯函数，执行期间无并发 reset。
            self._dispatched = spans[-1][1] if spans else dispatched_offset
            return events

        # ------------------------------------------------------------------
        # 常规模式（wait_urc 未启用，原 :731-790）：OK/ERROR 即终结
        # ------------------------------------------------------------------
        found_terminator = False
        for line, (_ls, le) in zip(complete_lines, spans, strict=True):
            if le <= dispatched_offset:
                continue  # 历史 chunk 已处理过的行（去重；终结判定也无需重做）
            stripped = line.strip()
            if not stripped:
                continue
            # 等待响应期间，URC 行同时提取（§6.4，双交付）。仅等待时在此派发
            # ——空闲态由下方专门分支统一派发（两处都派发会双发）。
            if awaiting and _urc_candidate(stripped):
                _emit_urc(stripped)
            if _TERMINATOR_RE.match(stripped) and awaiting:
                # 响应完整：交付 = 缓冲头至该终结行（含）——与终结行同 chunk
                # 到达的后续行是主动上报，立即派发（不丢失、不污染交付文本）。
                events.append(RxEvent(kind=RxEventKind.RESPONSE_COMPLETE, data=data[:le]))
                self._buffer = bytearray(tail)  # 保留终结行之后的数据作下一轮缓冲
                self._dispatched = 0  # buffer 已替换，偏移归零
                self._generation += 1
                found_terminator = True
                # 终结行之后的完整行：结构位置 = 命令应答已结束 → 非空即派发
                for rest, (_rls, rle) in zip(complete_lines, spans, strict=True):
                    if rle <= le:
                        continue
                    s2 = rest.strip()
                    if s2:
                        _emit_urc(s2)
                break

        if not found_terminator:
            if not awaiting:
                # 空闲态：收到的数据全部按 URC 处理（§6.4 基本策略，无前缀判断）
                for line, (_ls, le) in zip(complete_lines, spans, strict=True):
                    if le <= dispatched_offset:
                        continue
                    stripped = line.strip()
                    if stripped:
                        _emit_urc(stripped)
                # 已处理的完整行从 buffer 截断，只保留最后一个不完整行（tail）
                # ——否则设备持续发 URC 而无人发送命令时 buffer 无限增长。
                self._buffer = bytearray(tail)
                self._dispatched = 0
                self._generation += 1
                if complete_lines:
                    events.append(RxEvent(kind=RxEventKind.TRUNCATED_IDLE))
            else:
                # 等待中但未终结：推进已处理偏移（下个 chunk 不再重复派发历史行；
                # 代次校验省略理由同 wait_urc 分支尾注）
                self._dispatched = spans[-1][1] if spans else dispatched_offset
        return events
