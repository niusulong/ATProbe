"""升级子系统可调参数集中地（常量集合，不暴露到 atprobe.yaml）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateConfig:
    """升级检查/下载的可调参数。默认值即生产值；测试可传入不同值隔离。"""

    api_base: str = "https://api.github.com"
    repo: str = "niusulong/ATProbe"
    check_timeout: float = 8.0  # 检查请求超时（秒）
    download_timeout: float = 30.0  # 下载连接超时（秒）
    asset_name_template: str = "ATProbe-{version}-win64.zip"

    def asset_name_for(self, version: str) -> str:
        """渲染具体版本的 Windows zip 资产名。"""
        return self.asset_name_template.format(version=version)


DEFAULT_CONFIG = UpdateConfig()
