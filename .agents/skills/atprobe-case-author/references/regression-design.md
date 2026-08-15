# 缺陷回归用例设计（REGRESS）

> 当用户给出 **bug 报告 / 缺陷现象日志**（含 BUGID、实测结果）时，读本文件设计回归用例。
> 与指令中心用例（RESP/FUNC/PARA，走 `testcase-matrix.md` 矩阵）不同，回归用例的目标是
> **验证某个已修复 bug 不再复现**——设计起点是 bug 报告，不是指令文档矩阵。

## 核心差异：回归用例 vs 指令中心用例

| 维度 | 指令中心用例（FUNC/RESP/PARA） | 回归用例（REGRESS） |
|---|---|---|
| 设计起点 | 指令文档（一条指令的所有形态） | bug 报告（一个缺陷的复现路径） |
| 用例数量 | 每指令多文件（矩阵展开） | **每 bug 只 1 个核心用例**（不生对照） |
| 断言来源 | 指令文档响应格式表 | bug 错误码的反向断言（不再出现） + 修复后正确响应 |
| 命名变体段 | 场景描述（NORMAL_SEND/QUERY_FORMAT） | **BUGID**（BUG1234567890） |
| setup 复杂度 | 多数简单 | 常重（需完整业务前置：注网/拨号/建链） |

## 命名与目录规范

**文件名**：
```
<功能块>-<指令>-REGRESS-<BUGID>.yaml
```
- 功能块、指令段规则同功能用例（全大写）。
- 变体段 = `BUG` + 工作项 ID 数字（如 `BUG1234567890`）。
- 同一 bug 只产一个核心回归用例，**不生 IPv4/IPv6 对照用例**。

**目录结构**（与功能用例分离，独立 `regress/` 顶层）：
```
testcases/
  EC626/                    ← 平台功能用例
    tcp/
  regress/                  ← 回归用例顶层（与平台目录平级）
    EC626/                  ← 平台目录（与功能用例同平台名）
      http/                 ← 按功能块归类（目录名 = 文件名功能块段）
        HTTP-HTTPCON-REGRESS-BUG1234567890.yaml
        问题报告_<BUGID>_*.md       ← 问题报告随回归用例同目录
```

回归用例**不放进平台功能目录**（不放 `EC626/http/`），而是独立的 `regress/<平台>/<功能块>/`。
这样：①回归集可独立运行（`run regress/`）；②回归用例不污染功能用例集；
③同平台聚集便于跨 bug 对比。

示例：`regress/EC626/http/HTTP-HTTPCON-REGRESS-BUG1234567890.yaml`

## 设计 7 步流程

### 1. 解构 bug 报告

从 bug 报告提取：
- **BUGID** + 所属项目/功能块（决定文件名）
- **缺陷现象日志**：逐行读实测结果，标记**触发指令**（最后一个执行的业务指令）和**错误码**（如 `+HTTP ERROR: CONNECT FAILED`）
- **发现版本** + **前置条件**（决定 setup 起点）
- **执行步骤**（决定业务前置链怎么搭）

### 2. 定位验证点

区分 bug 类型，决定 setup 复杂度：

- **指令参数/格式问题**（如某参数越界没报 CME）——setup 简单，steps 直接测该指令。
- **业务功能问题**（如 IPv6 连接失败、TLS 握手失败）——需完整业务前置链（注网→拨号→建链→触发指令），setup 重。本次踩的坑几乎全在这类。

### 3. 查文档定响应格式（断言依据，不可臆测）

**这是最易错的一步。** 必须从指令文档确认触发指令是同步还是异步：

- **同步指令**：成功直接返回 `OK`（或带结果码的单段响应），**无后续 URC**。断言用 `matches: '^\r\nOK\r\n$'`，**绝不能加 `wait_urc`**。
- **异步指令**：先返回 OK（受理），随后主动上报 URC 才是结果。用 `wait_urc` 等 URC。

**判据只看文档**该指令的响应描述——有无「主动上报」「OK 后跟 URC」字样。**不参考其他项目/固件规律**（同名字令在不同项目可能同步/异步不同）。文档不明 → 问用户，不跑设备探测。

