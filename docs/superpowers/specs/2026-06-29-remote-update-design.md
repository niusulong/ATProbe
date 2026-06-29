# ATProbe 远程升级（检查 + 自动下载安装）设计

- 日期：2026-06-29
- 状态：已批准（设计阶段）
- 范围：为已发布的便携式 ATProbe（PyInstaller onedir）增加「检查更新 + 用户点击后自动下载并原地安装最新版」的能力，覆盖 GUI 与 CLI 两个入口

---

## 1. 背景与目标

### 1.1 现状

ATProbe 已实现打包分发（见 `2026-06-29-packaging-and-distribution-design.md`）：推送 `v*.*.*` tag 触发 GitHub Actions，构建 `ATProbe-<version>-win64.zip` 发布到 GitHub Releases。用户当前获取新版的唯一方式是**手动访问 Release 页下载解压替换**。

便携式打包形态：`atprobe.exe` + `_internal/` 文件夹，用户工作区（`reports/`、`logs/`、`atprobe.yaml`、`examples/`）与 exe 同级。

### 1.2 已确认的关键决策

| 决策项 | 选择 | 理由 |
|---|---|---|
| 更新程度 | 检查 + 通知 + 用户点击后自动下载安装 | 用户明确要求"点击更新后自动安装最新版"，介于纯通知与静默安装之间 |
| 检查时机 | GUI 启动自动检查（3s 延迟，静默）+ 手动菜单「帮助→检查更新」 | 对非技术用户友好，无需记住手动检查 |
| 安装方式 | 原地替换 `atprobe.exe` + `_internal/`，保留用户工作区 | 快捷方式/路径不变；用 detached 脚本在主程序退出后接管替换 |
| 版本来源 | VERSION 文件（打包注入）+ GitHub Releases API | 单一真相源 + 公开 API 零鉴权 |
| 依赖策略 | 纯 stdlib（urllib/json/zipfile/subprocess/tempfile/pathlib） | 符合项目"运行时依赖极简"风格，零新依赖 |

### 1.3 成功标准

1. GUI 启动 3 秒后自动检查；有新版弹升级对话框，无新版/网络失败静默不打扰
2. 用户点击「立即更新」→ 自动下载 zip 并显示进度 → 下载完成二次确认 → 程序退出 → 自动替换并重启新版
3. 升级后 `atprobe.exe --version` 显示新版本号；`reports/`、`logs/`、`atprobe.yaml`、`examples/` 完好无损
4. CLI 支持 `atprobe update --check`（只检查）、`atprobe update`（交互安装）、`atprobe update --yes`（非交互）
5. 升级失败时自动回滚到旧版，程序仍能启动（不变砖）
6. 修复版本 drift：`VERSION 文件 == pyproject.toml version == __init__.__version__`，并有测试防复发

### 1.4 非目标（YAGNI）

- 不做增量更新 / 差分包（zip 仅 ~80MB，全量下载够快）
- 不做下载断点续传（80MB 一次下完，复杂度不值）
- 不做 SHA256 校验（无签名下校验值本身无来源保证；大小校验已防残缺）
- 不做后台静默自动安装（用户明确要求"点击后才更新"）
- 不做更新参数暴露到 atprobe.yaml（用户无需调）
- 不做多渠道/镜像源（单一 GitHub 源足够）
- 不做代码签名（延续 packaging 设计，已接受无证书）

---

## 2. 整体架构与数据流

新增独立 `update` 子系统（纯 stdlib），四个职责清晰的小模块，GUI/CLI 共用。复用现有 `runtime`/`resources` 基础设施定位文件。

### 2.1 模块结构

```
src/atprobe/infra/
├── version.py              # 【新增】单一版本真相源：本地版本读取
├── update/                 # 【新增】升级子系统
│   ├── __init__.py         # 导出 + 自定义异常
│   ├── config.py           # UpdateConfig 常量集合
│   ├── checker.py          # 查 GitHub API 取最新版 + 版本比较
│   ├── downloader.py       # 下载 zip（带进度回调 + 超时 + 取消）
│   └── installer.py        # Windows 原地替换（生成并 detached 启动 updater 脚本）
```

