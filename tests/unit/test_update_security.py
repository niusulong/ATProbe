"""更新链路安全三合一测试（S-5 URL 白名单/重定向防降级、S-6 minisign 验签框架）。

- S-5：_validate_url（scheme/host 白名单）、_SafeRedirectHandler（30x 目标复检）、
  download() 入口前置校验（触网前拒绝）。
- S-6：verifier 的 minisign 格式解析/验签（pynacl 测试密钥对手拼 minisign 文件，
  不依赖 minisign 可执行文件）、public_key_path 定位（有/无）。
"""

from __future__ import annotations

import base64
import contextlib
import email.message
import hashlib
import io
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.response import addinfourl

import pytest
from nacl.signing import SigningKey

from atprobe.infra.update import DownloadError, verifier
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig
from atprobe.infra.update.downloader import (
    _SafeRedirectHandler,
    _validate_url,
    download,
)
from atprobe.infra.update.verifier import (
    PUBLIC_KEY_FILENAME,
    parse_minisign_key,
    parse_minisign_sig,
    public_key_path,
    verify_minisign,
)


# ---------------------------------------------------------------------------
# S-5：_validate_url
# ---------------------------------------------------------------------------
def test_validate_url_rejects_http() -> None:
    """http 明文地址拒绝（防降级/中间人替换）。"""
    with pytest.raises(DownloadError, match="https"):
        _validate_url("http://github.com/ATProbe-0.3.0-win64.zip", DEFAULT_CONFIG)


def test_validate_url_rejects_other_schemes() -> None:
    """ftp/file 等非 https scheme 一律拒绝。"""
    for url in ("ftp://github.com/a.zip", "file:///C:/evil.zip", "https:///nohost.zip"):
        with pytest.raises(DownloadError):
            _validate_url(url, DEFAULT_CONFIG)


def test_validate_url_accepts_builtin_whitelist() -> None:
    """内置白名单主机的 https 地址放行。"""
    for host in DEFAULT_CONFIG.effective_allowed_hosts():
        url = f"https://{host}/ATProbe-0.3.0-win64.zip"
        assert _validate_url(url, DEFAULT_CONFIG) == url


def test_validate_url_rejects_out_of_whitelist_host() -> None:
    """白名单外主机拒绝（即使 https）。"""
    with pytest.raises(DownloadError, match="白名单"):
        _validate_url("https://evil.example.com/a.zip", DEFAULT_CONFIG)


def test_validate_url_user_appended_host_passes() -> None:
    """用户经 allowed_hosts 追加的镜像主机放行。"""
    cfg = UpdateConfig(allowed_hosts=("mirror.example.com",))
    url = "https://mirror.example.com/a.zip"
    assert _validate_url(url, cfg) == url
    # 未追加的配置仍拒
    with pytest.raises(DownloadError):
        _validate_url(url, DEFAULT_CONFIG)


def test_yaml_update_allowed_hosts_reaches_downloader_whitelist() -> None:
    """批 5 T8 特征测试：atprobe.yaml 配 update.allowed_hosts → 经
    AppConfig.update_config() 接线 → downloader S-5 白名单对追加主机生效。"""
    from atprobe.infra.config.appconfig import load_app_config

    yaml_text = "update:\n  allowed_hosts:\n    - mirror.example.com\n"
    cfg = load_app_config(yaml_text).update_config()
    url = "https://mirror.example.com/ATProbe-0.3.0-win64.zip"
    assert _validate_url(url, cfg) == url  # 用户镜像主机放行
    # 内置 GitHub 白名单不受影响（合并而非替换）
    assert _validate_url("https://github.com/a.zip", cfg) == "https://github.com/a.zip"
    # 未配置的第三方主机仍拒（追加不等于放开一切）
    with pytest.raises(DownloadError, match="白名单"):
        _validate_url("https://evil.example.com/a.zip", cfg)


def test_validate_url_hostname_excludes_port() -> None:
    """白名单按 hostname 判断（不含端口）——带端口的白名单主机放行。"""
    url = "https://github.com:8443/a.zip"
    assert _validate_url(url, DEFAULT_CONFIG) == url


