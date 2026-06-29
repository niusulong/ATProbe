"""update/downloader.py：download 测试（全 mock，零真实网络）。"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest

from atprobe.infra.update import DownloadCancelled, DownloadError
from atprobe.infra.update.downloader import download


class _FakeResp:
    """模拟 HTTPResponse，逐块 read。"""

    def __init__(self, data: bytes, content_length: int | None = None) -> None:
        self._buf = BytesIO(data)
        cl = content_length if content_length is not None else len(data)
        self.headers = {"Content-Length": str(cl)}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read() if n == -1 else self._buf.read(n)

    def geturl(self) -> str:
        return "https://example.com/file.zip"

    def close(self) -> None:
        pass

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_download_writes_file_and_renames(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"x" * 1000
    resp = _FakeResp(data)
    with patch("urllib.request.urlopen", return_value=resp):
        result = download(
            "https://example.com/file.zip", tmp_path, filename="update.zip"
        )
    assert result.path == tmp_path / "update.zip"
    assert result.path.read_bytes() == data
    assert result.size == 1000
    # 临时 .part 已清理（重命名）
    assert not (tmp_path / "update.zip.part").exists()


def test_download_progress_callback(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"y" * 500
    resp = _FakeResp(data)
    calls: list[tuple[int, int]] = []

    def cb(done: int, total: int) -> None:
        calls.append((done, total))

    with patch("urllib.request.urlopen", return_value=resp):
        download("https://example.com/f.zip", tmp_path, filename="f.zip", progress_cb=cb)
    assert calls  # 至少调用一次
    assert calls[-1] == (500, 500)  # 最后一次：全部完成
    assert calls[0][1] == 500  # total 正确


def test_download_cancel_cleans_partfile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"z" * 1000
    resp = _FakeResp(data)
    counter = {"n": 0}

    def cancel() -> bool:
        counter["n"] += 1
        return counter["n"] >= 2  # 第 2 次检查时取消

    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(DownloadCancelled):
            download(
                "https://example.com/f.zip",
                tmp_path,
                filename="f.zip",
                cancel_token=cancel,
                progress_cb=lambda *_: None,
            )
    # .part 已清理
    assert not (tmp_path / "f.zip.part").exists()
    assert not (tmp_path / "f.zip").exists()


def test_download_size_mismatch_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"short"
    resp = _FakeResp(data)
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(DownloadError):
            download(
                "https://example.com/f.zip",
                tmp_path,
                filename="f.zip",
                expected_size=999,  # 期望 999，实际 5
            )
    assert not (tmp_path / "f.zip.part").exists()


def test_download_network_error_cleans_partfile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import urllib.error

    err = urllib.error.URLError("connection reset")
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(DownloadError):
            download("https://example.com/f.zip", tmp_path, filename="f.zip")
    assert not (tmp_path / "f.zip.part").exists()


def test_download_infers_filename_from_url(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"abc"
    resp = _FakeResp(data)
    with patch("urllib.request.urlopen", return_value=resp):
        result = download("https://example.com/path/ATProbe-0.3.0-win64.zip", tmp_path)
    assert result.path.name == "ATProbe-0.3.0-win64.zip"
