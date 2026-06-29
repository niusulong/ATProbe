# ATProbe 打包、安装与分发 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ATProbe 从「开发仓库运行」升级为「双击即用的 Windows 可执行分发包」，通过 GitHub Actions 在打 tag 时自动构建并发布 zip 到 GitHub Releases。

**Architecture:** 用 PyInstaller onedir 把 Python + PySide6 运行时打进目录；双入口（GUI exe + CLI exe）共享 `_internal` 运行时；引入 `runtime.py`/`resources.py` 消除所有 `parents[N]` 硬编码，统一资源定位（内置只读 via importlib.resources，用户可写 via exe 同级目录）；`packaging/build.py` 一键构建（本地与 CI 同一条命令）；`.github/workflows/release.yml` tag 触发自动发布。

**Tech Stack:** Python 3.11 · PyInstaller ≥6.0 · PySide6 · hatchling · GitHub Actions · uv

**Spec:** `docs/superpowers/specs/2026-06-29-packaging-and-distribution-design.md`

---

## 分支起点

从 `main` 起新分支 `feat/packaging`：
```bash
git checkout main
git pull
git checkout -b feat/packaging
```

---

## 文件结构

### 新增

| 路径 | 职责 |
|---|---|
| `src/atprobe/infra/runtime.py` | 打包态检测：`is_frozen()` / `app_root()`。唯一判据入口 |
| `src/atprobe/infra/resources.py` | 资源定位：内置只读（importlib.resources）/ 用户可写（app_root） |
| `packaging/entry_gui.py` | GUI 入口脚本（→ ATProbe.exe） |
| `packaging/entry_cli.py` | CLI 入口脚本（→ atprobe-cli.exe） |
| `packaging/atprobe.spec` | PyInstaller onedir spec（双 EXE） |
| `packaging/build.py` | 本地/CI 一键构建脚本 |
| `packaging/hooks/hook-atprobe.py` | PyInstaller hook（收集 atprobe 子模块） |
| `packaging/atprobe.yaml.template` | 用户工作区配置模板（外露到 zip 根） |
| `packaging/README.txt` | 解压后给最终用户看的说明 |
| `.github/workflows/release.yml` | tag 触发的自动发布流水线 |
| `tests/unit/test_runtime_resources.py` | runtime/resources 单测 |
| `tests/unit/test_store_builtin_path.py` | store.py 改造后的回归测试 |
| `tests/unit/test_mainwindow_env_fallback.py` | mainwindow env 回退的回归测试 |

### 修改

| 路径 | 改动 |
|---|---|
| `src/atprobe/domain/quickcmd/store.py` | 删 `_PROJECT_ROOT`/`_BUILTIN_PATH`，`builtin_library_path()` 改调 `resources` |
| `src/atprobe/gui/mainwindow.py:258` | `env_config_path()` 回退改调 `resources` |
| `pyproject.toml` | 新增 `packaging` extra；`examples/`/`packaging/README.txt` 纳入构建 |
| `README.md` | 补「下载使用」与「发布」章节 |

---

## Task 1：runtime.py — 打包态检测器

**Files:**
- Create: `src/atprobe/infra/runtime.py`
- Test: `tests/unit/test_runtime_resources.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_runtime_resources.py`：
```python
"""runtime.py 与 resources.py 单测。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atprobe.infra import runtime


def test_is_frozen_default_false():
    """开发态 sys.frozen 不存在 → False。"""
    assert runtime.is_frozen() is False


def test_is_frozen_true_when_sys_frozen_set():
    """打包态 sys.frozen 存在 → True。"""
    with patch.object(runtime.sys, "frozen", True, create=True):
        assert runtime.is_frozen() is True


def test_app_root_dev_mode_returns_repo_root():
    """开发态：app_root() 返回仓库根（含 pyproject.toml）。"""
    root = runtime.app_root()
    assert (root / "pyproject.toml").exists()
    assert (root / "src" / "atprobe").exists()


def test_app_root_frozen_returns_executable_dir(tmp_path):
    """打包态：app_root() 返回 sys.executable 所在目录。"""
    fake_exe = tmp_path / "ATProbe.exe"
    fake_exe.write_text("")
    with patch.object(runtime.sys, "frozen", True, create=True), \
         patch.object(runtime.sys, "executable", str(fake_exe)):
        assert runtime.app_root() == tmp_path
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_runtime_resources.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'atprobe.infra.runtime'`）

