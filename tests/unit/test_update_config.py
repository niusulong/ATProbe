"""update 子系统配置 + 异常测试。"""

from __future__ import annotations

from atprobe.infra.update import (
    AssetNotFoundError,
    DownloadCancelled,
    DownloadError,
    UpdateCheckError,
    UpdateError,
)
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig


def test_default_config_values() -> None:
    c = DEFAULT_CONFIG
    assert c.api_base == "https://api.github.com"
    assert c.repo == "niusulong/ATProbe"
    assert c.check_timeout == 8.0
    assert c.download_timeout == 30.0
    assert c.asset_name_template == "ATProbe-{version}-win64.zip"


def test_config_is_frozen() -> None:
    c = UpdateConfig()
    try:
        c.api_base = "x"  # type: ignore[misc]
        raise AssertionError("应冻结，不可变")
    except Exception as exc:  # noqa: BLE001
        # frozen dataclass 抛 FrozenInstanceError
        assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower()


def test_asset_name_for_version() -> None:
    """asset_name_template 渲染具体版本号。"""
    assert DEFAULT_CONFIG.asset_name_for("0.3.0") == "ATProbe-0.3.0-win64.zip"


def test_exception_hierarchy() -> None:
    """所有 update 异常都是 UpdateError 子类（便于上层统一 catch）。"""
    assert issubclass(UpdateCheckError, UpdateError)
    assert issubclass(AssetNotFoundError, UpdateError)
    assert issubclass(DownloadError, UpdateError)
    # DownloadCancelled 单独继承（非错误，是用户意图），但也是基类
    assert not issubclass(DownloadCancelled, UpdateError)
