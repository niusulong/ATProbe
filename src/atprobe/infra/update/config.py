"""升级子系统可调参数集中地（常量集合，不暴露到 atprobe.yaml）。"""

from __future__ import annotations

from dataclasses import dataclass

# S-5：内置下载主机白名单（GitHub Releases 官方发布链路）。
# downloader 的入口校验与重定向复检都以此为准；用户可经 allowed_hosts 追加
# （自建镜像/私有发布源），不可收窄内置项。
_DEFAULT_ALLOWED_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "api.github.com",
    "github-releases.githubusercontent.com",
)


@dataclass(frozen=True)
class UpdateConfig:
    """升级检查/下载的可调参数。默认值即生产值；测试可传入不同值隔离。"""

    api_base: str = "https://api.github.com"
    repo: str = "niusulong/ATProbe"
    check_timeout: float = 8.0  # 检查请求超时（秒）
    download_timeout: float = 30.0  # 下载连接超时（秒）
    asset_name_template: str = "ATProbe-{version}-win64.zip"
    # S-5：用户追加的下载主机（镜像/自建发布源）。与内置白名单合并生效，
    # 见 effective_allowed_hosts()。
    allowed_hosts: tuple[str, ...] = ()

    def asset_name_for(self, version: str) -> str:
        """渲染具体版本的 Windows zip 资产名。"""
        return self.asset_name_template.format(version=version)

    def effective_allowed_hosts(self) -> tuple[str, ...]:
        """下载主机白名单全集 = 内置 GitHub 白名单 + 用户追加项。"""
        return _DEFAULT_ALLOWED_HOSTS + tuple(self.allowed_hosts)


DEFAULT_CONFIG = UpdateConfig()
