# ATProbe MCP 服务使用说明

> 适用版本：0.8.x。MCP（Model Context Protocol）把 ATProbe 的测试能力开放给大模型：
> Claude Desktop、Cursor、自研 Agent 等任何 MCP 客户端都能发现串口、执行测试用例、
> 手动收发 AT 命令、订阅 URC 上报。本文讲怎么装、怎么配、怎么用。
> ATProbe 的 CLI 与 GUI 用法见同目录其他手册；测试用例编写见 `testcase-guide.md`。

## 1. 简介：两种服务形态

一台测试电脑 = 一个 MCP 端点 = 该机名下全部串口设备（ATProbe 本就是多端口架构，
用例步骤按 port 路由）。要操作另一台电脑的设备，客户端另行配置指向那台机即可。

| 形态 | 启动命令 | 认证 | 适用场景 |
|---|---|---|---|
| **本地 stdio** | `atprobe mcp stdio` | 无（进程由客户端拉起，信任边界即 OS 用户） | 个人电脑上，Claude Desktop / Cursor 直接操作本机串口 |
| **远程 serve** | `atprobe mcp serve` | Bearer Token（强制） | 测试电脑无头常驻，另一台机器的 LLM 客户端远程访问该机全部串口 |

```
形态一：本地 stdio（无认证，客户端拉起子进程）

 ┌─────────────────────┐   stdin/stdout（MCP 协议） ┌─────────────────────┐
 │ MCP 客户端           │ ────────────────────────▶ │ atprobe mcp stdio    │
 │ Claude Desktop /     │ ◀──────────────────────── │ （本机子进程）        │──串口──▶ 模组
 │ Cursor / 自研 Agent  │         JSON-RPC          └─────────────────────┘
 └─────────────────────┘

形态二：远程 serve（Bearer Token，测试电脑常驻）

 ┌─────────────────────┐   HTTP + Bearer Token      ┌─────────────────────┐
 │ MCP 客户端           │ ────────────────────────▶ │ atprobe mcp serve    │
 │ （另一台机器）        │ ◀──────────────────────── │ http://主机:8470/mcp │──串口──▶ 该机全部模组
 └─────────────────────┘                            └─────────────────────┘
```

开放的能力 = 14 个工具（4 组）：资源发现（server_info / list_ports / list_cases /
list_suites）、批量测试（validate_run / start_run / get_job / cancel_job）、手动调试
（open_port / close_port / send_at）、URC 监控（subscribe_urc / poll_urc /
unsubscribe_urc）。速查表见 §5。

## 2. 安装

MCP 依赖是可选组件（extra），核心安装不含它：

```powershell
# 源码仓库（推荐）
uv sync --extra mcp          # 仅 MCP；开发全套：uv sync --extra dev --extra gui --extra mcp

# 或 pip 安装（未发布 PyPI：git 直装，或 clone 后本地可编辑安装）
pip install "atprobe[mcp] @ git+https://github.com/niusulong/ATProbe"
# 或 clone 仓库后：
pip install -e ".[mcp]"
```

验证：

```powershell
uv run atprobe mcp --help    # 能列出 stdio / serve 两个子命令（--help 不验证 SDK 就绪）
uv run python -c "import mcp"  # 无报错即 mcp SDK 就绪
```

> **便携版注意**：Release 的便携包（`ATProbe.exe` / `atprobe-cli.exe`）当前**不内置**
> MCP 依赖，运行 `atprobe-cli.exe mcp ...` 会得到红字提示并以 exit 2 退出。MCP 形态
> 请使用上述 Python 安装方式。

## 3. 快速开始

### 3.1 本地 stdio —— Claude Desktop

编辑 Claude Desktop 配置文件（Windows：`%APPDATA%\Claude\claude_desktop_config.json`）：

方式 A——`atprobe` 已在 PATH（pip 安装或虚拟环境已激活）：

```json
{
  "mcpServers": {
    "atprobe": {
      "command": "atprobe",
      "args": ["mcp", "stdio"]
    }
  }
}
```

方式 B——用仓库虚拟环境的 Python 经 `-m` 启动，并显式指定配置文件（路径用 `\\` 转义）：

```json
{
  "mcpServers": {
    "atprobe": {
      "command": "D:\\atprobe\\.venv\\Scripts\\python.exe",
      "args": ["-m", "atprobe", "mcp", "stdio", "-c", "D:\\atprobe\\atprobe.yaml"]
    }
  }
}
```

