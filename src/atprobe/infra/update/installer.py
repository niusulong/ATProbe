"""安装器：主程序退出后，原地替换 atprobe.exe + _internal/，保留用户工作区。

机制（避 Windows 文件锁）：
    1. 主程序解压 zip 到 staging，生成 updater.bat，detached 启动 bat
    2. 主程序自行退出（释放 exe 文件锁）
    3. bat 轮询等待主程序进程消失 → 备份 .bak → xcopy 新版 → 成功删 .bak 重启；
       失败回滚 .bak 并弹错误框

只替换 atprobe.exe + _internal/，绝不碰 reports/logs/atprobe.yaml/examples。
开发态禁用（is_frozen() 守卫）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from atprobe.infra.runtime import is_frozen
from atprobe.infra.update import UpdateError

_EXE_NAME = "atprobe.exe"
_INTERNAL_NAME = "_internal"


def apply_update(
    zip_path: Path,
    app_root: Path,
    *,
    restart: bool = True,
) -> None:
    """准备并 detached 启动原地替换。调用后主程序应立即自行退出。

    Raises:
        UpdateError: 开发态调用 / zip 损坏 / 启动失败。
    """
    if not is_frozen():
        raise UpdateError("开发态不支持自更新，请用 git pull 更新代码")

    _validate_zip(zip_path)

    staging_root = Path(tempfile.gettempdir()) / "atprobe-staging"
    _clean_dir(staging_root)
    staging_app = _extract_staging(zip_path, staging_root)

    exe_path = app_root / _EXE_NAME
    internal_path = app_root / _INTERNAL_NAME
    pid = os.getpid()

    script = build_updater_script(
        exe_path=exe_path,
        internal_path=internal_path,
        staging_dir=staging_app,
        pid=pid,
        restart=restart,
    )
    bat_path = Path(tempfile.gettempdir()) / "atprobe-updater.bat"
    bat_path.write_text(script, encoding="utf-8")

    try:
        subprocess.Popen(  # noqa: S603,S607 - cmd 是 Windows 系统命令
            ["cmd", "/c", "start", "/b", "", str(bat_path)],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined]
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError(f"无法启动更新程序：{exc}") from exc


def _validate_zip(zip_path: Path) -> None:
    """zip 必须可打开且含 atprobe.exe + _internal/。"""
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise UpdateError(f"安装包损坏：{exc}") from exc
    has_exe = any(n.endswith("/" + _EXE_NAME) or n.endswith(_EXE_NAME) for n in names)
    has_internal = any(_INTERNAL_NAME in n for n in names)
    if not (has_exe and has_internal):
        raise UpdateError("安装包损坏：缺少 atprobe.exe 或 _internal/")


def _clean_dir(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)


def _extract_staging(zip_path: Path, staging_root: Path) -> Path:
    """解压 zip 到 staging_root，返回含 atprobe.exe 的应用目录。"""
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(staging_root)
    # zip 顶层目录名形如 ATProbe-<ver>/，找到含 atprobe.exe 的目录
    for item in staging_root.iterdir():
        if item.is_dir() and (item / _EXE_NAME).exists():
            return item
    # 兜底：exe 直接在 staging_root
    if (staging_root / _EXE_NAME).exists():
        return staging_root
    raise UpdateError("安装包结构异常：找不到应用目录")


def build_updater_script(
    *,
    exe_path: Path,
    internal_path: Path,
    staging_dir: Path,
    pid: int,
    restart: bool = True,
) -> str:
    """生成 updater.bat 内容（Windows 批处理）。

    所有路径加引号，防含空格/中文。bat 逻辑：等待退出 → 备份 → 替换 → 重启 / 失败回滚。
    """
    exe = _win(str(exe_path))
    internal = _win(str(internal_path))
    staging = _win(str(staging_dir))
    backup = _win(str(internal_path) + ".bak")
    exe_bak = _win(str(exe_path) + ".bak")
    restart_cmd = f'start "" "{exe}"' if restart else "exit /b 0"
    return f"""@echo off
chcp 65001 >nul
setlocal

set "EXE={exe}"
set "INTERNAL={internal}"
set "STAGING={staging}"
set "BACKUP={backup}"
set "EXE_BAK={exe_bak}"
set "PID={pid}"

REM 1. 等待主程序退出（轮询，最长约 30 秒）
REM 注意：inc/compare 不能放在 ( ) 块内（无 enabledelayedexpansion 时 %tries%
REM 在解析期展开，永远是 0），故用 goto 循环把判断放在块外。
set /a tries=0
:wait
tasklist /fi "pid eq %PID%" /nh 2>nul | findstr /b /c:"%PID% " >nul
if errorlevel 1 goto waited
set /a tries+=1
if %tries% GEQ 30 goto rollback
timeout /t 1 /nobreak >nul
goto wait
:waited

REM 2. 备份旧版
if exist "%BACKUP%" rmdir /s /q "%BACKUP%"
ren "%INTERNAL%" "_internal.bak"
if errorlevel 1 goto rollback
copy /y "%EXE%" "%EXE_BAK%" >nul
if errorlevel 1 goto rollback

REM 3. 部署新版
xcopy /e /i /y "%STAGING%\\_internal" "%INTERNAL%" >nul
if errorlevel 1 goto rollback
copy /y "%STAGING%\\atprobe.exe" "%EXE%" >nul
if errorlevel 1 goto rollback

REM 4. 成功：清理 + 重启
rmdir /s /q "%BACKUP%"
del "%EXE_BAK%" 2>nul
rmdir /s /q "%STAGING%"
(del "%~f0" & {restart_cmd})
exit /b 0

:rollback
if exist "%BACKUP%" (
    if exist "%INTERNAL%" rmdir /s /q "%INTERNAL%"
    ren "%BACKUP%" "_internal"
)
if exist "%EXE_BAK%" move /y "%EXE_BAK%" "%EXE%" >nul
mshta javascript:alert("ATProbe 升级失败，已恢复旧版本。请稍后重试。");close()
exit /b 1
"""


def _win(p: str) -> str:
    """路径转 Windows 风格反斜杠（bat 友好）。"""
    return p.replace("/", "\\")