### 2.2 数据流（用户点击「立即更新」）

```
GUI/CLI 调用
   │
   ├─ checker.fetch_latest()  ──HTTP──▶  api.github.com/repos/.../releases/latest
   │                                          (公开仓库，无需鉴权，60次/小时)
   │   ◀── {tag_name, assets:[{name,url,size}]}
   │
   ├─ checker.is_newer(remote, local)  ──▶  True/False (semver 元组比较)
   │
   ├─ downloader.download(url, progress_cb)  ──▶  %TEMP%\atprobe-update-<ver>.zip
   │
   └─ installer.apply_update(zip_path, app_root)
          │  1. 解压 zip 到 %TEMP%\atprobe-staging\
          │  2. 生成 updater.bat（等待 exe 退出 → 备份 → 替换 → 重启 → 清理）
          │  3. detached 启动该 bat，主程序立即退出
          │
          └─▶ bat 接管（主程序已退出，文件锁释放）：
                 · 轮询等待 atprobe.exe 进程消失
                 · _internal/ → _internal.bak/，atprobe.exe → atprobe.exe.bak
                 · xcopy 新版 _internal/ + atprobe.exe
                 · 成功：删 .bak，重启 atprobe.exe
                 · 失败：回滚 .bak，弹错误框
```

### 2.3 设计原则

- **职责隔离**：checker / downloader / installer 各自独立、可单测。installer 是唯一有平台特异性和风险的模块，单独隔离。
- **零新依赖**：全程 stdlib。
- **主程序退出后才替换**：避开 Windows 文件锁。主程序只负责"下载 + 准备 + 启动 detached 脚本 + 自杀"，真正替换由独立进程在主程序退出后完成。
- **保留用户工作区**：只替换 `atprobe.exe` + `_internal/`，绝不触碰用户数据。

---

## 3. 版本真相源（修复 drift）

### 3.1 当前问题

- `pyproject.toml` = `0.2.1`（build.py 读这个，打包进 zip 名）
- `src/atprobe/__init__.py` `__version__` = `0.1.0`（CLI `--version` 读这个）
- 打包后程序**根本不知道自己是 0.2.1** → 升级检查会误判

### 3.2 方案：单一真相源 + 运行时注入

真相源唯一化：`pyproject.toml` 的 `version` 字段是唯一真相源，其他地方都从它派生，不再硬编码。

**1. 新增 `src/atprobe/infra/version.py`**（唯一负责"我是谁"的模块）：

```python
def current_version() -> str:
    """当前运行版本号（如 '0.2.1'），未知返回 '0.0.0'。"""
    # 打包态：读 app_root() / "_internal" / "VERSION"
    # 开发态：读 app_root() / "VERSION"（仓库根）
    # 都没有：回退 '0.0.0'（不阻塞启动，但升级检查会认为该升级）
```

查找路径统一走现有 `runtime.app_root()`：
- 打包态：`app_root() / "_internal" / "VERSION"`（build.py 生成注入）
- 开发态：`app_root() / "VERSION"`（仓库根，git 跟踪）

**2. 修改 `src/atprobe/__init__.py`**：删掉硬编码的 `__version__ = "0.1.0"`，改为派生：

```python
def _read_version() -> str:
    from atprobe.infra.version import current_version
    return current_version()

__version__ = _read_version()  # 保持向后兼容（import atprobe; atprobe.__version__）
```

**3. `packaging/build.py` 新增 `write_version_file(version, app_dir)`**：PyInstaller 构建后、打包 zip 前，把 version 写到 `<app_dir>/_internal/VERSION`。纯文本一行文件。同时同步仓库根 `VERSION` 文件。

**4. drift 防护**：仓库根放一个 `VERSION` 文件（git 跟踪），内容与 pyproject.toml 同步。测试 `test_version_consistency` 断言三者一致，任一不一致即 fail，CI 强制防复发。

### 3.3 兼容性兜底

`current_version()` 在 VERSION 文件缺失时回退 `0.0.0` 而非崩溃——保证旧 zip（无 VERSION）用户也能启动并触发"该升级"判断，平滑过渡。

### 3.4 为何不直接运行时读 pyproject.toml

