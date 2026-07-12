"""虚拟 AT 模组应答状态机（库级，无 pyserial 依赖）.

把「收到某条 AT 指令 → 生成模组风格响应帧」的核心逻辑放在 src/ 库内，供：
- ``tools/vsim/at_responder.py``：守真实/虚拟串口的外部进程
- ``atprobe.infra.serial.vsim.VsimPortManager``：进程内零驱动模式
共用同一份事实源，避免逻辑重复。

帧格式对齐 ATProbe ``connection.py`` 终结符识别：回包以 ``OK``/``ERROR`` 结尾，
每行 ``\\r\\n``。
"""

from __future__ import annotations

from collections.abc import Callable

# 一行 \r\n
CRLF = b"\r\n"


def _line(text: str) -> bytes:
    return text.encode("utf-8") + CRLF


class AtResponder:
    """虚拟模组状态机：根据指令生成应答帧."""

    def __init__(self, *, rssi: int = 23, cereg: int = 1) -> None:
        self.rssi = max(0, min(31, rssi))
        self.cereg = max(0, min(5, cereg))
        # AT+CMGF 等可变状态
        self.cmgf = 0
        self.cereg_n = 0  # CEREG 上报开关
        self.echo = True  # 回显开关（ATE1 开 / ATE0 关），对齐 3GPP TS 27.007 §5.1
        # 指令分发表
        # handler 返回约定（list[str] | None）：
        #   list[str]  正文行，respond() 追加 OK（空 list = 仅 OK 的正常响应）
        #   None       解析失败/参数非法，respond() 返回 ERROR（对齐真实模组的错误拒绝）
        self._handlers: dict[str, Callable[[str], list[str] | None]] = {
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
        }

    # -- 各指令处理器：返回正文行（不含 OK/ERROR） ---------------------
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

    # -- 主分发：返回完整应答字节 --------------------------------------
    def respond(self, cmd: str) -> bytes:
        """根据指令返回完整应答帧（含结尾 OK/ERROR）.

        handler 返回 ``None`` 表示解析失败/参数非法 → 返回 ERROR；返回 ``list``（含
        空 list）表示正常 → 追加 OK。从而区分「合法空响应」与「错误拒绝」。

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
        # 精确匹配优先；否则前缀匹配（按前缀长度降序，保证最长/最具体者优先）。
        # 注意："AT" 这类裸指令只走精确匹配，不作前缀（否则会吞掉所有 AT+ 指令）。
        body: list[str] | None = None
        if c in self._handlers:
            body = self._handlers[c](cmd)
        else:
            for prefix, fn in sorted(
                self._handlers.items(), key=lambda kv: len(kv[0]), reverse=True
            ):
                # 裸指令（不含 + = ? &）不参与前缀匹配，仅精确匹配
                if prefix in ("AT", "ATI", "ATZ"):
                    continue
                if c.startswith(prefix):
                    body = fn(cmd)
                    break
        # 组装行列表：可选回显行 + body 行 + 结束行（OK/ERROR）
        lines: list[str] = []
        if self.echo:
            lines.append(cmd.strip())
        if body is None:
            lines.append("ERROR")
        else:
            lines.extend(body)
            lines.append("OK")
        # 渲染：整帧以 \r\n 起始，每行以 \r\n 结尾（如 \r\n+CSQ: 23,99\r\nOK\r\n）
        return CRLF + CRLF.join(line.encode("utf-8") for line in lines) + CRLF
