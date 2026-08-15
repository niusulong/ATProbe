# 新平台/芯片从零起步指南

> 当目标平台是**全新的模组/芯片**（无既有用例，如换厂商、换型号 EC616→EC626、N58→新平台）时读本文件。
> 本文件是「从无到有」为陌生平台生成用例的结构化流程——先把平台的指令集与响应规律勘测清楚，
> 再走主流程（SKILL.md 步骤 1→4）按矩阵生成用例。
>
> 核心矛盾：skill 的严格断言依赖「目标平台响应规律」，但新平台规律未知。解决：先勘测、再生成。

## 何时读本文件

| 情形 | 走什么 |
|---|---|
| 已有平台（N58/EC616…）追加新指令章节 | 走 SKILL.md 主流程（步骤 1→4），查 `response-patterns.md` 对应平台小节 |
| **全新平台**，无任何勘测记录 | **读本文件**，先完成响应勘测，再走主流程 |
| bug 回归 | 走 SKILL.md 步骤 3'（`regression-design.md`），回归用例本身会带勘测 |

## 新平台起步 5 步

### 1. 确认指令集文档来源

新平台的 AT 指令手册是断言的唯一事实源。确认：
- 文档路径/格式（`docs/at-ref/`、厂商 PDF、在线 wiki…）。
- 文档版本与目标固件版本匹配（固件升级可能改响应格式）。
- 是否区分 3GPP 标准指令（跨平台一致）与厂商扩展指令（平台特定）。

**3GPP 标准指令**（TS 27.007/27.005）几乎所有模组一致，可直接参照通用规律（见
`response-patterns.md` 第一部分）：`AT`/`ATE`/`AT+CSQ`/`AT+CPIN`/`AT+CEREG`/`AT+CGATT`/
`AT+CGDCONT`/`AT+CMGS`/`AT+CMGR` 等。**厂商扩展指令**（TCP/HTTP/MQTT/FTP/SSL 等）各平台不同，
必须逐条查文档。

### 2. 响应勘测（最关键，沉淀知识资产）

按 `response-patterns.md`「新平台响应勘测起步流程」实测，重点确认四类响应的字节细节：

1. **OK 终结成功**：数据行格式（`+CMD:` 后几个空格？字段分隔符？引号包裹规则？）
2. **业务码**：不以 OK 终结的指令结果（建链失败/发送失败等），格式与 timeout 必要性。
3. **错误码**：该平台用 CME / CMS / 通用 ERROR？参数错对应哪个码？指令不识别对应哪个码？
4. **同步/异步**：每条长耗时指令（建链/拨号/创建实例）成功是直接 OK 还是 OK+URC？

> 勘测结果**沉淀回 `response-patterns.md` 第二部分**（新增 `<平台>` 小节）。这是后续所有用例断言的依据，
> 也是 skill 跨项目复用的核心知识。

### 3. 建 env 参数表

读新平台指令手册，按业务域（网络/TCP/HTTP/MQTT/FTP/…）整理 env 参数清单：
- 已有业务的参数（见 `env-params.md`）大概率复用，但要**核对字段名/取值范围是否与新平台一致**。
- 新平台独有的业务/字段，在 `env-params.md` 加 `<新业务>.<字段>` 或在现有组追加。
- 服务器地址/端口：若工作区有本地集群清单（`references/server-cluster.local.md`，不入库），直接用其中默认值；
  无则留 `<占位>`。

把整理结果补到项目 `env.yaml`（真实值）与 `env-params.md`（清单）。

### 4. 确定平台目录与首批功能块

- **平台目录名**：用模组型号或芯片平台名（全大写，如 `N58`/`EC616`/`EC626`）。
  所有该平台用例放 `testcases/<平台>/<功能块>/` 下。
