"""串口配置层单测（F-4 / F-5）."""

from __future__ import annotations

import pytest

from atprobe.infra.serial.config import DataStreamSpec, FrameFormat, Parity


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


class TestDataStreamSpecValidation:
    """F-5：chunk 参数校验（chunk_size<=0 会致 send_data_stream 死循环）."""

    def test_chunk_size_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="chunk_size"):
            DataStreamSpec(data=b"x", chunk_size=0)

    def test_negative_interval_rejected(self) -> None:
        with pytest.raises(ValueError, match="chunk_interval_ms"):
            DataStreamSpec(data=b"x", chunk_interval_ms=-1)

    def test_threshold_lt_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="chunk_threshold"):
            DataStreamSpec(data=b"x", chunk_threshold=0)

    def test_defaults_valid(self) -> None:
        spec = DataStreamSpec(data=b"hello")
        assert spec.chunk_size == 1024
        assert spec.chunk_threshold == 4096
        assert spec.chunk_interval_ms == 50
