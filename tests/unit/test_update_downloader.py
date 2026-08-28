"""update/downloader.py：download 测试（全 mock，零真实网络）。"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest

from atprobe.infra.update import DownloadCancelled, DownloadError
from atprobe.infra.update.config import UpdateConfig
from atprobe.infra.update.downloader import download

# S-5：入口 URL 白名单校验后，测试用 example.com 需显式加入白名单
_TEST_CFG = UpdateConfig(allowed_hosts=("example.com",))


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


class _FakeOpener:
    """替代 _build_opener 产物的 stub：open() 直接返回预置响应。"""

    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    def open(self, req: object, timeout: float | None = None) -> _FakeResp:
        return self._resp


class _FailingOpener:
    """open() 直接抛预置异常（模拟网络层失败）。"""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def open(self, req: object, timeout: float | None = None) -> _FakeResp:
        raise self._exc


def test_download_writes_file_and_renames(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"x" * 1000
    resp = _FakeResp(data)
    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        result = download(
            "https://example.com/file.zip", tmp_path, filename="update.zip", config=_TEST_CFG
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

    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        download(
            "https://example.com/f.zip",
            tmp_path,
            filename="f.zip",
            progress_cb=cb,
            config=_TEST_CFG,
        )
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

    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        with pytest.raises(DownloadCancelled):
            download(
                "https://example.com/f.zip",
                tmp_path,
                filename="f.zip",
                cancel_token=cancel,
                progress_cb=lambda *_: None,
                config=_TEST_CFG,
            )
    # .part 已清理
    assert not (tmp_path / "f.zip.part").exists()
    assert not (tmp_path / "f.zip").exists()


def test_download_size_mismatch_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"short"
    resp = _FakeResp(data)
    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        with pytest.raises(DownloadError):
            download(
                "https://example.com/f.zip",
                tmp_path,
                filename="f.zip",
                expected_size=999,  # 期望 999，实际 5
                config=_TEST_CFG,
            )
    assert not (tmp_path / "f.zip.part").exists()


def test_download_network_error_cleans_partfile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import urllib.error

    err = urllib.error.URLError("connection reset")
    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FailingOpener(err)):
        with pytest.raises(DownloadError):
            download("https://example.com/f.zip", tmp_path, filename="f.zip", config=_TEST_CFG)
    assert not (tmp_path / "f.zip.part").exists()


def test_download_infers_filename_from_url(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"abc"
    resp = _FakeResp(data)
    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        result = download(
            "https://example.com/path/ATProbe-0.3.0-win64.zip", tmp_path, config=_TEST_CFG
        )
    assert result.path.name == "ATProbe-0.3.0-win64.zip"


# ---------------------------------------------------------------------------
# B9：SHA256 内容校验
# ---------------------------------------------------------------------------
def test_download_sha256_match_succeeds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """正确的 SHA256 → 下载成功。"""
    import hashlib

    data = b"update content here" * 100
    expected_sha = hashlib.sha256(data).hexdigest()
    resp = _FakeResp(data)
    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        result = download(
            "https://example.com/f.zip",
            tmp_path,
            filename="f.zip",
            expected_sha256=expected_sha,
            config=_TEST_CFG,
        )
    assert result.path == tmp_path / "f.zip"
    assert result.size == len(data)


def test_download_sha256_mismatch_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """错误的 SHA256 → 抛 DownloadError，.part 清理。"""
    data = b"actual content"
    resp = _FakeResp(data)
    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        with pytest.raises(DownloadError, match="SHA256"):
            download(
                "https://example.com/f.zip",
                tmp_path,
                filename="f.zip",
                expected_sha256="0" * 64,  # 完全错误的摘要
                config=_TEST_CFG,
            )
    assert not (tmp_path / "f.zip.part").exists()


def test_download_no_sha256_skips_check(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """expected_sha256=None 时跳过校验（向后兼容旧 Release 无哈希）。"""
    data = b"anything"
    resp = _FakeResp(data)
    with patch("atprobe.infra.update.downloader._build_opener", return_value=_FakeOpener(resp)):
        result = download(
            "https://example.com/f.zip",
            tmp_path,
            filename="f.zip",
            expected_sha256=None,
            config=_TEST_CFG,
        )
    assert result.size == len(data)