- **首批功能块优先级**：先覆盖基础类（几乎必测），再覆盖业务类。
  1. **网络注册**（3GPP 标准，跨平台）：CEREG/CGATT/CGDCONT/CPIN/CSQ —— 通用指令，参考已有
     `examples/testcases/3gpp/network/`。
  2. **基础查询**（ATI/CGMM/CGSN/GMR）：模组身份与版本。
  3. **平台核心业务**（按目标用途）：数据模组先 TCP/UDP；物联网先 MQTT/HTTP；定位先 GNSS。
  4. **扩展业务**：SMS/FTP/SSL/低功耗/OTA 等按需求。

### 5. 走主流程生成首批用例 + 验证

- 回到 SKILL.md 步骤 1→4，按 `testcase-matrix.md` 矩阵逐指令生成。
- 生成后跑 `scripts/validate-cases.py`（校验 schema/正则/env 引用/文件名）。
- 首批用例上设备实测，**校准断言**：实测响应与断言不符时，修正正则（通常是要改空格数/码值），
  并把校准结果同步回 `response-patterns.md` 该平台小节。

## 平台勘测最小用例（模板）

新平台首日用，确认串口通 + 基础指令可达。可作为 `testcases/<平台>/base/` 的起步用例：

```yaml
# 文件名：<平台>/base/BASE-AT-RESP-ECHO_OFF.yaml （功能块用 BASE，非标准业务）
name: AT-基础连通与回显关闭
description: |
  场景前提：模组上电、串口已连。
  验证目标：AT 返回 OK（串口通）；ATE0 关回显返回 OK（后续断言无需处理回显前缀）。
  文档依据：3GPP TS 27.007，AT 与 ATE0 为通用指令。
tags: [BASE, AT, RESP, p0]
port: COM5
steps:
  - command: AT
    assert: { matches: '^\r\nOK\r\n$' }
  - command: ATE0
    assert: { matches: '^\r\nOK\r\n$' }
```

> 若实测响应含回显前缀（如 `AT\r\nOK\r\n`），说明 ATE0 未生效或该固件强制回显——
> 此时断言需改为 `matches: 'AT\r\nOK\r\n$'` 或在 setup 重复发 ATE0。

## 常见新平台陷阱

| 陷阱 | 现象 | 对策 |
|---|---|---|
| 文档版本与固件不符 | 断言按文档写但实测不符 | 确认固件版本；必要时用实测覆盖文档描述 |
| CME 码语义不同 | 参数错在某平台返 53、另一平台返 3 | 逐平台勘测，记入 `response-patterns.md` 该平台小节 |
| 冒号后空格数不同 | `+CMD:`后 0/1/多空格，不同指令不同 | 逐指令实测，不假设统一 |
| 强制回显固件 | ATE0 后仍回显指令 | 断言包含回显前缀，或 setup 重复 ATE0 |
| 厂商扩展指令同名不同义 | 如 `AT+HTTPACTION` 各平台参数/响应不同 | 不跨平台照搬，逐条查文档 |
| 错误用 CMS 而非 CME | SMS 类指令错返 `+CMS ERROR` | SMS 类断言查 `+CMS ERROR`，见 `response-patterns.md` |
| 持续性主动上报（GPS 循环输出、心跳广播等） | URC 行插队在命令应答前混入响应文本，严格字节级断言偶发失败 | atprobe.yaml 配 `urc_filter`（行正则）剥离噪声行；URC 事件仍照常派发，`wait_urc` 目标行不受影响（优先级豁免，见 SKILL.md 异步指令陷阱） |

## 勘测产物清单（新平台起步完成的标志）

- [ ] `response-patterns.md` 新增 `<平台>` 小节（数据行/业务码/错误码/同步异步四类）
- [ ] `env-params.md` / `env.yaml` 含新平台所需 env 参数
- [ ] `testcases/<平台>/` 至少有 base + network 功能块首批用例
- [ ] 首批用例 `validate-cases.py` 通过 + 至少 base 用例上设备实测绿
