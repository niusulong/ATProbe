"""数据源路径信任边界（S-8，设计 §5）：data.file 与 {{file_size()}} 的路径
必须在锚集内——「用例文件所在目录 ∪ 额外根（EngineConfig.data_allowed_roots，
批 4 并入 mcp.allowed_roots）」。校验点=渲染后、发送前（路径可含模板变量）。

纯 domain 逻辑：仅 pathlib/os.path，无其它依赖（stat/read 属必要 IO）。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path


class DataPathError(ValueError):
    """数据路径越界/不可读（作者错误，引擎走 on_failure 决策）。"""


def _norm(p: Path) -> Path:
    """比较用规范化：Windows 上 normcase 折叠大小写与斜杠方向.

    pathlib 的 is_relative_to 在 Windows 按字符串比较、大小写敏感，
    `D:\\a` vs `d:\\a` 会误判越界；两侧先 normcase 再比较。
    """
    return Path(os.path.normcase(str(p)))


def data_roots(case_dir: Path | None, extra: tuple[Path, ...] = ()) -> list[Path]:
    """锚集：全部 resolve()（strict=False）去重；case_dir 为 None 时跳过之."""
    candidates: list[Path] = []
    if case_dir is not None:
        candidates.append(case_dir)
    candidates.extend(extra)
    roots: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        resolved = p.resolve()
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def resolve_case_path(raw: str, case_dir: Path | None) -> Path:
    """渲染后的路径解析：相对路径锚定 case_dir（case_dir 为 None 时按 CWD，即
    Path(raw) 原语义），绝对路径原样。返回未 resolve 的拼接结果（锚定判定在
    ensure_within 内 resolve）。"""
    path = Path(raw)
    if path.is_absolute() or case_dir is None:
        return path
    return case_dir / path


def ensure_within(path: Path, roots: Sequence[Path]) -> Path:
    """S-8 锚定校验：path.resolve() 须位于任一锚根（root.resolve()）内.

    越界抛 DataPathError（信息含渲染后路径与锚集）；roots 为空同样抛
    （提示：需用例目录或 data_allowed_roots）。返回 resolve 后的绝对路径。
    """
    if not roots:
        raise DataPathError(
            f"数据路径 {path} 无可用锚集：需用例目录（case_dir）或 data_allowed_roots 配置"
        )
    resolved = path.resolve()
    normalized = _norm(resolved)
    for root in roots:
        if normalized.is_relative_to(_norm(root.resolve())):
            return resolved
    raise DataPathError(f"数据路径越界：{path}（resolve 后 {resolved}）不在锚集 {list(roots)} 内")


def read_data_file(raw: str, case_dir: Path | None, extra_roots: tuple[Path, ...] = ()) -> bytes:
    """读取数据文件：锚定校验（S-8）通过后才读字节.

    resolve_case_path → ensure_within（锚集=data_roots(case_dir, extra_roots)）
    → read_bytes；OSError 包装为 DataPathError（含底层原因）。
    """
    path = resolve_case_path(raw, case_dir)
    anchored = ensure_within(path, data_roots(case_dir, extra_roots))
    try:
        return anchored.read_bytes()
    except OSError as exc:
        raise DataPathError(f"数据文件不可读：{raw}（resolve 后 {anchored}）：{exc}") from exc
