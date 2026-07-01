"""M2 套件 YAML 解析器（REQ-M2 §12）.

将 suite YAML 解析为 :class:`Suite` 模型。解析失败抛 :class:`SuiteParseError`。
仿 ``case.parser`` 的结构。
"""

from __future__ import annotations

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


_yaml = YAML(typ="safe")
_yaml.indent(mapping=2, sequence=4, offset=2)


def parse_suite(data: str | bytes | dict[str, Any], *, source: str | None = None) -> Suite:
    """解析套件数据为 Suite.

    Raises:
        SuiteParseError: YAML 语法错误或 schema 校验失败。
    """
    if isinstance(data, dict):
        raw: Any = data
    else:
        try:
            raw = _yaml.load(StringIO(data) if isinstance(data, str) else StringIO(data.decode("utf-8")))
        except YAMLError as exc:
            line = getattr(getattr(exc, "problem_mark", None), "line", None)
            loc = f"第 {line + 1} 行" if line is not None else "未知行"
            raise SuiteParseError(f"YAML 语法错误（{loc}）：{exc}", source=source) from exc

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