打包后 pyproject.toml **不在 exe 旁**（PyInstaller 不收集它），运行时找不到。所以必须打包时注入独立 VERSION 文件。这是 PyInstaller 应用的标准模式。读 exe 文件属性（Windows 版本信息）跨平台性差、需 win32 API、设 rc 文件复杂，纯文本 VERSION 最简单可靠。

---

## 4. 版本检查器（checker）

负责"最新版是什么、要不要升级"。纯逻辑、纯 stdlib、完全可单测。

### 4.1 数据结构（Pydantic，复用项目已有依赖）

```python
class ReleaseInfo(BaseModel):
    version: str        # "0.3.0"（去掉 v 前缀的纯版本号）
    tag: str            # "v0.3.0"
    zip_url: str        # ATProbe-<ver>-win64.zip 的 browser_download_url
    zip_size: int       # 字节数（用于预估下载、显示）
    release_notes: str  # release body（changelog，展示给用户）
    html_url: str       # GitHub Release 页面（备用：手动下载/查看）
```

### 4.2 `fetch_latest(timeout=8.0) -> ReleaseInfo`

```
GET https://api.github.com/repos/niusulong/ATProbe/releases/latest
    Accept: application/vnd.github+json
    User-Agent: ATProbe/<current_version>   # GitHub API 强制要求 UA
```

解析：`tag_name` → `tag` + 去 `v` 前缀 → `version`；`assets[]` 找 `name == "ATProbe-{version}-win64.zip"` → `zip_url`/`zip_size`；`body` → `release_notes`；`html_url` → 备用链接。

找不到匹配 asset（如某次发版忘传 zip）→ 抛 `AssetNotFoundError`，上层提示"该版本暂无 Windows 安装包"。

**测试端点可配置**：`fetch_latest` 接受可选 `api_base` 参数，默认 `https://api.github.com`，测试传入 mock 或本地构造 URL。避免 URL 硬编码成不可注入常量。

### 4.3 `is_newer(remote: str, local: str) -> bool`

语义化版本元组比较，**不靠字符串比较**（`"0.10.0"` vs `"0.9.0"` 字符串比较会错）：

```python
def _parse_semver(v: str) -> tuple[int, int, int]:
    # "0.2.1" → (0, 2, 1)；去掉 v 前缀、忽略 -pre 后缀
    # 容错：缺位补 0（"0.2" → (0,2,0)），非数字回退 0
```

### 4.4 错误处理矩阵（网络功能绝不能让程序崩溃）

| 情况 | 异常 | 上层行为 |
|---|---|---|
| 超时 / 无网络 / DNS 失败 | `UpdateCheckError`（"网络连接失败"） | 启动检查：静默；手动检查：弹"检查失败" |
| HTTP 403（API 限流） | `UpdateCheckError`（"请求过于频繁"） | 静默；手动弹提示 |
| HTTP 404（无 release） | `UpdateCheckError`（"尚未发布任何版本"） | 静默；手动弹提示 |
| JSON 解析失败 / 字段缺失 | `UpdateCheckError`（"响应格式异常"） | 静默；手动弹提示 |
| 找不到 win64 asset | `AssetNotFoundError` | 静默；手动弹"该版本无 Windows 包" |
| 本地版本读不到（`0.0.0`） | 不抛异常 | `is_newer` 正常工作，视为该升级 |

所有网络异常都收敛成 `UpdateCheckError`，绝不让 `urllib` 的 `URLError`/`HTTPError`/`socket.timeout` 泄漏到上层。

### 4.5 测试策略

- `fetch_latest`：`unittest.mock.patch` 拦截 `urllib.request.urlopen`，喂构造 JSON，断言 `ReleaseInfo` 字段。无需真实网络。
- `is_newer`：纯函数，覆盖 `(0.3.0, 0.2.1)→True`、`(0.2.1, 0.2.1)→False`、`(0.2.0, 0.2.1)→False`、`(0.10.0, 0.9.0)→True`（防字符串比较 bug）、带 `v` 前缀、缺位、pre-release 后缀。
- 错误矩阵：mock 各类异常，断言都收敛成 `UpdateCheckError`。

---

## 5. 下载器（downloader）