def test_validate_url_empty_host_rejected() -> None:
    """无主机（https:///path）拒绝。"""
    with pytest.raises(DownloadError):
        _validate_url("https:///path.zip", DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# S-5：download() 入口前置校验（触网前拒绝）
# ---------------------------------------------------------------------------
def test_download_rejects_http_before_network(tmp_path: Path) -> None:
    """入口即拒：http 地址在触网前抛 DownloadError（opener 不被调用）。"""
    with patch("atprobe.infra.update.downloader._build_opener") as build:
        with pytest.raises(DownloadError, match="https"):
            download("http://github.com/a.zip", tmp_path, filename="a.zip")
    build.assert_not_called()


def test_download_rejects_non_whitelisted_host_before_network(tmp_path: Path) -> None:
    """入口即拒：白名单外主机在触网前抛 DownloadError，无残留 .part。"""
    with patch("atprobe.infra.update.downloader._build_opener") as build:
        with pytest.raises(DownloadError, match="白名单"):
            download("https://evil.example.com/a.zip", tmp_path, filename="a.zip")
    build.assert_not_called()
    assert not (tmp_path / "a.zip").exists()


# ---------------------------------------------------------------------------
# S-5：_SafeRedirectHandler（重定向目标复检）
# ---------------------------------------------------------------------------
def _redirect_call(handler: _SafeRedirectHandler, newurl: str) -> None:
    """以标准 302 GET 参数直接调 redirect_request。"""
    req = urllib.request.Request("https://github.com/a.zip")
    headers = email.message.Message()
    handler.redirect_request(req, io.BytesIO(b""), 302, "Found", headers, newurl)


def test_redirect_handler_rejects_http_downgrade() -> None:
    """重定向目标降级到 http → 抛 DownloadError（异常不被 urllib 包装）。"""
    handler = _SafeRedirectHandler(DEFAULT_CONFIG)
    with pytest.raises(DownloadError, match="https"):
        _redirect_call(handler, "http://github.com/a.zip")


def test_redirect_handler_rejects_out_of_whitelist_host() -> None:
    """重定向跳到白名单外主机 → 抛 DownloadError。"""
    handler = _SafeRedirectHandler(DEFAULT_CONFIG)
    with pytest.raises(DownloadError, match="白名单"):
        _redirect_call(handler, "https://evil.example.com/a.zip")


def test_redirect_handler_allows_whitelisted_https() -> None:
    """重定向目标为白名单内 https → 走父类行为（返回新 Request，非 None）。"""
    handler = _SafeRedirectHandler(DEFAULT_CONFIG)
    req = urllib.request.Request("https://github.com/a.zip")
    headers = email.message.Message()
    result = handler.redirect_request(
        req, io.BytesIO(b""), 302, "Found", headers, "https://objects.githubusercontent.com/a.zip"
    )
    assert result is not None
    assert result.get_full_url() == "https://objects.githubusercontent.com/a.zip"


def test_redirect_handler_honors_user_appended_hosts() -> None:
    """用户追加的镜像主机对重定向目标同样生效。"""
    handler = _SafeRedirectHandler(UpdateConfig(allowed_hosts=("mirror.example.com",)))
    _redirect_call(handler, "https://mirror.example.com/a.zip")  # 不抛即通过


def test_redirect_downgrade_propagates_through_opener() -> None:
    """端到端：真实 opener 链路上 30x→http 的 DownloadError 原样传播（不被包成 HTTPError）。"""
    handler = _RedirectToHTTPSHandler("http://evil.example.com/a.zip")
    opener = urllib.request.build_opener(handler, _SafeRedirectHandler(DEFAULT_CONFIG))
    with pytest.raises(DownloadError, match="https"):
        opener.open("https://github.com/a.zip")


def test_redirect_error_propagates_via_http_error_302() -> None:
    """异常路径核实：DownloadError 从 http_error_302 内的 redirect_request 直接冒出。"""
    handler = _SafeRedirectHandler(DEFAULT_CONFIG)
    req = urllib.request.Request("https://github.com/a.zip")
    headers = email.message.Message()
    headers["Location"] = "http://evil.example.com/a.zip"
    with pytest.raises(DownloadError):
        handler.http_error_302(req, io.BytesIO(b""), 302, "Found", headers)


class _RedirectToHTTPSHandler(urllib.request.HTTPSHandler):
    """把一切 https 请求替换为 302 响应（Location 指向注入目标）的桩。"""

    def __init__(self, location: str) -> None:
        super().__init__()
        self._location = location

    def https_open(self, req: urllib.request.Request) -> addinfourl:
        headers = email.message.Message()
        headers["Location"] = self._location
        resp = addinfourl(io.BytesIO(b""), headers, req.full_url, code=302)
        # addinfourl 不带 .msg（真 HTTPResponse 才有），http_response 链会读它
        resp.msg = "Found"
        return resp


# ---------------------------------------------------------------------------
# S-6：verifier——minisign 格式解析
# ---------------------------------------------------------------------------
_ED = b"Ed"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _write_minisign_files(
    tmp_path: Path,
    content: bytes = b"fake zip payload" * 8,
    *,
    prehash: bool = False,
) -> tuple[Path, Path, Path]:
    """用 pynacl 测试密钥对手拼出 minisign 三件套（zip / .minisig / .pub）。

    格式对齐 minisign 0.12：公钥 42 字节（Ed||key_id||pk，恒 Ed），签名 74 字节
    （alg||key_id||sig，alg=Ed 为 legacy、ED 为默认 prehash——签文件内容的
    BLAKE2b-512 无键摘要），签名文件 4 行（untrusted/sig/trusted/注释签名）。
    """
    sk = SigningKey.generate()
    key_id = bytes(range(8))
    alg = b"ED" if prehash else _ED
    payload = hashlib.blake2b(content, digest_size=64).digest() if prehash else content
    pub_blob = _ED + key_id + bytes(sk.verify_key)
    sig_blob = alg + key_id + sk.sign(payload).signature

    zip_path = tmp_path / "ATProbe-9.9.9-win64.zip"
    zip_path.write_bytes(content)
    sig_path = tmp_path / "ATProbe-9.9.9-win64.zip.minisig"
    sig_path.write_text(
        "untrusted comment: signature from test key\n"
        f"{_b64(sig_blob)}\n"
        "trusted comment: ATProbe 9.9.9\n"
        f"{_b64(bytes(64))}\n",
        encoding="utf-8",
    )
    pub_path = tmp_path / PUBLIC_KEY_FILENAME
    pub_path.write_text(
        f"untrusted comment: minisign public key\n{_b64(pub_blob)}\n",
        encoding="utf-8",
    )
    return zip_path, sig_path, pub_path


def test_parse_minisign_key_ok() -> None:
    """42 字节 Ed 公钥 → 返回 32 字节 pk。"""
    sk = SigningKey.generate()
    blob = _ED + bytes(8) + bytes(sk.verify_key)
    assert parse_minisign_key(_b64(blob)) == bytes(sk.verify_key)


def test_parse_minisign_key_bad_base64() -> None:
    with pytest.raises(ValueError, match="base64"):
        parse_minisign_key("!!!not-base64!!!")


def test_parse_minisign_key_wrong_length() -> None:
    with pytest.raises(ValueError, match="长度"):
        parse_minisign_key(_b64(_ED + bytes(8)))  # 缺 pk，仅 10 字节


def test_parse_minisign_key_wrong_algorithm() -> None:
    """prehash 算法（ED，签 blake2 摘要）不在验证范围 → 拒。"""
    blob = b"ED" + bytes(8) + bytes(32)
    with pytest.raises(ValueError, match="算法"):
        parse_minisign_key(_b64(blob))


def test_parse_minisign_sig_ok() -> None:
    sk = SigningKey.generate()
    sig64 = sk.sign(b"m").signature
    key_id, sig, alg = parse_minisign_sig(_b64(_ED + bytes(8) + sig64))
    assert key_id == bytes(8)
    assert sig == sig64
    assert alg == b"Ed"


def test_parse_minisign_sig_prehash_alg_accepted() -> None:
    sk = SigningKey.generate()
    sig64 = sk.sign(b"m").signature
    key_id, sig, alg = parse_minisign_sig(_b64(b"ED" + bytes(8) + sig64))
    assert (key_id, sig, alg) == (bytes(8), sig64, b"ED")


def test_parse_minisign_sig_unknown_alg_rejected() -> None:
    with pytest.raises(ValueError, match="算法"):
        parse_minisign_sig(_b64(b"XX" + bytes(8) + bytes(64)))


def test_parse_minisign_sig_wrong_length() -> None:
    with pytest.raises(ValueError, match="长度"):
        parse_minisign_sig(_b64(_ED + bytes(8) + bytes(10)))


# ---------------------------------------------------------------------------
# S-6：verifier——verify_minisign
# ---------------------------------------------------------------------------
def test_verify_minisign_accepts_valid_signature(tmp_path: Path) -> None:
    zip_path, sig_path, pub_path = _write_minisign_files(tmp_path)
    assert verify_minisign(zip_path, sig_path, pub_path) is True


def test_verify_minisign_accepts_prehash_signature(tmp_path: Path) -> None:
    """ED（minisign 默认 prehash）签名：对 blake2b-512 摘要验签通过（审查 M2 修复）."""
    zip_path, sig_path, pub_path = _write_minisign_files(tmp_path, prehash=True)
    assert verify_minisign(zip_path, sig_path, pub_path) is True


def test_verify_prehash_tampered_content_fails(tmp_path: Path) -> None:
    zip_path, sig_path, pub_path = _write_minisign_files(tmp_path, prehash=True)
    zip_path.write_bytes(b"tampered payload")
    assert verify_minisign(zip_path, sig_path, pub_path) is False


def test_verify_minisign_rejects_tampered_zip(tmp_path: Path) -> None:
    """zip 篡改一字节 → 验签失败。"""
    zip_path, sig_path, pub_path = _write_minisign_files(tmp_path)
    data = bytearray(zip_path.read_bytes())
    data[0] ^= 0xFF
    zip_path.write_bytes(bytes(data))
    assert verify_minisign(zip_path, sig_path, pub_path) is False


def test_verify_minisign_rejects_wrong_key(tmp_path: Path) -> None:
    """签名有效但公钥不匹配（另一把钥匙）→ False。"""
    zip_path, sig_path, _ = _write_minisign_files(tmp_path)
    other = SigningKey.generate()
    other_pub = tmp_path / "other.pub"
    other_pub.write_text(
        f"c\n{_b64(_ED + bytes(8) + bytes(other.verify_key))}\n",
        encoding="utf-8",
    )
    assert verify_minisign(zip_path, sig_path, other_pub) is False


def test_verify_minisign_rejects_malformed_pub(tmp_path: Path) -> None:
    """公钥格式坏（长度错）→ False（verify 不抛业务异常）。"""
    zip_path, sig_path, _ = _write_minisign_files(tmp_path)
    bad_pub = tmp_path / "bad.pub"
    bad_pub.write_text(f"c\n{_b64(_ED + bytes(4))}\n", encoding="utf-8")
    assert verify_minisign(zip_path, sig_path, bad_pub) is False


def test_verify_minisign_rejects_malformed_sig(tmp_path: Path) -> None:
    """签名文件格式坏（缺 base64 行）→ False。"""
    zip_path, _, pub_path = _write_minisign_files(tmp_path)
    bad_sig = tmp_path / "bad.minisig"
    bad_sig.write_text("only one line\n", encoding="utf-8")
    assert verify_minisign(zip_path, bad_sig, pub_path) is False


def test_verify_minisign_rejects_missing_files(tmp_path: Path) -> None:
    """文件不存在（OSError）→ False 而非抛异常。"""
    zip_path, sig_path, pub_path = _write_minisign_files(tmp_path)
    assert verify_minisign(tmp_path / "nope.zip", sig_path, pub_path) is False
    assert verify_minisign(zip_path, tmp_path / "nope.minisig", pub_path) is False


# ---------------------------------------------------------------------------
# S-6：verifier——public_key_path（过渡期定位）
# ---------------------------------------------------------------------------
def test_public_key_path_none_when_not_shipped() -> None:
    """公钥未内置（当前过渡期）→ None（不可用而非硬失败）。"""
    assert public_key_path() is None


def test_public_key_path_found_in_resources_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """资源包内存在公钥 → 返回其路径（stub importlib.resources 定位口径）。"""
    key = tmp_path / PUBLIC_KEY_FILENAME
    key.write_text("k", encoding="utf-8")

    @contextlib.contextmanager
    def fake_as_file(traversable: object) -> Iterator[Path]:
        yield Path(str(traversable))

    stub = SimpleNamespace(files=lambda pkg: tmp_path, as_file=fake_as_file)
    monkeypatch.setattr(verifier, "resources", stub)
    assert public_key_path() == key


# ---------------------------------------------------------------------------
# S-6：verifier + installer 集成视角（真实 zip 字节验签）
# ---------------------------------------------------------------------------
def test_verify_minisign_against_real_zipfile(tmp_path: Path) -> None:
    """对真实 zipfile 产物（而非任意字节）验签通过——对齐实际使用形态。"""
    sk = SigningKey.generate()
    zip_path = tmp_path / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe-0.3.0/ATProbe.exe", b"PE")
        z.writestr("ATProbe-0.3.0/_internal/x.dll", b"dll")
    content = zip_path.read_bytes()
    sig_path = tmp_path / "app.zip.minisig"
    sig_path.write_text(
        f"c\n{_b64(_ED + bytes(8) + sk.sign(content).signature)}\nt\n{_b64(bytes(64))}\n",
        encoding="utf-8",
    )
    pub_path = tmp_path / PUBLIC_KEY_FILENAME
    pub_path.write_text(f"c\n{_b64(_ED + bytes(8) + bytes(sk.verify_key))}\n", encoding="utf-8")
    assert verify_minisign(zip_path, sig_path, pub_path) is True


def test_download_still_works_with_appended_host(tmp_path: Path) -> None:
    """S-5 不破坏正常路径：白名单内 https + mock opener 正常下载（追加主机）。"""
    cfg = UpdateConfig(allowed_hosts=("example.com",))
    data = b"payload"

    class _Resp:
        def __init__(self, payload: bytes) -> None:
            self._buf = io.BytesIO(payload)
            self.headers = {"Content-Length": str(len(payload))}

        def read(self, n: int = -1) -> bytes:
            return self._buf.read() if n == -1 else self._buf.read(n)

        def close(self) -> None:
            pass

    opener = MagicMock()
    opener.open.return_value = _Resp(data)
    with patch("atprobe.infra.update.downloader._build_opener", return_value=opener):
        result = download("https://example.com/f.zip", tmp_path, filename="f.zip", config=cfg)
    assert result.path == tmp_path / "f.zip"
    assert result.size == len(data)
