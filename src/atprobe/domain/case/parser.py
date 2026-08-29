"""M2 用例 YAML 解析器（REQ-M2 §2）.

将 YAML 文件/字符串解析为 :class:`Case` 模型。解析失败抛 :class:`CaseParseError`，
携带行号与原因（满足 M5 §3.5「解析失败提示行号原因」）。
"""

from __future__ import annotations

import threading
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from atprobe.domain.case.models import Case


class CaseParseError(ValueError):
    """用例解析错误，携带来源文件与原因（可能含行号）."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}" if source else message)


# ruamel YAML 实例**非线程安全**：并发 load 会互相破坏 composer 内部状态
# （AttributeError: 'NoneType' object has no attribute 'anchor'，且一处损坏
# 会波及同时解析的其它线程产出假语法错误）。任何多线程并发解析（GUI 主线程
# 与 MCP 会话线程、引擎线程等）都必须隔离——改为每线程独立实例
# （thread-local），单线程内行为不变。
_yaml_local = threading.local()


def _loader() -> YAML:
    """当前线程的 YAML 实例（lazy 创建，同一实例复用以保留 ruamel 缓存收益）."""
    y: YAML | None = getattr(_yaml_local, "yaml", None)
    if y is None:
        y = YAML(typ="safe")
        y.indent(mapping=2, sequence=4, offset=2)
        _yaml_local.yaml = y
    return y


def parse_case(data: str | bytes | dict[str, Any], *, source: str | None = None) -> Case:
    """解析用例数据为 Case.

    Args:
        data: YAML 字符串/字节，或已解析的 dict。
        source: 来源文件路径（仅用于错误信息与 Case.source_file 填充）。
    Raises:
        CaseParseError: YAML 语法错误或 schema 校验失败。
    """
    if isinstance(data, dict):
        raw: Any = data
    else:
        try:
            raw = _loader().load(
                StringIO(data) if isinstance(data, str) else StringIO(data.decode("utf-8"))
            )
        except YAMLError as exc:
            # ruamel 错误对象常带 .problem_mark.line（0-based）
            line = getattr(getattr(exc, "problem_mark", None), "line", None)
            loc = f"第 {line + 1} 行" if line is not None else "未知行"
            raise CaseParseError(f"YAML 语法错误（{loc}）：{exc}", source=source) from exc
        except UnicodeDecodeError as exc:
            # P3 修复：bytes 输入含非法 UTF-8 时收敛为 CaseParseError（带 source），
            # 旧实现裸 UnicodeDecodeError 违反「解析失败抛 CaseParseError」契约
            raise CaseParseError(f"文件不是有效 UTF-8：{exc}", source=source) from exc

    if not isinstance(raw, dict):
        raise CaseParseError(f"用例根节点必须是映射，实际为 {type(raw).__name__}", source=source)

    try:
        case = Case.model_validate(raw)
    except ValidationError as exc:
        # 将 pydantic 错误转为可读多行信息
        lines = ["用例字段校验失败："]
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            lines.append(f"  - {loc}: {err['msg']}")
        raise CaseParseError("\n".join(lines), source=source) from exc

    if source:
        case = case.model_copy(update={"source_file": source})
    return case


def parse_case_file(path: str | Path) -> Case:
    """从文件解析用例.

    Raises:
        CaseParseError: 文件不可读、非 UTF-8 编码或解析/校验失败。
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # F-16 同型：GBK 等非 UTF-8 文件在 read_text 处抛 UnicodeDecodeError
        # （ValueError 子类，非 OSError），旧实现裸抛逃逸——须收敛为 CaseParseError
        raise CaseParseError(
            f"用例文件非 UTF-8 编码，无法解析（请转存为 UTF-8）：{exc}", source=str(p)
        ) from exc
    except OSError as exc:
        raise CaseParseError(f"无法读取用例文件：{exc.strerror or exc}", source=str(p)) from exc
    return parse_case(text, source=str(p))