负责"把 zip 安全下载到本地"。带进度回调（GUI 进度条）、超时、取消、半成品文件保护（临时 `.part` + 原子重命名，非断点续传——见 §1.4 已排除）。

### 5.1 核心 API

```python
class DownloadResult(BaseModel):
    path: Path          # 下载完成的本地路径
    size: int           # 实际写入字节数

def download(
    url: str,
    dest_dir: Path,
    *,
    filename: str | None = None,    # 默认从 URL 推断
    timeout: float = 30.0,          # 连接超时
    expected_size: int | None = None,  # 来自 checker 的 zip_size，用于校验
    progress_cb: Callable[[int, int], None] | None = None,  # (已下载, 总大小)
    cancel_token: Callable[[], bool] | None = None,         # 返回 True 则中止
) -> DownloadResult:
    """下载 url 到 dest_dir/<filename>，支持进度回调与取消。"""
```

进度回调签名 `(downloaded, total)`：`total` 来自 HTTP `Content-Length`（`expected_size` 兜底）；每收到一个 chunk（8KB）累加并回调。GUI 用它驱动 `QProgressBar`，CLI 用它打印百分比。

### 5.2 安全写入策略（防半成品文件污染）

下载先写**临时文件**，成功后才原子重命名到目标名：

```
dest_dir/atprobe-update-<ver>.zip.part   ← 下载中
                ↓ rename（原子）
dest_dir/atprobe-update-<ver>.zip        ← 完成
```

`.part` 后缀确保中断/取消/崩溃留下的半成品一眼可辨。目标目录用系统临时目录（`tempfile.gettempdir()`），避免写 exe 同级（可能权限不足或被防软件监控）。

**任何退出路径（成功/失败/取消）都清理 `.part` 文件**，用 `try/finally` 保证。

### 5.3 错误处理矩阵

| 情况 | 异常 | 上层行为 |
|---|---|---|
| 超时 / 断网 | `DownloadError`（"下载失败：网络中断"） | GUI 弹"下载失败，请检查网络"；清理 .part |
| 磁盘空间不足 | `DownloadError`（"磁盘空间不足"） | GUI 弹具体提示；清理 .part |
| HTTP 4xx/5xx | `DownloadError`（含状态码） | GUI 弹"下载失败（HTTP 404）" |
| 用户取消 | `DownloadCancelled` | 静默清理 .part，不弹错误 |
| 写盘失败（权限等） | `DownloadError` | GUI 弹提示；清理 .part |

### 5.4 大小校验

下载完成后，若提供 `expected_size`，比对实际大小。不一致 → `DownloadError`（"下载文件大小不符，可能已损坏"）。防止代理截断/CDN 错误给残缺 zip。

### 5.5 测试策略

- mock `urllib.request.urlopen` 返回假响应对象（`read(chunk)` 逐块返回 bytes、有 `headers`、`geturl()`）。
- 断言：文件内容正确、`.part` 被重命名、`progress_cb` 被以正确累加值调用、`cancel_token` 在第 2 个 chunk 触发时抛 `DownloadCancelled` 并清理。
- 不碰真实网络。构造 `FakeResponse` 类即可。

---

## 6. 安装器（installer）⚠️风险最高

负责"在主程序退出后，原地替换 exe + `_internal/`，保留用户工作区"。整个功能唯一碰文件锁、需 detached 进程接管的地方。

### 6.1 核心 API

```python
def apply_update(
    zip_path: Path,
    app_root: Path,
    *,
    restart: bool = True,
) -> None:
    """准备并启动原地替换。

    1. 解压 zip 到 staging 目录
    2. 生成 updater 脚本（bat）
    3. detached 启动脚本，主程序随后应自行退出
    """
```

主程序调用后立即返回（脚本已 detached 启动），**主程序负责自己退出**（GUI 调 `QApplication.quit()`，CLI `sys.exit(0)`）。

### 6.2 替换边界（关键：哪些换、哪些不换）

zip 解压后结构与现有打包产物一致：

