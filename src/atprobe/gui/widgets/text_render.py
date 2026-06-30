"""RX/TX 文本渲染共享工具。

提供「按换行切行 + 保留空行」的逻辑，供手动调试页和监控页复用，
确保两处文本模式行为一致。

渲染规则（非 HEX 文本模式）：
    按实际换行符显示——一个 \\n 换一行，连续 \\n 之间的空行也保留，
    忠实反映模块返回的换行结构。\\r 视为行尾回车（rstrip 去除，避免
    光标回头造成显示错乱）。
"""

from __future__ import annotations


def split_lines_preserving_blanks(text: str) -> list[str]:
    """按 \\n 切行，rstrip 行尾 \\r，保留空行（忠实反映换行符数量）.

    与 text.split("\\n") + 过滤空行的区别：
        - 保留空行（连续 \\n 之间的空行如实保留，一个 \\n 一行）
        - 行尾的 \\r 去掉（\\r 是回车，\\n 才是换行；\\r\\n 作为单个换行）
        - 末尾 split 产生的空串不返回（避免末尾 \\n 凭空多一个空行）

    例：
        "A\\r\\n\\r\\nB\\r\\n" → ["A", "", "B"]  （A 和 B 之间保留一个空行）
        "A\\r\\nB\\r\\n"       → ["A", "B"]
        "AT\\r\\r\\nOK\\r\\n"  → ["AT", "OK"]    （回显的 \\r 被行尾 rstrip 去除）
    """
    parts = text.split("\n")
    lines: list[str] = []
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        stripped = part.rstrip("\r")
        if is_last:
            # 最后一段可能是不完整行（无 \\n）；仅当有内容时保留
            # （纯空串是末尾 \\n 造成的，不返回）
            if stripped:
                lines.append(stripped)
        else:
            # 完整行（以 \\n 结尾）：保留（含空行，忠实反映换行符数量）
            lines.append(stripped)
    return lines
