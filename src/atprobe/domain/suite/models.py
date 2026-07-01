"""M2 用例套件数据模型（REQ-M2 §12）.

套件是用例集合的索引文件，通过文件路径引用用例。复用 ``case.Step`` 表达
suite_setup/suite_teardown 步骤（结构一致），保持模型不重复定义。
"""

from __future__ import annotations

from pydantic import Field

from atprobe.domain.case.models import Step, _Frozen


class Suite(_Frozen):
    """用例套件（REQ-M2 §12）。

    通过 ``cases`` 列表引用用例文件（相对套件文件所在目录的路径）。
    suite_setup/suite_teardown 在套件执行的开头/结尾各执行一次（§12.2）。
    """

    name: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = Field(default_factory=tuple)
    suite_setup: tuple[Step, ...] = ()
    suite_teardown: tuple[Step, ...] = ()
    cases: tuple[str, ...] = ()
    source_file: str | None = None
