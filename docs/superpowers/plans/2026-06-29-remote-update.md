# ATProbe 远程升级（检查 + 自动下载安装）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为便携式 ATProbe 增加「检查更新 + 用户点击后自动下载并原地安装最新版」能力，覆盖 GUI 与 CLI，零新依赖（纯 stdlib）。

**Architecture:** 新增独立 `infra/update` 子系统（checker/downloader/installer 三模块，职责单一可单测），GUI/CLI 共用。核心机制：主程序下载 + 准备 + detached 启动 updater.bat 后自杀，bat 在主程序退出后接管原地替换 `atprobe.exe` + `_internal/`（.bak 备份 + 失败回滚），保留用户工作区。版本真相源统一为 `pyproject.toml`，打包注入 VERSION 文件，测试防 drift。

**Tech Stack:** Python 3.11 stdlib（urllib/json/zipfile/subprocess/tempfile/pathlib）、PySide6（GUI）、Typer（CLI）、Pydantic（模型）、PyInstaller（打包）、pytest（测试）。

**Spec:** `docs/superpowers/specs/2026-06-29-remote-update-design.md`

**运行测试的统一命令：**
- 单个测试：`uv run pytest tests/unit/test_xxx.py::test_name -v`
- 全量：`uv run pytest -q`
- lint/类型：`uv run ruff check src tests`、`uv run mypy src`

---

## 文件结构

### 新增文件

| 文件 | 职责 |
|---|---|
| `VERSION`（仓库根） | 开发态版本真相源，纯文本一行（如 `0.2.1`） |
| `src/atprobe/infra/version.py` | `current_version()` 读 VERSION 文件（打包态 `_internal/VERSION`，开发态仓库根 `VERSION`），缺失回退 `0.0.0` |
| `src/atprobe/infra/update/__init__.py` | 子系统导出 + 自定义异常（`UpdateError`/`UpdateCheckError`/`AssetNotFoundError`/`DownloadError`/`DownloadCancelled`） |
| `src/atprobe/infra/update/config.py` | `UpdateConfig` 冻结 dataclass（api_base/repo/timeouts/asset 模板） |
| `src/atprobe/infra/update/checker.py` | `ReleaseInfo` 模型 + `fetch_latest()` + `is_newer()` + `_parse_semver()` |
| `src/atprobe/infra/update/downloader.py` | `DownloadResult` 模型 + `download()`（临时 `.part` + 原子重命名 + 进度/取消回调 + 大小校验） |
| `src/atprobe/infra/update/installer.py` | `apply_update()`（解压 staging + 生成 updater.bat + detached 启动 + zip 预检 + 开发态禁用） |
| `tests/unit/test_version.py` | `current_version()` 各路径测试 |
| `tests/unit/test_version_consistency.py` | drift 防护（VERSION == pyproject.toml == `__version__`） |
| `tests/unit/test_update_checker.py` | mock urlopen + ReleaseInfo + is_newer + 错误收敛 |
| `tests/unit/test_update_downloader.py` | mock urlopen + FakeResponse + 进度/取消/清理 |
| `tests/unit/test_update_installer.py` | mock Popen/zipfile + bat 内容断言 + 开发态禁用 + zip 预检 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `src/atprobe/__init__.py` | `__version__` 改为派生自 `current_version()` |
| `src/atprobe/cli/main.py` | `--version` 调 `current_version()`；新增 `update` 子命令注册 |
| `src/atprobe/cli/commands/update.py` | 【新增】`update` 子命令实现（--check / 交互 / --yes） |
| `src/atprobe/gui/mainwindow.py` | 新增「帮助」菜单（检查更新/关于）+ `_check_update` + 升级对话框 + 进度对话框 |
| `src/atprobe/gui/app.py` | 启动 3 秒后 `QTimer.singleShot` 触发静默检查 |
| `packaging/build.py` | 新增 `write_version_file()`，打包后写 `_internal/VERSION` + 同步仓库根 VERSION |

---

## Task 1: 版本真相源基础设施（地基）

建立 `VERSION` 文件 + `current_version()` 读取，修复版本 drift。这是整个升级功能的地基——程序必须先正确知道自己是哪个版本。

**Files:**
- Create: `VERSION`
- Create: `src/atprobe/infra/version.py`
- Create: `tests/unit/test_version.py`
- Modify: `src/atprobe/__init__.py:16`

- [ ] **Step 1: 创建 VERSION 文件**

```
0.2.1
```

（纯文本，单行，与 `pyproject.toml` 的 `version` 一致）

- [ ] **Step 2: 写失败测试 `tests/unit/test_version.py`**

```python
"""infra/version.py：current_version() 版本读取测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atprobe.infra import version as version_mod


def test_current_version_reads_repo_version_in_dev(tmp_path: Path) -> None:
    """开发态：读 app_root()/VERSION（仓库根）。"""
    fake_root = tmp_path
    (fake_root / "VERSION").write_text("0.2.1\n", encoding="utf-8")
    with patch.object(version_mod, "app_root", return_value=fake_root), patch.object(
        version_mod, "is_frozen", return_value=False
    ):
        assert version_mod.current_version() == "0.2.1"


def test_current_version_reads_internal_in_frozen(tmp_path: Path) -> None:
    """打包态：读 app_root()/_internal/VERSION。"""
    fake_root = tmp_path
    internal = fake_root / "_internal"
    internal.mkdir()
    (internal / "VERSION").write_text("0.3.0", encoding="utf-8")
    with patch.object(version_mod, "app_root", return_value=fake_root), patch.object(
        version_mod, "is_frozen", return_value=True
    ):
        assert version_mod.current_version() == "0.3.0"


def test_current_version_strips_whitespace(tmp_path: Path) -> None:
    """VERSION 文件带换行/空格时 strip 干净。"""
    fake_root = tmp_path
    (fake_root / "VERSION").write_text("  1.2.3  \n", encoding="utf-8")
    with patch.object(version_mod, "app_root", return_value=fake_root), patch.object(
        version_mod, "is_frozen", return_value=False
    ):
        assert version_mod.current_version() == "1.2.3"


def test_current_version_fallback_on_missing(tmp_path: Path) -> None:
    """VERSION 文件缺失时回退 '0.0.0'，不抛异常。"""
    with patch.object(version_mod, "app_root", return_value=tmp_path), patch.object(
        version_mod, "is_frozen", return_value=False
    ):
        assert version_mod.current_version() == "0.0.0"


def test_current_version_reads_real_repo() -> None:
    """集成：读真实仓库根 VERSION，应等于 pyproject.toml 的 version。"""
    import tomllib

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert version_mod.current_version() == expected
```