- [ ] **Step 3: 实现 runtime.py**

创建 `src/atprobe/infra/runtime.py`：
```python
"""打包态运行时检测。

统一「我该去哪找文件」的判据，消除散落各处的 ``Path(__file__).parents[N]`` 硬编码。
- 开发态：仓库根（``src/atprobe/infra/runtime.py`` 上溯 2 级）
- 打包态：exe 所在目录（便携式工作区根）

判据：``sys.frozen`` 是否存在（PyInstaller 注入）。
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境。"""
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """应用根目录。

    - 打包态：exe 所在目录（便携式工作区根，用户可写）
    - 开发态：仓库根（含 pyproject.toml / src / examples）
    """
    if is_frozen():
        return Path(sys.executable).parent
    # src/atprobe/infra/runtime.py → 上溯 2 级到仓库根
    return Path(__file__).resolve().parents[2]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_runtime_resources.py -v`
Expected: 4 PASS

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/infra/runtime.py tests/unit/test_runtime_resources.py
git commit -m "feat(infra): runtime.py 打包态检测器（is_frozen/app_root）"
```

---

## Task 2：resources.py — 资源定位（内置只读 / 用户可写）

**Files:**
- Create: `src/atprobe/infra/resources.py`
- Test: `tests/unit/test_runtime_resources.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `tests/unit/test_runtime_resources.py` 末尾追加：
```python
from atprobe.infra import resources


def test_builtin_resource_env_yaml_exists():
    """内置 env.yaml 存在（开发态从仓库 examples 读到）。"""
    p = resources.builtin_resource("env.yaml")
    assert p.exists()
    assert p.name == "env.yaml"


def test_builtin_resource_quick_commands_exists():
    """内置 quick_commands.yaml 存在。"""
    p = resources.builtin_resource("quick_commands.yaml")
    assert p.exists()


def test_builtin_resource_missing_raises():
    """不存在的资源 → FileNotFoundError。"""
    import pytest
    with pytest.raises(FileNotFoundError):
        resources.builtin_resource("does_not_exist.yaml")


def test_user_workspace_dev_mode_returns_repo_root():
    """用户工作区 = app_root（开发态仓库根）。"""
    ws = resources.user_workspace()
    assert (ws / "pyproject.toml").exists()


def test_user_workspace_frozen_returns_exe_dir(tmp_path):
    """打包态用户工作区 = exe 同级目录。"""
    (tmp_path / "ATProbe.exe").write_text("")
    with patch.object(resources.sys, "frozen", True, create=True), \
         patch.object(resources.sys, "executable", str(tmp_path / "ATProbe.exe")):
        assert resources.user_workspace() == tmp_path
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_runtime_resources.py -v -k resource`
Expected: FAIL（`ImportError: cannot import name 'resources'`）

- [ ] **Step 3: 实现 resources.py**