```
ATProbe-<ver>/
├── atprobe.exe          ← 换
├── _internal/           ← 整个换
├── examples/            ← ⚠️不换（用户可能改过）
├── reports/             ← ⚠️不换（用户数据）
├── logs/                ← ⚠️不换（用户数据）
├── atprobe.yaml         ← ⚠️不换（用户配置）
└── README.txt           ← 换（无妨）
```

**保留策略**：installer 只从 staging 取 `atprobe.exe` 和 `_internal/`，其余用户区文件解压后直接忽略。从机制上杜绝覆盖用户数据。

### 6.3 updater.bat 脚本逻辑

installer 在运行时生成，内嵌路径与命令：

```bat
@echo off
chcp 65001 >nul
setlocal

set "EXE=...\atprobe.exe"
set "INTERNAL=...\_internal"
set "STAGING=...\ATProbe-<ver>"
set "BACKUP=...\_internal.bak"

REM 1. 等待主程序退出（轮询，最长 30 秒）
:wait
tasklist /fi "pid eq <PID>" 2>nul | find "<PID>" >nul && (
    timeout /t 1 /nobreak >nul
    goto wait
)

REM 2. 备份旧版（.bak 后缀，失败可回滚）
if exist "%INTERNAL%.bak" rmdir /s /q "%INTERNAL%.bak"
ren "%INTERNAL%" "_internal.bak" || goto rollback
copy /y "%EXE%" "%EXE%.bak" >nul || goto rollback

REM 3. 部署新版
xcopy /e /i /y "%STAGING%\_internal" "%INTERNAL%" >nul || goto rollback
copy /y "%STAGING%\atprobe.exe" "%EXE%" >nul || goto rollback

REM 4. 成功：清理备份与临时文件，重启
rmdir /s /q "%INTERNAL%.bak"
del "%EXE%.bak"
rmdir /s /q "%STAGING%"
del "%~f0"                         REM 脚本自删
start "" "%EXE%"                   REM 重启新版
exit /b 0

:rollback
REM 回滚：恢复 .bak，弹错误框
if exist "%INTERNAL%.bak" (
    if exist "%INTERNAL%" rmdir /s /q "%INTERNAL%"
    ren "%INTERNAL%.bak" "_internal"
)
if exist "%EXE%.bak" move /y "%EXE%.bak" "%EXE%" >nul
mshta javascript:alert("ATProbe 升级失败，已恢复旧版本。请稍后重试。");close()
exit /b 1
```

关键细节：
- **轮询等待主程序退出**：用主程序传入的 PID（`tasklist /fi "pid eq <PID>"`）。不靠固定 sleep，最长 30 秒超时。
- **.bak 备份 + 失败回滚**：替换前先把 `_internal/` 改名成 `_internal.bak/`，exe 复制成 `.bak`。任何 xcopy/copy 失败立即 `goto rollback` 恢复，保证**升级失败时程序仍能启动**（最坏退回旧版，而非变砖）。
- **chcp 65001**：脚本内中文提示用 UTF-8，避免 Windows 默认 GBK 乱码。
- **脚本自删**：`del "%~f0"`，不残留 updater.bat。
- **mshta 弹框**：用 Windows 自带 `mshta`（无需 PowerShell），失败时给用户明确反馈。

### 6.4 detached 启动

```python
import subprocess
# 主程序退出后脚本继续独立运行
subprocess.Popen(
    ["cmd", "/c", "start", "/b", "", str(bat_path)],
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # Windows-only
    close_fds=True,
)
```

`close_fds=True` 确保主程序退出时不因句柄继承阻塞脚本。

### 6.5 安全护栏

- **开发态禁用**：`is_frozen()` 为 False 时，`apply_update` 直接抛 `UpdateError("开发态不支持自更新，请用 git pull")`。
- **zip 完整性预检**：替换前验证 zip 能正常打开、含 `atprobe.exe` 和 `_internal/`，否则 `UpdateError("安装包损坏")`，不启动脚本。
- **PATH 注入防护**：所有路径用 `Path` 对象拼接，bat 内路径用引号包裹（`"%EXE%"`），防路径含空格/中文。

### 6.6 错误处理矩阵

