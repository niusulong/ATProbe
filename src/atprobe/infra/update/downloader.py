"""下载器：把 zip 安全下载到本地。

安全策略：
    - 先写 ``<name>.part`` 临时文件，成功后原子重命名为 ``<name>``
    - 任何退出路径（失败/取消）都清理 ``.part``；成功路径在 finally 前已完成重命名
    - 目标目录用系统临时目录，避免写 exe 同级（权限/防软件监控）
    - 可选 expected_size 校验，防止代理截断给残缺 zip
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from atprobe.infra.update import DownloadCancelled, DownloadError
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig

_CHUNK = 8192

ProgressCb = Callable[[int, int], None]
CancelToken = Callable[[], bool]


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
        progress_cb: ``(downloaded, total)`` 回调，每 chunk 调用。
        cancel_token: 返回 True 则中止下载（抛 DownloadCancelled）。
        config: 超时等配置。

    Returns:
        DownloadResult（path 指向最终文件，已无 .part 后缀）。

    Raises:
        DownloadCancelled: 用户取消。
        DownloadError: 网络/磁盘/大小不符。
    """
    cfg = config or DEFAULT_CONFIG
    if filename is None:
        filename = Path(urlparse(url).path).name or "download.bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / filename
    part = dest_dir / f"{filename}.part"

    # 清理可能的历史 .part（幂等）
    part.unlink(missing_ok=True)

    to = cfg.download_timeout if timeout is None else timeout
    req = urllib.request.Request(url, headers={"User-Agent": f"ATProbe/{cfg.repo}"})
    # 标记成功路径：仅当成功时跳过 finally 的 .part 清理
    # （成功时 .part 已被 replace 为 final，但显式标记更清晰）
    succeeded = False
    try:
        try:
            resp = urllib.request.urlopen(req, timeout=to)  # noqa: S310
        except urllib.error.HTTPError as exc:
            raise DownloadError(f"下载失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DownloadError(f"下载失败：网络中断（{exc}）") from exc

        total = _content_length(resp)
        written = 0
        try:
            with part.open("wb") as f:
                while True:
                    if cancel_token is not None and cancel_token():
                        raise DownloadCancelled("用户取消下载")
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    try:
                        f.write(chunk)
                    except OSError as exc:
                        raise DownloadError(f"写盘失败：{exc}") from exc
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
