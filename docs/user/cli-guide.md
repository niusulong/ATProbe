# ATProbe 命令行工具使用说明

> 适用版本：0.8.x。ATProbe 的 CLI 与桌面 GUI 共享同一测试引擎；本文只讲命令行。
> 全部示例在 Windows PowerShell 下可直接复制运行。

## 1. 两种使用形态

| 形态 | 启动方式 | 适用人群 |
|---|---|---|
| **便携版**（推荐） | 解压 Release 包后使用包内 `atprobe-cli.exe` | 最终用户，无需安装 Python（内置运行环境，Windows 10/11 x64） |
| **开发态**（源码仓库） | 仓库根目录执行 `uv run atprobe ...` | 用例/工具开发者，需先 `uv sync --extra dev --extra gui` |

两种形态参数完全一致，下文示例以便携版 `atprobe-cli.exe` 为主；开发态把命令开头
`atprobe-cli.exe` 换成 `uv run atprobe` 即可，例如：

```powershell
# 便携版
atprobe-cli.exe run examples\testcases --port COM5:115200
# 开发态（仓库根目录）
uv run atprobe run examples/testcases --port COM3:115200
```

> 便携版的「工作区」= exe 所在目录：`reports\`、`logs\`、`atprobe.yaml`、`examples\`
> 都相对它定位。开发态工作区 = 当前工作目录（通常是仓库根）。

## 2. 命令总览

| 命令 | 作用 |
|---|---|
| `atprobe run [PATHS...] [选项]` | 执行用例 / 套件 / 目录 |
| `atprobe list [cases\|suites\|ports]` | 列出可用用例 / 套件 / 串口 |
| `atprobe gui` | 启动桌面 GUI |
| `atprobe update [--check] [--yes]` | 检查 / 下载 / 安装新版本 |
| `atprobe --version` / `-V` | 打印 `atprobe <版本>` 后退出 |

- 不带任何子命令运行时直接打印帮助（`no_args_is_help`）。
- 未提供 shell 自动补全。
- 版本号是 `--version` / `-V` **标志**，不是子命令。

## 3. run 子命令参数全表

| 参数 | 形式 | 默认 / 缺省来源 | 说明 |
|---|---|---|---|
| `PATHS...`（位置参数） | 多值，可省略 | 配置 `cases_dir`（默认 `./examples/testcases`） | 用例文件 / 套件文件 / 目录可混合给出 |
| `--port, -p` | 可重复 | 配置 `ports` | 端口复合表达式，见 §5；命令行与配置可叠加 |
| `--baud` | 单值整数 | 不覆盖 | 强制覆盖**所有**端口的波特率 |
| `--tag, -t` | 可重复 | 无 | 标签并集过滤（命中任一即保留），见 §6 |
| `--exclude-tag` | 可重复 | 无 | 排除标签（命中任一即排除），可与 `--tag` 叠加 |
| `--config, -c` | 单值 | §11 定位规则 | 指定 `atprobe.yaml` 路径（相对当前目录） |
| `--env-config` | 单值 | 配置 `env_config`（默认 `./examples/env.yaml`） | M7 环境配置文件；文件不存在则本次无环境层 |
| `--log-level` | progress / debug | 配置 `default.log_level`（默认 progress） | 控制台渲染粒度，见 §10 |
| `--debug` | 开关 | 关 | 运行日志提级 DEBUG，写入 `logs\atprobe.log`（2MB×5 轮转）并镜像到 stderr；与 `--log-level` 是两套独立开关 |
| `--dry-run` | 开关 | 关 | 只校验不执行，见 §9 |
| `--no-report` | 开关 | 关 | 跳过 HTML 报告生成 |
| `--report-dir` | 单值 | 配置 `report_dir`（默认 `./reports`） | HTML 报告根目录 |
| `--no-color` | 开关 | 关 | 关闭控制台颜色（非 tty 环境自动无色） |
| `--vsim` | 开关 | 关 | 启用进程内虚拟模组，无需硬件，见 §7 |
| `--vsim-rssi` | 整数 | 23 | 仅 vsim：注入 `+CSQ` 应答的信号强度（钳位 0..31） |
| `--vsim-cereg` | 整数 | 1 | 仅 vsim：注入 `+CEREG?` 应答的注册状态（钳位 0..5） |

**参数优先级：命令行 > 配置文件（atprobe.yaml） > 内置默认值。**

## 4. 用例路径解析规则

位置参数支持三种形式，可混合：

| 给定形式 | 解析行为 |
|---|---|
| 目录 | **递归**收集其下全部 `*.yaml` / `*.yml`（字符串排序、按真实路径去重）；**跳过 `suite-` 前缀文件**，避免套件内用例被重复计入 |
| `xxx.yaml` / `xxx.yml` 单文件 | 直接作为用例文件加载 |
| `suite-xxx.yaml` 套件文件 | 解析套件，`cases` 项相对套件文件所在目录加载，并收集 `suite_setup` / `suite_teardown` |

- 不存在的路径：打印黄色警告到 stderr 后**继续**处理其余路径；若最终一个用例文件都没有 → exit 2。
- 参数化用例在加载后逐行展开为独立实例，显示为 `name#N`（N 从 1 起），与实际执行、报告一一对应。