- [ ] **Step 3: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_version.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.infra.version'`

- [ ] **Step 4: 实现 `src/atprobe/infra/version.py`**

```python
"""运行时版本读取（单一真相源的消费者）。

真相源：pyproject.toml 的 version（开发/构建时）。
运行时如何拿到：
    - 打包态：build.py 在构建后写 ``<app_root>/_internal/VERSION``，本模块读它。
    - 开发态：仓库根 ``VERSION`` 文件（build.py 维护与 pyproject.toml 一致）。
    - 都没有：回退 ``'0.0.0'``（不阻塞启动，升级检查会认为该升级）。
"""

from __future__ import annotations

from atprobe.infra.runtime import app_root, is_frozen

_FALLBACK = "0.0.0"


def current_version() -> str:
    """当前运行版本号（如 '0.2.1'），未知返回 '0.0.0'。"""
    if is_frozen():
        candidate = app_root() / "_internal" / "VERSION"
    else:
        candidate = app_root() / "VERSION"
    try:
        text = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK
    return text or _FALLBACK
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_version.py -v`
Expected: 5 passed

- [ ] **Step 6: 修复 `src/atprobe/__init__.py` 的 drift**

把第 16 行 `__version__ = "0.1.0"` 替换为派生：

```python
def _read_version() -> str:
    """延迟导入避免循环依赖；运行时版本来自 VERSION 文件。"""
    from atprobe.infra.version import current_version

    return current_version()


__version__ = _read_version()
```

（删掉原 `__version__ = "0.1.0"` 那一行）

- [ ] **Step 7: 验证 CLI --version 现在读到正确版本**

Run: `uv run atprobe --version`
Expected: `atprobe 0.2.1`（而非旧的 `atprobe 0.1.0`）

- [ ] **Step 8: 提交**

```bash
git add VERSION src/atprobe/infra/version.py src/atprobe/__init__.py tests/unit/test_version.py
git commit -m "feat(update): 版本真相源基础设施（VERSION 文件 + current_version，修复 drift）"
```

---

## Task 2: drift 防护测试

用测试从机制上保证 VERSION / pyproject.toml / `__version__` 三处永不漂移。

**Files:**
- Create: `tests/unit/test_version_consistency.py`

- [ ] **Step 1: 写测试 `tests/unit/test_version_consistency.py`**

```python
"""版本 drift 防护：VERSION 文件 / pyproject.toml / __version__ 必须一致。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import atprobe

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_version_file_matches_pyproject() -> None:
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    expected = tomllib.loads(pyproject)["project"]["version"]
    version_file = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version_file == expected, (
        f"VERSION 文件={version_file!r} 与 pyproject.toml version={expected!r} 不一致"
    )


def test_dunder_version_matches_pyproject() -> None:
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    expected = tomllib.loads(pyproject)["project"]["version"]
    assert atprobe.__version__ == expected, (
        f"__version__={atprobe.__version__!r} 与 pyproject.toml version={expected!r} 不一致"
    )
```

- [ ] **Step 2: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_version_consistency.py -v`
Expected: 2 passed（Task 1 已让三者一致：VERSION=0.2.1，pyproject=0.2.1，__version__ 经 current_version 读 VERSION=0.2.1）

- [ ] **Step 3: 提交**

```bash
git add tests/unit/test_version_consistency.py
git commit -m "test(update): 版本 drift 防护（三处来源一致性）"
```

---

## Task 3: update 子系统骨架（异常 + 配置）

建立 `infra/update/` 包，定义所有自定义异常与配置常量。后续 checker/downloader/installer 都依赖这些。

**Files:**
- Create: `src/atprobe/infra/update/__init__.py`
- Create: `src/atprobe/infra/update/config.py`
- Create: `tests/unit/test_update_config.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_update_config.py`**

```python
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_update_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.infra.update'`

- [ ] **Step 3: 实现 `src/atprobe/infra/update/__init__.py`**

```python
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
```

- [ ] **Step 4: 实现 `src/atprobe/infra/update/config.py`**

```python
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
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_update_config.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add src/atprobe/infra/update/__init__.py src/atprobe/infra/update/config.py tests/unit/test_update_config.py
git commit -m "feat(update): 子系统骨架（异常类 + UpdateConfig 配置）"
```

---

## Task 4: 版本检查器（checker）

查 GitHub Releases API 取最新版 + semver 比较。纯逻辑、纯 stdlib、全 mock 测。

**Files:**
- Create: `src/atprobe/infra/update/checker.py`
- Create: `tests/unit/test_update_checker.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_update_checker.py`**

```python
"""update/checker.py：fetch_latest + is_newer 测试（全 mock，零真实网络）。"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from atprobe.infra.update import AssetNotFoundError, UpdateCheckError
from atprobe.infra.update.checker import ReleaseInfo, fetch_latest, is_newer


def _github_response(tag: str = "v0.3.0", *, with_asset: bool = True) -> bytes:
    """构造 GitHub releases/latest API 响应 JSON。"""
    ver = tag.lstrip("v")
    asset = {
        "name": f"ATProbe-{ver}-win64.zip",
        "browser_download_url": f"https://example.com/ATProbe-{ver}-win64.zip",
        "size": 83558400,
    }
    body = {
        "tag_name": tag,
        "body": "## 更新内容\n- 修复 X\n- 新增 Y",
        "html_url": f"https://github.com/niusulong/ATProbe/releases/tag/{tag}",
        "assets": [asset] if with_asset else [],
    }
    return json.dumps(body).encode("utf-8")


class _FakeResp:
    """模拟 urllib 的 HTTPResponse。"""

    def __init__(self, data: bytes, status: int = 200) -> None:
        self._buf = BytesIO(data)
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read() if n == -1 else self._buf.read(n)

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> None:
        pass


# ---------- fetch_latest ----------

def test_fetch_latest_parses_release() -> None:
    resp = _FakeResp(_github_response("v0.3.0"))
    with patch("urllib.request.urlopen", return_value=resp):
        info = fetch_latest()
    assert info.version == "0.3.0"
    assert info.tag == "v0.3.0"
    assert info.zip_url == "https://example.com/ATProbe-0.3.0-win64.zip"
    assert info.zip_size == 83558400
    assert "修复 X" in info.release_notes
    assert info.html_url.endswith("v0.3.0")


def test_fetch_latest_missing_asset_raises() -> None:
    resp = _FakeResp(_github_response("v0.3.0", with_asset=False))
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(AssetNotFoundError):
            fetch_latest()


def test_fetch_latest_network_error_converges() -> None:
    import urllib.error

    err = urllib.error.URLError("timed out")
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(UpdateCheckError):
            fetch_latest()


def test_fetch_latest_http_404_converges() -> None:
    import urllib.error

    err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(UpdateCheckError):
            fetch_latest()


def test_fetch_latest_bad_json_converges() -> None:
    resp = _FakeResp(b"not json {{{")
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(UpdateCheckError):
            fetch_latest()


# ---------- is_newer ----------

@pytest.mark.parametrize(
    "remote, local, expected",
    [
        ("0.3.0", "0.2.1", True),
        ("0.2.1", "0.2.1", False),
        ("0.2.0", "0.2.1", False),
        ("0.10.0", "0.9.0", True),  # 防字符串比较 bug
        ("1.0.0", "0.9.9", True),
        ("v0.3.0", "0.2.1", True),  # 带 v 前缀
        ("0.3", "0.2.1", True),  # 缺位补 0
        ("0.0.0", "0.0.0", False),  # 兜底版本
    ],
)
def test_is_newer(remote: str, local: str, expected: bool) -> None:
    assert is_newer(remote, local) is expected
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_update_checker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.infra.update.checker'`

