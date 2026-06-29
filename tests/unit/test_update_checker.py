"""update/checker.py：fetch_latest + is_newer 测试（全 mock，零真实网络）。"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from atprobe.infra.update import AssetNotFoundError, UpdateCheckError
from atprobe.infra.update.checker import fetch_latest, is_newer


def _github_response(tag: str = "v0.3.0", *, with_asset: bool = True) -> bytes:
    """构造 GitHub releases/latest API 响应 JSON。"""
    ver = tag.lstrip("v")
    asset = {
        "name": f"ATProbe-{ver}-win64.zip",
        "browser_download_url": f"https://example.com/ATProbe-{ver}-win64.zip",
        "size": 83558400,
    }
    body = {
        "tag_name": tag,
        "body": "## 更新内容\n- 修复 X\n- 新增 Y",
        "html_url": f"https://github.com/niusulong/ATProbe/releases/tag/{tag}",
        "assets": [asset] if with_asset else [],
    }
    return json.dumps(body).encode("utf-8")


class _FakeResp:
    """模拟 urllib 的 HTTPResponse。"""

    def __init__(self, data: bytes, status: int = 200) -> None:
        self._buf = BytesIO(data)
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read() if n == -1 else self._buf.read(n)

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> None:
        pass


# ---------- fetch_latest ----------

def test_fetch_latest_parses_release() -> None:
    resp = _FakeResp(_github_response("v0.3.0"))
    with patch("urllib.request.urlopen", return_value=resp):
        info = fetch_latest()
    assert info.version == "0.3.0"
    assert info.tag == "v0.3.0"
    assert info.zip_url == "https://example.com/ATProbe-0.3.0-win64.zip"
    assert info.zip_size == 83558400
    assert "修复 X" in info.release_notes
    assert info.html_url.endswith("v0.3.0")


def test_fetch_latest_missing_asset_raises() -> None:
    resp = _FakeResp(_github_response("v0.3.0", with_asset=False))
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(AssetNotFoundError):
            fetch_latest()


def test_fetch_latest_network_error_converges() -> None:
    import urllib.error

    err = urllib.error.URLError("timed out")
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(UpdateCheckError):
            fetch_latest()


def test_fetch_latest_http_404_converges() -> None:
    import urllib.error

    err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(UpdateCheckError):
            fetch_latest()


def test_fetch_latest_bad_json_converges() -> None:
    resp = _FakeResp(b"not json {{{")
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(UpdateCheckError):
            fetch_latest()


# ---------- is_newer ----------

@pytest.mark.parametrize(
    "remote, local, expected",
    [
        ("0.3.0", "0.2.1", True),
        ("0.2.1", "0.2.1", False),
        ("0.2.0", "0.2.1", False),
        ("0.10.0", "0.9.0", True),  # 防字符串比较 bug
        ("1.0.0", "0.9.9", True),
        ("v0.3.0", "0.2.1", True),  # 带 v 前缀
        ("0.3", "0.2.1", True),  # 缺位补 0
        ("0.0.0", "0.0.0", False),  # 兜底版本
    ],
)
def test_is_newer(remote: str, local: str, expected: bool) -> None:
    assert is_newer(remote, local) is expected