## 5. 端口表达式（`--port` 与配置 `ports` 共用格式）

```
expr := name [":" baud [":" frame"]]     如 COM5:115200:8N1
frame := 数据位 + 校验 + 停止位（紧凑 3 字符）
```

| 段 | 示例 | 缺省 | 合法值 |
|---|---|---|---|
| name | `COM5`、`/dev/ttyUSB0` | 必填 | 任意非空串 |
| baud | `115200` | 115200 | 整数 |
| frame | `8N1` | 8N1 | 数据位 5/6/7/8；校验 N/E/O/M/S；停止位 1/1.5/2 |

- 只写 `COM5` 时波特率取默认 115200、帧格式 8N1。
- 非法表达式 / 波特率 / 帧格式 → exit 2（配置错误），不会裸抛异常。
- `--baud` 一旦给出，覆盖所有端口的波特率（包括已显式写波特率的端口）。

## 6. 标签过滤语义

- 过滤发生在用例加载与参数化展开**之后**。
- `--tag` 多次给出 = **并集**：用例 tags 命中任意一个 `--tag` 即保留。
- `--exclude-tag`：命中任意一个即排除；可与 `--tag` 组合成「先选后排」。
- 过滤后一个用例都不剩：黄色提示「过滤后无可用用例」，exit 1（不是 2）。

## 7. --vsim 详解（零硬件演示 / 联调）

没有开发板、也没装虚拟串口对（com0com / socat）时，`--vsim` 用**进程内虚拟模组**
替代真实串口：`AtResponder` 状态机动态生成真实模组风格响应（含 `\r\n` 帧），不经任何
真实串口；引擎、断言、压测、报告全链路照常工作。

行为要点：

- 启用后**忽略** `--port` 与配置 `ports`，统一使用虚拟端口 `VSIM0:115200:8N1`，控制台
  打印青色 `[vsim]` 横幅；不打开任何硬件端口。
- `--vsim-rssi`（默认 23）：控制 `+CSQ` 应答中的信号强度，取值钳位 0..31。
- `--vsim-cereg`（默认 1）：控制 `+CEREG?` 应答中的注册状态，取值钳位 0..5。
- vsim 模式下 `--baud` 覆盖与配置 `urc_filter` 注入均跳过；`--dry-run` 也跳过端口可用性检查。
- `--log-level debug` 时开启 echo：每条收发打印到 stderr（`[vsim] > cmd` / `[vsim] < line`），
  便于观察虚拟模组的逐行应答。

## 8. list 子命令

`atprobe list [cases|suites|ports] [--config] [--tag]`，target 缺省 `cases`。

| target | 行为 | 退出码 |
|---|---|---|
| `cases` | 递归扫描 `cases_dir` 下 `*.yaml`/`*.yml`（跳过 `suite-` 前缀），逐个解析并显示 相对目录 / `[tags]` / 用例名 / 文件名；解析失败的文件静默跳过；`--tag` 为并集过滤（与 §6 同语义） | 目录不存在 → 1 |
| `suites` | 扫描 `suite-*.yaml` / `suite-*.yml`，轻量读取 name / description / cases 数量 / tags；解析失败回退为仅显示文件名 | 目录不存在 → 1 |
| `ports` | 枚举系统串口，列出端口名与描述；无串口时给出提示 | 枚举失败 → 2 |

> `list ports` 不做系统级占用检测，`in_use` 仅反映本程序内部连接状态，CLI 一次性进程
> 恒为 False，故不展示。

## 9. gui 子命令

