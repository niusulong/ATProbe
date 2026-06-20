# ATProbe

> 串口 AT 命令自动化测试工具 (Serial AT Command Automation Testing Tool)

面向嵌入式通信模组（蜂窝/WiFi/蓝牙）的本地串口 AT 命令自动化测试工具，同时提供 CLI 与桌面 GUI 两个入口。

## 特性

- 标准 YAML 用例定义（M2），声明式「发什么、期望什么」
- 串口通信管理（M1）：多端口、URC 监听、热插拔重连、HEX+TEXT 原始日志
- 测试执行引擎（M3）：串行调度、retry/poll/when、on_failure、压测统计
- 测试报告（M4）：实时控制台 + 纯静态 HTML 报告
- CLI（M5）与桌面 GUI（M6，PySide6）共享同一引擎
- 测试环境配置（M7）：跨用例共享的全局只读配置（`{{group.param}}` 点号引用）

## 安装（开发）

```bash
uv sync --extra dev --extra gui
```

## 使用

### CLI

```bash
uv run atprobe run examples/testcases/network/network-basic_register.yaml --port COM3:115200
uv run atprobe list cases
uv run atprobe version
```

### GUI

```bash
uv run python -m atprobe gui
```

## 文档

完整文档位于 [`docs/`](docs/README.md)：

- 需求：`docs/requirements/PRD-总体需求.md` 与 `REQ-M1` ~ `REQ-M7`
- 技术选型：`docs/design/TSD-技术选型.md`

## 技术栈

Python 3.11+ · pyserial · PySide6 (Qt6) · Typer · Pydantic · ruamel.yaml · Jinja2

## 开发

```bash
uv run ruff check          # lint
uv run ruff format         # format
uv run mypy src            # type check
uv run pytest              # tests
uv run pytest --cov        # tests with coverage
```

## 许可

MIT