创建 `src/atprobe/infra/resources.py`：
```python
"""资源定位：内置只读资源 vs 用户可写工作区。

两类文件，两种策略：

1. **内置示例**（env.yaml / quick_commands.yaml / 出厂用例）
   只读，随包发布。开发态读仓库根 ``examples/``；打包态读
   ``_internal/examples/``（PyInstaller 注入，importlib.resources 可见）。

2. **用户工作区**（logs / 用户改的用例 / 用户保存的配置）
   可写、可持久化。统一锚定到 ``runtime.app_root()``：
   打包态 = exe 同级（便携式），开发态 = 仓库根。
"""

from __future__ import annotations

import sys
from pathlib import Path

from atprobe.infra.runtime import app_root, is_frozen


def builtin_resource(*parts: str) -> Path:
    """返回打包内置只读资源路径（examples/ 下）。

    开发态：``<repo>/examples/<parts>``
    打包态：``<app_root>/_internal/examples/<parts>``（PyInstaller datas 注入）

    Args:
        *parts: 相对 examples/ 的路径段，如 ``("testcases", "ntp", "x.yaml")``。

    Raises:
        FileNotFoundError: 两处都不存在。
    """
    rel = Path(*parts)

    # 打包态：PyInstaller 把 examples 打进 _internal/examples
    if is_frozen():
        candidate = app_root() / "_internal" / "examples" / rel
        if candidate.exists():
            return candidate
        # 极少数情况：onefile 解压目录
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            meipass_candidate = Path(meipass) / "examples" / rel
            if meipass_candidate.exists():
                return meipass_candidate
        raise FileNotFoundError(f"内置资源不存在（打包态）：{rel}")

    # 开发态：仓库根 examples
    candidate = app_root() / "examples" / rel
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"内置资源不存在（开发态）：{rel}")


def user_workspace() -> Path:
    """返回用户可写工作区根。

    打包态 = exe 同级目录（便携式）；开发态 = 仓库根。
    调用方在其下拼 ``logs`` / 用户用例目录等。
    """
    return app_root()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_runtime_resources.py -v`
Expected: 9 PASS（4 from Task 1 + 5 from Task 2）

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/infra/resources.py tests/unit/test_runtime_resources.py
git commit -m "feat(infra): resources.py 内置只读/用户可写资源定位"
```

---

## Task 3：改造 store.py — 消除 _PROJECT_ROOT

**Files:**
- Modify: `src/atprobe/domain/quickcmd/store.py`（删 L23–24，改 `builtin_library_path`）
- Test: `tests/unit/test_store_builtin_path.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_store_builtin_path.py`：
```python
"""store.py builtin_library_path 改造后的回归测试。"""

from __future__ import annotations

from pathlib import Path

from atprobe.domain.quickcmd.store import builtin_library_path


def test_builtin_library_path_exists():
    """builtin_library_path() 返回真实存在的 quick_commands.yaml。"""
    p = builtin_library_path()
    assert p.exists()
    assert p.name == "quick_commands.yaml"


def test_builtin_library_path_is_not_module_dir():
    """不能返回模块自身目录（即不能用 parents[N] 错位）。"""
    p = builtin_library_path()
    # 必须指向 examples/ 下，而非 atprobe 包内
    assert "examples" in p.parts
```

- [ ] **Step 2: 跑测试确认现状（先确认旧实现能过，作为基准）**

Run: `uv run pytest tests/unit/test_store_builtin_path.py -v`
Expected: PASS（旧实现 `_BUILTIN_PATH` 在开发态也能找到）—— 这一步是建立基准，确保改造不回归。

- [ ] **Step 3: 改造 store.py**

在 `src/atprobe/domain/quickcmd/store.py`：

删除 L23–24：
```python
# 项目根目录（src/atprobe/domain/quickcmd/store.py → 上溯 4 级到项目根）
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BUILTIN_PATH = _PROJECT_ROOT / "examples" / "quick_commands.yaml"
```

把末尾的 `builtin_library_path` 函数改为：
```python
def builtin_library_path() -> Path:
    """返回内置示例文件的绝对路径 examples/quick_commands.yaml。

    经 ``atprobe.infra.resources.builtin_resource`` 定位，开发态读仓库根、
    打包态读 _internal/examples，避免 ``parents[N]`` 硬编码在打包后失效。
    """
    from atprobe.infra.resources import builtin_resource

    return builtin_resource("quick_commands.yaml")
```

> 注：用函数内导入避免循环依赖风险，且仅在此函数用到。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_store_builtin_path.py tests/unit/test_runtime_resources.py -v`
Expected: PASS（11 个）

- [ ] **Step 5: 全量回归确认无副作用**

Run: `uv run pytest -q`
Expected: 全绿（基线 158 + 新增，应 ≥161）

- [ ] **Step 6: 提交**

```bash
git add src/atprobe/domain/quickcmd/store.py tests/unit/test_store_builtin_path.py
git commit -m "refactor(quickcmd): store.py 改用 resources.builtin_resource（消除 parents[4]）"
```

