"""下载器：把 zip 安全下载到本地。

安全策略：
    - 先写 ``<name>.part`` 临时文件，成功后原子重命名为 ``<name>``
    - 任何退出路径（失败/取消）都清理 ``.part``；成功路径在 finally 前已完成重命名
    - 目标目录用系统临时目录，避免写 exe 同级（权限/防软件监控）
    - 可选 expected_size 校验，防止代理截断给残缺 zip
    - B9 修复：可选 expected_sha256 内容校验，边下边哈希，下载完比对。
      防传输损坏 / CDN 缓存污染 / 等大小恶意替换（expected_size 来自同一 Release JSON
      防不住攻击者构造等大小 zip）。
    - S-5：入口 URL 校验（仅 https + 下载主机白名单）与重定向复检
      （防 30x 降级到 http / 跳到白名单外主机）。
"""

from __future__ import annotations

import hashlib
import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPMessage
from pathlib import Path
from typing import IO
from urllib.parse import urlparse

from pydantic import BaseModel

from atprobe.infra.update import DownloadCancelled, DownloadError
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig

_CHUNK = 8192

ProgressCb = Callable[[int, int], None]
CancelToken = Callable[[], bool]


def _validate_url(url: str, cfg: UpdateConfig) -> str:
    """S-5：下载地址白名单校验。

    - scheme 必须 https（拒 http 明文/ftp/file 等）
    - 主机（``urlparse().hostname``，不含端口）必须在 ``cfg.effective_allowed_hosts()``
      白名单内；端口不参与白名单判断（同主机任意端口放行，校验聚焦传输层与主机归属）

    Raises:
        DownloadError: scheme 非 https 或主机越界。
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    except ValueError as exc:
        raise DownloadError(f"下载地址非法：{url}") from exc
    if parsed.scheme != "https":
        raise DownloadError(f"仅允许 https 下载地址：{url}")
    hosts = cfg.effective_allowed_hosts()
    if not host or host not in hosts:
        raise DownloadError(
            f"下载主机不在白名单：{host}（允许：{hosts}；可在配置 update.allowed_hosts 追加）"
        )
    return url


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """S-5：重定向防降级/防越界——每个 30x 目标复检 https + 主机白名单。

    urllib 默认 opener 跟随重定向且不做任何检查（https→http 降级、跳任意主机
    均静默接受）。本 handler 在 redirect_request 里对 newurl 递归 _validate_url：
    校验失败直接抛 DownloadError——异常沿 ``opener.open()`` 原样传播
    （urllib 只对 HTTPError 有包装路径，普通异常不包装），download() 的调用方
    拿到的仍是语义清晰的 DownloadError 而非被截断的 HTTPError。
    """

    def __init__(self, cfg: UpdateConfig) -> None:
        super().__init__()
        self._cfg = cfg

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_url(newurl, self._cfg)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener(cfg: UpdateConfig) -> urllib.request.OpenerDirector:
    """构造带重定向复检的 opener（替代裸 urlopen 的默认 opener）。"""
    return urllib.request.build_opener(_SafeRedirectHandler(cfg))


class DownloadResult(BaseModel):
    """下载完成结果。"""

    path: Path
    size: int


def download(
    url: str,
    dest_dir: Path,
    *,
    filename: str | None = None,
    timeout: float | None = None,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    progress_cb: ProgressCb | None = None,
    cancel_token: CancelToken | None = None,
    config: UpdateConfig | None = None,
) -> DownloadResult:
    """下载 url 到 ``dest_dir/<filename>``。

    Args:
        url: 下载地址。
        dest_dir: 目标目录（已存在）。
        filename: 目标文件名；None 则从 URL 路径推断。
        timeout: 连接超时；None 用 config.download_timeout。
        expected_size: 期望字节数，下载后校验；None 不校验。
        expected_sha256: 期望的 SHA256 十六进制摘要（B9）。边下边哈希，下载完比对；
            None 不校验。防传输损坏 / CDN 缓存污染 / 等大小恶意替换。
        progress_cb: ``(downloaded, total)`` 回调，每 chunk 调用。
        cancel_token: 返回 True 则中止下载（抛 DownloadCancelled）。
        config: 超时等配置。

    Returns:
        DownloadResult（path 指向最终文件，已无 .part 后缀）。

    Raises:
        DownloadCancelled: 用户取消。
        DownloadError: 网络/磁盘/大小不符/SHA256 不符/URL 越界（S-5）。
    """
    cfg = config or DEFAULT_CONFIG
    _validate_url(url, cfg)  # S-5：入口校验——非 https / 白名单外主机在触网前拒绝
    if filename is None:
        filename = Path(urlparse(url).path).name or "download.bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / filename
    part = dest_dir / f"{filename}.part"

    # 清理可能的历史 .part（幂等）
    part.unlink(missing_ok=True)

    to = cfg.download_timeout if timeout is None else timeout
    req = urllib.request.Request(url, headers={"User-Agent": f"ATProbe/{cfg.repo}"})
    # S-5：带重定向复检的 opener（scheme 已校验、host 已过白名单，
    # S310 审计项由此收敛；重定向目标由 _SafeRedirectHandler 逐跳复检）
    opener = _build_opener(cfg)
    # 标记成功路径：仅当成功时跳过 finally 的 .part 清理
    # （成功时 .part 已被 replace 为 final，但显式标记更清晰）
    succeeded = False
    try:
        try:
            resp = opener.open(req, timeout=to)  # noqa: S310
        except urllib.error.HTTPError as exc:
            raise DownloadError(f"下载失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DownloadError(f"下载失败：网络中断（{exc}）") from exc

        total = _content_length(resp)
        written = 0
        sha = hashlib.sha256() if expected_sha256 is not None else None
        try:
            with part.open("wb") as f:
                while True:
                    if cancel_token is not None and cancel_token():
                        raise DownloadCancelled("用户取消下载")
                    try:
                        chunk = resp.read(_CHUNK)
                    except http.client.HTTPException as exc:
                        # P2 修复：读流中断（IncompleteRead 等 HTTPException）收敛为
                        # DownloadError（旧实现裸抛到 CLI）
                        raise DownloadError(f"下载中断：{exc}") from exc
                    except (TimeoutError, OSError) as exc:
                        raise DownloadError(f"下载中断：{exc}") from exc
                    if not chunk:
                        break
                    try:
                        f.write(chunk)
                    except OSError as exc:
                        raise DownloadError(f"写盘失败：{exc}") from exc
                    if sha is not None:
                        sha.update(chunk)
                    written += len(chunk)
                    if progress_cb is not None:
                        progress_cb(written, total)
        finally:
            resp.close()

        # 大小校验（在 finally 清理之前，失败时抛 DownloadError，finally 会清理 .part）
        if expected_size is not None and written != expected_size:
            raise DownloadError(
                f"下载文件大小不符：期望 {expected_size}，实际 {written}（可能已损坏）"
            )
        # B9：SHA256 内容校验（防传输损坏 / CDN 缓存污染 / 等大小恶意替换）
        if sha is not None and expected_sha256 is not None:
            actual = sha.hexdigest()
            if actual.lower() != expected_sha256.lower():
                raise DownloadError(
                    f"下载文件 SHA256 不符：期望 {expected_sha256}，实际 {actual}（文件可能被篡改）"
                )

        # 原子重命名（成功路径）
        try:
            part.replace(final)
        except OSError as exc:
            raise DownloadError(f"无法完成文件写入：{exc}") from exc
        succeeded = True
    finally:
        # 失败/取消：清理残留 .part；成功：.part 已 replace（不存在，missing_ok 安全）
        if not succeeded:
            part.unlink(missing_ok=True)

    return DownloadResult(path=final, size=written)


def _content_length(resp: object) -> int:
    headers = getattr(resp, "headers", {}) or {}
    val = headers.get("Content-Length") if hasattr(headers, "get") else None
    try:
        return int(val) if val else 0
    except (TypeError, ValueError):
        return 0
