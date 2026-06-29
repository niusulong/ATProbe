"""RX/TX 文本渲染共享工具。

提供「按换行切行 + 行内 CR/LF 转义成可见文本」的逻辑，供手动调试页和监控页
复用，确保两处文本模式行为一致。

转义规则（非 HEX 文本模式）：
    把不可见的 \\r / \\n 转义成可见的 \\r / \\n 文本，让用户直观看到每行的
    实际换行符构成——N58 回显行只有 \\r（吞掉 LF），响应行是完整 \\r\\n，
    转义后能清晰区分。
"""

from __future__ import annotations


def escape_control_chars(s: str) -> str:
    """把字符串里的 \\r / \\n 转义成可见的 \\r / \\n 文本.

    例：
        "AT\\r"        → "AT\\\\r"
        "+CSQ: 1\\r\\n" → "+CSQ: 1\\\\r\\\\n"
    其它控制字符保持原样（用 errors=replace 在上游已兜底）。
    """
    return s.replace("\r", "\\r").replace("\n", "\\n")


def split_lines_with_endings(text: str) -> list[str]:
    """按 \\n 切行，每行末尾的换行符转义成可见文本.

    与单纯的 text.split("\\n") 区别：保留每行对应的换行符构成并转义显示，
    便于用户看到「这行以 \\r 结束还是 \\r\\n」。

    - 以 \\n 结尾的完整行：part 中残留的 \\r 转义为 \\\\r，再补 \\n 的可见形式 \\\\n
    - 末尾无 \\n 的残留片段：其中的 \\r 也转义（不补 \\n）

    跳过完全为空的行（split 产生的尾部空串），但保留含 \\r 的「空内容行」
    （它是真实的换行，需转义显示）。
    """
    parts = text.split("\n")
    lines: list[str] = []
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        if is_last:
            # 最后一段可能是不完整行（无 \\n），转义其中残留的 \\r
            escaped = escape_control_chars(part)
            if escaped:  # 跳过尾部空串
                lines.append(escaped)
        else:
            # 完整行：part 末尾原本跟着 \\n（已被 split 消费），前面可能有 \\r
            # 转义 part（含其中的 \\r），再补上 \\n 的可见形式
            escaped = escape_control_chars(part) + "\\n"
            lines.append(escaped)
    return lines
