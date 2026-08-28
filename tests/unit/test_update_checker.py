"""update/checker.py：fetch_latest + is_newer 测试（全 mock，零真实网络）。"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from atprobe.infra.update import AssetNotFoundError, UpdateCheckError
from atprobe.infra.update.checker import fetch_latest, is_newer, is_prerelease


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


# ---------- B9：SHA256 解析 ----------


def _github_response_with_sha256(tag: str = "v0.3.0", sha: str = "abc123") -> bytes:
    """构造含 <zip>.sha256 asset 的 GitHub 响应。"""
    ver = tag.lstrip("v")
    zip_name = f"ATProbe-{ver}-win64.zip"
    body = {
        "tag_name": tag,
        "body": "## 更新内容",
        "html_url": f"https://github.com/niusulong/ATProbe/releases/tag/{tag}",
        "assets": [
            {
                "name": zip_name,
                "browser_download_url": f"https://example.com/{zip_name}",
                "size": 83558400,
            },
            {
                "name": f"{zip_name}.sha256",
                "browser_download_url": f"https://example.com/{zip_name}.sha256",
                "size": 95,
            },
        ],
    }
    return json.dumps(body).encode("utf-8")


def test_fetch_latest_parses_sha256() -> None:
    """Release 含 <zip>.sha256 asset → ReleaseInfo.sha256 解析出摘要。"""
    release_resp = _FakeResp(_github_response_with_sha256("v0.3.0"))
    # 第二次 urlopen（下载 sha256 文件）返回摘要内容
    sha_content = (
        b"abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789  ATProbe-0.3.0-win64.zip"
    )
    sha_resp = _FakeResp(sha_content)
    responses = iter([release_resp, sha_resp])
    with patch("urllib.request.urlopen", side_effect=lambda *a, **k: next(responses)):
        info = fetch_latest()
    assert info.sha256 == "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"


def test_fetch_latest_no_sha256_asset_returns_none() -> None:
    """Release 无 sha256 asset → ReleaseInfo.sha256 = None（降级为仅 size 校验）。"""
    resp = _FakeResp(_github_response("v0.3.0"))  # 无 sha asset
    with patch("urllib.request.urlopen", return_value=resp):
        info = fetch_latest()
    assert info.sha256 is None


def test_fetch_latest_sha256_download_failure_returns_none() -> None:
    """sha256 asset 存在但下载失败 → sha256 = None（降级，不阻断检查）。"""
    release_resp = _FakeResp(_github_response_with_sha256("v0.3.0"))
    sha_resp = _FakeResp(b"")  # 空内容（无效摘要）
    responses = iter([release_resp, sha_resp])
    with patch("urllib.request.urlopen", side_effect=lambda *a, **k: next(responses)):
        info = fetch_latest()
    assert info.sha256 is None  # 无效摘要降级为 None


# ---------- S-6：minisig 签名资产识别 ----------


def _github_response_with_minisig(tag: str = "v0.3.0", *, with_minisig: bool = True) -> bytes:
    """构造含（或不含）<zip>.minisig asset 的 GitHub 响应。"""
    ver = tag.lstrip("v")
    zip_name = f"ATProbe-{ver}-win64.zip"
    assets: list[dict[str, object]] = [
        {
            "name": zip_name,
            "browser_download_url": f"https://example.com/{zip_name}",
            "size": 83558400,
        }
    ]
    if with_minisig:
        assets.append(
            {
                "name": f"{zip_name}.minisig",
                "browser_download_url": f"https://example.com/{zip_name}.minisig",
                "size": 217,
            }
        )
    body = {
        "tag_name": tag,
        "body": "## 更新内容",
        "html_url": f"https://github.com/niusulong/ATProbe/releases/tag/{tag}",
        "assets": assets,
    }
    return json.dumps(body).encode("utf-8")


def test_fetch_latest_parses_minisig_url() -> None:
    """Release 含 <zip>.minisig asset → ReleaseInfo.minisig_url 取其 URL（不下载）。"""
    resp = _FakeResp(_github_response_with_minisig("v0.3.0", with_minisig=True))
    with patch("urllib.request.urlopen", return_value=resp) as mock_open:
        info = fetch_latest()
    assert info.minisig_url == "https://example.com/ATProbe-0.3.0-win64.zip.minisig"
    # 只取 URL 不触网下载（整个检查流程仅 1 次 API 请求，无 sha256 asset 时无第二次）
    assert mock_open.call_count == 1


def test_fetch_latest_no_minisig_asset_returns_none() -> None:
    """Release 无 .minisig asset（旧版本发布）→ minisig_url = None（过渡兼容）。"""
    resp = _FakeResp(_github_response_with_minisig("v0.3.0", with_minisig=False))
    with patch("urllib.request.urlopen", return_value=resp):
        info = fetch_latest()
    assert info.minisig_url is None


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


# ---------- P3：预发布识别 ----------


@pytest.mark.parametrize(
    "version, expected",
    [
        ("v0.10.0-rc1", True),  # tag 形态
        ("0.10.0-rc1", True),  # 去前缀 version 形态
        ("1.0.0-beta.2", True),  # beta 段
        ("1.0.0-alpha+b1", True),  # 带 build 元数据（+ 后仍识别 prerelease 段）
        ("0.10.0", False),  # 正式版
        ("0.10", False),  # 缺位补 0
        ("v1.2.3", False),  # v 前缀正式版
        ("", False),  # 空串兜底
    ],
)
def test_is_prerelease(version: str, expected: bool) -> None:
    assert is_prerelease(version) is expected


def test_fetch_latest_prerelease_flag() -> None:
    """tag 含 - 后缀 → ReleaseInfo.prerelease=True（供 CLI/GUI 标注）。"""
    resp = _FakeResp(_github_response("v0.10.0-rc1"))
    with patch("urllib.request.urlopen", return_value=resp):
        info = fetch_latest()
    assert info.version == "0.10.0-rc1"
    assert info.prerelease is True


def test_fetch_latest_stable_flag_false() -> None:
    """正式 tag → prerelease=False（默认值路径）。"""
    resp = _FakeResp(_github_response("v0.3.0"))
    with patch("urllib.request.urlopen", return_value=resp):
        info = fetch_latest()
    assert info.version == "0.3.0"
    assert info.prerelease is False
