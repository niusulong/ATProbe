# ATProbe 打包、安装与分发设计

- 日期：2026-06-29
- 状态：已批准（设计阶段）
- 范围：把 ATProbe（Python/PySide6 串口 AT 命令测试工具）从「开发仓库运行」升级为「双击即用的 Windows 可执行分发包」，并通过 GitHub Actions 自动发布到 GitHub Releases

---

## 1. 背景与目标

### 1.1 现状

ATProbe 当前只能在开发态运行（`uv run atprobe ...`）。最终使用者多为**没有 Python 环境的硬件测试/QA 人员**，他们需要的是「下载 → 解压 → 双击」即可使用的 Windows 可执行程序。

### 1.2 已确认的关键决策

| 决策项 | 选择 | 理由 |
|---|---|---|
| 使用者 | 非技术测试人员，双击即用 exe | 目标用户无 Python 环境 |
| 目标平台 | 仅 Windows x64 | COM5/USB 转串场景均在 Windows |
| 分发渠道 | GitHub Releases | 代码已在 `github.com/niusulong/ATProbe`，自带版本记录 |
| 打包形态 | onedir 目录版 + zip 压缩包 | 启动快（<1s）、examples 可外露、多文件可读 |
| 构建方式 | GitHub Actions 自动化（tag 触发） | 一次配置，后续只需 `git tag` |
| 打包器 | PyInstaller | 与 PySide6/Qt6 配合最成熟、社区文档最全 |

### 1.3 成功标准

1. 推送 `v*.*.*` tag → GitHub Actions 自动构建并发布 `ATProbe-<version>-win64.zip` 到该 tag 的 Release
2. 使用者在干净 Windows 机器下载 zip、解压、双击 `ATProbe.exe` → GUI 正常启动（无需 Python、无需安装）
3. GUI 内功能在打包态与开发态行为一致：能打开/运行 examples 用例、能写日志到工作区、环境配置默认有内容
4. 命令行用户可用 `atprobe-cli.exe run/list/gui`
5. 构建可复现：本地 `packaging/build.py` 与 CI 跑同一条命令，产物一致

### 1.4 非目标（YAGNI）

- 不做代码签名（个人/内部项目，杀软误报接受手动加白）
- 不做自动更新 / 在线升级（YAGNI，使用者重新下载即可）
- 不做 macOS/Linux 多平台（仅 Windows）
- 不做安装器（.msi/.exe installer）—— zip 解压即用已满足需求
- 不做 wheel 发布到 PyPI（工具面向固定团队，git 即分发）

---

## 2. 核心问题：资源文件定位（打包成败关键）

### 2.1 现有隐患

当前代码有两处 `Path(__file__).resolve().parents[N]` 硬编码回溯，在开发仓库里能跑，但**一旦 PyInstaller 打包就崩**（`__file__` 落到 `_internal\atprobe\...`，上溯 N 级到不了仓库根的 `examples/`）：

| 位置 | 代码 | 影响 |
|---|---|---|
| `src/atprobe/domain/quickcmd/store.py:23` | `_PROJECT_ROOT = Path(__file__).resolve().parents[4]` | 命令库默认示例找不到 |
| `src/atprobe/gui/mainwindow.py:258` | `Path(__file__).resolve().parents[3] / "examples" / "env.yaml"` | 环境配置页空白 |

### 2.2 解法：运行时检测 + importlib.resources

引入两个新模块，彻底消除 `parents[N]` 硬编码：

#### `src/atprobe/infra/runtime.py` — 打包态检测
```python
import sys
from pathlib import Path

def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境（sys.frozen 存在）。"""
    return getattr(sys, "frozen", False)

def app_root() -> Path:
    """应用根目录：
    - 打包态：exe 所在目录（便携式工作区根）
    - 开发态：仓库根
    """
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]  # src/atprobe/infra → 仓库根
```

#### `src/atprobe/infra/resources.py` — 资源定位（两类文件，两种策略）