| 情况 | 处理 |
|---|---|
| 解压失败 / zip 损坏 | `UpdateError`，不启动脚本，GUI 弹"安装包损坏" |
| 开发态调用 | `UpdateError`，明确提示用 git pull |
| staging 目录已存在 | 先清理再解压（幂等） |
| bat 启动失败（极少见） | `UpdateError`，GUI 弹"无法启动更新程序" |
| 替换过程失败 | 由 bat 内部回滚，主程序不受影响 |

### 6.7 测试策略

- **Python 层可单测**：mock `zipfile`/`subprocess.Popen`，验证：解压调用、bat 内容包含正确路径与命令、`Popen` 以正确参数调用、开发态抛错、损坏 zip 抛错。
- **bat 逻辑**：作为字符串内容断言关键命令存在（`tasklist`/`ren`/`xcopy`/`rollback` 标签/`start`）。
- **手动验收清单**（见第 10 节）。

### 6.8 局限性（如实告知）

- **无代码签名**：首次运行新 exe 时 Windows SmartScreen 可能弹"未知发布者"警告（用户点"仍要运行"）。无证书固有限制。
- **bat 可能被杀软误报**：极少数激进杀软会拦截"删除自身再启动 exe"的 bat。回滚机制保证不致数据丢失，最坏退回旧版。UI 会提示用户"若被拦截可手动解压"。
- **需用户确认关闭程序**：脚本等待主程序退出，GUI 会明确提示"程序将关闭以完成升级"。

---

## 7. GUI 集成

GUI 把 checker/downloader/installer 串起来，提供启动自动检查、手动菜单、进度展示、升级确认对话框。

### 7.1 菜单入口

`mainwindow.py` `_init_menubar` 在现有「视图(&V)」旁新增「帮助(&H)」：

```
帮助(&H)
├── 检查更新...        → _on_check_update(manual=True)
└── 关于 ATProbe       → _on_about()   # 显示 current_version()、项目地址
```

### 7.2 启动自动检查（app.py run_gui）

窗口 show 后，用 `QTimer.singleShot(3000, ...)` 延迟 3 秒触发后台检查。3 秒延迟避免抢占启动资源；后台线程做 HTTP，**绝不阻塞 UI**。

```python
def _startup_check():
    win._check_update(manual=False)   # 静默模式
QTimer.singleShot(3000, _startup_check)
```

静默检查行为：网络失败/超时/无新版 → 完全不弹窗（零打扰）；有新版 → 弹通知对话框。

### 7.3 检查行为矩阵

| 情况 | `manual=False`（启动自动） | `manual=True`（手动） |
|---|---|---|
| 网络失败 | 静默 | 弹"检查失败：网络连接失败" |
| 已是最新 | 静默 | 弹"当前已是最新版本 0.2.1" |
| 有新版 | 弹升级对话框 | 弹升级对话框 |

### 7.4 升级对话框（有新版时）

`QMessageBox` 无法容纳富文本 changelog，用自定义 `QDialog`（`QTextEdit` 放 release_notes + 两个按钮）：

```
┌─ 发现新版本 ────────────────────────┐
│  发现新版本 0.3.0（当前 0.2.1）       │
│                                       │
│  更新内容：                           │
│  ┌─────────────────────────────┐    │
│  │ <release_notes，可滚动>      │    │
│  │ ...                          │    │
│  └─────────────────────────────┘    │
│                                       │
│  下载大小：约 79 MB                   │
│                                       │
│         [稍后]      [立即更新]        │
└───────────────────────────────────────┘
```

release_notes 渲染为 HTML（GitHub body 已是 Markdown，用极简正则转 HTML 或直接 `<pre>` 展示，不引新依赖）。

### 7.5 下载进度对话框

`QProgressDialog`（自动支持 `canceled` 信号）。下载在独立工作线程，进度经信号投递回主线程更新条。点"取消"→ 设置 `cancel_token`，downloader 抛 `DownloadCancelled`，静默清理。

```
┌─ 正在更新到 0.3.0 ───────────────────┐
│  下载中... 45%                        │
│  ███████████░░░░░░░░░░  35.6 / 79 MB  │
│                  [取消]               │
└───────────────────────────────────────┘
```

### 7.6 下载完成 → 确认关闭 → 安装（关键交互序列）