---

## Task 4：改造 mainwindow.py env_config_path 回退

**Files:**
- Modify: `src/atprobe/gui/mainwindow.py:252-259`
- Test: `tests/unit/test_mainwindow_env_fallback.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_mainwindow_env_fallback.py`：
```python
"""mainwindow env_config_path 回退路径改造后的回归测试。

不启动 Qt，直接测 MainWindow.env_config_path 的回退逻辑。
由于该方法是实例方法，用 unittest.mock 注入一个最小 AppConfig 实例。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from atprobe.infra.config.appconfig import AppConfig


def test_env_config_path_falls_back_to_builtin(tmp_path, monkeypatch):
    """用户 env_config 不存在时，回退到内置 resources.builtin_resource('env.yaml')。"""
    # 构造一个不依赖 Qt 的 MainWindow 骨架：直接绑方法所需的属性
    from atprobe.gui.mainwindow import MainWindow

    cfg = AppConfig(env_config=str(tmp_path / "nonexistent.yaml"))
    mw = MainWindow.__new__(MainWindow)  # 跳过 __init__（避免 Qt）
    mw._app_config = cfg

    result = mw.env_config_path()
    assert result is not None
    p = Path(result)
    assert p.exists()
    assert p.name == "env.yaml"


def test_env_config_path_uses_user_file_when_exists(tmp_path):
    """用户 env_config 存在时，优先用用户文件。"""
    from atprobe.gui.mainwindow import MainWindow

    user_env = tmp_path / "my-env.yaml"
    user_env.write_text("env: {}\n", encoding="utf-8")

    cfg = AppConfig(env_config=str(user_env))
    mw = MainWindow.__new__(MainWindow)
    mw._app_config = cfg

    assert mw.env_config_path() == str(user_env)
```

- [ ] **Step 2: 跑测试确认失败（或基准通过）**

Run: `uv run pytest tests/unit/test_mainwindow_env_fallback.py -v`
Expected: 旧实现可能 PASS（开发态 `parents[3]` 也能找到）—— 基准。

- [ ] **Step 3: 改造 mainwindow.py**

在 `src/atprobe/gui/mainwindow.py`，找到 `env_config_path` 方法（约 L252–259），改为：
```python
    def env_config_path(self) -> str | None:
        # 优先用用户配置（app.yaml 的 env_config）；不存在则回退到项目内置示例，
        # 确保环境配置页默认打开就有内容可编辑，而非空白页。
        # 经 resources.builtin_resource 定位，开发态/打包态皆可用。
        p = Path(self._app_config.env_config)
        if p.exists():
            return str(p)
        from atprobe.infra.resources import builtin_resource

        try:
            builtin = builtin_resource("env.yaml")
            return str(builtin)
        except FileNotFoundError:
            return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_mainwindow_env_fallback.py -v`
Expected: 2 PASS

- [ ] **Step 5: 提交**

```bash
git add src/atprobe/gui/mainwindow.py tests/unit/test_mainwindow_env_fallback.py
git commit -m "refactor(gui): env_config_path 回退改用 resources（消除 parents[3]）"
```

---

## Task 5：确认无残留 parents[N] 硬编码

**Files:** 无新增，仅审计

- [ ] **Step 1: 全局扫描残留**

用 Grep 工具搜索 `parents\[\d+\]`，范围 `src/atprobe/`（排除 `runtime.py` 本身）：
- 若用 ZCode/Grep 工具：pattern=`parents\[\d+\]`，path=`src/atprobe`
- 或命令行：`uv run python -c "import pathlib,sys; [print(p) for p in pathlib.Path('src/atprobe').rglob('*.py') for i,l in enumerate(p.read_text(encoding='utf-8').splitlines(),1) if 'parents[' in l and 'runtime.py' not in str(p)]"`

Expected: 只允许 `runtime.py` 内出现 `parents[2]`（那是开发态锚点，合法）。其他位置每个都改调 `runtime.app_root()` 或 `resources.builtin_resource()`，并补单测后单独提交。

