"""update/installer.py：apply_update 测试（mock Popen/zipfile，不真实替换）。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from atprobe.infra.update import UpdateError
from atprobe.infra.update.installer import apply_update, build_updater_script


def _make_fake_zip(zip_path: Path) -> None:
    """构造含 ATProbe.exe + _internal/ 的假 zip（对齐 CI 真实产物结构）.

    注意：spec 里 GUI exe name="ATProbe"，PyInstaller 产出 ATProbe.exe（大写）。
    早期测试误用小写 atprobe.exe，与真实产物不符，导致真机校验失败而测试通过。
    """
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe-0.3.0/ATProbe.exe", b"PE")
        z.writestr("ATProbe-0.3.0/atprobe-cli.exe", b"PE-CLI")  # CLI exe 应被识别为非主 exe
        z.writestr("ATProbe-0.3.0/_internal/python311.dll", b"dll")
        z.writestr("ATProbe-0.3.0/examples/env.yaml", b"env")  # 应被忽略


def test_apply_update_dev_mode_rejected(tmp_path: Path) -> None:
    """开发态（is_frozen=False）直接拒绝。"""
    zip_path = tmp_path / "update.zip"
    _make_fake_zip(zip_path)
    with patch("atprobe.infra.update.installer.is_frozen", return_value=False):
        with pytest.raises(UpdateError, match="开发态"):
            apply_update(zip_path, tmp_path)


def test_apply_update_corrupt_zip_rejected(tmp_path: Path) -> None:
    """损坏 zip（无 atprobe.exe）拒绝启动脚本。"""
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("foo/bar.txt", b"x")  # 无 exe，无 _internal
    with patch("atprobe.infra.update.installer.is_frozen", return_value=True):
        with pytest.raises(UpdateError, match="损坏"):
            apply_update(zip_path, tmp_path)


def test_apply_update_generates_and_launches_script(tmp_path: Path) -> None:
    """打包态：解压 staging + 生成 bat + detached 启动 Popen。"""
    zip_path = tmp_path / "update.zip"
    _make_fake_zip(zip_path)
    fake_internal = tmp_path / "_internal"
    fake_internal.mkdir()
    (tmp_path / "ATProbe.exe").write_bytes(b"old")

    popen_mock = MagicMock()
    with (
        patch("atprobe.infra.update.installer.is_frozen", return_value=True),
        patch("atprobe.infra.update.installer.subprocess.Popen", return_value=popen_mock) as p_open,
        patch("atprobe.infra.update.installer.os.getpid", return_value=12345),
    ):
        apply_update(zip_path, tmp_path)

    # Popen 被调用一次，启动某个 .bat
    assert p_open.called
    cmd = p_open.call_args[0][0]
    bat_arg = [a for a in cmd if str(a).endswith(".bat") or ".bat" in str(a)]
    assert bat_arg, f"Popen 应启动 .bat 脚本，实际 cmd={cmd}"


def test_updater_script_contains_key_commands(tmp_path: Path) -> None:
    """生成的 bat 必须含关键命令：等待退出 / 备份 / xcopy / 回滚标签 / 重启。"""
    script = build_updater_script(
        exe_path=tmp_path / "ATProbe.exe",
        internal_path=tmp_path / "_internal",
        staging_dir=tmp_path / "ATProbe-0.3.0",
        pid=12345,
    )
    assert "tasklist" in script  # 等待主程序退出
    assert "12345" in script  # PID 嵌入
    assert "ren" in script  # 备份重命名
    assert "xcopy" in script  # 部署
    assert ":rollback" in script  # 回滚标签
    assert "start" in script  # 重启
    assert "chcp 65001" in script  # UTF-8 编码
    assert "mshta" in script  # 失败弹框
    # 防回归：PID 等待用 findstr 精确前缀匹配（非 find 子串匹配，避免 PID 123 误命中 1234）
    assert "findstr" in script
    # 防回归：等待循环的 inc/compare 必须在 ( ) 块外（无 enabledelayedexpansion 时
    # 块内 %tries% 解析期展开恒为 0，30 秒超时永不触发）。检查 "set /a tries+=1"
    # 所在行不以 4 空格缩进出现在 ( 块内。
    wait_lines = [ln for ln in script.splitlines() if "set /a tries" in ln]
    assert wait_lines, "缺少等待循环计数"
    for ln in wait_lines:
        # 行首不应带 "(" 上下文缩进标志：tries 增量须是顶层 goto 循环体
        assert not ln.startswith("    set /a tries+=1"), (
            "tries 增量不能放在 ( ) 块内（会触发解析期展开 bug）"
        )


def test_updater_script_tail_single_line(tmp_path: Path) -> None:
    """复审回归：自删除/重启/退出必须在**同一行**（& 链接）.

    cmd 逐行读 bat——`del %~f0` 执行后文件已删，读下一行失败：分行形态下
    start 与 exit 均不执行（升级成功但不重启）。单行在执行前整体解析，可靠。
    """
    script = build_updater_script(
        exe_path=tmp_path / "ATProbe.exe",
        internal_path=tmp_path / "_internal",
        staging_dir=tmp_path / "ATProbe-0.3.0",
        pid=12345,
    )
    tail_lines = [ln for ln in script.splitlines() if "%~f0" in ln]
    assert tail_lines, "缺少自删除行"
    for ln in tail_lines:
        assert "del" in ln
        # del 行必须同时含后续动作（& 链接）——独立 del 行是回归
        assert "&" in ln, f"自删除行必须单行 & 链接重启/退出，实际：{ln!r}"
        if "start" in ln or "exit" in ln:
            assert "start" in ln and "exit" in ln, f"del/start/exit 须同行：{ln!r}"


def test_updater_script_findstr_space_delimited(tmp_path: Path) -> None:
    """复审回归：PID 匹配用空格定界（tasklist 行首是映像名，/b 锚行首永不命中）."""
    script = build_updater_script(
        exe_path=tmp_path / "ATProbe.exe",
        internal_path=tmp_path / "_internal",
        staging_dir=tmp_path / "ATProbe-0.3.0",
        pid=4242,
    )
    findstr_lines = [ln for ln in script.splitlines() if "| findstr" in ln]
    assert findstr_lines
    for ln in findstr_lines:
        assert "/b" not in ln, f"findstr 不可用 /b 行首锚定（PID 在第 2 列）：{ln!r}"
        assert '" 4242 "' in ln or '" %PID% "' in ln, f"须空格定界匹配 PID：{ln!r}"


def test_ensure_recovered_rename_only_no_rmtree(tmp_path: Path) -> None:
    """复审回归：恢复路径绝不含 rmtree(current)（会半毁被锁定的 _internal）."""
    import inspect

    from atprobe.infra.update.installer import ensure_recovered

    src = inspect.getsource(ensure_recovered)
    assert "rmtree(current" not in src and "rmtree(\n" not in src.replace(" ", ""), (
        "恢复路径不得 rmtree current（bootloader 锁定 dll → 半毁）"
    )
    # 基本行为：无 pending/bak → False；有 → rename 恢复
    assert ensure_recovered(tmp_path) is False
    (tmp_path / "_internal.bak").mkdir()
    (tmp_path / "_internal.bak" / "old.txt").write_text("old")
    (tmp_path / "_internal.update.pending").write_text("pending")
    # current 不存在 → bak 直接顶上
    assert ensure_recovered(tmp_path) is True
    assert (tmp_path / "_internal" / "old.txt").read_text() == "old"
    assert not (tmp_path / "_internal.update.pending").exists()


def test_updater_script_paths_quoted(tmp_path: Path) -> None:
    """路径含空格时 bat 内必须加引号（防 PATH/参数注入）。"""
    exe = Path("D:/my tools/ATProbe/ATProbe.exe")
    script = build_updater_script(
        exe_path=exe,
        internal_path=exe.parent / "_internal",
        staging_dir=exe.parent / "ATProbe-0.3.0",
        pid=1,
    )
    assert '"D:/my tools/ATProbe/ATProbe.exe"' in script or (
        '"D:\\my tools\\ATProbe\\ATProbe.exe"' in script
    )


def test_updater_script_uses_staging_exe_name(tmp_path: Path) -> None:
    """回归：bat 的 copy 命令必须用 staging 真实 exe 名（ATProbe.exe），而非硬编码小写。

    bug：早期 bat 硬编码 copy "staging\\atprobe.exe"，但 CI 产出 ATProbe.exe。
    Windows 大小写不敏感时能跑通，但语义错误且跨平台/路径敏感场景会失败。
    修复后 staging_exe_name 参数注入真实名。
    """
    script = build_updater_script(
        exe_path=tmp_path / "ATProbe.exe",
        internal_path=tmp_path / "_internal",
        staging_dir=tmp_path / "ATProbe-0.3.1",
        pid=1,
        staging_exe_name="ATProbe.exe",
    )
    # copy 命令应引用 staging 下的真实 exe 名（ATProbe.exe，大小写保留）
    script_bs = script.replace("/", "\\")
    assert "ATProbe-0.3.1\\ATProbe.exe" in script_bs, (
        f"bat 应从 staging 复制真实名 ATProbe.exe，实际:\n{script}"
    )
    # 部署 copy 行不应是旧的硬编码小写 atprobe.exe
    copy_lines = [
        ln for ln in script.splitlines() if ln.strip().startswith("copy /y") and "%EXE%" in ln
    ]
    assert copy_lines, "应存在 copy 到 %EXE% 的部署行"
    for ln in copy_lines:
        assert "atprobe.exe" not in ln.lower() or "ATProbe.exe" in ln, (
            f"部署 copy 行不应硬编码小写 atprobe.exe：{ln!r}"
        )


def test_validate_zip_accepts_real_ci_layout(tmp_path: Path) -> None:
    """回归：CI 真实产物 zip（顶层 ATProbe-<ver>/ATProbe.exe + _internal/）必须通过校验。

    bug：早期 _validate_zip 用大小写敏感 endswith('atprobe.exe') 校验，
    而 CI 产出 ATProbe.exe（大写），导致真机报"缺少 atprobe.exe"。
    """
    zip_path = tmp_path / "ATProbe-0.3.1-win64.zip"
    _make_fake_zip(zip_path)  # 含 ATProbe.exe + atprobe-cli.exe + _internal/
    # 不应抛异常（直接调用内部函数）
    from atprobe.infra.update.installer import _validate_zip

    _validate_zip(zip_path)  # 通过即成功


# ---------------------------------------------------------------------------
# S-6 installer 加固：_internal 精确匹配 + bat % 转义
# ---------------------------------------------------------------------------
def test_validate_zip_rejects_internal_prefix_imposter(tmp_path: Path) -> None:
    """`_internal-evil/x` 子串可撞过旧校验（`_INTERNAL_NAME in n`），精确匹配须拒绝。"""
    from atprobe.infra.update.installer import _validate_zip

    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe-0.3.0/ATProbe.exe", b"PE")
        z.writestr("ATProbe-0.3.0/_internal-evil/payload.txt", b"evil")  # 撞名前缀
    with pytest.raises(UpdateError, match="损坏"):
        _validate_zip(zip_path)


def test_validate_zip_rejects_embedded_internal_substring(tmp_path: Path) -> None:
    """`docs_internal.txt` / `my_internal/` 等含 `_internal` 子串的成员不算数。"""
    from atprobe.infra.update.installer import _validate_zip

    zip_path = tmp_path / "sub.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe-0.3.0/ATProbe.exe", b"PE")
        z.writestr("ATProbe-0.3.0/docs_internal.txt", b"n")
        z.writestr("ATProbe-0.3.0/my_internal/x.txt", b"n")
    with pytest.raises(UpdateError, match="损坏"):
        _validate_zip(zip_path)


def test_validate_zip_accepts_uppercase_internal(tmp_path: Path) -> None:
    """大小写归一：`_INTERNAL/`（大写）成员应通过（Windows 文件系统大小写不敏感）。"""
    from atprobe.infra.update.installer import _validate_zip

    zip_path = tmp_path / "upper.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe-0.3.0/ATProbe.exe", b"PE")
        z.writestr("ATProbe-0.3.0/_INTERNAL/python311.dll", b"dll")
    _validate_zip(zip_path)  # 不抛即通过


def test_validate_zip_accepts_top_level_internal(tmp_path: Path) -> None:
    """顶层无版本目录的扁平布局（_internal 直接在根）也应通过（路径段精确匹配）。"""
    from atprobe.infra.update.installer import _validate_zip

    zip_path = tmp_path / "flat.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe.exe", b"PE")
        z.writestr("_internal/python311.dll", b"dll")
    _validate_zip(zip_path)


def test_bat_escape_doubles_percent() -> None:
    """`%` → `%%`（bat 双引号内 %VAR% 仍展开，须转义）。"""
    from atprobe.infra.update.installer import _bat_escape

    assert _bat_escape("C:\\100%fun\\ATProbe") == "C:\\100%%fun\\ATProbe"
    assert _bat_escape("%PROGRAMFILES%\\x") == "%%PROGRAMFILES%%\\x"
    assert _bat_escape("D:\\plain\\path") == "D:\\plain\\path"  # 无 % 不变


def test_updater_script_escapes_percent_in_paths(tmp_path: Path) -> None:
    """安装路径含 % 时，bat 内所有路径插值点都必须转义为 %%（防 %VAR% 展开）。"""
    exe = Path("D:/100%fun/ATProbe/ATProbe.exe")
    script = build_updater_script(
        exe_path=exe,
        internal_path=exe.parent / "_internal",
        staging_dir=exe.parent / "ATProbe-0.3.0",
        pid=1,
    )
    # 转义形态必须出现（set 行 + copy 目标 + start 重启行）
    assert "D:\\100%%fun\\ATProbe\\ATProbe.exe" in script
    assert "D:\\100%%fun\\ATProbe\\_internal" in script
    assert "D:\\100%%fun\\ATProbe\\ATProbe-0.3.0" in script
    # 未转义形态（单个 % 后跟字面文本）不得出现
    assert "D:\\100%fun" not in script
    # 真正的 bat 变量引用（%~f0 / %PID% / %tries%）不被转义破坏
    assert "%~f0" in script
    assert "%PID%" in script