```
下载完成（100%）
    ↓
弹最终确认框：
  "更新已就绪。点击『开始安装』后程序将关闭并自动完成升级。
   预计 5 秒，期间请勿操作。"
  [稍后]  [开始安装]
    ↓ 用户点"开始安装"
工作线程调用 installer.apply_update(zip_path, app_root())
    ↓ （脚本已 detached 启动）
主线程：QApplication.quit()  ← 主程序主动退出
    ↓
bat 接管：等待退出 → 备份 → 替换 → 重启新版
```

下载完不立即关程序：给用户最后一次反悔机会（可能正在跑测试，不想现在重启）。

### 7.7 错误兜底

任何环节（check/download/install）抛异常，都 catch 成 `QMessageBox.critical`，**绝不崩溃**。下载/安装过程中禁用菜单项避免重入（`_update_in_progress` 标志位）。

### 7.8 关于对话框（_on_about）

显示 `ATProbe {current_version()}`、GitHub 地址、Python 版本、许可证。复用 `current_version()`，零额外维护。

---

## 8. CLI 集成 + 配置

### 8.1 CLI（src/atprobe/cli/main.py）

新增 `update` 子命令，三种用法：

```bash
# 只检查是否有新版（不下载）
atprobe update --check
# 输出：当前 0.2.1，最新 0.3.0，有新版本可用。
#       下载：https://github.com/.../ATProbe-0.3.0-win64.zip
#  或：当前 0.2.1，已是最新版本。

# 检查并自动下载安装（交互确认）
atprobe update
# 输出进度后提示 "确认升级到 0.3.0？[y/N]"，确认后下载→安装→退出重启

# 非交互（脚本/CI 用，跳过确认直接装）
atprobe update --yes
```

CLI 复用同一套 checker/downloader/installer，只在"展示与交互"层不同（终端打印百分比 vs GUI 进度条）。进度打印用 `\r` 原地刷新（呼应现有 `reporting/console.py` 风格）。

版本命令对齐：`atprobe --version` / `-V` 改为调用 `current_version()`（而非旧 `__version__` 硬编码），与 GUI 关于框一致。

### 8.2 配置（infra/update/config.py）

升级功能可调参数集中，避免散落硬编码：

```python
@dataclass(frozen=True)
class UpdateConfig:
    api_base: str = "https://api.github.com"
    repo: str = "niusulong/ATProbe"
    check_timeout: float = 8.0      # 检查请求超时
    download_timeout: float = 30.0  # 下载连接超时
    asset_name_template: str = "ATProbe-{version}-win64.zip"
```

默认值即生产值；测试通过传入不同 `api_base`/`repo` 跑隔离测试。**不暴露到 atprobe.yaml**（YAGNI——用户无需调）。

---

## 9. CI 与版本注入

### 9.1 CI 增强（.github/workflows/release.yml）

现有流程不动，仅 build.py 增加写 VERSION 文件步骤。spec 无需改（build.py 在 PyInstaller 之后、打包 zip 之前调用，直接写文件）。

**关键：不动现有 release 成功路径**。只追加一个文件写入，风险隔离。发版仍走 `改 pyproject.toml version → tag → push`，零额外步骤。

### 9.2 build.py 新增

- `write_version_file(version, app_dir)`：把 version 写到 `<app_dir>/_internal/VERSION`
- 同步仓库根 `VERSION` 文件（确保 `VERSION == pyproject.toml version`）

### 9.3 drift 防护测试

`tests/unit/test_version_consistency.py`：

```python
def test_version_sources_agree():
    """三处版本必须一致：VERSION 文件 / pyproject.toml / __init__.__version__"""
    assert read_version_file() == read_pyproject_version() == atprobe.__version__
```

CI 跑测试时强制三处一致，**从机制上消灭 drift 复发**。

### 9.4 .gitignore

`VERSION` 文件需跟踪（gitignore 不忽略它）。无新增需忽略项。

---

## 10. 测试与验收

### 10.1 自动化测试

