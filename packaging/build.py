"""ATProbe 一键构建脚本（本地与 CI 共用同一条命令）。

用法：
    uv run python packaging/build.py

流程：
  1. 从 pyproject.toml 读 version（单一真相源）
  2. 渲染 atprobe.spec：把 ATProbe-VERSION 占位符替换为 ATProbe-<version>
  3. 调 PyInstaller 构建（onedir，cwd=packaging/，让 spec 内相对路径生效）
  4. 复制 examples/ + atprobe.yaml.template + README.txt 到产物目录（外露用户工作区）
  5. 压缩产物目录 → dist/ATProbe-<version>-win64.zip

产物：dist/ATProbe-<version>-win64.zip
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

# Windows（尤其 CI runner）默认控制台编码是 cp1252，print 中文会 UnicodeEncodeError。
# 强制 stdout/stderr 用 UTF-8，确保本地与 CI 行为一致。
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGING = REPO_ROOT / "packaging"
DIST = REPO_ROOT / "dist"
SPEC = PACKAGING / "atprobe.spec"
VERSION_PLACEHOLDER = "ATProbe-VERSION"


def read_version() -> str:
    """从 pyproject.toml 读 version（单一真相源）。"""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def render_spec(version: str) -> Path:
    """渲染 spec：替换 VERSION 占位符，写到 packaging/atprobe.rendered.spec。"""
    text = SPEC.read_text(encoding="utf-8")
    rendered = text.replace(VERSION_PLACEHOLDER, f"ATProbe-{version}")
    out = PACKAGING / "atprobe.rendered.spec"
    out.write_text(rendered, encoding="utf-8")
    return out


def run_pyinstaller(rendered_spec: Path) -> None:
    """调用 PyInstaller 构建。

    用 --distpath / --workpath 显式指定输出到 REPO_ROOT/dist 与 packaging/build，
    避免 cwd 导致产物路径漂移。spec 内相对路径（examples/..、entry 脚本）经
    PyInstaller 自身基于 spec 文件位置解析，不依赖 cwd。
    """
    workpath = PACKAGING / "build"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(rendered_spec),
        "--noconfirm",
        f"--distpath={DIST}",
        f"--workpath={workpath}",
    ]
    print(f"[build] 运行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def expose_user_assets(version: str) -> Path:
    """把外露用户资产复制到产物目录（与 _internal 同级）。

    返回产物目录路径 dist/ATProbe-<version>。
    """
    app_dir = DIST / f"ATProbe-{version}"
    if not app_dir.exists():
        raise SystemExit(f"PyInstaller 产物目录不存在：{app_dir}")

    # examples/ 外露（用户可改的用例/示例）
    shutil.copytree(
        REPO_ROOT / "examples",
        app_dir / "examples",
        dirs_exist_ok=True,
    )
    # 用户配置模板 + README
    shutil.copy2(
        PACKAGING / "atprobe.yaml.template",
        app_dir / "atprobe.yaml.template",
    )
    shutil.copy2(PACKAGING / "README.txt", app_dir / "README.txt")
    return app_dir


def write_version_file(version: str, app_dir: Path) -> None:
    """把版本号写入 <app_dir>/_internal/VERSION（运行时 current_version 读它）。

    同时同步仓库根 VERSION 文件，保持与 pyproject.toml 一致（防 drift）。
    """
    internal = app_dir / "_internal"
    internal.mkdir(exist_ok=True)
    (internal / "VERSION").write_text(version, encoding="utf-8")
    # 同步仓库根 VERSION（开发态 current_version 读它）
    (REPO_ROOT / "VERSION").write_text(version, encoding="utf-8")
    print(f"[build] VERSION 文件已写入：{version}")


def make_zip(app_dir: Path, version: str) -> Path:
    """压缩产物目录 → dist/ATProbe-<version>-win64.zip。"""
    zip_path = DIST / f"ATProbe-{version}-win64.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in app_dir.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(DIST))
    return zip_path


def main() -> int:
    version = read_version()
    print(f"[build] version = {version}")

    rendered = render_spec(version)
    run_pyinstaller(rendered)
    app_dir = expose_user_assets(version)
    write_version_file(version, app_dir)  # 注入运行时版本（current_version 读它）
    zip_path = make_zip(app_dir, version)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[build] 完成：{zip_path}（{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