没有硬件也想先体验？加 `--vsim` 用进程内虚拟模组应答：

```text
"args": ["mcp", "stdio", "--vsim"]
```

保存后重启 Claude Desktop，工具列表里出现 14 个 atprobe 工具即成功。

> `stdio` 形态下该进程的 **stdout 被协议独占**——在终端手动运行 `atprobe mcp stdio`
> 「没有任何输出」是正常现象：它在等 stdin 上的 JSON-RPC。日志走 stderr。

### 3.2 本地 / 远程 —— Cursor

编辑 `.cursor/mcp.json`（项目级）或全局 MCP 设置。本地 stdio 与 Claude Desktop 同构：

```json
{
  "mcpServers": {
    "atprobe": {
      "command": "atprobe",
      "args": ["mcp", "stdio"]
    }
  }
}
```

连接远程 serve 用 `url` + `Authorization` 头（注意 URL 要带 `/mcp` 路径）：

```json
{
  "mcpServers": {
    "atprobe-remote": {
      "url": "http://192.168.1.100:8470/mcp",
      "headers": { "Authorization": "Bearer <你的Token>" }
    }
  }
}
```

### 3.3 远程 serve

在接串口的测试电脑上：

```powershell
# ① 生成 Token 并写入文件（PowerShell 重定向有编码陷阱，让 Python 直接写文件最稳）
python -c "import secrets, pathlib; pathlib.Path('mcp-token.txt').write_text(secrets.token_hex(32))"

# ② 启动：0.0.0.0 = 允许其他机器访问（默认 127.0.0.1 仅本机，见 §9）
uv run atprobe mcp serve --host 0.0.0.0 --port 8470 --token-file mcp-token.txt
```

启动后 stderr 打印青色提示 `atprobe mcp serve → http://0.0.0.0:8470/mcp`，客户端按
`http://<测试电脑IP>:8470/mcp` + Token 连接（Token 详见 §4，防火墙放行见 §4.4）。

serve 子命令参数：

| 参数 | 缺省来源 | 说明 |
|---|---|---|
| `--host` | 配置 `mcp.host`（默认 `127.0.0.1`） | 监听地址；远程访问需显式 `0.0.0.0` |
| `--port` | 配置 `mcp.port`（默认 `8470`） | 监听端口 |
| `--token` | — | Token 明文（优先级低于 `--token-file`，不建议，见 §4.2） |
| `--token-file` | — | Token 文件路径（最高优先级） |
| `--vsim` | 关 | 进程内虚拟模组，无需真实串口（联调/演示） |
| `--config, -c` | 定位规则同 run/list | atprobe.yaml 路径 |

serve **必须有 Token** 才肯启动（四级来源全空或文件全空白 → 红字提示 + exit 2），
杜绝「以为有认证实际裸奔」。

### 3.4 DeepSeek Harness（dsh）接入

DeepSeek Harness（dsh）Web 界面自带 MCP 客户端（`@deepseek-ai/dsh-mcp-client`
插件）：把 atprobe 挂进它的 profile 补丁配置，模型工具表就会出现
`mcp__atprobe__*` 命名的 14 个工具（`serverName` 即命名空间前缀）。

编辑 `$DSH_HOME/profiles/web/cordis.patch.yml`（Windows 默认
`C:\Users\<用户名>\.dsh\profiles\web\cordis.patch.yml`），在文件的顶层
`[]` 处替换/追加：

```yaml
- insert:
    - id: mcp-atprobe
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: atprobe
        transport: stdio
        command: D:\niusulong\AI\ATProbe\.venv\Scripts\atprobe.exe
        args:
          - mcp
          - stdio
          - --config
          - D:\niusulong\AI\ATProbe\examples\atprobe-com5.yaml
        cwd: D:\niusulong\AI\ATProbe
        toolCallTimeoutMs: 120000
```

配置要点：

