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
    with patch("atprobe.infra.update.installer.is_frozen", return_value=True), patch(
        "atprobe.infra.update.installer.subprocess.Popen", return_value=popen_mock
    ) as p_open, patch(
        "atprobe.infra.update.installer.os.getpid", return_value=12345
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
