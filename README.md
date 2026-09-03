# ATProbe

[![CI](https://github.com/niusulong/ATProbe/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![Release](https://github.com/niusulong/ATProbe/actions/workflows/release.yml/badge.svg)](../../actions/workflows/release.yml)

> 串口 AT 命令自动化测试工具 (Serial AT Command Automation Testing Tool)

面向嵌入式通信模组（蜂窝/WiFi/蓝牙）的本地串口 AT 命令自动化测试工具，提供 CLI、桌面 GUI 与面向大模型的 MCP 服务（stdio / HTTP）三类入口。

## 特性

- 标准 YAML 用例定义（M2），声明式「发什么、期望什么」
- 串口通信管理（M1）：多端口、URC 监听与噪声过滤（`urc_filter`）、热插拔重连、HEX+TEXT 原始日志
- 测试执行引擎（M3）：串行调度、retry/poll/when、on_failure、压测统计
- 测试报告（M4）：实时控制台 + 纯静态 HTML 报告
- CLI（M5）与桌面 GUI（M6，PySide6）共享同一引擎
- 测试环境配置（M7）：跨用例共享的全局只读配置（`{{group.param}}` 点号引用）
- MCP 服务（M8）：向大模型 / Agent 开放测试能力——stdio 与 HTTP serve 两种形态、
  14 个工具（设备发现、手动调试、URC 监控、异步批量作业、服务端信息）、Bearer Token 认证

## 安装（开发）

```bash
uv sync --extra dev --extra gui --extra mcp    # mcp extra 仅 MCP 服务需要，可省略
```

## 下载使用（最终用户）

无需安装 Python。从 [Releases](../../releases) 下载 `ATProbe-<version>-win64.zip`，解压后双击 `ATProbe.exe` 即可。详细说明见压缩包内 `README.txt`。

## 使用

### CLI

```bash
uv run atprobe run examples/testcases/3gpp/network/NETWORK-CSQ-RESP-QUERY_FORMAT.yaml --port COM3:115200
uv run atprobe list cases
uv run atprobe --version     # 版本号是 --version / -V 标志，不是子命令
```

### GUI

```bash
uv run atprobe gui           # 桌面端 GUI（PySide6）
```

### MCP 服务（向大模型开放）

```bash
uv run atprobe mcp stdio --config examples/atprobe.yaml   # stdio 形态：接入本地 LLM 客户端（Claude Desktop / Cursor / DeepSeek Harness 等）
uv run atprobe mcp serve --config examples/atprobe.yaml --token <TOKEN>   # HTTP 形态：远程 / 局域网访问，Bearer Token 认证
```

启动后大模型即可调用 `list_ports` / `open_port` / `send_at` / `start_run` / `get_job`
等 14 个工具直接操作串口设备：发现端口、手动调试、监控 URC、跑批量用例并轮询结果。
完整配置、客户端接入与工作流见 [MCP 用户手册](docs/user/mcp-guide.md)。

## 文档

用户手册随仓库维护（[`docs/user/`](docs/user/README.md)）：用例设计、CLI、GUI、MCP 服务、
配置参考与快速上手。用例编写规范另见 `.agents/skills/atprobe-case-author/`；
指令参考（`docs/at-ref/`）与需求、技术设计文档（PRD/REQ/TSD）仅在本地维护，不随仓库分发。

## 技术栈

Python 3.11+ · pyserial · PySide6 (Qt6) · Typer · Pydantic · ruamel.yaml · Jinja2 · MCP SDK（可选 extra）

## 开发

```bash
uv run ruff check          # lint
uv run ruff format         # format
uv run mypy src            # type check
uv run pytest              # tests
uv run pytest --cov        # tests with coverage
```

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

## 许可

[MIT](LICENSE) © 2026 牛苏龙 (Niu Sulong)
