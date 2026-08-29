"""虚拟 AT 模组应答状态机（库级，无 pyserial 依赖）.

把「收到某条 AT 指令 → 生成模组风格响应帧」的核心逻辑放在 src/ 库内，供：
- ``tools/vsim/at_responder.py``：守真实/虚拟串口的外部进程
- ``atprobe.infra.serial.vsim.VsimPortManager``：进程内零驱动模式
共用同一份事实源，避免逻辑重复。

帧格式对齐 ATProbe ``connection.py`` 终结符识别：回包以 ``OK``/``ERROR`` 结尾，
每行 ``\\r\\n``。

批 2b Task 5 起支持两阶段发送指令（TCPSEND/UDPSEND/FSWF）：阶段一 respond 返回
提示符（无 OK）；阶段二 receive_data 收裸数据，收满声明长度出成功帧，超时由
expire_pending 出超时帧。FSRF/FSFS/FSDF 读写进程内 FS 存储（``_fs``）。
帧格式逐字对齐手册（docs/at-ref/ ch06 §6.4/§6.10、ch28 §28.1-28.6）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# 一行 \r\n
CRLF = b"\r\n"

# 裸指令（不含 + = ? &）不参与前缀匹配，仅精确匹配：
# "AT" 会吞掉所有 AT+ 指令；"ATE0"/"ATE1" 会吞掉 ATE0X 等无效变体误答 OK（应 ERROR）
_BARE_PREFIXES = ("AT", "ATI", "ATZ", "ATE0", "ATE1")

# TCPSEND/UDPSEND buffer 模式 ASCII <length> 上限（手册 ch06：1..4096）
_MAX_SEND_LEN = 4096
# FSWF <size> 上限（用户盘 1M，手册 ch28 §28.1：0..1024*1024）
_MAX_FS_SIZE = 1024 * 1024
# FSWF <time> 上限 ms。真机实测（2026-08-29，N58 V00F，COM5 二分探针）：
# 0..120000 接受（出提示符），120001 起拒（+CME ERROR: 53）——手册参数表
# （0~240000）与手册示例（60001 即 ERROR）**均与实机不符**，以实机为准
_MAX_FS_TIME_MS = 120000


def _line(text: str) -> bytes:
    return text.encode("utf-8") + CRLF


def _strict_int(text: str) -> int | None:
    """严格十进制整数解析：仅非空 ASCII 数字串，否则 None.

    拒绝 ``int()`` 的宽松形式（``"+5"``/``" 5"``/``"1_0"``），对齐模组 AT
    解析器对参数的严格性——非整数参数一律 ERROR。
    """
    if not text or not (text.isascii() and text.isdigit()):
        return None
    return int(text)


@dataclass
class _Prompt:
    """提示符响应（两阶段发送阶段一）：``\\r\\n`` + [回显行 + ``\\r\\n``] + 提示符字节.

    无尾 CRLF、无 OK/ERROR——裸数据发送仍待继续（手册 TCPSEND：``<CR><LF>><content>``）。
    TCPSEND 提示符 ``b">"``（无尾空格）、UDPSEND ``b"> "``（带尾空格，手册响应格式
    ``<CR><LF>> <CR><LF>OK``）、FSWF ``b">"``（形态手册未定义，默认同 TCPSEND）。
    """

    data: bytes


@dataclass
class _Raw:
    """裸业务帧：各行 ``\\r\\n`` 组装，不追加 OK（如 ``+TCPSEND: SOCKET ID OPEN FAILED``）."""

    lines: list[str]


@dataclass
class _PendingSend:
    """两阶段发送的进行中会话（respond 出提示符后 → 收满声明长度前）."""

    kind: str  # "tcp" | "udp" | "fs"
    link: int  # 链路号（fs 会话为 0）
    remaining: int  # 还需多少字节
    filename: str | None  # fs 会话的文件名（tcp/udp 为 None）
    mode: int  # fs 写模式 0=覆写起始 / 1=末尾追加
    declared: int  # 声明长度（成功帧回显用）


class AtResponder:
    """虚拟模组状态机：根据指令生成应答帧."""

    def __init__(
        self, *, rssi: int = 23, cereg: int = 1, fs_timeout_s: float | None = None
    ) -> None:
        self.rssi = max(0, min(31, rssi))
        self.cereg = max(0, min(5, cereg))
        # 数据会话设备侧等数据超时（秒）：会话未收满时经此超时强制出帧
        # （VsimPortManager.send_data 使用；expire_pending 由其调用）
        self.fs_timeout_s = fs_timeout_s
        # AT+CMGF 等可变状态
        self.cmgf = 0
        self.cereg_n = 0  # CEREG 上报开关
        self.echo = True  # 回显开关（ATE1 开 / ATE0 关），对齐 3GPP TS 27.007 §5.1
        # 两阶段发送会话（阶段一出提示符后挂起，等裸数据收满；同一时刻至多一个）
        self._pending: _PendingSend | None = None
        # 进程内 FS 存储：文件名原样键 → 字节内容（FSWF 写 / FSRF 读 / FSFS 大小 / FSDF 删）
        self._fs: dict[str, bytearray] = {}
        # 指令分发表
        # handler 返回约定（list[str] | _Prompt | _Raw | None）：
        #   list[str]  正文行，respond() 追加 OK（空 list = 仅 OK 的正常响应）
        #   _Prompt    提示符帧（两阶段发送阶段一，无 OK）
        #   _Raw       裸业务帧（如 +TCPSEND: DATA LENGTH ERROR，不追加 OK）
        #   None       解析失败/参数非法，respond() 返回 ERROR（对齐真实模组的错误拒绝）
        self._handlers: dict[str, Callable[[str], list[str] | _Prompt | _Raw | None]] = {
            "AT": self._h_at,
            "ATI": self._h_ati,
            "AT&V": self._h_ati,
            "AT+CSQ": self._h_csq,
            "AT+CSQ?": self._h_csq,
            "AT+CEREG?": self._h_cereg_query,
            "AT+CEREG=": self._h_cereg_set,
            "AT+CPIN?": self._h_cpin,
            "AT+CGDCONT?": self._h_cgdcont,
            "AT+CGATT?": self._h_cgatt,
            "AT+CGATT=": self._h_ok,
            "AT+CMGF=": self._h_cmgf,
            "AT+CNMI=": self._h_ok,
            "AT+CFUN=": self._h_ok,
            "AT+CGACT=": self._h_ok,
            "AT+CGDCONT=": self._h_ok,
            "AT&W": self._h_ok,
            "ATZ": self._h_ok,
            "ATE0": self._h_ok,
            "ATE1": self._h_ok,
            "AT+TCPSEND=": self._h_tcpsend,
            "AT+UDPSEND=": self._h_udpsend,
            "AT+FSWF=": self._h_fswf,
            "AT+FSRF=": self._h_fsrf,
            "AT+FSFS=": self._h_fsfs,
            "AT+FSDF=": self._h_fsdf,
        }
        # 前缀表预排序一次（最长前缀优先，保证最长/最具体者先匹配）：
        # respond 每次分发复用，不再重复排序（设计 §2.4 随批缺陷修复）
        self._prefix_handlers = [
            (p, fn)
            for p, fn in sorted(self._handlers.items(), key=lambda kv: len(kv[0]), reverse=True)
        ]

    # -- 各指令处理器：返回正文行 / 提示符 / 裸帧（不含 OK/ERROR） ------------------
    def _h_at(self, _cmd: str) -> list[str] | None:
        return []  # 仅 OK

    def _h_ati(self, _cmd: str) -> list[str] | None:
        return ["ATProbe Virtual Module", "Revision: vsim-1.0", "IMEI: 012345678901234"]

    def _h_csq(self, _cmd: str) -> list[str] | None:
        ber = 99  # BER 未知
        return [f"+CSQ: {self.rssi},{ber}"]

    def _h_cereg_query(self, _cmd: str) -> list[str] | None:
        # +CEREG: <n>,<stat>[,<tac>,<ci>,<AcT>]
        return [f"+CEREG: {self.cereg_n},{self.cereg}"]

    def _h_cereg_set(self, cmd: str) -> list[str] | None:
        # AT+CEREG=<n>
        try:
            n = int(cmd.split("=", 1)[1].split(",")[0])
            self.cereg_n = n
        except (IndexError, ValueError):
            return None  # 参数非法 → ERROR（真实模组对格式错误指令返回错误）
        return []  # OK

    def _h_cpin(self, _cmd: str) -> list[str] | None:
        return ["+CPIN: READY"]

    def _h_cgdcont(self, _cmd: str) -> list[str] | None:
        return [
            '+CGDCONT: 1,"IP","cmnet","","0.0.0.0",0,0',
            '+CGDCONT: 2,"IPV4V6","ims","","0.0.0.0",0,0',
        ]

    def _h_cgatt(self, _cmd: str) -> list[str] | None:
        return ["+CGATT: 1"]

    def _h_cmgf(self, cmd: str) -> list[str] | None:
        try:
            self.cmgf = int(cmd.split("=", 1)[1])
        except (IndexError, ValueError):
            return None  # 参数非法 → ERROR
        return []

    def _h_ok(self, _cmd: str) -> list[str] | None:
        return []

    # -- 两阶段发送：TCPSEND / UDPSEND（手册 ch06 §6.4/§6.10） ----------------------
    def _h_tcpsend(self, cmd: str) -> list[str] | _Prompt | _Raw | None:
        return self._h_xsend(cmd, "tcp", "AT+TCPSEND=")

    def _h_udpsend(self, cmd: str) -> list[str] | _Prompt | _Raw | None:
        return self._h_xsend(cmd, "udp", "AT+UDPSEND=")

    def _h_xsend(self, cmd: str, kind: str, prefix: str) -> list[str] | _Prompt | _Raw | None:
        """AT+TCPSEND/AT+UDPSEND=<n>,<length>（buffer 模式，恰两个参数）阶段一.

        合法 → 挂起会话并出提示符（tcp ``\\r\\n>`` 无尾空格 / udp ``\\r\\n> `` 带尾空格，
        逐字对齐手册响应格式行）；链路号非 0..5 → ``+X: SOCKET ID OPEN FAILED`` 裸帧；
        length 0 或 >4096 → ``+X: DATA LENGTH ERROR`` 裸帧；参数个数≠2 / 非整数 → ERROR
        （命令模式第三参数 content 不模拟——引擎侧仅用 buffer 模式）。
        """
        x = prefix.removeprefix("AT+").removesuffix("=")  # TCPSEND / UDPSEND
        params = cmd.partition("=")[2]
        parts = params.split(",")
        if len(parts) != 2:
            return None
        n = _strict_int(parts[0])
        length = _strict_int(parts[1])
        if n is None or length is None:
            return None
        if not 0 <= n <= 5:
            return _Raw([f"+{x}: SOCKET ID OPEN FAILED"])
        if length <= 0 or length > _MAX_SEND_LEN:
            return _Raw([f"+{x}: DATA LENGTH ERROR"])
        self._pending = _PendingSend(
            kind=kind, link=n, remaining=length, filename=None, mode=0, declared=length
        )
        return _Prompt(b">" if kind == "tcp" else b"> ")

    # -- 文件系统：FSWF / FSRF / FSFS / FSDF（手册 ch28 §28.1-28.6） ----------------
    @staticmethod
    def _split_quoted(arg: str) -> tuple[str, list[str]] | None:
        """解析 ``"<name>"[,<p1>[,<p2>...]]``：文件名仅接受双引号包裹（手册如此）.

        返回 (文件名, 其余参数列表)；格式错（无引号/引号未闭合/闭引号后非逗号参数串）
        → None。文件名内的 ``=`` 与引号外参数不受影响（首个 ``=`` 已由 partition 剥离）。
        """
        if len(arg) < 2 or arg[0] != '"':
            return None
        end = arg.find('"', 1)
        if end == -1:
            return None
        name = arg[1:end]
        rest = arg[end + 1 :]
        if rest == "":
            return name, []
        if not rest.startswith(","):
            return None
        return name, rest[1:].split(",")

    def _h_fswf(self, cmd: str) -> list[str] | _Prompt | _Raw | None:
        """AT+FSWF="<file_name>",<mode>,<size>,<time> 写文件阶段一（手册 §28.1）.

        mode 0=覆写起始 / 1=末尾追加；size 0..1048576；time 0..120000（真机
        实测上限，见 ``_MAX_FS_TIME_MS`` 注释——手册参数表与示例均与实机不符）。
        合法 → 提示符 ``\\r\\n> ``（**带尾空格**——真机实测 2026-08-29 hex 取证
        ``0D 0A 3E 20``，与 UDPSEND 手册形态一致；先前按 TCPSEND 无空格形态的
        假设已在真机验收中证伪并回填，手册 §28.1 响应格式表未列提示符行）。
        """
        parsed = self._split_quoted(cmd.partition("=")[2])
        if parsed is None:
            return None
        name, params = parsed
        if len(params) != 3:
            return None
        mode = _strict_int(params[0])
        size = _strict_int(params[1])
        time_ms = _strict_int(params[2])
        if mode is None or size is None or time_ms is None:
            return None
        if mode not in (0, 1) or not 0 <= size <= _MAX_FS_SIZE:
            return None
        if not 0 <= time_ms <= _MAX_FS_TIME_MS:
            return None
        self._pending = _PendingSend(
            kind="fs", link=0, remaining=size, filename=name, mode=mode, declared=size
        )
        return _Prompt(b"> ")

    def _h_fsrf(self, cmd: str) -> list[str] | _Prompt | _Raw | None:
        """AT+FSRF="<file_name>",<mode>,<size>[,<position>] 读文件（手册 §28.2）.

        mode 0=从起始读 / mode 1=从 position 读（mode 1 缺 position 视为格式错）；
        文件不存在 / size 超文件长 / position 越界 → ERROR（手册示例 1025>1024 即 ERROR）。
        越界口径：mode 1 下 position+size 超文件长同样 ERROR——否则切片短于 size，
        会生成「声明 N 字节实发 M 字节」的说谎帧（手册未明示该角落，从严处理）。
        """
        parsed = self._split_quoted(cmd.partition("=")[2])
        if parsed is None:
            return None
        name, params = parsed
        if len(params) not in (2, 3):
            return None
        mode = _strict_int(params[0])
        size = _strict_int(params[1])
        if mode is None or size is None or mode not in (0, 1) or size < 0:
            return None
        position = 0
        if mode == 1:
            if len(params) != 3:
                return None
            pos = _strict_int(params[2])
            if pos is None or pos < 0:
                return None
            position = pos
        content = self._fs.get(name)
        if content is None:
            return None  # 文件不存在 → ERROR
        if size > len(content) or position + size > len(content):
            return None
        chunk = content[position : position + size]
        text = bytes(chunk).decode("utf-8", errors="replace")
        return [f"+FSRF: {size},{text}"]  # size=0 → "+FSRF: 0,"（content 空串）

    def _h_fsfs(self, cmd: str) -> list[str] | _Prompt | _Raw | None:
        """AT+FSFS="<file_name>" 获取文件大小（手册 §28.6）：存在 → ``+FSFS: <size>``."""
        parsed = self._split_quoted(cmd.partition("=")[2])
        if parsed is None:
            return None
        name, params = parsed
        if params:
            return None
        content = self._fs.get(name)
        if content is None:
            return None  # 不存在 → ERROR
        return [f"+FSFS: {len(content)}"]

    def _h_fsdf(self, cmd: str) -> list[str] | _Prompt | _Raw | None:
        """AT+FSDF="<file_name>" 删除文件（手册 §28.4）：存在删除仅 OK；不存在 ERROR."""
        parsed = self._split_quoted(cmd.partition("=")[2])
        if parsed is None:
            return None
        name, params = parsed
        if params:
            return None
        if name not in self._fs:
            return None
        del self._fs[name]
        return []  # 仅 OK

    # -- 主分发：返回完整应答字节 --------------------------------------
    def respond(self, cmd: str) -> bytes:
        """根据指令返回完整应答帧（含结尾 OK/ERROR，或提示符/裸业务帧）.

        handler 返回 ``None`` 表示解析失败/参数非法 → 返回 ERROR；返回 ``list``（含
        空 list）表示正常 → 追加 OK；返回 ``_Prompt``/``_Raw`` → 提示符帧/裸业务帧
        （见各自 docstring）。从而区分「合法空响应」与「错误拒绝」。

        帧格式对齐真实模组：每行以 ``\\r\\n`` 分隔，整帧以 ``\\r\\n`` 起始
        （如 ``\\r\\n+CSQ: 23,99\\r\\nOK\\r\\n``），与 ATProbe connection.py 的终结符识别一致。
        回显遵循 ATE0/ATE1（3GPP TS 27.007 §5.1）：默认 ATE1 回显收到的指令；
        ATE0 后不再回显。这使得多数 setup 首步发 ATE0 的用例能整条跑通（断言不含回显前缀）。
        """
        c = cmd.strip().upper()
        if not c:
            return b""
        # ATE0/ATE1 切换回显（先于分发，确保 ATE0 自身响应也不回显——对齐真实模组）
        if c in ("ATE0", "ATE1"):
            self.echo = c.endswith("1")
        # 精确匹配优先；否则前缀匹配（__init__ 预排序的最长前缀优先表）。
        # 裸指令（"AT"/"ATI"/"ATZ"/"ATE0"/"ATE1"）只走精确匹配，不作前缀。
        outcome: list[str] | _Prompt | _Raw | None = None
        if c in self._handlers:
            outcome = self._handlers[c](cmd)
        else:
            for prefix, fn in self._prefix_handlers:
                if prefix in _BARE_PREFIXES:
                    continue
                if c.startswith(prefix):
                    outcome = fn(cmd)
                    break
        # 回显行（字节形态）：\r\n + [回显行 + \r\n] 前缀，_Prompt/_Raw 渲染复用
        echo = _line(cmd.strip()) if self.echo else b""
        if isinstance(outcome, _Prompt):
            # 提示符帧：\r\n + [回显行 + \r\n] + 提示符字节，无尾 CRLF、无 OK（等裸数据）
            return CRLF + echo + outcome.data
        if isinstance(outcome, _Raw):
            # 裸业务帧：\r\n + [回显行 + \r\n] + 各业务行（\r\n 结尾），不追加 OK
            return CRLF + echo + b"".join(_line(ln) for ln in outcome.lines)
        # 既有 list/None 路径（语义逐字不变）：组装 可选回显行 + body 行 + OK/ERROR
        lines: list[str] = []
        if self.echo:
            lines.append(cmd.strip())
        if outcome is None:
            lines.append("ERROR")
        else:
            lines.extend(outcome)
            lines.append("OK")
        # 渲染：整帧以 \r\n 起始，每行以 \r\n 结尾（如 \r\n+CSQ: 23,99\r\nOK\r\n）
        return CRLF + CRLF.join(line.encode("utf-8") for line in lines) + CRLF

    # -- 数据流两阶段会话（批 2b Task 5：TCPSEND/UDPSEND/FSWF 阶段二） --------------
    def receive_data(self, data: bytes) -> bytes:
        """接收裸数据流块（两阶段发送阶段二）：会话收满出完整帧，未收满返回 b"".

        无会话时的污染语义：设备把意外到达的数据当 AT 指令解析（decode 后走 respond）。
        这正是 data×retry 组合下引擎警告的场景——迟到/重发的裸数据会被模组当成命令，
        vsim 诚实模拟该行为而非静默吞掉，使此类误用用例在 vsim 上同样翻车（假绿零容忍）。

        fs 会话写语义（简化）：mode 0 从文件头按序覆写、保留超出写入段的旧尾部
        （bytearray 切片赋值）；mode 1 末尾追加。与真机差异：不校验用户盘总容量
        1M 上限，文件名长度上限（≤120）亦不校验。

        连续流：收满出帧后若 leftover 非空（同一次到达里命令紧跟数据尾），递归
        respond 追加其应答帧。
        """
        pending = self._pending
        if pending is None:
            # 污染语义：意外数据当命令解析（vsim 不掩盖引擎侧误用）
            return self.respond(data.decode("utf-8", errors="replace"))
        take = data[: pending.remaining]
        leftover = data[len(take) :]
        if pending.kind == "fs" and pending.filename is not None:
            pos = pending.declared - pending.remaining  # mode 0 的顺序写入游标
            buf = self._fs.setdefault(pending.filename, bytearray())
            if pending.mode == 0:
                buf[pos : pos + len(take)] = take  # 覆写起始段、保超出段
            else:
                buf.extend(take)
        pending.remaining -= len(take)
        if pending.remaining > 0:
            return b""  # 未收满：设备静默等数据（由 fs_timeout_s/expire_pending 收口）
        self._pending = None
        if pending.kind == "fs":
            frame = CRLF + b"OK" + CRLF
        else:
            x = "TCPSEND" if pending.kind == "tcp" else "UDPSEND"
            result = f"+{x}: {pending.link},{pending.declared}"
            frame = CRLF + b"OK" + CRLF + CRLF + result.encode("utf-8") + CRLF
        if leftover:
            frame += self.respond(leftover.decode("utf-8", errors="replace"))
        return frame

    def expire_pending(self) -> bytes:
        """强制结束未收满的数据会话（设备侧等数据超时），返回超时业务帧并清会话.

        fs → ``\\r\\n+FSWF: Timeout!\\r\\n``（手册 §28.1 示例）；tcp/udp →
        ``\\r\\n+X: <n>,OPERATION EXPIRED\\r\\n``（手册 §6.4/§6.10：提示符后 30s 无数据）。
        超时前已写入选 FS 存储的部分数据保留（真机上超时前到达的字节同样已落盘）。
        """
        pending = self._pending
        if pending is None:
            return b""
        self._pending = None
        if pending.kind == "fs":
            return CRLF + b"+FSWF: Timeout!" + CRLF
        x = "TCPSEND" if pending.kind == "tcp" else "UDPSEND"
        expired = f"+{x}: {pending.link},OPERATION EXPIRED"
        return CRLF + expired.encode("utf-8") + CRLF
