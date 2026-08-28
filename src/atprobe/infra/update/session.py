"""更新下载统一编排（D-3，设计 §5）：CLI/GUI 共用的目标目录/文件名模板/校验
参数/签名策略/进度回调单点——P1-9 的结构修（此前 CLI/GUI 两处拼装已实际分叉：
GUI 硬编码文件名、漏传 SHA256，靠逐项补丁追赶 CLI，同一策略两处维护必再漂移）。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from atprobe.infra.update import DownloadError
from atprobe.infra.update.checker import ReleaseInfo
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig
from atprobe.infra.update.downloader import (
    CancelToken,
    DownloadResult,
    ProgressCb,
    download,
)
from atprobe.infra.update.verifier import public_key_path, verify_minisign


def _default_dest_dir() -> Path:
    """默认下载目录：系统临时目录（与 downloader「避免写 exe 同级」的策略一致）。"""
    return Path(tempfile.gettempdir())


@dataclass(frozen=True)
class UpdateSession:
    """一次更新下载的编排上下文（dest_dir/config 可注入，测试隔离用）。"""

    config: UpdateConfig = field(default_factory=lambda: DEFAULT_CONFIG)
    dest_dir: Path = field(default_factory=_default_dest_dir)

    def download(
        self,
        info: ReleaseInfo,
        *,
        progress_cb: ProgressCb | None = None,
        cancel_token: CancelToken | None = None,
    ) -> DownloadResult:
        """按统一策略下载 Release 的 zip。

        策略单点：
        1. 文件名 = ``config.asset_name_for(info.version)``（消 GUI 硬编码）；
        2. expected_size = ``info.zip_size or None``（size 缺失/0 置 None 不误报：
           Release JSON 异常时 0 会导致「期望 0 实际 N」的假失败）；
        3. expected_sha256 = ``info.sha256``（None 时 downloader 自动降级）；
        4. **签名策略（S-6 接线，过渡三态）**：
           - info.minisig_url 且 public_key_path() 非 None → 下载 .minisig
             （同白名单经 downloader.download 到 dest_dir，sig 文件名 = zip 名
             + ``.minisig``）→ verify_minisign 失败 →
             DownloadError("签名验证失败——安装包可能被篡改，已拒绝安装")；
           - info.minisig_url 而 public_key_path() None →
             DownloadError("远端已启用签名校验但本版本未内置验签公钥（请从
             GitHub Release 页手动下载核对）")（防降级攻击面：新版已签名发布
             而本旧版无法验签时，宁可不自动升级也不裸装）；
           - 无 minisig_url → 现状（仅 SHA256——过渡期旧 Release）；
        5. 下载前清掉 dest_dir 同名旧 zip（残留清理 P3，幂等 unlink missing_ok：
           上次验签失败的残包不留给下次/不让「失败后旧包仍可被装」）；
        6. progress/cancel 透传（sig 下载不透传——几十字节）。

        Raises:
            DownloadCancelled: 用户取消（透传自 downloader）。
            DownloadError: 下载失败 / 校验失败 / 签名验证失败 / 公钥缺失。
        """
        filename = self.config.asset_name_for(info.version)
        # 公钥可用性是本地 FS 查询——有签名资产而本版本无公钥时，在下整包之前
        # 快速失败（T5 审查修复：避免白下 80MB 后才拒绝，zip 残留盘上）
        pubkey = public_key_path() if info.minisig_url is not None else None
        if info.minisig_url is not None and pubkey is None:
            raise DownloadError(
                "远端已启用签名校验但本版本未内置验签公钥（请从 GitHub Release 页手动下载核对）"
            )
        zip_path = self.dest_dir / filename
        zip_path.unlink(missing_ok=True)
        result = download(
            info.zip_url,
            self.dest_dir,
            filename=filename,
            expected_size=info.zip_size or None,
            expected_sha256=info.sha256,
            progress_cb=progress_cb,
            cancel_token=cancel_token,
            config=self.config,
        )

        if info.minisig_url is None:
            # 过渡期旧 Release：无签名资产，维持仅 SHA256 校验
            return result

        assert pubkey is not None  # 上方已拒绝无公钥场景（mypy 收窄）
        sig_name = filename + ".minisig"
        (self.dest_dir / sig_name).unlink(missing_ok=True)
        # sig 走同一 downloader（白名单/https 校验复用）；几十字节，不透传进度/取消
        sig_result = download(
            info.minisig_url,
            self.dest_dir,
            filename=sig_name,
            config=self.config,
        )
        if not verify_minisign(result.path, sig_result.path, pubkey):
            raise DownloadError("签名验证失败——安装包可能被篡改，已拒绝安装")
        return result


__all__ = ["UpdateSession"]
