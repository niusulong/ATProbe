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

# GUI 主 exe 名（spec 里 EXE name="ATProbe"，PyInstaller 产出 ATProbe.exe）。
# 校验/部署都用这个名字；CLI exe（atprobe-cli.exe）不在原地替换范围。
_EXE_NAME = "ATProbe.exe"
_INTERNAL_NAME = "_internal"


def ensure_recovered(app_root: Path) -> bool:
    """启动侧中断恢复（P2 修复）：检测上次升级被中断的残留并回滚.

    updater.bat 在动 ``_internal`` 前写 ``_internal.update.pending`` 标记，成功与
    回滚两条退出路径都会删除它。若标记残留且 ``_internal.bak`` 存在，说明上次
    升级中途被杀（断电/强杀 bat）。

    复审重构（防半毁）：冻结进程的 bootloader 已锁定 ``_internal/python3xx.dll``
    等文件——**rmtree 会把未锁文件删光而留下锁定的 dll**（半毁：后续 import
    PySide6 直接 ModuleNotFoundError）。因此恢复只做**原子 rename**：
    current → ``_internal.broken``（探测锁定：rename 含打开文件的目录在
    Windows 上失败 → 说明本进程正占用 _internal，**整体放弃恢复**，原状启动
    比半毁强）；成功后 bak → current。运行中的 exe 不可删除/替换（进程映像
    锁定），启动侧不碰 exe——exe 的还原由 bat 的 rollback 分支负责。

    Returns:
        True 表示执行了回滚（调用方可提示用户重新升级）。
    """
    pending = app_root / (_INTERNAL_NAME + ".update.pending")
    backup = app_root / (_INTERNAL_NAME + ".bak")
    current = app_root / _INTERNAL_NAME
    if not (pending.exists() and backup.exists()):
        return False
    broken = app_root / (_INTERNAL_NAME + ".broken")
    try:
        if current.exists():
            # 清掉上次恢复尝试的残骸（无锁，通常可删）
            if broken.exists():
                shutil.rmtree(broken, ignore_errors=True)
            try:
                current.rename(broken)
            except OSError:
                # rename 失败 = _internal 被本进程锁定 → 放弃恢复（保持原状），
                # 绝不走 rmtree（会半毁：未锁文件删光、锁定 dll 留存）
                return False
        backup.rename(current)
        pending.unlink(missing_ok=True)
    except OSError:
        return False
    return True


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

    # staging 里主 exe 的真实文件名（大小写与 zip 产物一致，传给 bat 用于 copy）
    staging_exe = _find_exe(staging_app)
    if staging_exe is None:
        raise UpdateError("安装包结构异常：找不到主程序 exe")
    staging_exe_name = staging_exe.name
    # M8：查找 staging 里的 CLI exe（atprobe-cli.exe），若存在则 bat 同时替换
    staging_cli_exe_name: str | None = None
    for candidate in staging_app.iterdir():
        if candidate.is_file() and candidate.name.lower() == "atprobe-cli.exe":
            staging_cli_exe_name = candidate.name
            break

    exe_path = app_root / _EXE_NAME
    internal_path = app_root / _INTERNAL_NAME
    pid = os.getpid()

    script = build_updater_script(
        exe_path=exe_path,
        internal_path=internal_path,
        staging_dir=staging_app,
        pid=pid,
        restart=restart,
        staging_exe_name=staging_exe_name,
        staging_cli_exe_name=staging_cli_exe_name,
    )
    bat_path = Path(tempfile.gettempdir()) / "atprobe-updater.bat"
    # M9 修复：用 utf-8-sig（带 BOM）写 bat，兼容中文用户路径。
    # chcp 65001 只影响 echo/set 显示，不影响 cmd 解析 bat 源字节的编码；
    # 无 BOM 的 UTF-8 bat 在中文 Windows（默认 ANSI=GBK）下，含中文的 set 值会被
    # 按 GBK 解析导致 xcopy 找不到路径。BOM 让 cmd 按 UTF-8 解析 bat 源字节。
    bat_path.write_text(script, encoding="utf-8-sig")

    try:
        subprocess.Popen(  # noqa: S603,S607 - cmd 是 Windows 系统命令
            ["cmd", "/c", "start", "/b", "", str(bat_path)],
            # CREATE_NEW_PROCESS_GROUP 仅 Windows 存在；Linux（CI 单测）取 0。
            # 升级流程本身只在 Windows 运行，此处仅为让单测跨平台通过。
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError(f"无法启动更新程序：{exc}") from exc


def _validate_zip(zip_path: Path) -> None:
    """zip 必须可打开且含 ATProbe.exe + _internal/。

    exe 名校验大小写不敏感（容错：spec 改大小写时不致再次翻车），
    但排除 atprobe-cli.exe（CLI exe 不是原地替换目标）。
    """
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise UpdateError(f"安装包损坏：{exc}") from exc
    target = _EXE_NAME.lower()
    cli_name = "atprobe-cli.exe"
    has_exe = any(
        n.lower().endswith("/" + target) or (n.lower() == target)
        for n in names
        if not n.lower().endswith("/" + cli_name)
    )
    has_internal = any(_INTERNAL_NAME in n for n in names)
    if not (has_exe and has_internal):
        raise UpdateError(f"安装包损坏：缺少 {_EXE_NAME} 或 {_INTERNAL_NAME}/")


def _clean_dir(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        # P3 修复：清理失败（被锁文件残留）不再静默吞——否则新旧版本文件混入
        # 下次 staging（rmtree ignore_errors 掩盖了部分删除）
        if d.exists():
            raise UpdateError(f"无法清空目录（可能被占用）：{d}")
    d.mkdir(parents=True, exist_ok=True)


def _extract_staging(zip_path: Path, staging_root: Path) -> Path:
    """解压 zip 到 staging_root，返回含主 exe 的应用目录."""
    with zipfile.ZipFile(zip_path) as z:
        # P3 修复（zip-slip 消毒）：成员名含 ../ 等相对路径时可写出 staging 外。
        # 当前 zip 来自可信 GitHub Releases + SHA256 校验，属纵深防御。
        # 复审补充：`\` 分隔的 `..\evil` 对 PurePosixPath 是单段——先归一为
        # 正斜杠再判（盘符 `C:` 同理被 posix 语义视为普通段，归一后可拦）。
        from pathlib import PurePosixPath

        for member in z.namelist():
            norm = member.replace("\\", "/")
            p = PurePosixPath(norm)
            if p.is_absolute() or ".." in p.parts or (len(norm) > 1 and norm[1] == ":"):
                raise UpdateError(f"安装包含非法路径成员：{member!r}")
        z.extractall(staging_root)
    # zip 顶层目录名形如 ATProbe-<ver>/，找到含主 exe（ATProbe.exe）的目录。
    # 大小写不敏感探测（Windows 文件系统本身大小写不敏感，且 spec 名可能调整）。
    for item in staging_root.iterdir():
        if item.is_dir() and _find_exe(item) is not None:
            return item
    # 兜底：exe 直接在 staging_root
    if _find_exe(staging_root) is not None:
        return staging_root
    raise UpdateError("安装包结构异常：找不到应用目录")


def _find_exe(directory: Path) -> Path | None:
    """在目录下大小写不敏感地查找主 GUI exe（ATProbe.exe），排除 atprobe-cli.exe。"""
    target = _EXE_NAME.lower()
    cli_name = "atprobe-cli.exe"
    for p in directory.iterdir():
        if p.is_file() and p.name.lower() == target and p.name.lower() != cli_name:
            return p
    return None


def build_updater_script(
    *,
    exe_path: Path,
    internal_path: Path,
    staging_dir: Path,
    pid: int,
    restart: bool = True,
    staging_exe_name: str = _EXE_NAME,
    staging_cli_exe_name: str | None = None,
) -> str:
    """生成 updater.bat 内容（Windows 批处理）。

    所有路径加引号，防含空格/中文。bat 逻辑：等待退出 → 备份 → 替换 → 重启 / 失败回滚。

    Args:
        staging_exe_name: staging 目录里主 exe 的真实文件名（大小写与 zip 产物一致），
            默认 ATProbe.exe。bat 用它从 staging 复制到目标。
        staging_cli_exe_name: M8 修复——staging 目录里 CLI exe 的真实文件名（如
            atprobe-cli.exe）。非空时 bat 同时替换 CLI exe，避免 GUI 升级后 CLI 仍是旧版。
    """
    exe = _win(str(exe_path))
    internal = _win(str(internal_path))
    staging = _win(str(staging_dir))
    backup = _win(str(internal_path) + ".bak")
    exe_bak = _win(str(exe_path) + ".bak")
    staging_exe = _win(str(staging_dir / staging_exe_name))
    restart_cmd = f'start "" "{exe}"' if restart else "exit /b 0"
    # M8：CLI exe 替换块（仅 staging 含 atprobe-cli.exe 时执行）
    cli_replace_block = ""
    if staging_cli_exe_name is not None:
        staging_cli = _win(str(staging_dir / staging_cli_exe_name))
        cli_dest = _win(str(exe_path.parent / staging_cli_exe_name))
        # P3 修复：CLI copy 加错误检查（旧实现失败静默 → GUI 已升级、CLI 仍旧版）
        cli_replace_block = (
            f'if exist "{staging_cli}" (\n'
            f'    copy /y "{staging_cli}" "{cli_dest}" >nul\n'
            f"    if errorlevel 1 goto rollback\n)\n"
        )
    # P3 修复：重启命令不放进括号块（exe 路径含 ")" 时 cmd 解析错乱）。
    # 自删除/重启/退出必须**同一行 & 链接**——cmd 逐行读 bat，`del %~f0` 后再读
    # 下一行会失败（实测：分行时 start 与 exit 均不执行，升级成功但不重启）；
    # 单行在执行前整体解析，三段全部可靠执行。
    tail_cmd = f'del "%~f0" 2>nul & {restart_cmd} & exit /b 0\n'
    return f"""@echo off
chcp 65001 >nul
setlocal

set "EXE={exe}"
set "INTERNAL={internal}"
set "STAGING={staging}"
set "BACKUP={backup}"
set "EXE_BAK={exe_bak}"
set "PID={pid}"
set "PENDING={internal}.update.pending"

REM 1. 等待主程序退出（轮询，最长约 30 秒）
REM 注意：inc/compare 不能放在 ( ) 块内（无 enabledelayedexpansion 时 %tries%
REM 在解析期展开，永远是 0），故用 goto 循环把判断放在块外。
REM P1 修复：旧实现 findstr /b 锚定行首匹配 PID，而 tasklist 输出行首是映像名
REM （PID 在第 2 列）→ 永不命中 → 立即 goto waited，等待循环形同虚设，升级与
REM 退出中的主进程抢文件锁（间歇性升级失败回滚）。改为按空格定界 token 匹配
REM （" %PID% " 两侧空格避免 123 误命中 1234）。
REM 另：timeout /t 在无控制台（双击 GUI 启动）下报错直接跳过等待，改用 ping 计时。
set /a tries=0
:wait
tasklist /fi "pid eq %PID%" /nh 2>nul | findstr /c:" %PID% " >nul
if errorlevel 1 goto waited
set /a tries+=1
if %tries% GEQ 30 goto rollback
ping -n 2 127.0.0.1 >nul
goto wait
:waited

REM P2 修复（中断恢复标记）：写 pending 标记后再动 _internal；成功与回滚两条
REM 退出路径都会删除它。若升级中途被杀（断电/强杀 bat），标记残留 → 主程序
REM 下次启动检测到 [_internal.bak + pending] 自动回滚（ensure_recovered）。
del "%PENDING%" 2>nul
echo pending> "%PENDING%"

REM 2. 备份旧版
if exist "%BACKUP%" rmdir /s /q "%BACKUP%"
ren "%INTERNAL%" "_internal.bak"
if errorlevel 1 goto rollback
copy /y "%EXE%" "%EXE_BAK%" >nul
if errorlevel 1 goto rollback

REM 3. 部署新版
xcopy /e /i /y "%STAGING%\\_internal" "%INTERNAL%" >nul
if errorlevel 1 goto rollback
copy /y "{staging_exe}" "%EXE%" >nul
if errorlevel 1 goto rollback
{cli_replace_block}
REM 4. 成功：清理 + 重启
del "%PENDING%" >nul 2>&1
rmdir /s /q "%BACKUP%"
del "%EXE_BAK%" 2>nul
rmdir /s /q "%STAGING%"
{tail_cmd}
exit /b 0

:rollback
del "%PENDING%" >nul 2>&1
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