- [ ] **Step 3: 实现 `src/atprobe/infra/update/checker.py`**

```python
"""版本检查器：查 GitHub Releases API 取最新版 + semver 比较。

纯逻辑、纯 stdlib、所有网络异常收敛成 UpdateCheckError（上层静默/弹窗可控）。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel

from atprobe.infra.update import AssetNotFoundError, UpdateCheckError
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig
from atprobe.infra.version import current_version

_API_PATH = "/repos/{repo}/releases/latest"


class ReleaseInfo(BaseModel):
    """远程最新 Release 解析结果。"""

    version: str  # "0.3.0"（去掉 v 前缀）
    tag: str  # "v0.3.0"
    zip_url: str  # Windows zip 下载地址
    zip_size: int  # 字节数
    release_notes: str  # release body（changelog）
    html_url: str  # GitHub Release 页面（备用）


def fetch_latest(
    config: UpdateConfig | None = None,
    *,
    timeout: float | None = None,
) -> ReleaseInfo:
    """查询最新 Release。

    所有网络/解析异常都收敛成 UpdateCheckError；找不到 Windows 包抛 AssetNotFoundError。
    """
    cfg = config or DEFAULT_CONFIG
    url = cfg.api_base.rstrip("/") + _API_PATH.format(repo=cfg.repo)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ATProbe/{current_version()}",
        },
    )
    to = cfg.check_timeout if timeout is None else timeout
    try:
        with urllib.request.urlopen(req, timeout=to) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(_http_error_msg(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateCheckError(f"网络连接失败：{exc}") from exc

    try:
        body: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpdateCheckError(f"响应格式异常：{exc}") from exc

    return _parse_release(body, cfg)


def _parse_release(body: dict[str, Any], cfg: UpdateConfig) -> ReleaseInfo:
    try:
        tag = str(body["tag_name"])
    except KeyError as exc:
        raise UpdateCheckError("响应缺少 tag_name 字段") from exc
    version = tag.lstrip("v")
    expected_name = cfg.asset_name_for(version)
    asset = next(
        (a for a in body.get("assets", []) if a.get("name") == expected_name), None
    )
    if asset is None:
        raise AssetNotFoundError(f"版本 {version} 无 Windows 安装包（{expected_name}）")
    return ReleaseInfo(
        version=version,
        tag=tag,
        zip_url=str(asset.get("browser_download_url", "")),
        zip_size=int(asset.get("size", 0)),
        release_notes=str(body.get("body", "")),
        html_url=str(body.get("html_url", "")),
    )


def _http_error_msg(code: int) -> str:
    if code == 403:
        return "请求过于频繁（GitHub API 限流），请稍后重试"
    if code == 404:
        return "尚未发布任何版本"
    return f"服务器返回错误（HTTP {code}）"


def is_newer(remote: str, local: str) -> bool:
    """remote 版本是否比 local 新（semver 元组比较）。"""
    return _parse_semver(remote) > _parse_semver(local)


def _parse_semver(v: str) -> tuple[int, int, int]:
    """解析 '0.2.1' / 'v0.3.0' / '0.3' → (major, minor, patch)。

    去掉 v 前缀、忽略 -pre 后缀；缺位补 0；非数字段回退 0。
    """
    core = re.split(r"[-+]", v.strip().lstrip("vV"), 1)[0]
    parts = core.split(".")
    nums: list[int] = []
    for p in parts[:3]:
        m = re.match(r"\d+", p)
        nums.append(int(m.group()) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_update_checker.py -v`
Expected: 13 passed（5 fetch + 8 is_newer 参数化）

- [ ] **Step 5: 类型检查**

Run: `uv run mypy src/atprobe/infra/update/checker.py`
Expected: 无错误

- [ ] **Step 6: 提交**

```bash
git add src/atprobe/infra/update/checker.py tests/unit/test_update_checker.py
git commit -m "feat(update): 版本检查器（GitHub API + semver 比较）"
```

---

## Task 5: 下载器（downloader）

下载 zip 到本地，带进度回调、取消、临时 `.part` + 原子重命名、大小校验。

**Files:**
- Create: `src/atprobe/infra/update/downloader.py`
- Create: `tests/unit/test_update_downloader.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_update_downloader.py`**