历史教训：`AT+HTTPCON` 文档明确「成功返回 OK」是同步，误当异步加 `wait_urc` → 等满 30s 超时失败。

### 4. 设计 setup（业务前置链）

业务功能类 bug 的 setup 常含注网/拨号/建链链路，按以下经验设计：

- **注网判断用 `AT+CEREG?`**：`CGATT=1` 的 OK 仅表示"指令受理"，实际注网需数秒。用 `AT+CEREG?` 轮询，`+CEREG: <n>,<stat>` 中 `<stat>=1`（家用注册）或 `5`（漫游注册）才算成功。配 `retry: { count: 30, interval: 2000 }`。
- **`CGPADDR` 地址查询宽松断言**：地址格式由网络决定，IPv6 地址可能是**十进制点分字节格式**（如 `36.9.141.112.4.20...`，对应 `2409:...`），**不含冒号**。不要用"含冒号"判 IPv6，会误判。只断言返回非空地址行即可。
- **PDP 类型按实测卡调整**：缺陷报告写的 `CGDCONT=0,IPV4V6,`（双栈）**不能照搬**——某些卡在双栈下分不到 IPv6 地址（IPv6 字段全 0），需改纯 `IPV6` 才能分配。若 setup 卡在地址获取，优先排查 PDP 类型。
- **setup 首步 `ATE0` 加 `retry`**：串口刚打开有残留数据/时序抖动，首条指令可能偶发失败。加 `retry: { count: 3, interval: 300 }` 兜底。
- **`CGDCONT` 第三段 APN 常可留空**：由模组自动获取，不必 env 化、不必照搬缺陷报告的具体值。

### 5. 设计断言（bug 反向断言）

steps **只含触发指令**（单一职责），断言两条线：

```yaml
steps:
  - command: AT+HTTPCON=0       # 触发指令
    timeout: 45                 # 文档说最大响应 40s，留余量
    assert:
      - { name: 修复后正确响应, matches: '^\r\nOK\r\n$' }      # 文档定的成功格式
      - { name: 回归-不再CONNECT_FAILED, not_contains: "CONNECT FAILED" }  # bug 错误码
      - { name: 回归-不再HTTP_ERROR, not_contains: "+HTTP ERROR" }
```

要点：
- 修复后正确响应：据步骤 3 查到的文档格式写严格断言。
- bug 错误码不再出现：用 `not_contains`，把缺陷现象日志里的错误码逐条反向断言。
- 若 bug 未修复：触发指令返回错误码（非 OK 终结），框架空等 timeout 后断言跑——`matches OK` 不通过 + `not_contains` 也失败 → 用例 FAIL，捕获缺陷。

**缺陷报告的执行步骤/参数不能照搬**——它是 bug 复现路径，可能含 bug 触发所需的特殊配置（如错误的 PDP 类型）。回归用例要用"正确配置 + 触发指令"验证修复后的正常行为。

### 6. 命名 + teardown

- 文件名：`<功能块>-<指令>-REGRESS-<BUGID>.yaml`。
- teardown 必须双层资源清理（见 SKILL.md「双层资源清理陷阱」）：连接层（HTTPCLOSE/MQTTDISCONNECT）+ 实例层（HTTPDESTROY/MQTTDESTROY），都加 `on_failure: continue`。
- 恢复 PDP 上下文为项目默认（通常 `AT+CGDCONT=0,IP,`）。

### 7. 输出问题报告字段填充

回归用例交付时，同步生成问题报告字段填充文档（markdown），含：

| 字段 | 来源 |
|---|---|
| 前置条件 | 从 bug 报告"前置条件"提取 + 补充实测所需（SIM/网络覆盖/服务器可达） |
| 执行步骤 | setup + steps 的指令序列，表格化 |
| 预期结果 | 文档定的正确响应（修复后应出现的） |
| 实测结果（修复前） | bug 报告的缺陷现象日志原文 |
| 实测结果（修复后） | 步骤 5 断言的成功响应 |
| 回归判定标准 | 修复后正确响应出现 + bug 错误码消失 = 通过 |

