"""text_render：按实际换行符切行（保留空行）逻辑测试.

验证：非 HEX 文本模式按 \\n 换行，保留空行（忠实反映换行符数量），
行尾 \\r 去除（避免回车造成显示错乱），不显示任何转义字符。
"""

from __future__ import annotations

from atprobe.gui.widgets.text_render import split_lines_preserving_blanks


class TestSplitLinesPreservingBlanks:
    def test_n58_multiline_response(self) -> None:
        """N58 真实回包 b'AT+CSQ\\r\\r\\n+CSQ: 12,99\\r\\nOK\\r\\n'.

        干净换行：回显行、响应行、结果行各占一行，无转义字符。
        """
        text = "AT+CSQ\r\r\n+CSQ: 12,99\r\nOK\r\n"
        assert split_lines_preserving_blanks(text) == [
            "AT+CSQ",
            "+CSQ: 12,99",
            "OK",
        ]

    def test_blank_line_preserved(self) -> None:
        """响应间的空行应保留（两个 \\r\\n 中间有空行）.

        用户需求：一个 \\r\\n 显示一行，两个显示两行（含空行）。
        """
        text = "+CSQ: 12,99\r\n\r\nOK\r\n"
        assert split_lines_preserving_blanks(text) == ["+CSQ: 12,99", "", "OK"]

    def test_no_escape_chars(self) -> None:
        """结果不含任何转义字样 \\r / \\n（干净文本）."""
        text = "AT\r\r\nOK\r\n"
        lines = split_lines_preserving_blanks(text)
        for ln in lines:
            assert "\\r" not in ln
            assert "\\n" not in ln

    def test_partial_line_no_newline(self) -> None:
        """末尾未到换行的残留片段 → 保留（rstrip 行尾 \\r）."""
        text = "AT\r"  # 无 \n
        assert split_lines_preserving_blanks(text) == ["AT"]

    def test_empty_input(self) -> None:
        assert split_lines_preserving_blanks("") == []

    def test_trailing_newline_no_extra_blank(self) -> None:
        """以 \\n 结尾不产生多余尾部空行（'OK\\r\\n' → ['OK']）."""
        assert split_lines_preserving_blanks("OK\r\n") == ["OK"]

    def test_multiple_blank_lines(self) -> None:
        """连续多个空行全部保留（忠实反映换行符数量）."""
        text = "A\r\n\r\n\r\nB\r\n"
        assert split_lines_preserving_blanks(text) == ["A", "", "", "B"]