```python
"""update/downloader.py：download 测试（全 mock，零真实网络）。"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest

from atprobe.infra.update import DownloadCancelled, DownloadError
from atprobe.infra.update.downloader import download


class _FakeResp:
    """模拟 HTTPResponse，逐块 read。"""

    def __init__(self, data: bytes, content_length: int | None = None) -> None:
        self._buf = BytesIO(data)
        cl = content_length if content_length is not None else len(data)
        self.headers = {"Content-Length": str(cl)}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read() if n == -1 else self._buf.read(n)

    def geturl(self) -> str:
        return "https://example.com/file.zip"

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_download_writes_file_and_renames(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"x" * 1000
    resp = _FakeResp(data)
    with patch("urllib.request.urlopen", return_value=resp):
        result = download(
            "https://example.com/file.zip", tmp_path, filename="update.zip"
        )
    assert result.path == tmp_path / "update.zip"
    assert result.path.read_bytes() == data
    assert result.size == 1000
    # 临时 .part 已清理（重命名）
    assert not (tmp_path / "update.zip.part").exists()


def test_download_progress_callback(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"y" * 500
    resp = _FakeResp(data)
    calls: list[tuple[int, int]] = []

    def cb(done: int, total: int) -> None:
        calls.append((done, total))

    with patch("urllib.request.urlopen", return_value=resp):
        download("https://example.com/f.zip", tmp_path, filename="f.zip", progress_cb=cb)
    assert calls  # 至少调用一次
    assert calls[-1] == (500, 500)  # 最后一次：全部完成
    assert calls[0][1] == 500  # total 正确


def test_download_cancel_cleans_partfile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"z" * 1000
    resp = _FakeResp(data)
    counter = {"n": 0}

    def cancel() -> bool:
        counter["n"] += 1
        return counter["n"] >= 2  # 第 2 次检查时取消

    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(DownloadCancelled):
            download(
                "https://example.com/f.zip",
                tmp_path,
                filename="f.zip",
                cancel_token=cancel,
                progress_cb=lambda *_: None,
            )
    # .part 已清理
    assert not (tmp_path / "f.zip.part").exists()
    assert not (tmp_path / "f.zip").exists()


def test_download_size_mismatch_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"short"
    resp = _FakeResp(data)
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(DownloadError):
            download(
                "https://example.com/f.zip",
                tmp_path,
                filename="f.zip",
                expected_size=999,  # 期望 999，实际 5
            )
    assert not (tmp_path / "f.zip.part").exists()


def test_download_network_error_cleans_partfile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import urllib.error

    err = urllib.error.URLError("connection reset")
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(DownloadError):
            download("https://example.com/f.zip", tmp_path, filename="f.zip")
    assert not (tmp_path / "f.zip.part").exists()


def test_download_infers_filename_from_url(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"abc"
    resp = _FakeResp(data)
    with patch("urllib.request.urlopen", return_value=resp):
        result = download("https://example.com/path/ATProbe-0.3.0-win64.zip", tmp_path)
    assert result.path.name == "ATProbe-0.3.0-win64.zip"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_update_downloader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.infra.update.downloader'`

- [ ] **Step 3: 实现 `src/atprobe/infra/update/downloader.py`**

```python
"""下载器：把 zip 安全下载到本地。

安全策略：
    - 先写 ``<name>.part`` 临时文件，成功后原子重命名为 ``<name>``
    - 任何退出路径（失败/取消）都清理 ``.part``；成功路径在 finally 前已完成重命名
    - 目标目录用系统临时目录，避免写 exe 同级（权限/防软件监控）
    - 可选 expected_size 校验，防止代理截断给残缺 zip
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from atprobe.infra.update import DownloadCancelled, DownloadError
from atprobe.infra.update.config import DEFAULT_CONFIG, UpdateConfig

_CHUNK = 8192

ProgressCb = Callable[[int, int], None]
CancelToken = Callable[[], bool]


class DownloadResult(BaseModel):
    """下载完成结果。"""

    path: Path
    size: int


def download(
    url: str,
    dest_dir: Path,
    *,
    filename: str | None = None,
    timeout: float | None = None,
    expected_size: int | None = None,
    progress_cb: ProgressCb | None = None,
    cancel_token: CancelToken | None = None,
    config: UpdateConfig | None = None,
) -> DownloadResult:
    """下载 url 到 ``dest_dir/<filename>``。

    Args:
        url: 下载地址。
        dest_dir: 目标目录（已存在）。
        filename: 目标文件名；None 则从 URL 路径推断。
        timeout: 连接超时；None 用 config.download_timeout。
        expected_size: 期望字节数，下载后校验；None 不校验。
        progress_cb: ``(downloaded, total)`` 回调，每 chunk 调用。
        cancel_token: 返回 True 则中止下载（抛 DownloadCancelled）。
        config: 超时等配置。

    Returns:
        DownloadResult（path 指向最终文件，已无 .part 后缀）。

    Raises:
        DownloadCancelled: 用户取消。
        DownloadError: 网络/磁盘/大小不符。
    """
    cfg = config or DEFAULT_CONFIG
    if filename is None:
        filename = Path(urlparse(url).path).name or "download.bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / filename
    part = dest_dir / f"{filename}.part"

    # 清理可能的历史 .part（幂等）
    part.unlink(missing_ok=True)

    to = cfg.download_timeout if timeout is None else timeout
    req = urllib.request.Request(url, headers={"User-Agent": f"ATProbe/{cfg.repo}"})
    # 标记成功路径：仅当此处置 True 时跳过 finally 的 .part 清理
    # （成功时 .part 已被 replace 为 final，不存在了，但显式标记更清晰）
    succeeded = False
    try:
        try:
            resp = urllib.request.urlopen(req, timeout=to)  # noqa: S310
        except urllib.error.HTTPError as exc:
            raise DownloadError(f"下载失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DownloadError(f"下载失败：网络中断（{exc}）") from exc

        total = _content_length(resp)
        written = 0
        try:
            with part.open("wb") as f:
                while True:
                    if cancel_token is not None and cancel_token():
                        raise DownloadCancelled("用户取消下载")
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    try:
                        f.write(chunk)
                    except OSError as exc:
                        raise DownloadError(f"写盘失败：{exc}") from exc
                    written += len(chunk)
                    if progress_cb is not None:
                        progress_cb(written, total)
        finally:
            resp.close()

        # 大小校验（在 finally 清理之前，失败时抛 DownloadError，finally 会清理 .part）
        if expected_size is not None and written != expected_size:
            raise DownloadError(
                f"下载文件大小不符：期望 {expected_size}，实际 {written}（可能已损坏）"
            )

        # 原子重命名（成功路径）
        try:
            part.replace(final)
        except OSError as exc:
            raise DownloadError(f"无法完成文件写入：{exc}") from exc
        succeeded = True
    finally:
        # 失败/取消：清理残留 .part；成功：.part 已 replace（不存在，missing_ok 安全）
        if not succeeded:
            part.unlink(missing_ok=True)

    return DownloadResult(path=final, size=written)


def _content_length(resp: object) -> int:
    headers = getattr(resp, "headers", {}) or {}
    val = headers.get("Content-Length") if hasattr(headers, "get") else None
    try:
        return int(val) if val else 0
    except (TypeError, ValueError):
        return 0
```