- **路径全部用绝对路径**：dsh 拉起的子进程 cwd 不可控，`command` / `--config` /
  `cwd` 都必须绝对化（目录分隔符用 `\` 转义或 `/` 均可）。
- `toolCallTimeoutMs`：AT 指令可能较慢（异步指令要等 URC 终结），建议从 SDK 默认
  60s 调到 120s 以上。
- 生效方式：**实测（2026-08-16）保存 patch 后 loader 会热加载**——dsh web 无需
  重启即自动拉起 `atprobe.exe mcp stdio` 子进程并建立连接（可从任务管理器看到
  atprobe.exe 子进程确认）。若你的版本未生效，重启 dsh web 进程即可。
- **工具对已开会话不可见**：模型工具快照在会话启动时定型，新增/修改 MCP 工具后
  必须**新开一个会话**才能看到 `mcp__atprobe__*`（旧会话继续用旧快照）。
- **单实例共享语义**：一个 dsh 实例只 spawn 一个 atprobe stdio 子进程，所有会话
  共享这条连接与端口状态——互斥规则（§6.4）照常生效（一个会话开着的 COM5，其他
  会话能看到 connected=true；作业运行中任何会话 send_at 都得 BUSY）。
- 回滚：删除这个 `- insert:` 块（或把 `mcp-atprobe` 条目移出），热加载/重启后
  工具即消失。

验证接入是否成功：

```powershell
# ① 子进程被拉起（任务管理器/Get-Process 看到 atprobe.exe）
Get-Process atprobe -ErrorAction SilentlyContinue | Select-Object Id, StartTime
# ② 新开会话后让模型执行：mcp__atprobe__list_ports
#    应返回 COM5 等真实串口；send_at("COM5", "AT") 响应含 OK
```

> 与 §3.1/§3.2 的关系：dsh 只是**又一个 stdio MCP 客户端**，协议与 Claude
> Desktop/Cursor 完全相同；`atprobe mcp stdio` 这一侧无任何 dsh 专属行为。

## 4. Token 指南（serve 形态）

### 4.1 生成

```powershell
# 打印到屏幕（配合 --token 用，或自己粘贴进文件）
python -c "import secrets; print(secrets.token_hex(32))"

# 直接写入文件（推荐；避免 PowerShell 重定向的 UTF-16 编码陷阱）
python -c "import secrets, pathlib; pathlib.Path('mcp-token.txt').write_text(secrets.token_hex(32))"
```

### 4.2 四级优先级

serve 启动时按以下顺序取 Token，命中即停：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | `--token-file` | 文件内容去掉首尾空白；全空白 → 返回 None，serve 即 exit 2（不再下探其他来源）；文件不存在 exit 2 |
| 2 | `--token` | 明文。会进 shell 历史与进程列表，仅临时调试用 |
| 3 | 环境变量 `ATPROBE_MCP_TOKEN` | 去空白后为空则忽略，继续下探 |
| 4 | 配置 `mcp.token_file` | 同优先级 1 的文件语义 |

全部为空 → serve 拒绝启动（exit 2）。Token 永远不会写进任何日志。

### 4.3 文件权限

Token 文件等同密码本，收紧到仅当前用户可读：

```powershell
# Windows（icacls）
icacls mcp-token.txt /inheritance:r /grant:r "$($env:USERNAME):F"

# Linux / macOS
chmod 600 mcp-token.txt
```

### 4.4 Windows 防火墙放行

远程访问需在**测试电脑**上放行 8470（管理员 PowerShell）：

```powershell
netsh advfirewall firewall add rule name="ATProbe MCP" dir=in action=allow protocol=TCP localport=8470
```

### 4.5 nginx TLS 反向代理（最小示例）

ATProbe 自身不终结 TLS（内网信任假设）。需要加密传输时，让 serve 继续绑定回环
`127.0.0.1`，由 nginx 挂证书对外：

```nginx
server {
    listen 443 ssl;
    server_name atprobe.example.internal;           # 占位：换成你的内网域名/IP
    ssl_certificate     /etc/nginx/ssl/atprobe.crt; # 占位：证书路径
    ssl_certificate_key /etc/nginx/ssl/atprobe.key; # 占位：私钥路径

    location /mcp {
        proxy_pass http://127.0.0.1:8470;   # 不带路径后缀，/mcp 原样转发
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_buffering off;                # Streamable HTTP 流式响应不能缓冲
        proxy_read_timeout 3600s;           # 长连接/流不被中间层掐断
    }
}
```

客户端连接 `https://atprobe.example.internal/mcp`（Token 头照常携带）。

## 5. 工具速查表（14 个）

