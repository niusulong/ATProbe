"""minisign 签名验证（S-6 验签框架，过渡兼容）。

minisign 文件格式（Ed25519；签名算法两种：``Ed`` = legacy 对文件原始字节直接
签名（``minisign -S -l``），``ED`` = **默认** prehash——对文件内容的 BLAKE2b-512
摘要签名（裸 ``minisign -S``）。两种均支持验证）：

- 公钥文件两行：untrusted comment / base64。base64 解码 42 字节：
  ``sig_alg(2) || key_id(8) || pk(32)``
- 签名文件四行：untrusted comment / base64(签名) / trusted comment /
  base64(可信注释签名，历史遗留，验证不依赖)。签名 base64 解码 74 字节：
  ``sig_alg(2) || key_id(8) || sig(64)``

过渡语义（本模块只交付验签**能力**，不改下载流程语义）：

- 内置公钥（``atprobe/resources/atprobe-update.pub``）尚未发布 →
  ``public_key_path()`` 返回 None，验签**不可用**而非硬失败——旧版本/过渡期
  继续走 SHA256 校验（见 docs/user/update-signing.md）。
- 下载与验签的接线（何时拉取 .minisig、公钥缺失时的策略）由 UpdateSession
  （T5）负责；本模块不触网。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import sys
from importlib import resources
from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from atprobe.infra.runtime import app_root, is_frozen

PUBLIC_KEY_FILENAME = "atprobe-update.pub"

# 算法标识：``Ed``（legacy，对文件原始字节签名）/ ``ED``（默认，prehash——
# 签文件内容的 BLAKE2b-512 无键摘要）。公钥文件的算法标识恒为 ``Ed``。
_ALG_ED = b"Ed"
_ALG_ED_PREHASH = b"ED"
_PK_BLOB_LEN = 2 + 8 + 32  # sig_alg || key_id || pk
_SIG_BLOB_LEN = 2 + 8 + 64  # sig_alg || key_id || sig


def public_key_path() -> Path | None:
    """定位内置 minisign 公钥；未内置（过渡期）返回 None。

    定位口径与 ``atprobe/resources`` 包（app_icon 等打包资源）一致：

    - 开发态：``src/atprobe/resources/atprobe-update.pub``
      （importlib.resources 经包定位）
    - 打包态（PyInstaller onedir）：``<app_root>/_internal/atprobe/resources/
      atprobe-update.pub``（spec 的 collect_data_files("atprobe") 收集），
      onefile 兜底 ``_MEIPASS``。本工具用 onedir，_MEIPASS 仅为兼容。

    Returns:
        公钥文件路径；不存在返回 None（过渡期未内置公钥，验签不可用）。
    """
    # 1) importlib.resources（开发态与打包态均适用，包内数据文件的正规口径）
    try:
        traversable = resources.files("atprobe.resources").joinpath(PUBLIC_KEY_FILENAME)
        if traversable.is_file():
            # as_file 对文件系统部署（开发态/onedir）原样返回真实路径；
            # 本项目不做 zip 导入分发，返回的路径在 context 外仍有效。
            with resources.as_file(traversable) as path:
                if path.is_file():
                    return path
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    # 2) 打包态显式兜底（collect_data_files 布局 / onefile 解压目录）
    if is_frozen():
        frozen_candidates = [
            app_root() / "_internal" / "atprobe" / "resources" / PUBLIC_KEY_FILENAME,
        ]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass is not None:
            frozen_candidates.append(Path(meipass) / "atprobe" / "resources" / PUBLIC_KEY_FILENAME)
        for candidate in frozen_candidates:
            if candidate.is_file():
                return candidate
    return None


def parse_minisign_key(b64: str) -> bytes:
    """解析 minisign 公钥行 → 32 字节 Ed25519 公钥。

    Args:
        b64: 公钥文件的次行（base64；解码后应为 42 字节
            ``sig_alg(2) || key_id(8) || pk(32)``）。

    Returns:
        pk（32 字节）。

    Raises:
        ValueError: base64 非法 / 长度不符 / 算法标识非 ``Ed``。
    """
    raw = _b64decode(b64, what="公钥")
    if len(raw) != _PK_BLOB_LEN:
        raise ValueError(
            f"minisign 公钥长度错误：应为 {_PK_BLOB_LEN} 字节（alg+key_id+pk），实际 {len(raw)}"
        )
    if raw[:2] != _ALG_ED:
        raise ValueError(
            f"minisign 公钥算法标识错误：期望 {_ALG_ED!r}（Ed，对文件内容直接签名），"
            f"实际 {raw[:2]!r}"
        )
    return raw[10:]


def parse_minisign_sig(b64: str) -> tuple[bytes, bytes, bytes]:
    """解析 minisign 签名行 → (key_id 8 字节, 签名 64 字节, 算法标识 2 字节)。

    Args:
        b64: 签名文件的次行（base64；解码后应为 74 字节
            ``sig_alg(2) || key_id(8) || sig(64)``）。

    Raises:
        ValueError: base64 非法 / 长度不符 / 算法标识既非 ``Ed``（legacy）也非
            ``ED``（默认 prehash）。
    """
    raw = _b64decode(b64, what="签名")
    if len(raw) != _SIG_BLOB_LEN:
        raise ValueError(
            f"minisign 签名长度错误：应为 {_SIG_BLOB_LEN} 字节（alg+key_id+sig），实际 {len(raw)}"
        )
    alg = raw[:2]
    if alg not in (_ALG_ED, _ALG_ED_PREHASH):
        raise ValueError(
            f"minisign 签名算法标识错误：期望 {_ALG_ED!r}（legacy）或 "
            f"{_ALG_ED_PREHASH!r}（默认 prehash），实际 {alg!r}"
        )
    return raw[2:10], raw[10:], alg


def verify_minisign(zip_path: Path, sig_path: Path, pubkey_path: Path) -> bool:
    """验证 zip 的 minisign 签名（Ed legacy 与 ED prehash 双算法）。

    - ``Ed``（legacy，``-l``）：对 zip 原始字节直接做 Ed25519 验签；
    - ``ED``（默认）：对 zip 内容的 BLAKE2b-512 无键摘要做 Ed25519 验签
      （minisign 的 crypto_generichash 构造：unkeyed、64 字节输出）。

    Args:
        zip_path: 被签名的安装包。
        sig_path: ``<zip>.minisig`` 签名文件（首行 untrusted comment 跳过）。
        pubkey_path: minisign 公钥文件（首行 untrusted comment 跳过）。

    Returns:
        True 验签通过；任何失败（格式坏 / IO 错 / 签名不匹配）→ False。
        调用方按 T5 策略决定降级或阻断，本函数不抛业务异常。
    """
    try:
        pk = parse_minisign_key(_payload_line(pubkey_path))
        _key_id, sig, alg = parse_minisign_sig(_payload_line(sig_path))
        data = zip_path.read_bytes()
        payload = data if alg == _ALG_ED else hashlib.blake2b(data, digest_size=64).digest()
        VerifyKey(pk).verify(payload, sig)
        return True
    except (ValueError, BadSignatureError, OSError):
        return False


def _payload_line(path: Path) -> str:
    """读 minisign 文件的次行（base64 数据行；首行 untrusted comment 跳过）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2 or not lines[1].strip():
        raise ValueError(f"{path.name} 缺少 base64 数据行（minisign 格式：首行注释 + 次行 base64）")
    return lines[1].strip()


def _b64decode(b64: str, *, what: str) -> bytes:
    """严格 base64 解码，失败抛 ValueError（带定位信息）。"""
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"minisign {what} base64 解码失败：{exc}") from exc