> 如发现其他位置，每个都改调 `runtime.app_root()` 或 `resources.builtin_resource()`，并补单测后单独提交。

- [ ] **Step 2: 全量回归**

Run: `uv run pytest -q`
Expected: 全绿

- [ ] **Step 3: 提交（若有补改）**

```bash
# 仅当 Step 1 发现并修复了额外位置时
git add -A
git commit -m "refactor: 消除剩余 parents[N] 硬编码路径"
```

---

## Task 6：packaging/ 入口脚本

**Files:**
- Create: `packaging/entry_gui.py`
- Create: `packaging/entry_cli.py`

- [ ] **Step 1: 创建 entry_gui.py**

创建 `packaging/entry_gui.py`：
```python
"""ATProbe GUI 入口（打包用）。

双击 ATProbe.exe 直接进 GUI，跳过 Typer CLI 层，对非技术用户友好。
PyInstaller 把本文件作为 Analysis 第一个脚本，生成 console=False 的 ATProbe.exe。
"""

from __future__ import annotations

import sys

from atprobe.gui.app import run_gui

if __name__ == "__main__":
    sys.exit(run_gui())
```

- [ ] **Step 2: 创建 entry_cli.py**

创建 `packaging/entry_cli.py`：
```python
"""ATProbe CLI 入口（打包用）。

暴露完整 run/list/gui 子命令，供会命令行的工程师使用：
    atprobe-cli.exe run examples/testcases/ntp/x.yaml --port COM5:115200
    atprobe-cli.exe list cases
PyInstaller 把本文件作为 Analysis 第二个脚本，生成 console=True 的 atprobe-cli.exe。
"""

from __future__ import annotations

from atprobe.cli.main import app

if __name__ == "__main__":
    app()
```

- [ ] **Step 3: 烟测入口能 import**

Run: `uv run python -c "import importlib.util; spec=importlib.util.spec_from_file_location('e','packaging/entry_gui.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)" 2>&1 | head`
Expected: 无报错（PySide6 已装）。若报 PySide6 未装，先 `uv sync --extra gui`。

对 entry_cli 同样验证：
Run: `uv run python -c "import importlib.util; spec=importlib.util.spec_from_file_location('e','packaging/entry_cli.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)"`
Expected: 无报错（应打印 Typer help，因为无参数）。

- [ ] **Step 4: 提交**

```bash
git add packaging/entry_gui.py packaging/entry_cli.py
git commit -m "feat(packaging): GUI/CLI 双入口脚本"
```

---

## Task 7：PyInstaller spec + hook

**Files:**
- Create: `packaging/atprobe.spec`
- Create: `packaging/hooks/hook-atprobe.py`

- [ ] **Step 1: 创建 spec**

创建 `packaging/atprobe.spec`：
```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec — ATProbe（GUI + CLI 双入口，Windows x64）。

构建：uv run python packaging/build.py（build.py 会动态注入版本号到 COLLECT name）。
关键点：
  - collect_all('PySide6'/'shiboken6')：Qt 插件全量收集，否则启动崩
  - collect_submodules('atprobe')：覆盖延迟导入
  - examples/ 打进 _internal/examples（via importlib.resources）
  - 双 EXE：GUI（console=False）+ CLI（console=True）共享 COLLECT
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = []
binaries = []
hiddenimports = []

# Qt6 / PySide6 全量收集（plugins、translations、QML）—— 打包铁律
for pkg in ("PySide6", "shiboken6"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 内置只读资源 → _internal/examples（resources.py 经 importlib.resources 读取）
datas += [
    ("../examples/env.yaml", "examples"),
    ("../examples/quick_commands.yaml", "examples"),
    ("../examples/testcases", "examples/testcases"),
]

# 源码全量收集（含延迟导入的子模块）
hiddenimports += collect_submodules("atprobe")

a = Analysis(
    ["entry_gui.py", "entry_cli.py"],
    pathex=[str(Path("..", "src").resolve())],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(Path("hooks").resolve())],
    excludes=["tkinter", "PyQt5", "PyQt6", "pytest", "_pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# GUI exe：取 Analysis scripts[0]（entry_gui.py 对应），console=False
gui_exe = EXE(
    pyz,
    a.scripts[:1],
    [],
    exclude_binaries=True,
    name="ATProbe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,  # 后续可加 packaging/atprobe.ico
)

# CLI exe：取 Analysis scripts[1]（entry_cli.py 对应），console=True
cli_exe = EXE(
    pyz,
    a.scripts[1:],
    [],
    exclude_binaries=True,
    name="atprobe-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

# COLLECT name 由 build.py 在调用前用字符串注入版本号（见 build.py 的 spec 渲染）
# 此处占位 ATProbe-VERSION，build.py 会 sed 替换。
COLLECT(gui_exe, cli_exe, a.binaries, a.datas, name="ATProbe-VERSION")
```

