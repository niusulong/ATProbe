"""F-16：read_suite_meta 对非 UTF-8 文件的容错（list 命令不裸崩）."""

from __future__ import annotations

from pathlib import Path

from atprobe.domain.suite.collect import read_suite_meta


def test_gbk_encoded_suite_returns_empty_meta(tmp_path: Path) -> None:
    p = tmp_path / "suite-gbk.yaml"
    p.write_bytes("名称: 中文套件\n".encode("gbk"))
    meta = read_suite_meta(p)
    assert meta.name is None


def test_utf8_suite_still_parsed(tmp_path: Path) -> None:
    p = tmp_path / "suite-ok.yaml"
    p.write_text("name: 正常套件\ncases: []\n", encoding="utf-8")
    meta = read_suite_meta(p)
    assert meta.name == "正常套件"
