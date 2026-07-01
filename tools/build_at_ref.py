#!/usr/bin/env python3
"""AT 命令手册 PDF -> Markdown 转换工具（坐标驱动，PDF 技能：提取+程序处理+人工抽检）.

输入：项目根的 neoway_n58_at命令手册_v2.0_20241203.pdf
输出：docs/at-ref/ch{NN}-{标题}.md

核心原理（手册排版特征）：
  手册「命令格式表」只有顶部一条横线、主体无边框，find_tables 只能抓到表头；
  主体（执行/命令/响应多行）以文本 span 存在。纯文本流会把响应多行打乱顺序。
  因此用 span 坐标按 x 分三列桶重建命令格式表（实测列阈值：类型 x<110、命令 110-285、响应 x>285）。
  「参数表」有完整边框，用 find_tables 几何提取 + 去噪列。
  其余文本（描述/示例）按 y 顺序作为正文。

用法：
    uv run --no-project --with pymupdf python tools/build_at_ref.py ch05 [ch06 ...]
    uv run --no-project --with pymupdf python tools/build_at_ref.py --all
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "neoway_n58_at命令手册_v2.0_20241203.pdf"
OUT = ROOT / "docs" / "at-ref"

# (章号, 中文标题, 起始物理页1-based, 结束物理页1-based不含)
CHAPTERS: list[tuple[int, str, int, int]] = [
    (5, "短消息服务指令", 67, 84),
    (6, "TCP/UDP客户端指令", 84, 103),
    (7, "TCP服务器指令", 103, 113),
    (8, "TCP/UDP透传指令", 113, 118),
    (9, "TCP透明传输服务器指令", 118, 121),
    (10, "FTP指令", 121, 136),
    (11, "HTTP/HTTPS指令", 136, 162),
    (12, "呼叫控制指令", 162, 170),
    (13, "Wi-Fi功能", 170, 172),
    (14, "SSL TCP数据业务", 172, 184),
    (15, "阿里MQTT指令", 184, 195),
    (16, "标准MQTT指令", 195, 209),
    (17, "AWS MQTT指令", 209, 218),
    (18, "GPS功能", 218, 229),
    (19, "BT/BLE通用基础AT指令", 229, 232),
    (20, "BLE功能通用指令", 232, 236),
    (21, "BLE外围设备(从机)", 236, 249),
    (22, "BLE中心设备(主机)", 249, 258),
    (23, "DTMF功能指令", 258, 259),
    (24, "基站定位", 259, 261),
    (25, "网络时间同步", 261, 264),
    (26, "网络共享", 264, 267),
    (27, "流量统计", 267, 269),
    (28, "文件系统操作", 269, 280),
    (29, "录音功能相关指令", 280, 290),
    (30, "SIM卡操作相关指令", 290, 292),
    (31, "其他指令", 292, 347),
    (32, "UDP服务器功能", 347, 354),
    (33, "管道云功能", 354, 356),
]

NOISE_RE = [
    re.compile(r"^N\d{2,4}[A-Z]?\s*AT\s*命令手册.*$"),  # N58 AT命令手册 / N58 AT 命令手册 / N510M...
    re.compile(r"^第\d+\s*章.*$"),
    re.compile(r"^深圳市有方.*$"),
    re.compile(r"^版权所有.*$"),
    re.compile(r"^关于本文档\s*$"),
    re.compile(r"^\s*\d{1,3}\s*$"),
]


def is_noise(s: str) -> bool:
    return any(p.search(s.strip()) for p in NOISE_RE)


# ---------------------------------------------------------------------------
# 坐标 span
# ---------------------------------------------------------------------------

@dataclass
class Span:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


def page_spans(page: fitz.Page, pno: int) -> list[Span]:
    out: list[Span] = []
    d = page.get_text("dict")
    for b in d.get("blocks", []):
        if b.get("type", 0) != 0:
            continue
        for line in b.get("lines", []):
            txt = "".join(s["text"] for s in line.get("spans", [])).strip()
            if not txt or is_noise(txt):
                continue
            x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
            out.append(Span(txt, x0, y0, x1, y1, pno))
    return out


# ---------------------------------------------------------------------------
# 有框表（参数表/对照表）
# ---------------------------------------------------------------------------

@dataclass
class FTable:
    y0: float
    y1: float
    rows: list[list[str]]


def collect_ftables(page: fitz.Page, pno: int) -> list[FTable]:
    out: list[FTable] = []
    try:
        tabs = page.find_tables()
    except Exception:
        return out
    for t in tabs.tables:
        raw = t.extract()
        rows: list[list[str]] = []
        for r in raw:
            row = [("".join(c) if isinstance(c, list) else (c or "")).replace("\n", " ").strip() for c in r]
            rows.append(row)
        # 去噪空列
        if rows:
            ncol = max(len(r) for r in rows)
            rows = [r + [""] * (ncol - len(r)) for r in rows]
            keep = []
            for ci in range(ncol):
                nonempty = sum(1 for r in rows if r[ci].strip())
                head_nonempty = bool(rows[0][ci].strip())
                if nonempty / max(len(rows), 1) >= 0.3 or head_nonempty or nonempty >= 2:
                    keep.append(ci)
            if not keep:
                keep = [0]
            rows = [[r[ci] for ci in keep] for r in rows]
            rows = [r for r in rows if any(c.strip() for c in r)]
        if rows:
            out.append(FTable(t.bbox[1], t.bbox[3], rows))
    return out


def table_md(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "| " + " | ".join("---" for _ in rows[0]) + " |"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 有序元素流
# ---------------------------------------------------------------------------

@dataclass
class Elem:
    y: float
    page: int
    kind: str  # 'text' | 'ftable'
    payload: object
    xc: float = 0.0
    yc: float = 0.0


def page_elems(page: fitz.Page, pno: int) -> list[Elem]:
    spans = page_spans(page, pno)
    ftables = collect_ftables(page, pno)
    in_table = [False] * len(spans)
    for ft in ftables:
        for i, s in enumerate(spans):
            if ft.y0 - 2 <= s.yc <= ft.y1 + 2:
                in_table[i] = True
    elems: list[Elem] = []
    for s, used in zip(spans, in_table):
        if not used:
            elems.append(Elem(s.yc, pno, "text", s.text, s.xc, s.yc))
    for ft in ftables:
        elems.append(Elem(ft.y0, pno, "ftable", ft))
    elems.sort(key=lambda e: (e.page, e.y))
    return elems


# ---------------------------------------------------------------------------
# 命令切分与渲染
# ---------------------------------------------------------------------------

CMD_TITLE = re.compile(r"^(\d+\.\d+)\s+([A-Za-z0-9_+*$=!/?#@&]+)\s*[–\-—]\s*(.+)$")
SEC_FMT = "命令格式"
SEC_PARAM = "参数"
SEC_EXAMPLE = "示例"
SUB_MARKS = {"说明", "注意事项", "备注", "取值", "参考", "参考命令", "主动上报", "定义"}
FMT_HEADER = {"类型", "命令", "响应格式", "命令。", "响应"}
TYPE_VALUES = {"执行", "查询", "测试", "设置", "读取指令", "测试命令", "查询命令", "设置命令"}
FMT_X_TYPE = 110.0
FMT_X_CMD = 285.0


def mdcode(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    if re.search(r"[<>\[\]|,=]", s) or s.startswith("AT") or "<CR>" in s or s.startswith("+"):
        return f"`{s}`"
    return s


@dataclass
class Command:
    num: str
    name: str
    desc: str
    elems: list[Elem] = field(default_factory=list)


def split_commands(elems: list[Elem], chap_num: int) -> tuple[list[Elem], list[Command]]:
    intro: list[Elem] = []
    cmds: list[Command] = []
    cur: Command | None = None
    for e in elems:
        if e.kind == "text":
            m = CMD_TITLE.match(str(e.payload).strip())
            if m and m.group(1).split(".")[0] == str(chap_num):
                if cur:
                    cmds.append(cur)
                cur = Command(m.group(1), m.group(2).strip(), m.group(3).strip())
                continue
        if cur is None:
            intro.append(e)
        else:
            cur.elems.append(e)
    if cur:
        cmds.append(cur)
    return intro, cmds


def render_fmt(buf: list[Elem]) -> str:
    ftables = [e.payload for e in buf if e.kind == "ftable"]
    real = [ft for ft in ftables if ft.rows and not _header_only(ft.rows)]  # type: ignore[union-attr]
    if real:
        return table_md(real[0].rows)  # type: ignore[union-attr]
    points: list[tuple[float, float, str]] = []
    for e in buf:
        if e.kind != "text":
            continue
        t = str(e.payload).strip()
        if not t or t in FMT_HEADER:
            continue
        points.append((e.xc, e.yc, t))
    if not points:
        return ""
    rows: list[tuple[str, str, str]] = []
    cur_type = ""; cur_cmd: list[str] = []; cur_resp: list[str] = []

    def flush() -> None:
        nonlocal cur_type, cur_cmd, cur_resp
        if cur_type or cur_cmd or cur_resp:
            rows.append((cur_type, " ".join(cur_cmd).strip(), " ".join(cur_resp).strip()))
        cur_type = ""; cur_cmd = []; cur_resp = []

    for xc, _yc, t in sorted(points, key=lambda p: p[1]):
        if t in TYPE_VALUES:
            flush(); cur_type = t; continue
        if xc < FMT_X_TYPE:
            cur_type = (cur_type + " " + t).strip() if cur_type else t
        elif xc < FMT_X_CMD:
            cur_cmd.append(t)
        else:
            cur_resp.append(t)
    flush()
    if not rows:
        return ""
    out = ["| 类型 | 命令 | 响应格式 |", "| --- | --- | --- |"]
    for t, c, r in rows:
        out.append(f"| {t} | {mdcode(c)} | {mdcode(r)} |")
    return "\n".join(out)


def _header_only(rows: list[list[str]]) -> bool:
    flat = {c.strip() for r in rows for c in r if c.strip()}
    return flat <= FMT_HEADER and bool(flat)


def render_param(buf: list[Elem]) -> str:
    ftables = [e.payload for e in buf if e.kind == "ftable"]
    text_lines = [str(e.payload).strip() for e in buf if e.kind == "text" and str(e.payload).strip()]
    if ftables:
        blocks = [table_md(ft.rows) for ft in ftables if ft.rows]  # type: ignore[union-attr]
        intro_txt = " ".join(text_lines).strip()
        parts = []
        if intro_txt:
            parts.append(intro_txt); parts.append("")
        parts.extend(blocks)
        return "\n".join(parts)
    # 无框：参数名/说明成对
    pairs: list[tuple[str, str]] = []
    i = 0
    n = len(text_lines)
    while i < n:
        s = text_lines[i]
        is_name = bool(re.search(r"<[^>]+>", s)) or bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*$", s))
        if is_name and i + 1 < n and not _is_name(text_lines[i + 1]):
            desc = []
            j = i + 1
            while j < n and not _is_name(text_lines[j]):
                desc.append(text_lines[j]); j += 1
            pairs.append((s, " ".join(desc).strip())); i = j
        else:
            pairs.append(("", s)); i += 1
    merged: list[tuple[str, str]] = []
    for name, desc in pairs:
        if not name and merged and desc:
            merged[-1] = (merged[-1][0], (merged[-1][1] + " " + desc).strip())
        elif name or desc:
            merged.append((name, desc))
    if not merged:
        return ""
    out = ["| 参数 | 说明 |", "| --- | --- |"]
    for name, desc in merged:
        out.append(f"| {name} | {desc} |")
    return "\n".join(out)


def _is_name(s: str) -> bool:
    return bool(re.search(r"<[^>]+>", s)) or bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*$", s))


def render_example(buf: list[Elem]) -> str:
    """示例区：find_tables 常把示例的命令/响应行误识别为无表头表，
    此类表需展开为代码块文本（取每行非空单元格拼接）。"""
    lines: list[str] = []
    for e in buf:
        if e.kind == "text":
            s = str(e.payload).strip()
            if s:
                lines.append(s)
        elif e.kind == "ftable":
            ft = e.payload  # type: ignore[assignment]
            for r in ft.rows:  # type: ignore[union-attr]
                cells = [c.strip() for c in r if c.strip()]
                if cells:
                    lines.append(" ".join(cells))
    return "```\n" + "\n".join(lines) + "\n```"


def render_command(cmd: Command) -> str:
    out = [f"### {cmd.num} {cmd.name} — {cmd.desc}", ""]
    sections: list[tuple[str, list[Elem]]] = []
    cur_label = "preamble"; cur_buf: list[Elem] = []
    for e in cmd.elems:
        if e.kind == "text":
            s = str(e.payload).strip()
            if s == SEC_FMT:
                if cur_buf:
                    sections.append((cur_label, cur_buf[:])); cur_buf.clear()
                cur_label = "fmt"; continue
            if s == SEC_PARAM:
                if cur_buf:
                    sections.append((cur_label, cur_buf[:])); cur_buf.clear()
                cur_label = "param"; continue
            if s == SEC_EXAMPLE:
                if cur_buf:
                    sections.append((cur_label, cur_buf[:])); cur_buf.clear()
                cur_label = "example"; continue
            if s in SUB_MARKS:
                if cur_buf:
                    sections.append((cur_label, cur_buf[:])); cur_buf.clear()
                cur_label = s; continue
        cur_buf.append(e)
    if cur_buf:
        sections.append((cur_label, cur_buf[:]))

    for label, buf in sections:
        body = [x for x in buf if (x.kind != "text" or str(x.payload).strip())]
        if not body:
            continue
        if label == "preamble":
            txt = " ".join(str(e.payload) for e in body if e.kind == "text").strip()
            if txt:
                out.append(txt); out.append("")
        elif label == "fmt":
            tbl = render_fmt(buf)
            if tbl:
                out += ["**命令格式**", "", tbl, ""]
        elif label == "param":
            tbl = render_param(buf)
            if tbl:
                out += ["**参数**", "", tbl, ""]
        elif label == "example":
            out += ["**示例**", "", render_example(buf), ""]
        else:
            txt = " ".join(str(e.payload) for e in body if e.kind == "text").strip()
            out += [f"**{label}**", ""]
            if txt:
                out += [txt, ""]
    return "\n".join(out).rstrip() + "\n"


def process_chapter(doc: fitz.Document, num: int, title: str, start: int, end: int) -> str:
    elems: list[Elem] = []
    for pno in range(start - 1, end - 1):
        elems.extend(page_elems(doc[pno], pno))
    intro, cmds = split_commands(elems, num)
    out = [f"# 第 {num} 章 {title}", "",
           f"> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 {num} 章",
           "> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。", "", "---", ""]
    if intro:
        intro_txt = " ".join(str(e.payload) for e in intro if e.kind == "text").strip()
        # 去章大标题残留
        intro_txt = re.sub(rf"^{num}\s+\S.+", "", intro_txt).strip()
        if intro_txt:
            out.append(intro_txt); out.append("")
    for cmd in cmds:
        out.append(render_command(cmd)); out.append("")
    return "\n".join(out)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    if args and args[0] == "--all":
        targets = CHAPTERS
    else:
        want = {int(a.removeprefix("ch").split(".")[0]) for a in args}
        targets = [c for c in CHAPTERS if c[0] in want]
    if not targets:
        print("无匹配章节", file=sys.stderr); return 1
    doc = fitz.open(str(PDF))
    for num, title, start, end in targets:
        md = process_chapter(doc, num, title, start, end)
        # 文件名：标题中的非法字符替换
        safe_title = re.sub(r"[\\/:*?\"<>|]", "-", title)
        fname = f"ch{num:02d}-{safe_title}.md"
        (OUT / fname).write_text(md, encoding="utf-8")
        ncmd = len(re.findall(r"^### ", md, re.M))
        print(f"  ch{num:02d} {title}: p.{start}-{end} ({ncmd} 条命令) -> {fname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