- [ ] **Step 2: 创建 hook**

创建 `packaging/hooks/hook-atprobe.py`：
```python
"""PyInstaller hook：收集 atprobe 全部子模块（覆盖延迟导入）。"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("atprobe")
```

- [ ] **Step 3: 静态校验 spec 可被 PyInstaller 解析**

Run: `uv run pip install pyinstaller && uv run python -c "import ast; ast.parse(open('packaging/atprobe.spec').read()); print('spec syntax OK')"`
Expected: `spec syntax OK`

- [ ] **Step 4: 提交**

```bash
git add packaging/atprobe.spec packaging/hooks/hook-atprobe.py
git commit -m "feat(packaging): PyInstaller onedir spec + atprobe hook"
```

---

## Task 8：用户工作区模板 + README

**Files:**
- Create: `packaging/atprobe.yaml.template`
- Create: `packaging/README.txt`

- [ ] **Step 1: 看现有 atprobe.yaml 模板**

Run: `cat examples/atprobe.yaml`（了解配置结构，作为模板基础）

- [ ] **Step 2: 创建用户工作区配置模板**

创建 `packaging/atprobe.yaml.template`（用户解压后改名 atprobe.yaml 放 exe 同级即可自定义）：
```yaml
# ATProbe 用户配置（便携版）
# 解压后把本文件改名为 atprobe.yaml 放在 ATProbe.exe 同级目录即可生效。
# 所有路径相对 exe 所在目录。

# 端口列表（COM 名:波特率:帧格式）。先从设备管理器查你的 COM 号。
ports:
  - "COM5:115200:8N1"

default:
  step_timeout: 5.0
  baud: 115200
  log_level: progress   # progress | debug

# 用例目录（相对 exe 同级）
cases_dir: "./examples/testcases"
report_dir: "./reports"
env_config: "./examples/env.yaml"

console:
  color: true
  command_truncate: 40

log:
  dir: "./logs"
  keep: 0   # 0 = 不自动清理，手动删

pressure:
  pass_rate_threshold: 95.0
```

- [ ] **Step 3: 创建给最终用户的 README**

创建 `packaging/README.txt`：
```
ATProbe — 串口 AT 命令自动化测试工具
========================================

【快速开始】
1. 解压本压缩包到任意目录（如 D:\ATProbe）
2. 双击 ATProbe.exe 启动图形界面
3. 在「环境配置」页填你的串口（如 COM5:115200:8N1）

【命令行用法】（可选）
  atprobe-cli.exe list cases
  atprobe-cli.exe run examples\testcases\ntp\xxx.yaml --port COM5:115200

【自定义】
- 改用例：编辑 examples\testcases\ 下的 .yaml 文件
- 改默认配置：把 atprobe.yaml.template 复制为 atprobe.yaml，放在
  ATProbe.exe 同级目录，按需修改后重启程序
- 日志在 logs\，报告在 reports\

【系统要求】
- Windows 10/11 x64
- 无需安装 Python，本程序已内置运行环境
- 首次运行若被杀毒软件拦截，请加白名单（程序未做代码签名）

【版本】见 ATProbe.exe「关于」或 atprobe-cli.exe --version
```

- [ ] **Step 4: 提交**

