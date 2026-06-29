"""远程升级子系统：检查更新、下载、原地安装。

对外导出：
    - 配置：UpdateConfig（见 config.py）
    - 异常：UpdateError（基类）/ UpdateCheckError / AssetNotFoundError /
            DownloadError / DownloadCancelled
    - 主要 API 见 checker / downloader / installer 各模块。
"""

from __future__ import annotations


class UpdateError(Exception):
    """升级相关错误基类（检查/下载/安装失败均收敛到此或其子类）。"""


class UpdateCheckError(UpdateError):
    """版本检查失败（网络/HTTP/解析）。"""


class AssetNotFoundError(UpdateError):
    """某 Release 无匹配的 Windows 安装包。"""


class DownloadError(UpdateError):
    """下载失败（网络/磁盘/HTTP/大小不符）。"""


class DownloadCancelled(Exception):
    """用户主动取消下载（非错误，不继承 UpdateError）。"""
