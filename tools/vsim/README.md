# 虚拟串口测试（无开发板联调）

手上没有实板时，有两种方式跑通 ATProbe 完整链路（M1 串口 → M3 引擎 → M4 报告）：

- **方式一（推荐，零驱动）**：CLI 加 `--vsim`，进程内虚拟模组直接驱动引擎，**无需 com0com / 开发板**。
- **方式二（真实串口字节流）**：虚拟串口对（com0com / socat）+ `at_responder.py` 守一端。

本目录提供：

- `at_responder.py` —— 虚拟 AT 模组应答器（方式二：守虚拟串口对的一端）
- `selftest.py` —— 应答器逻辑自检（**不需要任何串口/驱动**，先跑它确认逻辑对）

> 应答状态机逻辑（`AtResponder`）在库内 `src/atprobe/infra/serial/atresponder.py`，
> 方式一（`VsimPortManager`）与方式二（`at_responder.py`）共用同一份事实源。

---

## 方式一：`--vsim` 进程内模式（推荐，零依赖）

最快：一行命令跑通用例，不装任何驱动、不开第二个终端。

```bash
# network 用例（含 AT+CSQ 信号断言、AT+CEREG? 注册断言）
uv run atprobe run examples/testcases/network/network-basic_register.yaml --vsim

# 压测用例（循环发 AT，统计响应时间分布）
uv run atprobe run examples/testcases/stress/stress-loop_at.yaml --vsim

# 故意制造 FAIL：rssi=5 < 10，network 用例的「信号合格」断言会失败
uv run atprobe run examples/testcases/network/network-basic_register.yaml --vsim --vsim-rssi 5
```

参数：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--vsim` | off | 启用进程内虚拟模组，忽略 `--port` / 配置端口，统一用虚拟端口 `VSIM0` |
| `--vsim-rssi` | 23 | CSQ 信号 0..31（network 用例断言 >=10） |
| `--vsim-cereg` | 1 | CEREG 状态 0..5（1=已注册） |

原理：`Engine(sender_factory=...)` 注入 `VsimPortManager`，它实现和真 PortManager
一致的接口，但 `send_command` 不走硬件，直接调 `AtResponder.respond()` 生成响应。
所以提取器、断言、压测、报告全链路真实运转，只是字节不经过串口。

---

## 方式二：虚拟串口对 + `at_responder.py`（测真实字节流）

适合要验证 pyserial 字节流读写、URC 分流、重连等 M1 串口层细节时。

### 原理

```
   ┌─────────────┐    AT 指令     ┌──────────────┐    AT 响应     ┌──────────────┐
   │   ATProbe   │ ─────────────▶ │  虚拟串口对  │ ─────────────▶ │   ATProbe    │
   │ (连 COM20)  │                │ COM20<->COM21│                │   (收响应)   │
   └─────────────┘ ◀───────────── └──────────────┘ ◀───────────── └──────────────┘
                       AT 响应            ▲                                ▲
                                          │  AT 指令                       │
                                  ┌───────┴───────┐                ┌───────┴───────┐
                                  │ at_responder  │                │ at_responder  │
                                  │  (守 COM21)   │                │  (生成响应)   │
                                  └───────────────┘                └───────────────┘