| 文件类型 | 定位方式 | 读写性 | 位置 |
|---|---|---|---|
| **内置示例**（`env.yaml`、`quick_commands.yaml` 默认值、出厂用例） | `importlib.resources`（PyInstaller 原生支持） | 只读 | 打包后 `_internal/examples/` |
| **用户工作区**（`logs/`、用户改的用例、用户保存的命令库） | `runtime.app_root() / "..."` | 读写 | exe 同级（便携式） |

```python
from importlib import resources
from atprobe.infra.runtime import app_root

def builtin_resource(*parts: str) -> Path:
    """打包内置只读资源（examples/ 下），via importlib.resources。"""
    # 开发态读仓库根 examples；打包态读 _internal/examples（PyInstaller 注入）
    with resources.files("atprobe") as pkg_dir:
        candidate = Path(str(pkg_dir)).parent.parent / "examples" / Path(*parts)
        if candidate.exists():
            return candidate
    # 打包态：PyInstaller 把 examples 打到 _internal/examples
    frozen_candidate = app_root() / "_internal" / "examples" / Path(*parts)
    if frozen_candidate.exists():
        return frozen_candidate
    raise FileNotFoundError(f"内置资源不存在：{parts}")

def user_workspace() -> Path:
    """用户可写工作区根：打包态 = exe 同级；开发态 = 仓库根。"""
    return app_root()
```

> **关键原则**：所有「我该去哪找文件」的逻辑必须走 `runtime.py` / `resources.py`，**绝不再出现 `parents[N]`**。这是打包能否跑通的判据。

### 2.3 现有代码改造点

| 文件 | 改造 |
|---|---|
| `store.py` | 删 `_PROJECT_ROOT`/`_BUILTIN_PATH`；`builtin_library_path()` 改调 `resources.builtin_resource("quick_commands.yaml")` |
| `mainwindow.py` `env_config_path()` | 回退路径改调 `resources.builtin_resource("env.yaml")` |
| `logs/` 写入路径（若有硬编码） | 改走 `runtime.app_root() / "logs"` |

---

## 3. 双入口 exe 与运行时

### 3.1 入口脚本（`packaging/entry_*.py`）

放专门的 `packaging/` 目录，不污染仓库根：

```python
# packaging/entry_gui.py — GUI 入口（非技术用户双击）
import sys
from atprobe.gui.app import run_gui
sys.exit(run_gui())

# packaging/entry_cli.py — CLI 入口（会命令行的工程师）
from atprobe.cli.main import app
app()
```

### 3.2 打包态产物布局

```
ATProbe-<version>/
├── ATProbe.exe              ← 双击进 GUI（console=False，不弹黑窗）
├── atprobe-cli.exe          ← 命令行入口（console=True，保留控制台）
├── python311.dll
├── PySide6/                 ← Qt6 运行时
├── examples/                ← 外露用户工作区（可改）
│   ├── env.yaml
│   ├── quick_commands.yaml
│   └── testcases/{tcp,ntp}/
├── logs/                    ← 运行日志（运行时生成）
└── _internal/               ← PyInstaller 私有运行时（用户不用管）
```

**为什么 examples 外露**：用户的真实诉求是「改用例、配置环境」。`_internal` 是 PyInstaller 私有区，用户不该动；examples 放外面是用户的工作区。`cases_dir` 默认指向 `examples/testcases/`，用户随意改。

### 3.3 为什么需要两个 exe

PyInstaller onedir 只能有一个「主 exe」+ 多个 `EXE(...)` 声明，共享同一份 `_internal`。分开两个入口避免：
- 只给 GUI 入口 → CLI 工程师失去 `run/list` 命令行能力
- 只给 CLI 入口 → 非技术用户被 Typer help 文本劝退

两个 exe 共享运行时，体积不重复（第二个 exe 仅多几百 KB）。

---

## 4. PyInstaller spec 与构建脚本

### 4.1 `packaging/atprobe.spec`

