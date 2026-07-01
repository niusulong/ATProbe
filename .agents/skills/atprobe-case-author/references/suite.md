# 套件组织（suite）

套件是"用例集合的索引文件"——按功能域把多个用例文件组织起来，一次运行整组。

## suite 定义

独立的 YAML 文件，通过文件路径引用用例：

```yaml
name: 网络注册测试套件
description: 网络注册相关用例集合
tags: [network, regression]

suite_setup:                       # 可选，套件开头执行一次
  - command: AT+CFUN=1
suite_teardown:                    # 可选，套件结尾执行一次
  - command: AT+CFUN=0

cases:
  - NETWORK-CEREG-RESP-QUERY_FORMAT.yaml
  - NETWORK-CGACT-FUNC-ACTIVATE.yaml
  - NETWORK-CGACT-PARA-VALID_PDP.yaml
```

顶层字段：`name`、`description`、`tags`、`suite_setup`（可选，套件开头执行一次）、`suite_teardown`（可选，套件结尾执行一次）、`cases`（用例文件路径列表）。

## 执行顺序

```
suite_setup → [用例setup → 用例steps → 用例teardown]×N → suite_teardown
```

- 按顺序执行 `cases` 引用的用例。
- 套件内用例之间**独立，不共享变量**（每个用例有自己的变量池，见 `variables.md`）。
- 支持按标签筛选执行套件中的部分用例。

## 运行方式

两种触发方式：

- **`run suite-xxx.yaml`**（显式套件）：按套件 `cases` 列表的顺序载入并执行用例，套件前后置
  （`suite_setup`/`suite_teardown`）在用例组前后各执行一次。
- **`run <目录>`**（批量）：执行目录下所有用例文件（按文件名排序），框架自动跳过 `suite-` 前缀文件
  避免重复。此模式下套件文件仅作人类阅读的索引，不读取其 `cases` 列表。

`--tag`/`--exclude-tag` 筛选对两种方式都生效（按各用例自身的 tags 过滤）。

## 命名与目录结构

> **命名以 SKILL.md「命名与结构规范」为准**（4 段全大写）。下方 REQ-M2 §12.3 的旧式小写命名已被 SKILL.md 新规范取代。

**用例文件命名**（SKILL.md 新规范）：`<功能块>-<指令>-<类型>-<变体>.yaml`，四段全大写。

**套件文件命名**：`suite-<功能块>.yaml`，`suite-` 前缀区分套件与用例文件。例：`suite-TCP.yaml`、`suite-NETWORK.yaml`。

**用例 name 字段**：支持中文，报告/日志展示用。建议格式 `{功能点}-{测试场景}`，如 `网络注册-基础验证`。

**目录结构**：按功能块组织，每个功能块一个目录，套件与用例就近放一起：

```
testcases/
├── TCP/                            # TCP 功能块
│   ├── suite-TCP.yaml              # 该功能的套件
│   ├── TCP-TCPSEND-FUNC-NORMAL_SEND.yaml
│   ├── TCP-TCPSEND-FUNC-NOLINK.yaml
│   └── TCP-RECVMODE-RESP-QUERY_FORMAT.yaml
├── NETWORK/                        # 网络注册功能块
│   ├── suite-NETWORK.yaml
│   ├── NETWORK-CEREG-RESP-QUERY_FORMAT.yaml
│   └── NETWORK-CGACT-FUNC-ACTIVATE.yaml
└── STRESS/                         # 压测功能块
    ├── suite-STRESS.yaml
    └── STRESS-AT-PRESSURE-LOOP_AT.yaml
```

- 套件中引用用例用同目录相对路径。
- 功能块目录名与用例文件名第一段（功能块段）保持一致。
