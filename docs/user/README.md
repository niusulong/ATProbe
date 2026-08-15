# ATProbe 用户手册

> 面向最终用户的使用文档（随仓库分发）。当前版本：0.8.0。

## 手册目录

| 文档 | 内容 | 适合谁 |
|---|---|---|
| [testcase-guide.md](testcase-guide.md) | **用例设计说明**——YAML 用例从零编写：字段、断言、变量、控制流、套件、压测、常见陷阱 | 写测试用例的工程师 |
| [cli-guide.md](cli-guide.md) | **命令行工具**——run/list/gui/update 全参数、--vsim 无硬件演示、退出码、CI 集成 | 命令行用户 / CI |
| [gui-guide.md](gui-guide.md) | **图形界面**——手动调试、实时监控、用例执行、环境配置、命令库 | 桌面用户 |
| [config-reference.md](config-reference.md) | **配置参考**——atprobe.yaml 与 env.yaml 逐字段含义、端口表达式、urc_filter 详解 | 所有人（速查） |

## 5 分钟快速上手

### 第 1 步：拿到工具

- **最终用户**：从 [Releases](https://github.com/niusulong/ATProbe/releases) 下载
  `ATProbe-<version>-win64.zip`，解压后双击 `ATProbe.exe`（无需安装 Python）。
- **开发者**：`git clone` 后 `uv sync --extra dev --extra gui`。

### 第 2 步：确认串口

设备管理器查到模组串口号（如 `COM5`），记下波特率（模组默认通常 115200）。

### 第 3 步（GUI 路线）：手动连一下

1. 打开 ATProbe.exe → 手动调试页；
2. 选端口 `COM5`、波特率 `115200` → 连接；
3. 发送框输入 `ATE0`，结束符选 `CR+LF`，发送——响应区出现 `OK` 即通。

### 第 3 步（CLI 路线）：跑一个自带用例

```bash
# 便携版
atprobe-cli.exe run examples\testcases\3gpp\network\NETWORK-CSQ-RESP-QUERY_FORMAT.yaml --port COM5:115200

# 开发态
uv run atprobe run examples/testcases/3gpp/network/NETWORK-CSQ-RESP-QUERY_FORMAT.yaml --port COM5:115200
```

看到步骤 PASS、控制台汇总「全部通过」即成功。HTML 报告生成在
`reports\<会话>\report.html`，原始串口日志在 `logs\<会话>\COM5\`。

### 第 4 步：无硬件？先玩虚拟模组

```bash
atprobe-cli.exe run examples\testcases\3gpp\network --vsim
```

进程内虚拟模组直接应答，验证用例与工具链路，不需要任何设备。

## 核心概念（30 秒版）

| 概念 | 一句话 |
|---|---|
| 用例 | 一个 YAML 文件：声明式描述「发什么 AT 命令、期望什么响应」 |
| 断言 | 字节级严格校验（含 `\r\n`、空格、错误码格式），不是宽松 contains |
| URC | 模组主动上报的行（如 `+CEREG: 1`）；监控可见、不污染命令断言 |
| urc_filter | 设备有持续上报（如 GPS 循环输出）时，配置剥离噪声行保护严格断言 |
| 环境配置 | env.yaml 存设备指纹/服务器地址等事实，用例里 `{{group.param}}` 引用 |
| 套件 | `suite-*.yaml` 把多个用例编排成组，可带套件级 setup/teardown |

## 常见问题速查

| 现象 | 去哪看 |
|---|---|
| 步骤 FAIL，想看设备实际回了什么 | CLI 加 `--log-level debug`；或看 `logs/<会话>/<端口>/` 原始日志 |
| 严格断言偶发失败、响应里混了定位行 | [config-reference.md](config-reference.md) 的 urc_filter 一节 |
| 异步指令（OK 只是受理）怎么断言 | [testcase-guide.md](testcase-guide.md) 的 wait_urc 一节 |
| 设备没插 / 没串口 | 用 `--vsim` 虚拟模组 |
| 端口打开失败 | 确认没有其他程序占用（串口助手、另一个 ATProbe 实例） |

## 反馈与开发资源

- 仓库：<https://github.com/niusulong/ATProbe>
- 开发文档（需求/设计）在本地 `docs/` 维护，不随仓库分发。
