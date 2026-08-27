"""串口配置层单测（F-4 / F-5）."""

from __future__ import annotations

import pytest

from atprobe.infra.serial.config import FrameFormat, Parity


class TestFrameFormat15Stopbits:
    """F-4：1.5 停止位可解析（旧实现 len!=3 早退使分支不可达）."""

    def test_parse_8n15(self) -> None:
        ff = FrameFormat.parse("8N1.5")
        assert ff.databits == 8
        assert ff.parity is Parity.NONE
        assert ff.stopbits == 1.5

    def test_roundtrip_with_str(self) -> None:
        ff = FrameFormat(databits=7, parity=Parity.EVEN, stopbits=1.5)
        assert str(ff) == "7E1.5"
        assert FrameFormat.parse(str(ff)) == ff

    def test_legacy_3char_still_works(self) -> None:
        assert FrameFormat.parse("8N1").stopbits == 1.0
        assert FrameFormat.parse("7O2").stopbits == 2.0

    def test_invalid_rejected(self) -> None:
        with pytest.raises(ValueError, match="帧格式"):
            FrameFormat.parse("8N3")
        with pytest.raises(ValueError, match="帧格式"):
            FrameFormat.parse("9N1")