设计要点：用 `succeeded` 标志位区分成功/失败路径。`finally` 只在非成功时清理 `.part`，成功路径在 `finally` 执行前已完成 `part.replace(final)`（此时 `.part` 已不存在，但 `succeeded=True` 跳过清理，无需依赖 missing_ok）。这样取消/网络错误/大小不符/写盘失败/重命名失败所有路径都保证 `.part` 被清理。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_update_downloader.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/infra/update/downloader.py tests/unit/test_update_downloader.py
git commit -m "feat(update): 下载器（临时.part + 原子重命名 + 进度/取消/大小校验）"
```

---

## Task 6: 安装器（installer）⚠️风险最高

生成 updater.bat 并 detached 启动，主程序退出后由 bat 接管原地替换。含 .bak 备份回滚、开发态禁用、zip 预检。

**Files:**
- Create: `src/atprobe/infra/update/installer.py`
- Create: `tests/unit/test_update_installer.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_update_installer.py`**

```python
"""update/installer.py：apply_update 测试（mock Popen/zipfile，不真实替换）。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from atprobe.infra.update import UpdateError
from atprobe.infra.update.installer import apply_update, build_updater_script


def _make_fake_zip(zip_path: Path) -> None:
    """构造含 atprobe.exe + _internal/ 的假 zip。"""
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ATProbe-0.3.0/atprobe.exe", b"PE")
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
    (tmp_path / "atprobe.exe").write_bytes(b"old")

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
        exe_path=tmp_path / "atprobe.exe",
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


def test_updater_script_paths_quoted(tmp_path: Path) -> None:
    """路径含空格时 bat 内必须加引号（防 PATH/参数注入）。"""
    exe = Path("D:/my tools/ATProbe/atprobe.exe")
    script = build_updater_script(
        exe_path=exe,
        internal_path=exe.parent / "_internal",
        staging_dir=exe.parent / "ATProbe-0.3.0",
        pid=1,
    )
    assert '"D:/my tools/ATProbe/atprobe.exe"' in script or (
        '"D:\\my tools\\ATProbe\\atprobe.exe"' in script
    )
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_update_installer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.infra.update.installer'`

- [ ] **Step 3: 实现 `src/atprobe/infra/update/installer.py`**

```python
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
import subprocess
import sys
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
    import shutil

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
set /a tries=0
:wait
tasklist /fi "pid eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (
    set /a tries+=1
    if %tries% GEQ 30 goto rollback
    timeout /t 1 /nobreak >nul
    goto wait
)

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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_update_installer.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/infra/update/installer.py tests/unit/test_update_installer.py
git commit -m "feat(update): 安装器（detached bat + .bak 回滚 + zip 预检 + 开发态禁用）"
```

---

## Task 7: 全量回归 + lint/类型

三个核心模块完成后，跑全量测试确保零回归。

**Files:** 无新增（验证任务）

- [ ] **Step 1: 全量测试**

Run: `uv run pytest -q`
Expected: 全部 passed（含原有 ~230 个 + 新增 update 测试）

- [ ] **Step 2: ruff lint**

Run: `uv run ruff check src tests`
Expected: 无错误

- [ ] **Step 3: mypy 类型检查（update 子系统）**

Run: `uv run mypy src/atprobe/infra/update/ src/atprobe/infra/version.py`
Expected: 无错误

- [ ] **Step 4: 修复发现的问题（如有）**

根据上述输出修复，无问题则跳过。

---

## Task 8: build.py 写入 VERSION 文件

打包时把版本注入 `_internal/VERSION`，并同步仓库根 VERSION。

**Files:**
- Modify: `packaging/build.py`（新增 `write_version_file` 函数 + 在 `main()` 调用）

- [ ] **Step 1: 在 `packaging/build.py` 新增 `write_version_file` 函数**

在 `expose_user_assets` 函数之后插入：

```python
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
```

- [ ] **Step 2: 在 `main()` 调用 `write_version_file`**

把 `main()` 的 `expose_user_assets(version)` 之后、`make_zip` 之前，加入调用：

```python
def main() -> int:
    version = read_version()
    print(f"[build] version = {version}")

    rendered = render_spec(version)
    run_pyinstaller(rendered)
    app_dir = expose_user_assets(version)
    write_version_file(version, app_dir)  # 新增：注入运行时版本
    zip_path = make_zip(app_dir, version)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[build] 完成：{zip_path}（{size_mb:.1f} MB）")
    return 0
```

- [ ] **Step 3: 验证 VERSION 文件语法正确**

Run: `uv run python -c "from packaging.build import write_version_file; print('ok')"`
Expected: `ok`（注意：`packaging` 是脚本目录，需在仓库根用 `uv run python -c` 验证 import。若 import 失败，改为直接在 build.py 内验证函数定义无语法错误）

Run: `uv run python -c "import ast; ast.parse(open('packaging/build.py', encoding='utf-8').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 4: 提交**

```bash
git add packaging/build.py
git commit -m "feat(update): build.py 打包时注入 _internal/VERSION 文件"
```

---

## Task 9: CLI update 子命令

新增 `atprobe update` 子命令：`--check` 只检查、交互确认安装、`--yes` 非交互。

**Files:**
- Create: `src/atprobe/cli/commands/update.py`
- Modify: `src/atprobe/cli/main.py`（注册 update 子命令）
- Create: `tests/unit/test_cli_update.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_cli_update.py`**

```python
"""CLI update 子命令测试（mock checker/installer，零真实网络/替换）。"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from atprobe.cli.main import app

runner = CliRunner()


