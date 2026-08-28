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
    # B9：随包发布的 SHA256 摘要（来自 <zip>.sha256 asset）。可能为空（旧版未发布哈希文件）。
    sha256: str | None = None
    # S-6：随包发布的 minisign 签名文件下载地址（来自 <zip>.minisig asset）。
    # 旧版本无此资产 → None。此处只识别 URL 不下载；下载与验签由 UpdateSession
    # （T5 接线）负责，过渡期策略见 docs/user/update-signing.md。
    minisig_url: str | None = None
    # P3：是否预发布版本（tag 含 -rc1/-beta 等 ``-`` 后缀）。GitHub 的
    # releases/latest 端点理论上只返回正式版，但 tag 命名带后缀时旧实现
    # 把预发布当正式版静默推荐升级；此标记供 CLI/GUI 在确认提示处标注。
    prerelease: bool = False


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
    # P3 修复：解析段整体兜底（size=null / body 非 dict 等异常输入旧实现裸抛
    # TypeError/ValueError，违反「所有异常收敛 UpdateCheckError」的模块承诺）
    try:
        return _parse_release_inner(body, cfg)
    except UpdateCheckError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise UpdateCheckError(f"Release 响应结构异常：{exc!r}") from exc


def _parse_release_inner(body: dict[str, Any], cfg: UpdateConfig) -> ReleaseInfo:
    try:
        tag = str(body["tag_name"])
    except KeyError as exc:
        raise UpdateCheckError("响应缺少 tag_name 字段") from exc
    version = tag.lstrip("v")
    expected_name = cfg.asset_name_for(version)
    asset = next((a for a in body.get("assets", []) if a.get("name") == expected_name), None)
    if asset is None:
        raise AssetNotFoundError(f"版本 {version} 无 Windows 安装包（{expected_name}）")
    # B9：查找随包发布的 <zip>.sha256 哈希文件（可选 asset）。若存在，下载并解析摘要；
    # 失败则 sha256=None（降级为仅校验 size）。哈希文件几十字节，下载开销可忽略。
    sha256_digest: str | None = None
    sha_name = f"{expected_name}.sha256"
    sha_asset = next((a for a in body.get("assets", []) if a.get("name") == sha_name), None)
    if sha_asset is not None:
        sha_url = str(sha_asset.get("browser_download_url", ""))
        if sha_url:
            sha256_digest = _fetch_sha256(sha_url, cfg)
    # S-6：识别 <zip>.minisign 签名资产（同 sha256 资产模式，但只取 URL 不下载——
    # 签名文件几十 KB，何时取、如何验（含过渡期策略）由 T5 的 UpdateSession 决定）
    sig_name = f"{expected_name}.minisig"
    sig_asset = next((a for a in body.get("assets", []) if a.get("name") == sig_name), None)
    minisig_url: str | None = None
    if sig_asset is not None:
        url = str(sig_asset.get("browser_download_url", ""))
        minisig_url = url or None
    return ReleaseInfo(
        version=version,
        tag=tag,
        zip_url=str(asset.get("browser_download_url", "")),
        zip_size=int(asset.get("size", 0)),
        release_notes=str(body.get("body", "")),
        html_url=str(body.get("html_url", "")),
        sha256=sha256_digest,
        minisig_url=minisig_url,
        prerelease=is_prerelease(tag),
    )


def _fetch_sha256(url: str, cfg: UpdateConfig) -> str | None:
    """下载 .sha256 文件并解析出摘要（小文件，失败返回 None 降级）.

    批 4 终审 Minor：与主 zip 同走 S-5 体系（https 强制 + host 白名单 +
    重定向复检的 opener）——此前裸 urlopen 是更新链上唯一绕开校验的触网点。
    校验失败（DownloadError）与网络失败同口径降级为 None。
    """
    from atprobe.infra.update import DownloadError
    from atprobe.infra.update.downloader import _build_opener, _validate_url

    req = urllib.request.Request(url, headers={"User-Agent": f"ATProbe/{current_version()}"})
    to = cfg.check_timeout
    try:
        _validate_url(url, cfg)
        with _build_opener(cfg).open(req, timeout=to) as resp:
            raw = resp.read(256)  # sha256 摘要 64 hex 字符，读 256 字节足够
    except (DownloadError, urllib.error.URLError, TimeoutError, OSError):
        return None
    # .sha256 文件格式："<64位hex>  <filename>" 或纯摘要。取首段 hex。
    text = raw.decode("utf-8", errors="replace").strip()
    first = text.split()[0] if text else ""
    # 校验是合法的 64 位十六进制
    if len(first) == 64 and all(c in "0123456789abcdefABCDEF" for c in first):
        return first.lower()
    return None


def _http_error_msg(code: int) -> str:
    if code == 403:
        return "请求过于频繁（GitHub API 限流），请稍后重试"
    if code == 404:
        return "尚未发布任何版本"
    return f"服务器返回错误（HTTP {code}）"


def is_newer(remote: str, local: str) -> bool:
    """remote 版本是否比 local 新（semver 元组比较）。"""
    return _parse_semver(remote) > _parse_semver(local)


def is_prerelease(version: str) -> bool:
    """版本是否为预发布（semver prerelease 段：core 后带 ``-`` 后缀）。

    P3：``_parse_semver`` 为比较而忽略 ``-rc1`` 后缀，导致 ``v0.10.0-rc1``
    被当作 ``0.10.0`` 正式版参与比较；本函数单独识别预发布形态，供
    ``ReleaseInfo.prerelease`` 与 CLI/GUI 的确认提示标注用。

    >>> is_prerelease("v0.10.0-rc1"), is_prerelease("0.10.0"), is_prerelease("0.10")
    (True, False, False)
    """
    # 去 v 前缀与 +build 元数据后，剩余部分含 "-" 即预发布（semver 语法中
    # prerelease 段是第三个 "." 段之后以 "-" 起始的整段，此处按宽松口径识别）
    core = version.strip().lstrip("vV").split("+", 1)[0]
    return "-" in core


def _parse_semver(v: str) -> tuple[int, int, int]:
    """解析 '0.2.1' / 'v0.3.0' / '0.3' → (major, minor, patch)。

    去掉 v 前缀、忽略 -pre 后缀；缺位补 0；非数字段回退 0。
    """
    core = re.split(r"[-+]", v.strip().lstrip("vV"), maxsplit=1)[0]
    parts = core.split(".")
    nums: list[int] = []
    for p in parts[:3]:
        m = re.match(r"\d+", p)
        nums.append(int(m.group()) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])