```powershell
atprobe-cli.exe gui          # 便携版：启动桌面 GUI
uv run atprobe gui           # 开发态
```

- 延迟导入 PySide6：若依赖缺失，提示安装方式（开发态 `uv sync --extra gui`）并以
  exit 2 退出；正常启动时 GUI 进程的返回值作为 CLI 退出码。
- GUI 与 CLI 共享同一引擎与配置（`atprobe.yaml`），手动调试、URC 监控等图形功能见
  `docs\user\gui-guide.md`。

## 10. update 子命令（自动更新）

`atprobe update [--check] [--yes/-y]`，检查 GitHub Releases 上的新版本并可一键升级。

| 选项 | 说明 |
|---|---|
| `--check` | 只检查并展示新版本信息（当前/最新版本、下载地址、大小、release notes），不下载 |
| `--yes` / `-y` | 跳过交互确认，直接下载安装 |

流程与行为：

1. 请求 GitHub Releases API（超时 8s），按 semver 元组比较远程/本地版本；已是最新则
   提示后正常退出（exit 0）。HTTP 403 提示限流、404 提示尚未发布；Release 缺 Windows
   包等异常统一收敛为可读错误信息 → exit 1。
2. 默认交互确认后下载到系统临时目录（`.part` 临时文件 + 原子重命名，带进度条，边下
   边做大小 + SHA256 校验）；取消或失败 → exit 1。
3. 安装只替换 `ATProbe.exe`（及随包的 `atprobe-cli.exe`）与 `_internal\`，
   **绝不触碰** `reports\`、`logs\`、`atprobe.yaml`、`examples\` 等用户数据；失败自动回滚。
4. **开发态（源码运行）拒绝在线安装**，提示改用 `git pull`（exit 1）。

退出码：已是最新 / 升级成功 → 0；检查失败 / 用户取消 / 下载或安装失败 → 1。

## 11. 配置文件定位与产物位置

### 11.1 atprobe.yaml 定位（run 与 list 同规则）

1. 显式 `--config/-c`：按给定路径（相对当前目录）。
2. 便携版：exe 同级的 `atprobe.yaml`（模板见包内 `atprobe.yaml.template`，复制后修改）。
3. 否则回退当前目录下的 `atprobe.yaml`。

文件不存在 → 使用全默认值，不报错；存在但非法（YAML 语法错、类型不符等）→ exit 2。
各字段含义见 `docs\user\config-reference.md`。

### 11.2 每次运行的产物

| 产物 | 位置 |
|---|---|
| HTML 报告 | `<report_dir>/<session>/report.html`（`--no-report` 跳过；生成后控制台打印路径） |
| 串口原始日志 | `logs/<session>/<端口>/`（按会话留存，HEX+TEXT 双格式） |
| 运行日志 | `logs\atprobe.log`（`--debug` 时为 DEBUG 级，2MB×5 轮转） |

`session_id = 日期时间(%Y%m%d_%H%M%S) + "_" + 4 位随机 hex`，同时用作报告目录名与
日志目录名；随机后缀防止同秒连续运行互相覆盖。

## 12. 退出码与 CI 集成

| 码 | 语义 | 典型触发 |
|---|---|---|
| 0 | 全部用例 PASS 且未中断 | — |
| 1 | 有失败 / 跳过 / 中断 | 任一用例 FAIL 或 SKIP；Ctrl+C 中断；标签过滤后无可用用例；启动级失败（如端口全部打开失败，原因打印到 stderr） |
| 2 | 配置 / 输入错误 | `atprobe.yaml` 或 env.yaml 非法；未指定端口且非 vsim；未找到任何用例文件；用例/套件解析失败；GUI 依赖缺失 |

CI（GitHub Actions、Jenkins 等）直接以退出码判定：`0` 全过、非 `0` 失败。示例：

```yaml
- run: atprobe-cli.exe run examples\testcases --port COM5:115200 --no-color
```

建议 CI 中加 `--no-color`（CI 日志通常不是 tty，颜色本会自动失效，显式声明更稳妥）。

## 13. 控制台输出解读

- **progress 级**（默认）：打印用例开始行（名称 + 序号/总数）、步骤行（阶段/端口/命令/
  状态/耗时，命令按 `console.command_truncate` 默认 40 字符截断）、压测进度行（轮次/
  成功/失败/平均耗时）、用例结果行。响应文本**只打印非 PASS 步骤的**——失败时一定
  能看到设备实际响应，方便对照指令文档定位差异。
- **debug 级**（`--log-level debug`）：打印**全部**步骤的响应文本。
- 响应中的 `\r` / `\n` 转义显示为 `<CR>` / `<LF>`，字节级行为一目了然（例如区分 `\r\nOK\r\n`
  与 `\nOK\n`）。失败定位套路：先看失败步骤的「期望 vs 实际」，再开
  `--log-level debug` 重跑，仍不确定时查 `logs/<session>/<端口>/` 原始字节日志。
- 颜色由 `--no-color`（取反）、配置 `console.color`（默认 true）、stdout 是否 tty 三者
  共同决定。

## 14. Ctrl+C 行为

- 首次 Ctrl+C：打印 `\n[Ctrl+C] 中断信号`，停止整个运行：
  - 当前用例标记 INTERRUPTED，后续用例不再启动；
  - 套件的 `suite_teardown` **无条件执行**（不响应取消，尽量恢复设备状态）；
  - 已完成用例的统计保留，仍会生成汇总与 HTML 报告。
- 中断后 `summary.interrupted = true` → 退出码 1（CI 判为失败）。
- 兜底：若信号未经处理器直达引擎主循环，状态仍记为 FINISHED（非 ERROR），
  错误信息为「被用户中断（Ctrl-C）」。

## 15. 常用命令示例速查

```powershell
# ① 最小可运行：单文件 + 指定端口（便携版，README.txt 同款）
atprobe-cli.exe run examples\testcases\3gpp\network\NETWORK-CSQ-RESP-QUERY_FORMAT.yaml --port COM5:115200

