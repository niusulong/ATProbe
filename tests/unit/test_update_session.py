"""update/session.py：UpdateSession 统一编排测试（mock downloader，零真实网络）。

覆盖 D-3（CLI/GUI 下载编排单点）与 S-6 接线（minisign 签名过渡三态）：
- 校验参数：size=0→None / 文件名走模板 / progress+cancel 透传；
- 签名三态：①minisig+公钥可用（真 minisign 三件套）②minisig+公钥缺失 ③无 minisig；
- 旧 zip 残留清理（下载前幂等 unlink）；
- GUI _download_worker 迁移（经 UpdateSession，信号投递）。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from nacl.signing import SigningKey

from atprobe.infra.update import DownloadError
from atprobe.infra.update.checker import ReleaseInfo
from atprobe.infra.update.config import UpdateConfig
from atprobe.infra.update.downloader import DownloadResult
from atprobe.infra.update.session import UpdateSession
from atprobe.infra.update.verifier import verify_minisign

_ZIP_URL = "https://github.com/niusulong/ATProbe/releases/download/v0.3.0/ATProbe-0.3.0-win64.zip"
_SIG_URL = _ZIP_URL + ".minisig"
_ZIP_NAME = "ATProbe-0.3.0-win64.zip"


def _info(**overrides: Any) -> ReleaseInfo:
    defaults: dict[str, Any] = {
        "version": "0.3.0",
        "tag": "v0.3.0",
        "zip_url": _ZIP_URL,
        "zip_size": 83558400,
        "release_notes": "notes",
        "html_url": "https://github.com/niusulong/ATProbe/releases/tag/v0.3.0",
        "sha256": "a" * 64,
        "minisig_url": None,
    }
    defaults.update(overrides)
    return ReleaseInfo(**defaults)


class _FakeDownloader:
    """替代 session 引用的 downloader.download：按 URL→内容落盘并记录调用。"""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, dest_dir: Path, **kwargs: Any) -> DownloadResult:
        record = {"url": url, "dest_dir": dest_dir, **kwargs}
        self.calls.append(record)
        if url not in self._files:
            raise DownloadError(f"下载失败（HTTP 404）：{url}")
        content = self._files[url]
        name = kwargs.get("filename") or "download.bin"
        path = dest_dir / name
        path.write_bytes(content)
        return DownloadResult(path=path, size=len(content))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _minisign_trio(content: bytes, tmp_path: Path) -> tuple[bytes, bytes, Path]:
    """pynacl 拼真 minisign 三件套：返回 (zip 内容, .minisig 内容, .pub 路径)。

    格式对齐 minisign 0.12（legacy Ed：对文件原始字节签名），
    与 test_update_security._write_minisign_files 同构。
    """
    sk = SigningKey.generate()
    key_id = bytes(range(8))
    pub_blob = b"Ed" + key_id + bytes(sk.verify_key)
    sig_blob = b"Ed" + key_id + sk.sign(content).signature
    pub_path = tmp_path / "atprobe-update.pub"
    pub_path.write_text(f"untrusted comment\n{_b64(pub_blob)}\n", encoding="utf-8")
    sig_text = f"untrusted comment\n{_b64(sig_blob)}\ntrusted comment: test\n{_b64(bytes(64))}\n"
    return content, sig_text.encode("utf-8"), pub_path


# ---------- 校验参数（D-3 策略单点）----------


def test_size_zero_passes_expected_size_none(tmp_path: Path) -> None:
    """zip_size=0（Release JSON 异常）→ expected_size=None，不误报大小不符。"""
    fake = _FakeDownloader({_ZIP_URL: b"zip payload"})
    with patch("atprobe.infra.update.session.download", fake):
        result = UpdateSession(dest_dir=tmp_path).download(_info(zip_size=0))
    assert fake.calls[0]["expected_size"] is None
    assert result.path == tmp_path / _ZIP_NAME


def test_filename_from_config_template(tmp_path: Path) -> None:
    """文件名 = config.asset_name_for(version)（消 GUI 硬编码 P1-9）。"""
    fake = _FakeDownloader({_ZIP_URL: b"zip payload"})
    session = UpdateSession(
        config=UpdateConfig(asset_name_template="atp-{version}.zip"), dest_dir=tmp_path
    )
    with patch("atprobe.infra.update.session.download", fake):
        session.download(_info())
    assert fake.calls[0]["filename"] == "atp-0.3.0.zip"
    assert fake.calls[0]["dest_dir"] == tmp_path


def test_progress_and_cancel_passthrough(tmp_path: Path) -> None:
    """progress_cb/cancel_token 原样透传给 downloader。"""
    fake = _FakeDownloader({_ZIP_URL: b"zip payload"})
    progress = MagicMock()
    cancel = MagicMock()
    with patch("atprobe.infra.update.session.download", fake):
        UpdateSession(dest_dir=tmp_path).download(
            _info(), progress_cb=progress, cancel_token=cancel
        )
    assert fake.calls[0]["progress_cb"] is progress
    assert fake.calls[0]["cancel_token"] is cancel
    assert fake.calls[0]["expected_size"] == 83558400
    assert fake.calls[0]["expected_sha256"] == "a" * 64


# ---------- S-6 签名过渡三态 ----------


def test_sig_state1_valid_signature_downloads_and_verifies(tmp_path: Path) -> None:
    """①minisig_url + 公钥可用：sig 经 downloader 下载 + verify_minisign 通过。"""
    payload = b"real zip bytes" * 16
    zip_content, sig_content, pub_path = _minisign_trio(payload, tmp_path)
    fake = _FakeDownloader({_ZIP_URL: zip_content, _SIG_URL: sig_content})
    with (
        patch("atprobe.infra.update.session.download", fake),
        patch("atprobe.infra.update.session.public_key_path", return_value=pub_path),
        patch(
            "atprobe.infra.update.session.verify_minisign",
            wraps=verify_minisign,
        ) as spy_verify,
    ):
        result = UpdateSession(dest_dir=tmp_path).download(_info(minisig_url=_SIG_URL))
    assert result.path == tmp_path / _ZIP_NAME
    assert result.size == len(payload)
    # 验签以 (zip, sig, pubkey) 被调用且真实验证通过
    assert spy_verify.call_count == 1
    assert spy_verify.call_args.args == (
        tmp_path / _ZIP_NAME,
        tmp_path / (_ZIP_NAME + ".minisig"),
        pub_path,
    )
    # sig 走同一 downloader（白名单复用），文件名 = zip 名 + .minisig，不透传进度/取消
    assert len(fake.calls) == 2
    assert fake.calls[1]["url"] == _SIG_URL
    assert fake.calls[1]["filename"] == _ZIP_NAME + ".minisig"
    assert "progress_cb" not in fake.calls[1]
    assert "cancel_token" not in fake.calls[1]


def test_sig_state1_tampered_zip_rejected(tmp_path: Path) -> None:
    """①篡改 zip：验签失败 → DownloadError（含「签名验证失败」）。"""
    payload = b"real zip bytes" * 16
    _zip, sig_content, pub_path = _minisign_trio(payload, tmp_path)
    fake = _FakeDownloader({_ZIP_URL: b"tampered zip bytes" * 8, _SIG_URL: sig_content})
    with (
        patch("atprobe.infra.update.session.download", fake),
        patch("atprobe.infra.update.session.public_key_path", return_value=pub_path),
    ):
        with pytest.raises(DownloadError, match="签名验证失败"):
            UpdateSession(dest_dir=tmp_path).download(_info(minisig_url=_SIG_URL))


def test_sig_state2_no_pubkey_blocked(tmp_path: Path) -> None:
    """②minisig_url 而 public_key_path()=None：拒绝自动安装（防降级攻击面）。"""
    fake = _FakeDownloader({_ZIP_URL: b"zip payload"})
    with (
        patch("atprobe.infra.update.session.download", fake),
        patch("atprobe.infra.update.session.public_key_path", return_value=None),
    ):
        with pytest.raises(DownloadError, match="未内置验签公钥"):
            UpdateSession(dest_dir=tmp_path).download(_info(minisig_url=_SIG_URL))
    # 只下了 zip（1 次调用），未尝试下 sig
    assert len(fake.calls) == 1


def test_sig_state3_no_sig_url_keeps_sha256_only(tmp_path: Path) -> None:
    """③无 minisig_url（过渡期旧 Release）：仅 SHA256，不下载 sig。"""
    fake = _FakeDownloader({_ZIP_URL: b"zip payload"})
    with patch("atprobe.infra.update.session.download", fake):
        result = UpdateSession(dest_dir=tmp_path).download(_info(minisig_url=None))
    assert len(fake.calls) == 1
    assert result.path.name == _ZIP_NAME


# ---------- 旧 zip 残留清理（P3）----------


def test_stale_zip_removed_before_download(tmp_path: Path) -> None:
    """dest 已有同名旧 zip → 下载前被清（幂等 unlink，验签失败的残包不留给下次）。"""
    stale = tmp_path / _ZIP_NAME
    stale.write_bytes(b"stale zip from last failed attempt")
    seen_at_download: dict[str, bool] = {}

    def probe(url: str, dest_dir: Path, **kwargs: Any) -> DownloadResult:
        seen_at_download["stale_exists"] = (dest_dir / _ZIP_NAME).exists()
        return DownloadResult(path=dest_dir / _ZIP_NAME, size=3)

    with patch("atprobe.infra.update.session.download", side_effect=probe):
        UpdateSession(dest_dir=tmp_path).download(_info())
    assert seen_at_download["stale_exists"] is False  # 下载调用发生时残留已清
    assert not stale.exists()


def test_no_stale_zip_is_noop(tmp_path: Path) -> None:
    """dest 无同名文件 → unlink(missing_ok) 幂等，不报错。"""
    fake = _FakeDownloader({_ZIP_URL: b"zip payload"})
    with patch("atprobe.infra.update.session.download", fake):
        UpdateSession(dest_dir=tmp_path).download(_info())  # 不应抛 FileNotFoundError
    assert fake.calls[0]["filename"] == _ZIP_NAME


# ---------- GUI _download_worker 迁移（D-3/P1-9）----------


class _StubSignals:
    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    def emit(self, *args: Any) -> None:
        self.events.append(args)


class _StubWindow:
    """替代 MainWindow：只提供 _download_worker 用到的信号与取消标记。"""

    def __init__(self) -> None:
        self.update_download_progress = _StubSignals()
        self.update_download_done = _StubSignals()
        self._cancelled = False


def test_gui_download_worker_uses_session() -> None:
    """GUI worker 经 UpdateSession.download 编排；进度经信号转发、结果投递 Path。"""
    from atprobe.gui.mainwindow import MainWindow

    result = DownloadResult(path=Path("tmp") / _ZIP_NAME, size=1)
    session = MagicMock()
    session.download.return_value = result
    stub = _StubWindow()
    with patch("atprobe.infra.update.session.UpdateSession", return_value=session):
        MainWindow._download_worker(stub, _info())  # type: ignore[arg-type]
    args, kwargs = session.download.call_args
    assert args[0].version == "0.3.0"
    assert callable(kwargs["progress_cb"])
    assert callable(kwargs["cancel_token"])
    assert stub.update_download_done.events == [(result.path,)]
    kwargs["progress_cb"](10, 100)  # 进度回调 → 信号投递
    assert stub.update_download_progress.events == [(10, 100)]


def test_gui_download_worker_failure_emitted() -> None:
    """GUI worker：下载异常经 update_download_done 投递 Exception（弹窗路径）。"""
    from atprobe.gui.mainwindow import MainWindow

    session = MagicMock()
    session.download.side_effect = DownloadError("签名验证失败——安装包可能被篡改，已拒绝安装")
    stub = _StubWindow()
    with patch("atprobe.infra.update.session.UpdateSession", return_value=session):
        MainWindow._download_worker(stub, _info())  # type: ignore[arg-type]
    assert len(stub.update_download_done.events) == 1
    assert isinstance(stub.update_download_done.events[0][0], DownloadError)
