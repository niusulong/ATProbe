"""domain/case 公共错误（D-2 领域纯净：自 templater.py 下沉）.

UndefinedReferenceError 的引用方不止 templater 自身——infra/envconfig（resolve_str
未定义引用）、engine/step_runner（错误分类）、evaluator（旧写法 {{}} 预处理契约）
与多处测试都要 import 它。放在单一职责的渲染模块里迫使无关方依赖渲染实现细节，
故下沉为 case 包级公共错误模块。
"""

from __future__ import annotations


class UndefinedReferenceError(KeyError):
    """模板中引用了未定义的变量/环境配置项."""

    def __init__(self, ref: str) -> None:
        self.ref = ref
        super().__init__(ref)