```bash
git add packaging/atprobe.yaml.template packaging/README.txt
git commit -m "feat(packaging): 用户工作区配置模板 + 最终用户 README"
```

---

## Task 9：build.py — 一键构建脚本

**Files:**
- Create: `packaging/build.py`

- [ ] **Step 1: 创建 build.py**

创建 `packaging/build.py`：
```python
"""ATProbe 一键构建脚本（本地与 CI 共用同一条命令）。

用法：
    uv run python packaging/build.py

流程：
  1. 从 pyproject.toml 读 version（单一真相源）
  2. 渲染 atprobe.spec：把 ATProbe-VERSION 替换为 ATProbe-<version>
  3. 调 PyInstaller 构建（onedir）
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
    """调用 PyInstaller 构建（cwd=packaging/，让 spec 内相对路径生效）。"""
    cmd = [sys.executable, "-m", "PyInstaller", str(rendered_spec), "--noconfirm"]
    print(f"[build] 运行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=PACKAGING)


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


def make_zip(app_dir: Path, version: str) -> Path:
    """压缩产物目录 → dist/ATProbe-<version>-win64.zip。"""
    zip_path = DIST / f"ATProbe-{version}-win64.zip"
    zip_path.unlink(missing_ok=True)
    arcname_root = app_dir.name  # ATProbe-<version>
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
    zip_path = make_zip(app_dir, version)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[build] 完成：{zip_path}（{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 在 pyproject.toml 加 packaging extra**

修改 `pyproject.toml` 的 `[project.optional-dependencies]`，在 `dev` 之后加：
```toml
packaging = [
    "pyinstaller>=6.0",
]
```

- [ ] **Step 3: 装构建依赖并冒烟跑构建（本地验证）**

Run:
```bash
uv sync --extra gui --extra packaging
uv run python packaging/build.py
```
Expected:
- `dist/ATProbe-<version>/` 目录生成，含 `ATProbe.exe`、`atprobe-cli.exe`、`_internal/`、`examples/`、`atprobe.yaml.template`、`README.txt`
- `dist/ATProbe-<version>-win64.zip` 生成（40–120MB）

> 首次 PyInstaller 构建约 2–4 分钟。若失败，看报错——常见：Qt 插件缺失（检查 collect_all）、隐藏 import（检查 hook）。

- [ ] **Step 4: 手动验证产物（关键！）**

在 `dist/ATProbe-<version>/` 下：
```bash
./ATProbe.exe          # 应启动 GUI，无黑窗、无报错
./atprobe-cli.exe list cases   # 应列出 examples/testcases/ 用例
```
逐条核对 spec §6.2 验证清单：
- [ ] GUI 启动无黑窗、无报错
- [ ] GUI「环境配置」页默认有内容（env.yaml 回退生效）
- [ ] GUI「手动调试」命令库有默认指令（quick_commands.yaml 回退生效）
- [ ] GUI「用例执行」列出 examples/testcases/ 用例
- [ ] `atprobe-cli.exe list cases` 正常输出
- [ ] `atprobe-cli.exe --version` 输出版本号

> 完整「运行用例产生 logs」验证需接 COM5 硬件；若手边无硬件，至少确认 GUI 能开、命令库/环境配置有内容。

- [ ] **Step 5: 加 .gitignore 排除构建产物**

确认项目根 `.gitignore` 含：
```
dist/
build/
*.spec.bak
packaging/atprobe.rendered.spec
packaging/__pycache__/
```
若缺，追加。

- [ ] **Step 6: 提交**

```bash
git add packaging/build.py packaging/atprobe.spec pyproject.toml .gitignore
git commit -m "feat(packaging): build.py 一键构建（本地/CI 同一命令）+ packaging extra"
```

---

## Task 10：GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: 创建 workflow**

创建 `.github/workflows/release.yml`：
```yaml
name: Release

# 仅在推送 v*.*.* tag 时触发构建发布；普通 push 不构建
on:
  push:
    tags:
      - "v*.*.*"

# 需要写权限以创建 Release 并上传 asset
permissions:
  contents: write

