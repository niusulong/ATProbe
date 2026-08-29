"""`update` 子命令：检查更新 / 交互安装 / 非交互安装。

复用 infra/update 的 checker/session/installer（D-3：下载编排收敛到
UpdateSession，本层只做展示与交互），只在展示与交互层不同。

顶层只留 typer/stdlib（infra.update 经 checker 拉 pydantic，下沉到命令体，
其它子命令不为 update 的网络/校验链买单）。
"""

from __future__ import annotations

import sys

import typer

from atprobe.infra.runtime import app_root, is_frozen
from atprobe.infra.version import current_version, is_version_known


def update(
    check_only: bool = typer.Option(False, "--check", help="只检查是否有新版，不下载"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认直接安装（非交互）"),
) -> None:
    """检查并安装 ATProbe 最新版本。"""
    # 重型依赖下沉到命令体（见模块 docstring）
    from atprobe.infra.update import (
        DownloadCancelled,
        DownloadError,
        UpdateError,
    )
    from atprobe.infra.update.checker import fetch_latest, is_newer
    from atprobe.infra.update.installer import apply_update
    from atprobe.infra.update.session import UpdateSession

    local = current_version()
    try:
        info = fetch_latest()
    except UpdateError as exc:
        # P2 修复：捕获 UpdateError 基类——旧实现只捕 UpdateCheckError，漏掉
        # AssetNotFoundError（Release 缺 Windows 安装包时 checker 抛它）→ 裸 traceback
        typer.secho(f"检查失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if not is_version_known(local):
        # VERSION 缺失时 current_version() 回退 '0.0.0'——不能当真实版本参与
        # semver 比较（任何远端版本都"更新"，恒提示升级误导用户）。给特殊文案
        # 并给出 Release 页，不进入升级流程。
        typer.secho(
            f"无法确定当前版本（VERSION 文件缺失，读取到回退值 {local}），请从 Release 页确认。",
            fg=typer.colors.YELLOW,
        )
        typer.echo(f"最新版本：{info.version}")
        typer.echo(f"Release 页：{info.html_url}")
        return

    if not is_newer(info.version, local):
        typer.echo(f"当前 {local}，已是最新版本。")
        return

    # P3：预发布版本显式标注，避免 -rc1 被 semver 比较剥掉后缀后当正式版推荐
    ver_label = f"{info.version}（预发布）" if info.prerelease else info.version
    typer.echo(f"当前 {local}，最新 {ver_label}，有新版本可用。")
    typer.echo(f"下载：{info.zip_url}")
    typer.echo(f"大小：{_mb(info.zip_size)} MB")
    if info.release_notes:
        typer.echo("\n更新内容：")
        typer.echo(info.release_notes)

    if check_only:
        return

    # 开发态直接拒绝安装（installer 内部也会拒绝，这里提前给清晰提示）
    if not is_frozen():
        typer.secho("开发态不支持自更新，请用 git pull。", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)

    if not yes:
        confirm = typer.confirm(f"确认升级到 {ver_label}？", default=False)
        if not confirm:
            typer.echo("已取消。")
            return

    try:
        # D-3：下载编排收敛 UpdateSession（文件名模板/校验参数/签名策略单点）
        result = UpdateSession().download(info, progress_cb=_print_progress)
    except DownloadCancelled:
        # 退出码口径：用户主动取消不是错误 → 0（旧实现 1，脚本无法区分失败与取消）
        typer.echo("\n已取消下载。")
        raise typer.Exit(0) from None
    except DownloadError as exc:
        typer.secho(f"\n下载失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    typer.echo("\n下载完成，开始安装（程序将退出并重启）...")
    try:
        apply_update(result.path, app_root())
    except UpdateError as exc:
        typer.secho(f"安装失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    # 脚本已 detached 启动，主动退出释放文件锁
    typer.echo("正在退出以完成升级...")
    raise typer.Exit(0)


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.1f}"


def _print_progress(done: int, total: int) -> None:
    if total <= 0:
        return
    pct = done * 100 // total
    sys.stdout.write(f"\r下载中... {pct}%  ({_mb(done)}/{_mb(total)} MB)")
    sys.stdout.flush()