| 测试文件 | 覆盖 |
|---|---|
| `test_version.py` | current_version 各路径（打包/开发/缺失回退） |
| `test_version_consistency.py` | drift 防护（三处一致） |
| `test_update_checker.py` | mock urlopen + ReleaseInfo 解析 + is_newer + 错误收敛 |
| `test_update_downloader.py` | mock urlopen + FakeResponse + 进度/取消/清理 |
| `test_update_installer.py` | mock Popen/zipfile + bat 内容断言 + 开发态禁用 + zip 预检 |
| `tests/integration/test_gui.py` | mock fetch_latest 验证对话框分支（有新版/无新版/失败） |

策略：纯逻辑层全 mock 测（零真实网络、零真实文件替换）。CI 友好、快、确定。

### 10.2 手动验收清单（不自动化）

1. 本地用旧版 zip（0.2.1）+ 推一个 v0.3.0 tag 触发 release
2. 双击 0.2.1 exe → 3 秒后弹"发现新版本"
3. 点"立即更新" → 进度条到 100%
4. 点"开始安装" → 程序退出 → bat 替换 → 自动重启
5. 验证 `atprobe.exe --version` 显示 0.3.0
6. 验证 reports/、logs/、atprobe.yaml、examples/ 完好无损
7. CLI `atprobe update --check` 报告已是最新
8. 模拟断网 → 启动不报错、手动检查弹"网络失败"

### 10.3 风险与局限汇总

| 风险 | 等级 | 缓解 |
|---|---|---|
| 无代码签名 → SmartScreen 警告 | 中 | 用户点"仍要运行"；已接受无证书 |
| bat 被激进杀软误报 | 低 | .bak 回滚保数据；UI 提示可手动解压 |
| GitHub API 限流（60次/小时/未鉴权） | 低 | 启动检查一天最多一次足够；失败静默 |
| 替换中途中断（断电） | 极低 | .bak 备份 + 回滚标签；最坏手动恢复 |
| 开发态误触自更新 | — | `is_frozen()` 守卫，开发态直接拒绝 |

---

## 11. 文件清单

### 11.1 新增文件

| 文件 | 职责 | 行数估计 |
|---|---|---|
| `src/atprobe/infra/version.py` | 单一版本读取 | ~30 |
| `src/atprobe/infra/update/__init__.py` | 子系统导出 + 自定义异常 | ~25 |
| `src/atprobe/infra/update/config.py` | UpdateConfig 常量集合 | ~20 |
| `src/atprobe/infra/update/checker.py` | fetch_latest + is_newer + semver | ~120 |
| `src/atprobe/infra/update/downloader.py` | download + 临时文件 + 进度/取消 | ~110 |
| `src/atprobe/infra/update/installer.py` | apply_update + 生成 updater.bat + detached | ~150 |
| `VERSION`（仓库根） | 开发态版本真相源 | 1 |
| `tests/unit/test_version_consistency.py` | drift 防护 | ~25 |
| `tests/unit/test_version.py` | current_version 各路径 | ~30 |
| `tests/unit/test_update_checker.py` | mock urlopen + is_newer | ~120 |
| `tests/unit/test_update_downloader.py` | mock urlopen + FakeResponse | ~110 |
| `tests/unit/test_update_installer.py` | mock Popen/zipfile + bat 断言 | ~130 |

### 11.2 修改文件

| 文件 | 改动 |
|---|---|
| `src/atprobe/__init__.py` | `__version__` 改为派生自 `current_version()`，修复 drift |
| `src/atprobe/cli/main.py` | `--version` 调 `current_version()`；新增 `update` 子命令 |
| `src/atprobe/gui/mainwindow.py` | 新增「帮助」菜单 + `_check_update` + 升级/进度对话框 + `_on_about` |
| `src/atprobe/gui/app.py` | 启动 3 秒后 `QTimer.singleShot` 触发静默检查 |
| `packaging/build.py` | 新增 `write_version_file()`，打包后写 `_internal/VERSION` |

### 11.3 实现顺序建议

1. `version.py` + 修 drift + drift 测试（地基）
2. `checker.py` + 测试（纯逻辑，最先稳）
3. `downloader.py` + 测试
4. `installer.py` + 测试（风险最高，最后碰）
5. GUI 集成（菜单 + 对话框）
6. CLI 集成
7. `build.py` 写 VERSION 文件
8. 本地端到端手动验收