| 工具 | 用途 | 关键参数 | 返回要点 |
|---|---|---|---|
| `server_info` | 服务端信息（编码机协作入口） | — | `{version, vsim, workspace, paths: {cases_dir, log_dir, report_dir}}`，全部为**绝对路径** |
| `list_ports` | 设备发现入口 | — | `[{name, description, connected}]`（connected 为服务进程内的连接态） |
| `list_cases` | 列可执行用例 | `path?`（缺省配置 `cases_dir`）、`tags?`（并集过滤） | `[{name, tags, file}]`；参数化用例显示 `name#N` |
| `list_suites` | 列测试套件 | `path?` | `[{name, description, case_count, tags, file}]` |
| `validate_run` | dry-run 校验一次执行 | `paths?`、`ports?`、`tags?` | `{case_count, cases, ports, ports_available}`；不实际执行 |
| `start_run` | 启动异步批量测试 | 同 `validate_run` | `{job_id}`；立即返回，用 get_job 轮询 |
| `get_job` | 查作业状态/进度/结果 | `job_id` | `{status, progress?, summary?, report_path?, events, error?}` |
| `cancel_job` | 取消运行中的作业 | `job_id` | `{cancelled: bool}`；幂等（已结束返回 false） |
| `open_port` | 打开串口（手动调试） | `port_expr`（如 `COM5:115200:8N1`，波特率/帧可省略） | `{name, baud, frame}` |
| `close_port` | 关闭串口（幂等） | `port` | `{closed: true, port}`；同时拆掉该端口 URC 转发 |
| `send_at` | 发单条 AT 命令并等响应 | `port`、`command`、`timeout?`（秒）、`wait_urc?`（URC 终结正则） | `{text, status, error?, error_kind?}`；端口须已 open |
| `subscribe_urc` | 订阅端口 URC 上报 | `port`、`pattern?`（正则，缺省全收） | `{subscription_id}`；端口须已 open |
| `poll_urc` | 按游标增量拉取 URC | `subscription_id`、`cursor?`（默认 0）、`limit?`（默认 100） | `{events, next_cursor, truncated?}` |
| `unsubscribe_urc` | 退订（幂等） | `subscription_id` | `{unsubscribed: true}` |

## 6. 典型工作流（给 LLM 的使用建议）

### 6.1 探测 / 手动调试

```
server_info()                          # 服务端信息：workspace/cases_dir/log_dir/report_dir 绝对路径
list_ports()                          # 找到目标端口（如 COM5）
open_port("COM5:115200:8N1")          # 连接
send_at("COM5", "AT")                 # 响应 text 含 OK 即通
send_at("COM5", "AT+CGMI")            # 逐条探索；异步指令可用 wait_urc 等 URC 终结
close_port("COM5")                    # 用完关闭（同时拆 URC 转发）
```

> **编码机协作流**（用例/日志文件由外部工具传输，MCP 只按路径引用）：
> `server_info` 拿到 cases_dir 绝对路径 → 用文件工具把用例 YAML 放进去 →
> `list_cases` 确认可见 → `start_run` → `get_job` 拿 report_path →
> 按 `log_dir/<job_id>/` 取回原始串口日志。

### 6.2 批量测试（异步作业）

```
list_cases() / list_suites()                            # 挑用例
validate_run(paths=["D:\\cases\\smoke"], ports=["COM5:115200"])   # 先演练：几条用例、哪些端口
start_run(paths=[...], ports=[...], tags=[...])          # → {job_id}（job_id 即报告目录名）
get_job(job_id)                                          # 轮询（建议 1~5 秒一次）：
                                                         #   running 看 progress/events
                                                         #   finished 看 summary + report_path
cancel_job(job_id)                                       # 跑偏/耗时过长时取消（幂等）
```

- 同一时刻只允许一个作业：再 `start_run` 会得到 BUSY（`detail.job_id` 告诉你谁占着）。
- `report_path` 是**测试电脑上**的 HTML 报告路径（`<report_dir>/<job_id>/report.html`）——
  远程形态下客户端拿不到文件内容，应把路径告知用户在测试电脑上查看。
- summary 字段：`total / passed / failed / skipped / interrupted / pass_rate`。

### 6.3 URC 监控

```
open_port("COM5:115200:8N1")
subscribe_urc("COM5", pattern="^\\+CEREG:")     # pattern 可省（全收）；正则匹配整行（去首尾空白）
poll_urc(subscription_id, cursor)               # → events + next_cursor
poll_urc(subscription_id, cursor=<上次 next_cursor>)   # 游标如此推进，不丢不重
unsubscribe_urc(subscription_id)                # 不再需要时退订
```

