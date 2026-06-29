"""text_render：行末换行符转义逻辑测试.

用 N58 真实回包字节流（回显行只有 \\r，响应行完整 \\r\\n）验证转义正确性。
"""

from __future__ import annotations

from atprobe.gui.widgets.text_render import escape_control_chars, split_lines_with_endings


class TestEscapeControlChars:
    def test_cr_only(self) -> None:
        """回显行只有 \\r（N58 吞 LF 的回显）→ 转义成可见 \\r."""
        assert escape_control_chars("AT\r") == "AT\\r"

    def test_crlf(self) -> None:
        """响应行 \\r\\n → 转义成可见 \\r\\n."""
        assert escape_control_chars("+CSQ: 1\r\n") == "+CSQ: 1\\r\\n"

    def test_no_control_chars(self) -> None:
        assert escape_control_chars("OK") == "OK"

    def test_multiple(self) -> None:
        """AT\\r\\r\\n（回显 CR + 响应分隔 CRLF）→ 全部转义."""
        assert escape_control_chars("AT\r\r\n") == "AT\\r\\r\\n"


class TestSplitLinesWithEndings:
    def test_n58_multiline_response(self) -> None:
        """N58 真实回包 b'AT+CSQ\\r\\r\\n+CSQ: 12,99\\r\\nOK\\r\\n'.

        split('\\n') → ['AT+CSQ\\r\\r', '+CSQ: 12,99\\r', 'OK\\r', '']
        - 'AT+CSQ\\r\\r' → 'AT+CSQ\\\\r\\\\r' + '\\\\n' = 'AT+CSQ\\\\r\\\\r\\\\n'
          （回显 CR + 响应分隔 CRLF，全部转义，能看出有两个 \\r）
        - '+CSQ: 12,99\\r' → '+CSQ: 12,99\\\\r\\\\n'
        - 'OK\\r' → 'OK\\\\r\\\\n'
        - '' 尾部空串跳过
        """
        text = "AT+CSQ\r\r\n+CSQ: 12,99\r\nOK\r\n"
        lines = split_lines_with_endings(text)
        assert lines == [
            "AT+CSQ\\r\\r\\n",
            "+CSQ: 12,99\\r\\n",
            "OK\\r\\n",
        ]

    def test_cr_only_echo(self) -> None:
        """仅 CR 结束的回显行 b'AT\\r\\r\\n' → 'AT\\\\r\\\\r\\\\n'."""
        text = "AT\r\r\n"
        lines = split_lines_with_endings(text)
        assert lines == ["AT\\r\\r\\n"]

    def test_partial_line_no_newline(self) -> None:
        """末尾未到换行的残留片段 → 转义其中的 \\r，不补 \\n."""
        text = "AT\r"  # 无 \\n
        lines = split_lines_with_endings(text)
        assert lines == ["AT\\r"]

    def test_empty_input(self) -> None:
        assert split_lines_with_endings("") == []

    def test_trailing_empty_skipped(self) -> None:
        """以 \\n 结尾产生的尾部空串应跳过（如 'OK\\r\\n' → ['OK\\\\r\\\\n'])."""
        text = "OK\r\n"
        lines = split_lines_with_endings(text)
        assert lines == ["OK\\r\\n"]
