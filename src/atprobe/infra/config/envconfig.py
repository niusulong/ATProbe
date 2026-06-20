"""M7 测试环境配置（REQ-M7）.

承载跨用例共享的全局只读配置（FTP/HTTP/TCP/MQTT 服务器、FOTA 版本号等）。
用例通过 ``{{group.param}}`` 点号引用，执行时填充到 AT 指令（REQ-M7 §1）。

模型（§2/§3）：
    - 单一全局配置文件 env.yaml，顶层键 = 职责域（组），组内扁平键值对。
    - 不支持嵌套组（引用路径固定两级 ``{{group.param}}``）。
    - 组与参数由用户自定义，可任意增删（§5 可扩展性，无 schema 强约束）。

查找语义（§4，配合 templater）：
    - 点号名 ``{{group.param}}`` 仅查环境配置（不被 extract 覆盖，§4.4 边界）。
    - 简单名 ``{{param}}`` 在用例级未命中时回退到环境配置的「默认组」（可选）。

加载（§2.4）：引擎 start 时一次性加载为只读快照，加载失败 → 引擎 ERROR。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from atprobe.domain.case.templater import UndefinedReferenceError

# 默认组名：简单名 {{param}} 在用例级未命中时回退到这里查找（§4.2 默认组）
_DEFAULT_GROUP = "default"

# 值类型：字符串 / 数值 / 布尔（§2.3）
_Scalar = str | int | float | bool


class EnvConfigError(ValueError):
    """环境配置加载/校验错误，携带来源文件."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}" if source else message)


@dataclass(frozen=True)
class EnvConfig:
    """环境配置的只读快照（REQ-M7 §2）.

    内部以「组 → 参数 → 标量值」的二级映射存储。
    不可变，跨用例共享同一实例（执行期间只读语义）。
    """

    # 组 → {参数 → 值}
    _groups: Mapping[str, Mapping[str, _Scalar]]
    source: str | None = None

    # ------------------------------------------------------------------
    # 解析与访问
    # ------------------------------------------------------------------
    def resolve_str(self, ref: str) -> str:
        """解析 ``group.param`` 或简单名引用，返回字符串形式.

        Raises:
            UndefinedReferenceError: 引用未定义。
        """
        value = self._lookup(ref)
        if value is _MISSING:
            raise UndefinedReferenceError(ref)
        return _to_str(value)

    def has(self, name: str) -> bool:
        """简单名是否在环境配置中定义（默认组查找）."""
        return self._lookup(name) is not _MISSING

    def _lookup(self, ref: str) -> _Scalar | object:
        parts = ref.split(".")
        if len(parts) == 1:
            # 简单名 → 默认组（§4.2）
            return self._groups.get(_DEFAULT_GROUP, {}).get(parts[0], _MISSING)
        if len(parts) == 2:
            group, param = parts
            return self._groups.get(group, {}).get(param, _MISSING)
        return _MISSING

    def groups(self) -> Mapping[str, Mapping[str, _Scalar]]:
        """返回全部组的只读视图."""
        return self._groups

    def items(self) -> Iterator[tuple[str, str, _Scalar]]:
        """遍历所有 (group, param, value) 三元组（UI 面板渲染用）."""
        for gname, params in self._groups.items():
            for pname, val in params.items():
                yield gname, pname, val

    def is_empty(self) -> bool:
        return not self._groups


# 哨兵：与 None 区分（None 也可能是合法值，虽然不推荐）
_MISSING: object = object()


def _to_str(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------
_yaml = YAML(typ="safe")


def load_env_config(data: str | bytes, *, source: str | None = None) -> EnvConfig:
    """从 YAML 文本加载环境配置.

    Raises:
        EnvConfigError: YAML 语法错误或结构非法（非两级映射、值非标量等）。
    """
    try:
        raw = _yaml.load(StringIO(data) if isinstance(data, str) else StringIO(data.decode("utf-8")))
    except YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        loc = f"第 {line + 1} 行" if line is not None else "未知行"
        raise EnvConfigError(f"YAML 语法错误（{loc}）：{exc}", source=source) from exc

    if raw is None:
        return EnvConfig(_groups={}, source=source)
    if not isinstance(raw, dict):
        raise EnvConfigError(
            f"环境配置根节点必须是映射，实际为 {type(raw).__name__}", source=source
        )

    groups: dict[str, dict[str, _Scalar]] = {}
    for gname, gval in raw.items():
        if not isinstance(gname, str):
            raise EnvConfigError(f"组名必须是字符串，实际为 {type(gname).__name__}", source=source)
        if not isinstance(gval, dict):
            raise EnvConfigError(
                f"组 {gname!r} 的值必须是映射（键值对），实际为 {type(gval).__name__}",
                source=source,
            )
        params: dict[str, _Scalar] = {}
        for pname, pval in gval.items():
            if not isinstance(pname, str):
                raise EnvConfigError(
                    f"组 {gname!r} 内参数名必须是字符串，实际为 {type(pname).__name__}",
                    source=source,
                )
            if isinstance(pval, dict) or isinstance(pval, list):
                raise EnvConfigError(
                    f"组 {gname!r} 内参数 {pname!r} 不支持嵌套结构（值类型应为标量）"
                    f"，实际为 {type(pval).__name__}",
                    source=source,
                )
            if not isinstance(pval, (str, int, float, bool)):
                raise EnvConfigError(
                    f"组 {gname!r} 内参数 {pname!r} 的值类型 {type(pval).__name__} 不被支持"
                    f"（允许 str/int/float/bool）",
                    source=source,
                )
            params[pname] = pval
        groups[gname] = params

    return EnvConfig(_groups=groups, source=source)


def load_env_config_file(path: str | Path) -> EnvConfig:
    """从 env.yaml 文件加载（文件不存在 → 抛 EnvConfigError）."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnvConfigError(f"无法读取环境配置文件：{exc.strerror or exc}", source=str(p)) from exc
    return load_env_config(text, source=str(p))


def empty_env_config() -> EnvConfig:
    """构造空的环境配置（不依赖环境配置的用例使用）."""
    return EnvConfig(_groups={}, source=None)


# ---------------------------------------------------------------------------
# UI 编辑：写回 env.yaml（M7 §7）
# ---------------------------------------------------------------------------
def dump_env_config(env: EnvConfig) -> str:
    """把 EnvConfig 序列化为 env.yaml 文本（UI「保存」用）."""
    out = StringIO()
    yaml_write = YAML()
    yaml_write.default_flow_style = False
    yaml_write.indent(mapping=2, sequence=4, offset=2)
    data: dict[str, dict[str, _Scalar]] = {
        gname: dict(params) for gname, params in env.groups().items()
    }
    yaml_write.dump(data, out)
    return out.getvalue()
