"""版本检查器：查 GitHub Releases API 取最新版 + semver 比较。

纯逻辑、纯 stdlib、所有网络异常收敛成 UpdateCheckError（上层静默/弹窗可控）。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel

from atprobe.infra.update import AssetNotFoundError, UpdateCheckError
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig
from atprobe.infra.version import current_version

_API_PATH = "/repos/{repo}/releases/latest"


class ReleaseInfo(BaseModel):
    """远程最新 Release 解析结果。"""

    version: str  # "0.3.0"（去掉 v 前缀）
    tag: str  # "v0.3.0"
    zip_url: str  # Windows zip 下载地址
    zip_size: int  # 字节数
    release_notes: str  # release body（changelog）
    html_url: str  # GitHub Release 页面（备用）


def fetch_latest(
    config: UpdateConfig | None = None,
    *,
    timeout: float | None = None,
) -> ReleaseInfo:
    """查询最新 Release。

    所有网络/解析异常都收敛成 UpdateCheckError；找不到 Windows 包抛 AssetNotFoundError。
    """
    cfg = config or DEFAULT_CONFIG
    url = cfg.api_base.rstrip("/") + _API_PATH.format(repo=cfg.repo)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ATProbe/{current_version()}",
        },
    )
    to = cfg.check_timeout if timeout is None else timeout
    try:
        with urllib.request.urlopen(req, timeout=to) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(_http_error_msg(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateCheckError(f"网络连接失败：{exc}") from exc

    try:
        body: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpdateCheckError(f"响应格式异常：{exc}") from exc

    return _parse_release(body, cfg)


def _parse_release(body: dict[str, Any], cfg: UpdateConfig) -> ReleaseInfo:
    try:
        tag = str(body["tag_name"])
    except KeyError as exc:
        raise UpdateCheckError("响应缺少 tag_name 字段") from exc
    version = tag.lstrip("v")
    expected_name = cfg.asset_name_for(version)
    asset = next(
        (a for a in body.get("assets", []) if a.get("name") == expected_name), None
    )
    if asset is None:
        raise AssetNotFoundError(f"版本 {version} 无 Windows 安装包（{expected_name}）")
    return ReleaseInfo(
        version=version,
        tag=tag,
        zip_url=str(asset.get("browser_download_url", "")),
        zip_size=int(asset.get("size", 0)),
        release_notes=str(body.get("body", "")),
        html_url=str(body.get("html_url", "")),
    )


def _http_error_msg(code: int) -> str:
    if code == 403:
        return "请求过于频繁（GitHub API 限流），请稍后重试"
    if code == 404:
        return "尚未发布任何版本"
    return f"服务器返回错误（HTTP {code}）"


def is_newer(remote: str, local: str) -> bool:
    """remote 版本是否比 local 新（semver 元组比较）。"""
    return _parse_semver(remote) > _parse_semver(local)


def _parse_semver(v: str) -> tuple[int, int, int]:
    """解析 '0.2.1' / 'v0.3.0' / '0.3' → (major, minor, patch)。

    去掉 v 前缀、忽略 -pre 后缀；缺位补 0；非数字段回退 0。
    """
    core = re.split(r"[-+]", v.strip().lstrip("vV"), 1)[0]
    parts = core.split(".")
    nums: list[int] = []
    for p in parts[:3]:
        m = re.match(r"\d+", p)
        nums.append(int(m.group()) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])