- 每订阅一个环形缓冲存最近 **500 条**；消费慢于上报时旧事件被挤掉，此时返回带
  `truncated: true`——加大轮询频率或收窄 `pattern`。
- 空页时 `next_cursor` 原样返回，下次继续轮询即可。

### 6.4 BUSY 与互斥速查

| 场景 | 行为 |
|---|---|
| 作业运行中再 `start_run` | BUSY（附占用中的 job_id；不做排队） |
| 作业运行中 `send_at` | BUSY（AT 状态机串行，引擎持有端口期间不允许手动发送） |
| 作业运行中 `open_port` / URC 订阅与轮询 | **允许**（URC 是纯观察者通道） |
| 手动打开的端口 | 作业不会替你关（作业只关闭自己新开的端口）；`close_port` 显式关闭 |
| GUI 与 MCP | **不能同时用同一串口**：pyserial 独占，冲突方 open 失败（DEVICE_ERROR 提示占用）。用 MCP 前先关 GUI / 串口助手 |

### 6.5 错误通道：kind 枚举 + JSON 解析

工具失败时返回 `is_error=true`，文本是一段 JSON：`{"kind", "message", "detail"}`。
**注意**：SDK 会在 JSON 前面加一段 `"Error executing tool <name>: "` 前缀——解析时从
**第一个 `{` 字符**起截取再 `json.loads`，不要做文案匹配：

| kind | 含义 | 建议处理 |
|---|---|---|
| `INVALID_INPUT` | 参数/配置/用例解析错误；端口表达式非法；端口未开；URC 正则非法 | 读 message 修正参数；先 open_port 再操作 |
| `NOT_FOUND` | job_id 不存在（含被历史淘汰）；subscription_id 不存在/已退订 | 核对 id；作业历史仅保留最近 100 条 |
| `BUSY` | 单并发互斥 | 从 detail.job_id 找到占用作业，等它结束或 cancel_job |
| `DEVICE_ERROR` | 串口打开/发送失败（含被 GUI/其他程序占用） | list_ports 核对；关闭占用程序后重试 |
| `INTERNAL` | 未预期异常（含异常类名） | 重试一次；仍失败按报障处理 |

另有两种错误**不走**工具通道：Token 错误由 HTTP 层直接返回 `401
{"error":"unauthorized"}`（客户端表现为连接/初始化失败）；serve 启动失败（缺 Token、
配置非法、依赖缺失）是进程 exit 2 + 红字 stderr，见 §8。

### 6.6 原始串口日志（自动落盘）

MCP 服务进程内常驻原始日志记录器，两类通道的字节级收发**自动落盘**（HEX+TEXT
双文件，与 CLI/GUI 同款格式）：

| 通道 | 日志位置 | 内容 |
|---|---|---|
| `start_run` 作业 | `<log.dir>/<job_id>/<端口>/<用例名>.text.log` / `.hex.log` | 每用例的收发字节（引擎按用例绑定，与 CLI `atprobe run` 完全一致） |
| 手动调试（`open_port` 之后） | `<log.dir>/manual_<时间戳>/<端口>/manual.text.log` / `.hex.log` | 端口打开期间的全部原始字节流——含回显、GPS 循环上报等噪声，**未经 urc_filter 剥离**（按字节原样记录，字节级定位以此为准） |

- manual 会话随 MCP 服务进程生成（一个进程一个），`close_port` 后停止记录，
  重开同端口继续追加同一文件。
- `log.dir` 配置控制日志根目录（默认 `./logs`，锚定服务进程工作区）。
- 定位断言问题时：作业失败看作业日志（干净文本 + 原始字节两份），手动调试看
  manual 日志（含噪声的完整字节流）。

> 可把下面这段直接粘进 Claude/Cursor 的自定义指令（project instructions）：
>
> 「你可以调用 atprobe 的 14 个 MCP 工具操作串口 AT 设备。推荐流程：list_ports 发现
> 设备 → open_port 连接 → send_at 手动调试 / subscribe_urc 监控 → start_run 批量执行
> → get_job 轮询结果（report_path 是服务端路径，转告用户即可）。同一时刻只有一个测试
> 作业（再启动得 BUSY）；作业运行期间禁止 send_at（BUSY）。工具报错时 is_error=true，
> 从文本第一个 `{` 起解析 JSON，按 kind（INVALID_INPUT/NOT_FOUND/BUSY/DEVICE_ERROR/
> INTERNAL）决策，不要匹配文案。」

