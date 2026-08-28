"""M2 套件 YAML 解析器（REQ-M2 §12）.

将 suite YAML 解析为 :class:`Suite` 模型。解析失败抛 :class:`SuiteParseError`。
仿 ``case.parser`` 的结构。
"""

from __future__ import annotations

import threading
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from atprobe.domain.suite.models import Suite


class SuiteParseError(ValueError):
    """套件解析错误，携带来源文件与原因."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}" if source else message)


# 线程安全（批 4 T6 审查补充）：ruamel YAML 实例非线程安全，模块级共享实例
# 在 MCP 线程池并发解析下互毁 composer 状态（load_cases→parse_suite_file 与
# case parser 同链路可达）——改为每线程独立实例（thread-local），单线程不变。
_yaml_local = threading.local()


def _loader() -> YAML:
    """当前线程的 YAML 实例（lazy 创建，同一实例复用以保留 ruamel 缓存收益）."""
    y: YAML | None = getattr(_yaml_local, "yaml", None)
    if y is None:
        y = YAML(typ="safe")
        y.indent(mapping=2, sequence=4, offset=2)
        _yaml_local.yaml = y
    return y


def parse_suite(data: str | bytes | dict[str, Any], *, source: str | None = None) -> Suite:
    """解析套件数据为 Suite.

    Raises:
        SuiteParseError: YAML 语法错误或 schema 校验失败。
    """
    if isinstance(data, dict):
        raw: Any = data
    else:
        try:
            raw = _loader().load(
                StringIO(data) if isinstance(data, str) else StringIO(data.decode("utf-8"))
            )
        except YAMLError as exc:
            line = getattr(getattr(exc, "problem_mark", None), "line", None)
            loc = f"第 {line + 1} 行" if line is not None else "未知行"
            raise SuiteParseError(f"YAML 语法错误（{loc}）：{exc}", source=source) from exc
        except UnicodeDecodeError as exc:
            # P3 修复：非法 UTF-8 收敛为 SuiteParseError（与 case parser 同口径）
            raise SuiteParseError(f"文件不是有效 UTF-8：{exc}", source=source) from exc

    if not isinstance(raw, dict):
        raise SuiteParseError(f"套件根节点必须是映射，实际为 {type(raw).__name__}", source=source)

    try:
        suite = Suite.model_validate(raw)
    except ValidationError as exc:
        lines = ["套件字段校验失败："]
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            lines.append(f"  - {loc}: {err['msg']}")
        raise SuiteParseError("\n".join(lines), source=source) from exc

    if source:
        suite = suite.model_copy(update={"source_file": source})
    return suite


def parse_suite_file(path: str | Path) -> Suite:
    """从文件解析套件."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteParseError(f"无法读取套件文件：{exc.strerror or exc}", source=str(p)) from exc
    return parse_suite(text, source=str(p))