# ② 开发态等价写法（仓库根目录）
uv run atprobe run examples/testcases/3gpp/network/NETWORK-CSQ-RESP-QUERY_FORMAT.yaml --port COM3:115200

# ③ 整个目录递归 + 多端口（不同波特率/帧格式）+ 标签过滤
atprobe-cli.exe run examples\testcases -p COM5:115200:8N1 -p COM6:921600 --tag network --exclude-tag slow

# ④ 无硬件演示：vsim 虚拟模组，自定义 CSQ/CEREG 应答，debug 级看全部响应
atprobe-cli.exe run examples\testcases --vsim --vsim-rssi 18 --vsim-cereg 5 --log-level debug

# ⑤ 演练：只校验用例与端口，不真正执行
atprobe-cli.exe run examples\testcases --port COM5:115200 --dry-run

# ⑥ CI 集成：无色输出、固定报告目录、DEBUG 运行日志
atprobe-cli.exe run examples\testcases -p COM5:115200 --no-color --report-dir reports\ci --debug

# ⑦ 查看可跑什么：列用例（按标签筛）、列套件、列本机串口
atprobe-cli.exe list cases --tag network
atprobe-cli.exe list suites
atprobe-cli.exe list ports

# ⑧ 指定配置文件与环境配置运行
atprobe-cli.exe run examples\testcases -c D:\atprobe.yaml --env-config examples\env.yaml --port COM5

# ⑨ 只跑套件（suite- 前缀文件，自动带 suite_setup/suite_teardown）
atprobe-cli.exe run examples\testcases\suite-smoke.yaml --port COM5:115200

# ⑩ 启动 GUI / 查看版本 / 检查更新
atprobe-cli.exe gui
atprobe-cli.exe --version
atprobe-cli.exe update --check
```

## 16. 常见问题

| 现象 | 原因与处理 |
|---|---|
| exit 2 且提示未指定端口 | 三处（命令行/配置/默认）都没有端口；加 `--port` 或改 `atprobe.yaml`，或改用 `--vsim` |
| exit 2 且带 YAML 行号 | `atprobe.yaml` 或 env.yaml 值非法，按提示修正 |
| 黄色警告某路径不存在后继续 | 位置参数里混入了不存在路径，检查拼写；若全部无效最终 exit 2 |
| 过滤后无可用用例（exit 1） | `--tag`/`--exclude-tag` 组合把用例筛空了，先用 `list cases --tag xxx` 确认 |
| 端口打开失败（exit 1） | 端口被占用或不存在：`list ports` 核对；拔插后重试 |
| 便携版更新后配置丢了？ | 更新只替换程序与 `_internal\`，不触碰用户数据；检查是否解压到了新目录 |