```python
# PyInstaller onedir spec — ATProbe（GUI + CLI 双入口，Windows x64）
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# PySide6/Qt6 全量收集（plugins、translations、QML）—— 铁律，否则启动崩
for pkg in ("PySide6", "shiboken6"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# 内置只读资源 → 打进 _internal/examples（via importlib.resources）
datas += [
    ("examples/env.yaml",            "examples"),
    ("examples/quick_commands.yaml", "examples"),
    ("examples/testcases",           "examples/testcases"),
]

# 源码全量收集（含延迟导入）
hiddenimports += collect_submodules("atprobe")

a = Analysis(
    ["packaging/entry_gui.py", "packaging/entry_cli.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["packaging/hooks"],   # 自定义 hook（若有）
    excludes=["tkinter", "PyQt5", "PyQt6", "pytest"],  # 砍体积
)

pyz = PYZ(a.pure)

# GUI exe：取 scripts[0]（entry_gui.py），console=False
gui_exe = EXE(
    pyz, a.scripts[:1], a.binaries, a.datas, [],
    name="ATProbe",
    console=False,
    icon="packaging/atprobe.ico",       # 图标（若有）
    onefile=False,
)

# CLI exe：取 scripts[1]（entry_cli.py），console=True
cli_exe = EXE(
    pyz, a.scripts[1:], [],
    name="atprobe-cli",
    console=True,
)

COLLECT(gui_exe, cli_exe, name="ATProbe-<version>")  # 版本号由 build.py 注入
```

> spec 中 `name="ATProbe-<version>"` 的实际版本号由 `build.py` 在调用 PyInstaller 前动态注入（避免手写漂移）。详见 4.3。

### 4.2 自定义 hook（按需）

`packaging/hooks/hook-atprobe.py`（若 PyInstaller 静态分析遗漏某些延迟导入）：
```python
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules("atprobe")
```

### 4.3 `packaging/build.py` — 本地一键构建

```python
# 用法：uv run python packaging/build.py
# 1. 读 pyproject.toml 的 version（单一真相源）
# 2. 渲染 atprobe.spec（注入版本号）
# 3. 调 PyInstaller（subprocess）
# 4. 复制 examples/ → dist/ATProbe-<ver>/examples（外露工作区）
# 5. 压缩 dist/ATProbe-<ver>/ → dist/ATProbe-<version>-win64.zip
import subprocess, shutil, zipfile
from pathlib import Path
import tomllib  # py3.11+

ROOT = Path(__file__).resolve().parents[1]
version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
dist_dir = ROOT / "dist"
app_dir = dist_dir / f"ATProbe-{version}"
zip_path = dist_dir / f"ATProbe-{version}-win64.zip"

# 2. 渲染 spec（版本号注入 COLLECT name）
# 3. 构建
subprocess.run(["pyinstaller", "packaging/atprobe.spec", "--noconfirm"], check=True)
# 4. 外露 examples（与 _internal 同级，即 COLLECT 输出目录）
shutil.copytree(ROOT / "examples", app_dir / "examples", dirs_exist_ok=True)
# 5. 压缩
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for f in app_dir.rglob("*"):
        z.write(f, f.relative_to(dist_dir))
print(f"产物：{zip_path}")
```

### 4.4 构建期依赖

`pyproject.toml` 新增 `packaging` extra：
```toml
[project.optional-dependencies]
# ... 现有 gui / dev ...
packaging = ["pyinstaller>=6.0"]
```

---

## 5. GitHub Actions 自动发布

### 5.1 `.github/workflows/release.yml`

```yaml
name: Release

on:
  push:
    tags: ["v*.*.*"]       # 仅 tag 触发，普通 push 不构建

permissions:
  contents: write          # 创建 Release + 上传 asset

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install uv
      - run: uv sync --extra gui --extra packaging
      - run: uv run python packaging/build.py
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/ATProbe-*-win64.zip
          generate_release_notes: true
          fail_on_unmatched_files: true
```

### 5.2 版本号一致性（符合标准）

- **单一真相源**：`pyproject.toml` 的 `version`
- tag 名（`v0.1.0`）、zip 名、目录名、Release 标题均派生自它
- CI 不写死版本，从 `pyproject.toml` 动态读，杜绝漂移