jobs:
  build-and-release:
    runs-on: windows-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install uv
        run: pip install uv

      - name: Sync dependencies（运行时 + PyInstaller）
        run: uv sync --extra gui --extra packaging

      - name: Build
        run: uv run python packaging/build.py

      - name: Upload artifact（便于排查）
        uses: actions/upload-artifact@v4
        with:
          name: ATProbe-win64-zip
          path: dist/ATProbe-*-win64.zip
          if-no-files-found: error

      - name: Create GitHub Release & upload zip
        uses: softprops/action-gh-release@v2
        with:
          files: dist/ATProbe-*-win64.zip
          generate_release_notes: true   # 自动从 commit 生成 changelog
          fail_on_unmatched_files: true
```

- [ ] **Step 2: 静态校验 YAML 语法**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/release.yml
git commit -m "ci: tag 触发自动构建并发布到 GitHub Releases"
```

---

## Task 11：README 文档更新

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README.md 安装章节后插入「下载使用」与「发布」**

在 `README.md` 的 `## 安装（开发）` 章节之后、`## 使用` 之前，插入：

```markdown
## 下载使用（最终用户）

无需安装 Python。从 [Releases](../../releases) 下载 `ATProbe-<version>-win64.zip`，解压后双击 `ATProbe.exe` 即可。

详细说明见压缩包内 `README.txt`。
```

并在 `## 开发` 章节之后，文件末尾追加：

```markdown
## 打包与发布

### 本地构建（验证用）

```bash
uv sync --extra gui --extra packaging
uv run python packaging/build.py
# 产物：dist/ATProbe-<version>-win64.zip
```

### 自动发布（GitHub Actions）

1. 改 `pyproject.toml` 的 `version` → commit
2. `git tag v<version> && git push origin v<version>`
3. GitHub Actions 自动构建并发布到 Releases（约 3–5 分钟）

详见 [`docs/superpowers/specs/2026-06-29-packaging-and-distribution-design.md`](docs/superpowers/specs/2026-06-29-packaging-and-distribution-design.md)。
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: README 补下载使用与打包发布章节"
```

---

## Task 12：端到端验证 + 合并准备

**Files:** 无新增，仅验证

- [ ] **Step 1: 全量回归测试**

Run: `uv run pytest -q`
Expected: 全绿（应 ≥163：158 基线 + Task1/2/3/4 新增）

- [ ] **Step 2: 本地完整构建冒烟**

Run: `uv run python packaging/build.py`
Expected: zip 生成，且 Task 9 Step 4 的验证清单全过。

- [ ] **Step 3: lint + type check 不破坏**

Run:
```bash
uv run ruff check src tests packaging
uv run mypy src
```
Expected: 无新增错误（packaging/ 脚本是构建期，mypy 范围是 src；ruff 对 packaging 建议干净）。

- [ ] **Step 4: 触发一次真实 tag 发布（可选，需推送权限）**

```bash
# 仅当分支已合并 main 且你确认要发版时
git checkout main
git merge --no-ff feat/packaging
# 改 pyproject.toml version 为 0.1.0（若已是则跳过），commit
git tag v0.1.0
git push origin main --tags
```
Expected: GitHub Actions 触发，几分钟后 Releases 页出现 zip。

> 这一步是 outward-facing 不可逆动作，**必须用户确认后再做**。

- [ ] **Step 5: 收尾**

分支 `feat/packaging` 完成使命，视团队流程决定是否删除。

---

## 验证总结（对应 spec §6.2）

| spec §6.2 验证项 | 对应 Task |
|---|---|
| 双击 ATProbe.exe → GUI 启动 | Task 9 Step 4 |
| 环境配置页有内容（env.yaml 回退） | Task 4 + Task 9 Step 4 |
| 命令库有默认指令（quick_commands 回退） | Task 3 + Task 9 Step 4 |
| 用例执行列出 examples/testcases | Task 9 Step 4 |
| atprobe-cli.exe list/run 跑通 | Task 9 Step 4 |
| 关闭再开用户配置持久化 | Task 9 Step 4（需硬件或 vsim） |
| 开发态全量测试不回归 | Task 1/3/4/5/12 |