def test_update_check_reports_new_version() -> None:
    """--check：有新版时报告版本与下载地址。"""
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.3.0",
        tag="v0.3.0",
        zip_url="https://example.com/ATProbe-0.3.0-win64.zip",
        zip_size=80000000,
        release_notes="notes",
        html_url="https://github.com/niusulong/ATProbe/releases/tag/v0.3.0",
    )
    with patch("atprobe.cli.commands.update.fetch_latest", return_value=fake), patch(
        "atprobe.cli.commands.update.is_newer", return_value=True
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "0.3.0" in result.stdout
    assert "ATProbe-0.3.0-win64.zip" in result.stdout


def test_update_check_already_latest() -> None:
    """--check：已是最新时报告。"""
    from atprobe.infra.update.checker import ReleaseInfo

    fake = ReleaseInfo(
        version="0.2.1", tag="v0.2.1", zip_url="u", zip_size=1,
        release_notes="", html_url="h",
    )
    with patch("atprobe.cli.commands.update.fetch_latest", return_value=fake), patch(
        "atprobe.cli.commands.update.is_newer", return_value=False
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "最新" in result.stdout


def test_update_check_network_error_exit_code() -> None:
    """--check：网络失败时非零退出码 + 错误提示。"""
    from atprobe.infra.update import UpdateCheckError

    with patch(
        "atprobe.cli.commands.update.fetch_latest",
        side_effect=UpdateCheckError("网络连接失败"),
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code != 0
    assert "网络" in result.stdout or "网络" in (result.output or "")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_cli_update.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atprobe.cli.commands.update'`

- [ ] **Step 3: 实现 `src/atprobe/cli/commands/update.py`**

```python
"""`update` 子命令：检查更新 / 交互安装 / 非交互安装。

复用 infra/update 的 checker/downloader/installer，只在展示与交互层不同。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import typer

from atprobe.infra.runtime import is_frozen
from atprobe.infra.update import (
    DownloadCancelled,
    DownloadError,
    UpdateCheckError,
    UpdateError,
)
from atprobe.infra.update.checker import fetch_latest, is_newer
from atprobe.infra.update.downloader import download
from atprobe.infra.update.installer import apply_update
from atprobe.infra.version import current_version


def update(
    check_only: bool = typer.Option(False, "--check", help="只检查是否有新版，不下载"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认直接安装（非交互）"),
) -> None:
    """检查并安装 ATProbe 最新版本。"""
    local = current_version()
    try:
        info = fetch_latest()
    except UpdateCheckError as exc:
        typer.secho(f"检查失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not is_newer(info.version, local):
        typer.echo(f"当前 {local}，已是最新版本。")
        return

    typer.echo(f"当前 {local}，最新 {info.version}，有新版本可用。")
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
        confirm = typer.confirm(f"确认升级到 {info.version}？", default=False)
        if not confirm:
            typer.echo("已取消。")
            return

    dest = Path(tempfile.gettempdir())
    try:
        result = download(
            info.zip_url,
            dest,
            filename=f"ATProbe-{info.version}-win64.zip",
            expected_size=info.zip_size,
            progress_cb=_print_progress,
        )
    except DownloadCancelled:
        typer.echo("\n已取消下载。")
        raise typer.Exit(1)
    except DownloadError as exc:
        typer.secho(f"\n下载失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.echo("\n下载完成，开始安装（程序将退出并重启）...")
    from atprobe.infra.runtime import app_root

    try:
        apply_update(result.path, app_root())
    except UpdateError as exc:
        typer.secho(f"安装失败：{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
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
```

- [ ] **Step 4: 在 `src/atprobe/cli/main.py` 注册 update 子命令**

在文件末尾的子命令注册区添加：

```python
from atprobe.cli.commands.update import update as update_cmd  # noqa: E402

app.command(name="update")(update_cmd)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_cli_update.py -v`
Expected: 3 passed

- [ ] **Step 6: 手动验证子命令注册**

Run: `uv run atprobe update --help`
Expected: 显示 `--check` / `--yes` / `-y` 选项

Run: `uv run atprobe --help`
Expected: 子命令列表含 `update`

- [ ] **Step 7: 提交**

```bash
git add src/atprobe/cli/commands/update.py src/atprobe/cli/main.py tests/unit/test_cli_update.py
git commit -m "feat(update): CLI update 子命令（--check / 交互 / --yes）"
```

---

## Task 10: GUI 帮助菜单 + 关于对话框

新增「帮助(&H)」菜单（检查更新 / 关于），先实现关于对话框与菜单骨架。检查更新的对话框逻辑在 Task 11。

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py`（`_init_menubar` 扩展 + `_on_about` + `_on_check_update` 占位）
- Modify: `tests/integration/test_gui.py`（新增菜单构造断言）

- [ ] **Step 1: 写失败测试 `tests/integration/test_gui.py` 新增**

在 `TestMainWindow` 类中新增方法：

```python
    def test_help_menu_exists(self, qapp) -> None:  # type: ignore[no-untyped-def]
        """帮助菜单存在，含检查更新/关于两个 action。"""
        from atprobe.gui.mainwindow import MainWindow

        win = MainWindow()
        menubar = win.menuBar()
        actions = menubar.actions()
        help_actions = [a for a in actions if a.text().startswith("帮助")]
        assert len(help_actions) == 1
        help_menu = help_actions[0].menu()
        assert help_menu is not None
        texts = [a.text() for a in help_menu.actions() if a.text()]
        assert any("检查更新" in t for t in texts)
        assert any("关于" in t for t in texts)

    def test_about_dialog_shows_version(self, qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """关于对话框显示当前版本号。"""
        from atprobe.gui.mainwindow import MainWindow
        from PySide6.QtWidgets import QMessageBox

        shown = {}
        monkeypatch.setattr(
            QMessageBox, "about",
            lambda parent, title, text: shown.update(title=title, text=text),
        )
        win = MainWindow()
        win._on_about()  # noqa: SLF001
        assert "ATProbe" in shown.get("text", "")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/integration/test_gui.py::TestMainWindow::test_help_menu_exists -v`
Expected: FAIL — 帮助菜单不存在

- [ ] **Step 3: 修改 `src/atprobe/gui/mainwindow.py` `_init_menubar`**

把现有 `_init_menubar` 改为同时构造视图菜单和帮助菜单：

```python
    def _init_menubar(self) -> None:
        """构造菜单栏：视图（主题切换）+ 帮助（检查更新/关于）."""
        from PySide6.QtGui import QAction

        view_menu = self.menuBar().addMenu("视图(&V)")
        self._theme_action = QAction("切换深色主题", self)
        self._theme_action.setCheckable(True)
        self._theme_action.setChecked(self._dark)
        self._theme_action.toggled.connect(self._toggle_theme)
        view_menu.addAction(self._theme_action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        check_action = QAction("检查更新...", self)
        check_action.triggered.connect(lambda: self._on_check_update(manual=True))
        help_menu.addAction(check_action)
        help_menu.addSeparator()
        about_action = QAction("关于 ATProbe", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
```

并在类中新增 `_on_about` 和 `_on_check_update` 占位方法（检查更新完整实现在 Task 11）：

```python
    def _on_about(self) -> None:
        """关于对话框：显示版本号与项目地址。"""
        import sys as _sys

        from PySide6.QtWidgets import QMessageBox

        from atprobe.infra.version import current_version

        QMessageBox.about(
            self,
            "关于 ATProbe",
            (
                f"<h3>ATProbe</h3>"
                f"<p>版本：{current_version()}</p>"
                f"<p>串口 AT 命令自动化测试工具</p>"
                f"<p>项目地址：<a href='https://github.com/niusulong/ATProbe'>"
                f"github.com/niusulong/ATProbe</a></p>"
                f"<p>Python {_sys.version.split()[0]} · MIT License</p>"
            ),
        )

    def _on_check_update(self, manual: bool = True) -> None:
        """检查更新（手动触发）。完整实现见 Task 11。"""
        self._check_update(manual=manual)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/integration/test_gui.py::TestMainWindow::test_help_menu_exists tests/integration/test_gui.py::TestMainWindow::test_about_dialog_shows_version -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/gui/mainwindow.py tests/integration/test_gui.py
git commit -m "feat(update): GUI 帮助菜单（检查更新/关于）+ 关于对话框"
```

---

## Task 11: GUI 检查更新 + 升级对话框 + 进度对话框

实现完整的检查→通知→下载→安装流程的 GUI 交互。复用 checker/downloader/installer，工作线程做网络，信号投递回主线程。

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py`（新增 `_check_update` + 升级对话框 + 进度对话框 + 安装确认）

- [ ] **Step 1: 在 `src/atprobe/gui/mainwindow.py` 类顶部信号定义旁新增升级信号**

在 `progress = Signal(object)` 下方新增：

```python
    # 升级检查/下载结果投递信号（工作线程 → 主线程）
    update_check_result = Signal(object)  # ReleaseInfo | None(无新版/失败) | Exception
    update_download_progress = Signal(int, int)  # (done, total)
    update_download_done = Signal(object)  # Path | Exception
```

- [ ] **Step 2: 在 `__init__` 末尾（`self.progress.connect(...)` 之后）连接新信号**

```python
        self.update_check_result.connect(self._on_check_result)
        self.update_download_progress.connect(self._on_download_progress)
        self.update_download_done.connect(self._on_download_done)
        self._update_in_progress = False
        self._pending_release = None  # ReleaseInfo，下载期间持有
```

- [ ] **Step 3: 实现 `_check_update`（后台线程检查）**

```python
    def _check_update(self, manual: bool = True) -> None:
        """后台检查更新（工作线程做 HTTP，结果经信号回主线程）。

        manual=False（启动自动）：失败/无新版静默；manual=True（手动）：弹提示。
        """
        if self._update_in_progress:
            return
        self._check_manual = manual
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self) -> None:
        from atprobe.infra.update import UpdateCheckError
        from atprobe.infra.update.checker import fetch_latest, is_newer
        from atprobe.infra.version import current_version

        try:
            info = fetch_latest()
            result = info if is_newer(info.version, current_version()) else None
            self.update_check_result.emit(result)
        except (UpdateCheckError, Exception) as exc:  # noqa: BLE001
            # 网络失败等：手动模式弹窗，自动模式静默
            self.update_check_result.emit(exc)
```

- [ ] **Step 4: 实现 `_on_check_result`（处理检查结果，弹升级对话框）**

```python
    def _on_check_result(self, result: object) -> None:
        """主线程：处理检查结果。"""
        from PySide6.QtWidgets import QMessageBox

        from atprobe.infra.update import UpdateCheckError

        # 异常：失败
        if isinstance(result, Exception):
            if getattr(self, "_check_manual", False):
                QMessageBox.warning(self, "检查更新", f"检查失败：{result}")
            return
        # None：已是最新
        if result is None:
            if getattr(self, "_check_manual", False):
                from atprobe.infra.version import current_version

                QMessageBox.information(
                    self, "检查更新", f"当前已是最新版本 {current_version()}"
                )
            return
        # ReleaseInfo：有新版 → 弹升级对话框
        self._show_update_dialog(result)  # type: ignore[arg-type]
```

- [ ] **Step 5: 实现升级对话框 `_show_update_dialog`**

```python
    def _show_update_dialog(self, info: object) -> None:
        """有新版时弹升级对话框（版本号 + changelog + 立即更新/稍后）。"""
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QTextEdit,
            QVBoxLayout,
        )

        from atprobe.infra.version import current_version

        dlg = QDialog(self)
        dlg.setWindowTitle("发现新版本")
        dlg.setMinimumWidth(480)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"<b>发现新版本 {info.version}</b>（当前 {current_version()}）"  # type: ignore[attr-defined]
        ))
        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setHtml(f"<pre>{info.release_notes}</pre>")  # type: ignore[attr-defined]
        layout.addWidget(QLabel("更新内容："))
        layout.addWidget(notes, 1)
        size_mb = getattr(info, "zip_size", 0) / (1024 * 1024)
        layout.addWidget(QLabel(f"下载大小：约 {size_mb:.1f} MB"))
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("立即更新")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("稍后")
        btns.accepted.connect(lambda: self._start_download(info, dlg))
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.exec()
```

- [ ] **Step 6: 实现 `_start_download` + 进度对话框 + 工作线程下载**

```python
    def _start_download(self, info: object, dlg: object) -> None:
        """用户点立即更新：关闭对话框，启动下载（工作线程 + 进度对话框）。"""
        from PySide6.QtWidgets import QProgressDialog

        dlg.accept()  # type: ignore[attr-defined]
        self._update_in_progress = True
        self._pending_release = info

        size_mb = getattr(info, "zip_size", 0) / (1024 * 1024)
        self._progress_dlg = QProgressDialog(f"正在更新到 {info.version}...", "取消", 0, 100, self)  # type: ignore[attr-defined]
        self._progress_dlg.setWindowTitle("更新")
        self._progress_dlg.setMinimumDuration(0)
        self._progress_dlg.setValue(0)
        self._progress_dlg.canceled.connect(self._cancel_download)
        self._cancelled = False

        threading.Thread(target=self._download_worker, args=(info,), daemon=True).start()

    def _download_worker(self, info: object) -> None:
        import tempfile
        from pathlib import Path

        from atprobe.infra.update import DownloadCancelled, DownloadError
        from atprobe.infra.update.downloader import download

        url = getattr(info, "zip_url", "")
        name = f"ATProbe-{getattr(info, 'version', '')}-win64.zip"
        try:
            result = download(
                url,
                Path(tempfile.gettempdir()),
                filename=name,
                expected_size=getattr(info, "zip_size", None),
                progress_cb=lambda d, t: self.update_download_progress.emit(d, t),
                cancel_token=lambda: getattr(self, "_cancelled", False),
            )
            self.update_download_done.emit(result.path)
        except (DownloadCancelled, DownloadError, Exception) as exc:  # noqa: BLE001
            self.update_download_done.emit(exc)
```

- [ ] **Step 7: 实现进度更新与下载完成处理**

```python
    def _on_download_progress(self, done: int, total: int) -> None:
        if hasattr(self, "_progress_dlg") and total > 0:
            self._progress_dlg.setValue(done * 100 // total)

    def _cancel_download(self) -> None:
        self._cancelled = True

    def _on_download_done(self, result: object) -> None:
        """下载完成（Path）或失败（Exception）。"""
        from PySide6.QtWidgets import QApplication, QMessageBox

        from atprobe.infra.update import DownloadCancelled, DownloadError

        if hasattr(self, "_progress_dlg"):
            self._progress_dlg.close()
        self._update_in_progress = False

        if isinstance(result, Exception):
            if not isinstance(result, DownloadCancelled):
                QMessageBox.critical(self, "更新失败", f"下载失败：{result}")
            return
        # 下载成功 → 最终确认安装
        from pathlib import Path

        zip_path = Path(result)  # type: ignore[arg-type]
        choice = QMessageBox.question(
            self, "开始安装",
            "更新已就绪。点击「是」后程序将关闭并自动完成升级（约 5 秒）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        from atprobe.infra.runtime import app_root
        from atprobe.infra.update import UpdateError
        from atprobe.infra.update.installer import apply_update

        try:
            apply_update(zip_path, app_root())
        except UpdateError as exc:
            QMessageBox.critical(self, "安装失败", str(exc))
            return
        # 脚本已 detached 启动，主动退出
        QApplication.quit()
```

- [ ] **Step 8: 运行 GUI 集成测试（确认不破坏构造）**

Run: `uv run pytest tests/integration/test_gui.py -v`
Expected: 全部 passed（含原有 + Task 10 新增）

- [ ] **Step 9: 提交**

```bash
git add src/atprobe/gui/mainwindow.py
git commit -m "feat(update): GUI 检查更新 + 升级对话框 + 下载进度 + 安装确认"
```

---

## Task 12: GUI 启动自动检查

窗口 show 后延迟 3 秒静默检查。

**Files:**
- Modify: `src/atprobe/gui/app.py`（`run_gui` 末尾加 QTimer）

- [ ] **Step 1: 修改 `src/atprobe/gui/app.py` `run_gui`**

在 `win.show()` 之后、`return app.exec()` 之前加入：

```python
    # 启动 3 秒后静默检查更新（后台线程，失败不打扰）
    from PySide6.QtCore import QTimer

    def _startup_check():
        win._check_update(manual=False)  # noqa: SLF001

    QTimer.singleShot(3000, _startup_check)
```

- [ ] **Step 2: 运行 GUI 集成测试确认不破坏**

Run: `uv run pytest tests/integration/test_gui.py -v`
Expected: 全部 passed

- [ ] **Step 3: 提交**

```bash
git add src/atprobe/gui/app.py
git commit -m "feat(update): GUI 启动 3 秒后静默检查更新"
```

---

## Task 13: 最终全量验证

所有功能集成完成后的整体验证。

**Files:** 无（验证任务）

- [ ] **Step 1: 全量测试**

Run: `uv run pytest -q`
Expected: 全部 passed

- [ ] **Step 2: ruff + mypy**

Run: `uv run ruff check src tests && uv run mypy src`
Expected: 无错误

- [ ] **Step 3: 版本一致性**

Run: `uv run pytest tests/unit/test_version_consistency.py -v && uv run atprobe --version`
Expected: 测试 passed，`--version` 显示 0.2.1

- [ ] **Step 4: CLI 烟雾测试**

Run: `uv run atprobe update --help && uv run atprobe --help`
Expected: update 子命令注册正常

- [ ] **Step 5: 本地构建验证（注入 VERSION）**

Run: `uv run python packaging/build.py`
Expected:
- 构建成功
- `dist/ATProbe-0.2.1/_internal/VERSION` 存在且内容为 `0.2.1`
- 仓库根 `VERSION` 同步为 `0.2.1`
- zip 大小约 80MB（与之前一致）

验证 VERSION 文件：
Run: `cat dist/ATProbe-0.2.1/_internal/VERSION`
Expected: `0.2.1`

- [ ] **Step 6: 打包态运行时版本读取验证**

Run: `dist/ATProbe-0.2.1/atprobe.exe --version`
Expected: `atprobe 0.2.1`（证明 VERSION 注入 + current_version 在打包态工作）

- [ ] **Step 7: 打包态 GUI 冒烟（启动后杀掉）**

Run（Windows，5 秒后超时杀掉）：
```bash
timeout 8 dist/ATProbe-0.2.1/ATProbe.exe; echo "exit=$?"
```
Expected: 程序启动（无崩溃），超时后被杀（exit code 非关健，关键是能启动）

- [ ] **Step 8: 清理构建产物（不入库）**

```bash
rm -rf dist packaging/build packaging/atprobe.rendered.spec packaging/build.log
```

- [ ] **Step 9: 最终提交（如有清理 .gitignore 或文档更新）**

```bash
git status
# 若仅 dist 等产物被 .gitignore 忽略，无新增可提交文件，则跳过此步
```

---

## 手动验收清单（spec §10.2，需真实发版 + 真实 Windows 桌面）

> 这部分无法自动化，需在真实环境执行。实现完成后由开发者手动走一遍：

1. 本地用旧版 zip（0.2.1）+ 推一个 v0.3.0 tag（改 pyproject.toml version=0.3.0 + VERSION=0.3.0 → tag → push）触发 release
2. 双击 0.2.1 exe → 3 秒后弹"发现新版本"
3. 点"立即更新" → 进度条到 100%
4. 点"开始安装" → 程序退出 → bat 替换 → 自动重启
5. 验证 `atprobe.exe --version` 显示 0.3.0
6. 验证 reports/、logs/、atprobe.yaml、examples/ 完好无损
7. CLI `atprobe update --check` 报告已是最新
8. 模拟断网 → 启动不报错、手动检查弹"网络失败"
9. 模拟升级失败（如手动锁文件）→ 回滚到旧版 + 弹错误框
