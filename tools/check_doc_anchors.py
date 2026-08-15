"""设计文档章节锚点一致性检查.

提取源码注释中的 § 引用（M1 §x / M2 §x / TSD §x / REQ-Mx §x / 裸 §x 按
模块上下文归并），与 docs/ 下文档的实际标题比对，输出缺失锚点清单。

用法：python tools/check_doc_anchors.py
退出码：0 全部命中；1 有缺失（CI 可用）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DOCS = ROOT / "docs"

# 模块 → REQ 文档路径
DOC_OF = {
    "M1": DOCS / "requirements" / "REQ-M1-串口通信管理.md",
    "M2": DOCS / "requirements" / "REQ-M2-测试用例定义.md",
    "M3": DOCS / "requirements" / "REQ-M3-测试执行引擎.md",
    "M4": DOCS / "requirements" / "REQ-M4-测试报告.md",
    "M5": DOCS / "requirements" / "REQ-M5-CLI界面.md",
    "M6": DOCS / "requirements" / "REQ-M6-GUI管理界面.md",
    "M7": DOCS / "requirements" / "REQ-M7-测试环境配置.md",
    "TSD": DOCS / "design" / "TSD-技术选型.md",
}

# 源码路径前缀 → 归属模块（裸 § 引用的上下文归并）
PATH_MOD = [
    ("infra/serial", "M1"),
    ("domain/case", "M2"),
    ("domain/suite", "M2"),
    ("engine", "M3"),
    ("domain/report", "M4"),
    ("reporting", "M4"),
    ("cli", "M5"),
    ("infra/config/appconfig", "M5"),
    ("gui", "M6"),
    ("infra/config/envconfig", "M7"),
]


def cite_mod(rel: str) -> str | None:
    for prefix, mod in PATH_MOD:
        if rel.startswith(prefix):
            return mod
    return None


def collect_citations() -> dict[str, set[str]]:
    cites: dict[str, set[str]] = {}
    for f in sorted(SRC.rglob("*.py")):
        rel = f.relative_to(SRC).as_posix()
        default_mod = cite_mod(rel)
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(?:REQ-)?(M[1-7]|TSD)\s*§\s*([\d.]+)", text):
            cites.setdefault(m.group(1), set()).add(m.group(2))
        if default_mod:
            # 裸 § 引用（模块已在文件头 docstring 声明，如 M1 §x.x）
            header = text[:2000]
            hm = re.search(r"\b(M[1-7])\b", header)
            ctx = hm.group(1) if hm else default_mod
            for m in re.finditer(r"(?<![\w.\-])§\s*([\d.]+)", text):
                # 排除已被显式前缀匹配覆盖的（简易法：位置回看不属于 REQ-Mx/TSD 模式）
                start = m.start()
                prefix_span = text[max(0, start - 12) : start]
                if re.search(r"(?:REQ-)?(?:M[1-7]|TSD)\s*$", prefix_span):
                    continue
                cites.setdefault(ctx, set()).add(m.group(1))
    return cites


def doc_headings(path: Path) -> set[str]:
    """收集文档全部标题的章节号（含父级链：## 4.1 同时命中 4）."""
    nums: set[str] = set()
    if not path.exists():
        return nums
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{1,6}\s+(?:[A-Za-z ]+)?(\d+(?:\.\d+)*)[.\s]", line)
        if m:
            parts = m.group(1).split(".")
            for i in range(1, len(parts) + 1):
                nums.add(".".join(parts[:i]))
    return nums


def main() -> int:
    cites = collect_citations()
    missing_total = 0
    for mod in sorted(cites):
        doc = DOC_OF[mod]
        heads = doc_headings(doc)
        if not heads:
            print(f"[{mod}] 文档缺失: {doc}")
            missing_total += 1
            continue
        missing = sorted(cites[mod] - heads, key=lambda s: [int(x) for x in s.split(".")])
        status = "OK " if not missing else "MISS"
        print(f"[{mod}] {status} 引用 {len(cites[mod])} 个章节", end="")
        if missing:
            print(f"，缺失锚点: {missing}（文档 {doc.name}）")
            missing_total += len(missing)
        else:
            print()
    print(f"\n合计缺失: {missing_total}")
    return 1 if missing_total else 0


if __name__ == "__main__":
    sys.exit(main())