## 7. atprobe.yaml 的 mcp 段

```yaml
mcp:
  host: 127.0.0.1            # serve 监听地址。默认故意回环——远程访问需显式 0.0.0.0
  port: 8470                 # serve 监听端口
  # token_file: ./mcp-token.txt   # serve 的第 4 级 Token 来源（可选）
```

- 仅 `serve` 形态消费这些键；`stdio` 形态忽略（stdio 无认证）。
- 优先级：命令行（`--host`/`--port`/`--token-file`）> 配置 > 内置默认。
- 值非法（如 `mcp.port` 不是整数）→ 启动红字报错 exit 2；`mcp` 段缺失或留空 = 全默认。
- 其余通用键（`cases_dir`、`ports`、`report_dir`、`urc_filter` 等）对 MCP 同样生效，
  含义见 `config-reference.md`。

## 8. 故障排查

| 现象 | 原因与处理 |
|---|---|
| 客户端连不上 serve / 初始化失败 | 多半是 Token 错误 → HTTP 401 `{"error":"unauthorized"}`（客户端通常显示为连接错误而非工具错误）。按 §4.2 核对四级来源；`--token-file` 文件是否存在、是否全空白 |
| serve 一启动就 exit 2「serve 需要 Token」 | 四级来源全空，或 token 文件内容全空白——按 §4.1 重新生成 |
| exit 2「Token 文件不存在」 | `--token-file` / `mcp.token_file` 路径写错 |
| exit 2「MCP 依赖未安装 … uv sync --extra mcp」 | 没装 mcp extra：`uv sync --extra mcp`；便携版 exe 不含 MCP，见 §2 |
| `open_port` 报 DEVICE_ERROR「可能被 GUI 或其他程序占用」 | 串口被 GUI / 串口助手 / 另一个 ATProbe 占用（pyserial 独占）。用 MCP 前先关掉它们 |
| job 一直 running | 看快照的 `progress` 与 `events` 判断是否正常推进；确要停就 `cancel_job`（幂等）。引擎有终态兜底，作业不会无限悬挂 |
| 远程机器访问不到 8470 | 三查：serve 是否 `--host 0.0.0.0`；Windows 防火墙是否放行（§4.4）；客户端 URL 是否带 `/mcp` 路径 |
| `poll_urc` 返回 `truncated: true` | 消费慢于上报，500 条环形缓冲被挤掉——加大轮询频率或收窄 pattern |
| 终端手动运行 `atprobe mcp stdio` 没有任何输出 | 正常：stdout 被协议独占，进程在等 stdin 的 JSON-RPC；日志走 stderr。由 MCP 客户端拉起即可 |
| `list_cases` 返回空 | path 参数 / 配置 `cases_dir` 指向的目录没有用例 YAML（或全部解析失败被跳过） |
| dsh 新会话仍看不到 `mcp__atprobe__*` | ① 工具快照在会话启动时定型，确认是**新开**的会话；② 检查 patch 语法与路径（§3.4）：`Get-Process atprobe` 应看到子进程；③ atprobe 侧缺依赖 → 先 `uv sync --extra mcp`；④ 改过 `serverName`？工具名跟着变 |

## 9. 安全注意事项

- **默认回环**：`mcp.host` 默认 `127.0.0.1`，不显式改 `0.0.0.0` 不会暴露到网络。
  开放到内网后，服务等同「持 Token 者可操作该机全部串口」，Token 管理见 §4。
- **Token 不入日志**；文件权限收紧（§4.3）；避免 `--token` 明文（shell 历史/进程列表）。
- **stdio 的信任边界是本机 OS 用户**：能拉起进程就能操作串口，因此不设 Token——
  不要把 stdio 形态暴露给不可信的远程执行环境。
- **TLS 不内置**：跨不可信网络必须走反向代理（§4.5），不要裸 HTTP 出内网。
- **生产设备风险**：LLM 可能构造危险指令（关射频 `AT+CFUN=0`、关机、恢复出厂类）。
  建议：优先 `start_run` 跑**受控白名单用例目录**，而非放任 `send_at` 自由探索；
  生产设备测试全程专人监督；新 prompt / 新客户端先用 `--vsim` 演练。
- 无速率限制与审计日志（内网信任 + 单并发 BUSY 天然限流）；对外开放前自行评估。