## 回归专项陷阱清单（实战提炼）

| 陷阱 | 现象 | 对策 |
|---|---|---|
| 同步指令误用 `wait_urc` | 触发指令步骤等满 timeout 失败 | 查文档定同步/异步；同步用 `matches OK`，绝不加 `wait_urc`（见 SKILL.md） |
| 注网未完成就读地址 | CGPADDR 返回全 0 | 用 `CEREG?` 轮询确认注网后再查地址 |
| 地址格式误判 | 用"含冒号"判 IPv6 失败 | 地址可能是十进制点分字节格式，宽松断言 |
| 双栈 PDP 分不到 IPv6 | IPv6 地址全 0，建链失败 | 按实测卡调整 PDP 类型（双栈→单栈） |
| env 变量未替换 | 创建指令 0.0ms FAIL，命令含 `{{}}` | 便携版 GUI 加载 `_internal/` 下的 env，两份都要改 |
| setup 首步 ATE0 偶发失败 | 31ms 不匹配 | 首步加 `retry` 兜底串口抖动 |
| 资源清理不完整连锁污染 | 某用例创建指令 5s 无响应，前后正常 | teardown 双层清理（连接+实例），见 SKILL.md |
| 缺陷报告步骤照搬 | setup 卡在某步 | 报告是复现路径非正确路径，参数按实测调整 |

## 完整示例（节选）

```yaml
# 文件名：HTTP-HTTPCON-REGRESS-BUG1234567890.yaml
name: HTTPCON-IPv6 HTTPS连接成功(回归6689722922)
description: |
  场景前提：需 IPv6 基站覆盖的 SIM 卡 + 已注网。CGDCONT=0,IPV6, 配 IPv6 单栈，
    CEREG 确认注网，HTTPCREATE 创建 HTTPS 实例。
  验证目标：回归缺陷 6689722922【HTTPS】不支持 ipv6 的https。修复后 HTTPCON 返回 OK，
    不再出现 +HTTP ERROR: CONNECT FAILED。
  文档依据：据应用笔记 3.6.2，HTTPCON 是同步指令，成功直接返回 OK。
tags: [HTTP, HTTPCON, REGRESS, p0, ipv6]
setup:
  - command: ATE0
    retry: { count: 3, interval: 300 }      # 首步兜底
    assert: { matches: '^\r\nOK\r\n$' }
  - command: AT+CGATT=0
    assert: { contains: "OK" }
  - command: 'AT+CGDCONT=0,IPV6,'           # 纯单栈，不照搬报告的双栈
    assert: { matches: '^\r\nOK\r\n$' }
  - command: AT+CGATT=1
    assert: { contains: "OK" }
  - command: AT+CEREG?                       # 注网判断
    retry: { count: 30, interval: 2000 }
    extract: { cereg_stat: '\+CEREG:\s*\d+,(\d)' }
    assert:
      - { name: 注网成功, var: cereg_stat, op: in, values: ["1", "5"] }
  - command: 'AT+HTTPCREATE=0,{{http.https_ipv6_url}}'   # env 引用
    assert: { contains: "+HTTPCREATE:" }
steps:
  - command: AT+HTTPCON=0                    # 触发指令，同步，无 wait_urc
    timeout: 45
    assert:
      - { name: HTTPCON成功, matches: '^\r\nOK\r\n$' }
      - { name: 回归-不再CONNECT_FAILED, not_contains: "CONNECT FAILED" }
      - { name: 回归-不再HTTP_ERROR, not_contains: "+HTTP ERROR" }
teardown:
  - command: AT+HTTPCLOSE=0                  # 连接层
    timeout: 3
    on_failure: continue
  - command: AT+HTTPDESTROY=0                # 实例层
    timeout: 6
    on_failure: continue
  - command: AT+CGATT=0
    on_failure: continue
  - command: 'AT+CGDCONT=0,IP,'              # 恢复默认
    on_failure: continue
```