### 5.3 发布流程（用户视角）

1. 维护者改 `pyproject.toml` version → commit
2. `git tag v0.1.0 && git push origin v0.1.0`
3. GitHub Actions 自动构建（~3–5 分钟）
4. Release 页出现 `ATProbe-0.1.0-win64.zip`，自动生成 changelog
5. 使用者下载 → 解压 → 双击 `ATProbe.exe`

---

## 6. 错误处理与验证

### 6.1 已知风险与对策

| 风险 | 对策 |
|---|---|
| PySide6 Qt 插件缺失 → 启动崩 "failed to load platform plugin" | `collect_all("PySide6")` 全量收集 |
| 隐藏 import 遗漏（延迟导入） | `collect_submodules("atprobe")` + CI 实跑验证 |
| 杀软误报 | 接受手动加白（非目标：不做代码签名） |
| `parents[N]` 残留 → 打包崩 | 全局 grep 检查，新增 lint 规则禁用 |
| 工作区无写权限 | 便携式放 exe 同级，一般 Program Files 外无此问题；docs 说明 |

### 6.2 验证清单（打包后必跑）

打包完成后，在**干净 Windows 机器**（无 Python）验证：

- [ ] 双击 `ATProbe.exe` → GUI 启动无黑窗、无报错
- [ ] GUI「环境配置」页默认有内容（env.yaml 回退生效）
- [ ] GUI「手动调试」命令库有默认指令（quick_commands.yaml 回退生效）
- [ ] GUI「用例执行」能列出 examples/testcases/ 的用例
- [ ] 运行一个 ntp/tcp 用例 → 产生 `logs/`（写工作区生效）
- [ ] `atprobe-cli.exe list cases` 正常输出
- [ ] `atprobe-cli.exe run examples/testcases/ntp/*.yaml --port COM5:115200` 跑通
- [ ] 关闭再开，用户改的命令库/配置持久化

### 6.3 开发态回归

打包改造不应破坏 `uv run atprobe ...` 的开发态行为。改造后跑 `uv run pytest` 全绿，确认 `runtime.py`/`resources.py` 在开发态返回仓库根路径。

---

## 7. 改动清单

### 7.1 新增

| 路径 | 用途 |
|---|---|
| `src/atprobe/infra/runtime.py` | 打包态检测（is_frozen / app_root） |
| `src/atprobe/infra/resources.py` | 资源定位（内置只读 / 用户可写） |
| `packaging/entry_gui.py` | GUI 入口脚本 |
| `packaging/entry_cli.py` | CLI 入口脚本 |
| `packaging/atprobe.spec` | PyInstaller spec |
| `packaging/build.py` | 本地一键构建脚本 |
| `packaging/hooks/hook-atprobe.py` | PyInstaller hook（按需） |
| `.github/workflows/release.yml` | GitHub Actions 自动发布 |
| `tests/unit/test_runtime_resources.py` | runtime/resources 单测 |

### 7.2 修改

| 路径 | 改动 |
|---|---|
| `src/atprobe/domain/quickcmd/store.py` | 删 `_PROJECT_ROOT`/`_BUILTIN_PATH`，改调 `resources` |
| `src/atprobe/gui/mainwindow.py` | `env_config_path()` 回退改调 `resources` |
| `pyproject.toml` | 新增 `packaging` extra |
| `README.md` | 补「下载使用」与「发布」章节 |

---

## 8. 实施顺序

1. **修复资源定位**（§2）：新建 `runtime.py`/`resources.py`，改造 store/mainwindow，跑全量测试
2. **入口脚本 + spec**（§3–4）：`packaging/` 目录、entry_*.py、atprobe.spec、build.py
3. **本地构建验证**：`uv run python packaging/build.py`，在干净机器跑验证清单（§6.2）
4. **CI 自动发布**（§5）：release.yml，打 tag 验证自动发布
5. **文档**：README 补发布说明