```

`at_responder.py` 读取 ATProbe 发来的指令，按真实模组帧格式回包（正文行 +
`OK`/`ERROR` 结尾，每行 `\r\n`），帧格式与 ATProbe `connection.py` 终结符识别严格对齐。

### 第一步：跑自检（确认应答器逻辑正确）

不需要任何驱动：

```bash
uv run python tools/vsim/selftest.py    # 期望：全部通过 ✓
```

### 第二步：装虚拟串口对

**Windows（com0com）**：

⚠️ **重要前提——VBS/HVCI 必须关闭**。Windows 11/26200 默认启用 VBS（虚拟化安全）+ HVCI，
强制内核驱动必须 EV 代码签名。com0com 的驱动**不是 EV 签名**，会被拒绝加载
（设备管理器显示 Problem Code 39 = `CM_PROB_DRIVER_FAILED_LOAD`），表现为端口对能
创建但 pyserial 枚举不到、也打不开。

检查是否启用 VBS（管理员 PowerShell）：
```powershell
(Get-CimInstance -ClassName Win32_DeviceGuard -Namespace root\Microsoft\Windows\DeviceGuard).VirtualizationBasedSecurityStatus
# 0=关, 2=开。若为 2，需按下面关闭。
```

关闭 VBS + 开测试签名（**管理员 cmd，改完重启**）：
```bat
reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard" /v EnableVirtualizationBasedSecurity /t REG_DWORD /d 0 /f
reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard" /v RequirePlatformSecurityFeatures /t REG_DWORD /d 0 /f
reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity" /v Enabled /t REG_DWORD /d 0 /f
bcdedit /set testsigning on
bcdedit /set nointegritychecks on
:: 重启电脑
```

> 重启后桌面右下角会有「测试模式」水印，正常。若公司策略禁止关 VBS，改用方式一（`--vsim`）。

装好驱动并重启后，创建端口对（管理员 cmd）：
```bat
:: com0com 的 setupc 硬编码找 System32\com0com.inf，需先把 INF 复制过去（设计缺陷）
copy /Y "C:\Program Files (x86)\com0com\com0com.inf" C:\Windows\System32\com0com.inf
copy /Y "C:\Program Files (x86)\com0com\com0com.cat" C:\Windows\System32\com0com.cat
"C:\Program Files (x86)\com0com\setupc.exe" install PortName=COM20 PortName=COM21
"C:\Program Files (x86)\com0com\setupc.exe" change CNCA0 EmuBR=yes
"C:\Program Files (x86)\com0com\setupc.exe" change CNCB0 EmuBR=yes
"C:\Program Files (x86)\com0com\setupc.exe" list
```

如果 `setupc install` 报 `UpdateDriverForPlugAndPlayDevices ERROR: 2`，用 pnputil 接管
驱动安装（比 setupc 自带的旧逻辑可靠）：
```bat
pnputil /add-driver "C:\Program Files (x86)\com0com\com0com.inf" /install
"C:\Program Files (x86)\com0com\setupc.exe" --no-update install PortName=COM20 PortName=COM21
"C:\Program Files (x86)\com0com\setupc.exe" update
pnputil /scan-devices
```

**Linux / macOS（socat）**：

```bash
socat -d -d pty,raw,echo=0,link=/tmp/vcom0 pty,raw,echo=0,link=/tmp/vcom1
# /tmp/vcom0 给 ATProbe，/tmp/vcom1 给 at_responder
```

### 第三步：联调

**终端 A** —— 应答器守 COM21：

```bash
uv run python tools/vsim/at_responder.py COM21
#   --rssi 23          CSQ 信号（network 用例断言 >=10）
#   --cereg 1          CEREG 状态（1=已注册）
#   --baud 115200      波特率（与 ATProbe 端一致）
#   --urc-interval 5   每 5s 随机上报 URC（测 M1 URC 分流，0=关）
```

**终端 B** —— ATProbe 连 COM20（先把 `examples/atprobe.yaml` 端口改成 COM20）：

```bash
uv run atprobe run examples/testcases/network/network-basic_register.yaml --port COM20
uv run atprobe gui    # 或开 GUI 手动调试
```

---

## 应答器覆盖的指令

| 指令 | 应答 | 说明 |
|------|------|------|
| `AT` | `OK` | 基础连通 |
| `ATI` | 产品信息 + `OK` | 模组标识 |
| `AT&V` | 产品信息 + `OK` | 别名到 ATI（产品信息） |
| `AT+CSQ` / `AT+CSQ?` | `+CSQ: <rssi>,99` + `OK` | rssi 可配，默认 23 |
| `AT+CEREG?` | `+CEREG: <n>,<stat>` + `OK` | stat 可配，默认 1=已注册 |
| `AT+CEREG=<n>` | `OK`（置位上报开关 n，状态被记忆） | 写指令，影响后续 `AT+CEREG?` 的 n |
| `AT+CPIN?` | `+CPIN: READY` + `OK` | SIM 就绪 |
| `AT+CGDCONT?` | 多行 PDP 上下文 + `OK` | |
| `AT+CGDCONT=` | `OK` | 写指令（占位） |
| `AT+CGATT?` | `+CGATT: 1` + `OK` | 已附着 |
| `AT+CGATT=` | `OK` | 写指令（占位） |
| `AT+CMGF=` | `OK`（cmgf 模式被记忆） | 写指令，状态持久（0=PDU/1=文本） |
| `AT+CNMI=` / `AT+CFUN=` / `AT+CGACT=` | `OK` | 占位 |
| `ATZ` / `ATE0` / `ATE1` / `AT&W` | `OK` | 常规 |
| 其他未知 | `ERROR` | |

> 应答状态机的单一事实源：`src/atprobe/infra/serial/atresponder.py`（`AtResponder._handlers`）。
> `tools/vsim/at_responder.py` 仅是同一状态机的 CLI 包装。

---

## 扩展应答器

新增指令：编辑 `src/atprobe/infra/serial/atresponder.py` 的 `AtResponder`：

1. 在 `_handlers` 字典加键（精确指令如 `AT+XXX?`，或写指令前缀如 `AT+XXX=`）。
2. 加 `_h_xxx(self, cmd) -> list[str]` 方法，返回正文行（不含 OK/ERROR）。

分发规则：精确匹配优先；否则按前缀长度降序匹配（最长最具体者优先）；
裸指令 `AT`/`ATI`/`ATZ` 只精确匹配、不作前缀，避免吞掉 `AT+` 指令。

