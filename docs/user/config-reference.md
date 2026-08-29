# ATProbe 配置文件完全参考

> 适用对象：ATProbe 用户（CLI / GUI）。本文是两份配置文件的完全参考：
> `atprobe.yaml` 管**工具行为**，`env.yaml` 管**测试环境事实**。
> 事实来源：`infra/config/appconfig.py`（atprobe.yaml 键的权威实现）、
> `infra/serial/config.py`（串口默认值）、`docs/requirements/REQ-M7-测试环境配置.md`（env.yaml 行为）。

## 1. 配置体系总览

两份文件各管一件事，互不重叠：

| 文件 | 角色 | 承载内容 | 生命周期 |
|---|---|---|---|
| `atprobe.yaml` | 工具行为 | 端口列表、步骤超时、日志级别、目录布局、控制台显示、压测阈值、噪声 URC 过滤 | 每次启动加载 |
| `env.yaml` | 测试环境事实 | 设备指纹（型号/IMEI）、FTP/HTTP/TCP/MQTT 服务器地址与账号、FOTA 版本、号码等 | 引擎会话开始一次性快照，会话内只读 |

所有可变参数遵循同一条优先级链（高 → 低）：

```text
命令行参数  >  配置文件（atprobe.yaml / env.yaml）  >  内置默认值
```

示例：`--port COM5:9600:8N1` 覆盖 `ports:` 列表；未给 `--port` 时才读 `ports:`；
`ports:` 未提供时用内置默认（波特率 115200、帧格式 8N1）。同理 `--env-config`
覆盖 `env_config:` 指定的 env.yaml——命令行项永远是最高优先级。

## 2. 配置文件定位（atprobe.yaml）

启动时按以下顺序查找 atprobe.yaml，命中即停：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | `--config <PATH>` | 命令行显式指定 |
| 2 | 打包态 exe 同级 | 打包发行时与可执行文件同目录的 atprobe.yaml |
| 3 | 当前工作目录（cwd） | 开发态在仓库根直接运行时的常用位置 |

- 文件不存在 → 静默使用内置默认值，不报错（空文件 / `---` 同样得到全默认值）。
- YAML 语法错误 → 错误消息带行号（`YAML 语法错误（第 N 行）：...`）。
- 值非法（如 `step_timeout: abc`、`ports` 非列表、帧格式非法）→
  统一收敛为 `AppConfigError`，CLI 以 **exit 2** 退出，不出现 traceback。
- 根节点必须是映射；写成列表/标量 → 报「配置根节点必须是映射」。

## 3. atprobe.yaml 逐字段详解

### 3.1 字段速查表

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `ports` | 字符串列表 | `[]` | 默认端口列表（`--port` 未指定时使用） |
| `default.step_timeout` | 数值（秒） | `5` | 步骤级默认超时 |
| `default.baud` | 整数 | `115200` | 默认波特率（回填省略波特率的端口表达式，见 §3.2） |
| `default.log_level` | 字符串 | `progress` | `progress` / `debug` 两种 |
| `cases_dir` | 字符串 | `./examples/testcases` | 不提供用例路径时的默认加载目录 |
| `report_dir` | 字符串 | `./reports` | HTML 报告输出目录 |
| `env_config` | 字符串 | `./examples/env.yaml` | 测试环境配置文件路径（第 4 章） |
| `console.color` | bool | `true` | 控制台彩色输出；非终端环境自动忽略 |
| `console.command_truncate` | 整数 | `40` | 控制台命令显示截断长度（字符） |
| `log.dir` | 字符串 | `./logs` | 原始日志根目录（按会话留存，手动清理） |
| `pressure.pass_rate_threshold` | 数值（%） | `95` | 压测用例 PASS 的成功率阈值 |
| `urc_filter` | 字符串列表 | `[]` | 噪声 URC 过滤正则（§3.8 重点） |
| `mcp.host` | 字符串 | `127.0.0.1` | MCP serve 监听地址；默认故意回环（最小暴露面），远程访问需显式 `0.0.0.0` |
| `mcp.port` | 整数 | `8470` | MCP serve 监听端口 |
| `mcp.token_file` | 字符串 | 不设置 | serve 形态的 Token 文件（可选；Token 四级优先级的第 4 级） |
| `mcp.allowed_roots` | 字符串列表 | `[]` | MCP 路径参数（用例/套件/data 文件）的白名单根目录（§3.9）；空 = 仅 cases_dir |
| `update.allowed_hosts` | 字符串列表 | `[]` | 更新下载 URL 的 host 追加白名单（§3.10）；空 = 仅内置 GitHub 域 |

注意：`log.keep`（日志保留份数）字段**已移除**——它从未接入任何清理逻辑，
写进文件会被静默忽略；日志目录按会话留存，需手动清理。

`mcp.*` 四键仅 `serve` 形态消费（`stdio` 形态忽略），命令行
`--host`/`--port`/`--token-file` 优先于配置；详见 `mcp-guide.md` §4.2/§7。

`mcp.allowed_roots` 是**管理员语义的显式扩权**：判定按「路径在根目录树内」
（`is_relative_to`），配置父目录即放行整棵子树——配 `D:\` 等于全盘可达。
始终配置**最小必要目录**（如共享用例库的根），不要图省事配大盘符根。

### 3.2 ports：复合端口表达式

列表每项是一个字符串——冒号分隔的复合表达式（与 `--port` 同一语法）：

```yaml
ports:
  - COM3:115200:8N1
```

三段解析规则：

| 段 | 内容 | 省略规则 |
|---|---|---|
| 第 1 段 | 端口名：`COM3`、`/dev/ttyUSB0` 等 | 必填；空白 → 报「端口表达式无效」 |
| 第 2 段 | 波特率（整数） | 可省略或留空 → 115200；非整数报「波特率无效」 |
| 第 3 段 | 帧格式（紧凑写法，如 `8N1` / `8N1.5`） | 可省略或留空 → `8N1`；非法报「帧格式无效」 |

合法写法示例：

| 表达式 | 实际效果 | 说明 |
|---|---|---|
| `COM3:115200:8N1` | 115200 / 8N1 | 全参显式（推荐） |
| `COM3:9600` | 9600 / 8N1 | 帧格式段省略 |
| `COM3` | default.baud / 8N1 | 无冒号段，波特率由 default.baud 回填 |
| `COM3::7E1` | 115200 / 7E1 | 波特率段留空 → 保留内置 115200，不回填 |

**default.baud 回填规则**：仅当端口表达式**完全不含冒号**（未显式给波特率）
时，用 `default.baud` 填充该端口波特率。例：`default.baud: 9600` 时
`ports: ["COM3"]` 实际按 9600 连接；而 `"COM3:115200"` 与 `"COM3::8N1"`
都含冒号，不受影响仍按 115200。未配置 `default.baud` 时，无冒号表达式按
内置 115200。

### 3.3 default：全局默认块

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `step_timeout` | 数值（秒） | `5` | 单步骤默认超时；用例可逐步覆盖 |
| `baud` | 整数 | `115200` | 默认波特率；回填规则见 §3.2 |
| `log_level` | 字符串 | `progress` | 控制台输出详略 |

`log_level` 两种级别的输出差异：

- `progress`（默认）：进度级——用例/套件的开始与结果、失败摘要等高层信息，
  输出简洁，日常运行使用。
- `debug`：调试级——额外输出逐步骤的命令交互细节与内部事件，用于定位步骤
  失败、时序等问题，输出量大。

### 3.4 cases_dir / report_dir / env_config：相对路径的工作区锚定

三个路径字段遵循同一规则：**绝对路径原样使用；相对路径锚定到工作区根**——
打包态为 exe 同级目录，开发态为仓库根，而不按 cwd 解析。因此示例中的
`./examples/testcases`、`./examples/env.yaml` 在打包态能命中随工具外露的
examples 目录副本，在开发态命中仓库内同名目录。

`env_config` 解析后的路径**存在才加载**；不存在 → 静默降级为「无环境配置层」
（env=None），不报错，代价是 `{{group.param}}` 占位符全部无法替换（§4.6）。

### 3.5 console：控制台显示

| 键 | 默认 | 说明 |
|---|---|---|
| `color` | `true` | 结果/错误着色；重定向到文件等非终端环境自动忽略，不会出乱码。**必须是裸布尔**——`"false"`（带引号）会报配置错误（防字符串被强转为真） |
| `command_truncate` | `40` | 控制台显示 AT 命令的截断长度；过长命令截断显示，日志文件仍完整 |
| `mask_credentials` | `false` | 凭据脱敏（v0.10+）：开启后呈现层（控制台/HTML 报告/GUI 进度/MCP 事件）掩 `AT+CPIN=`/`AT+CPINW=`/`AT+CPWD=`/`AT+CLCK=` 的参数段为 `****`；**rawlog 原始字节日志不掩**（字节核对用途）。须为裸布尔（同 `color`） |

### 3.6 log：原始日志

| 键 | 说明 |
|---|---|
| `dir`（默认 `./logs`） | 原始串口日志根目录，按会话留存；无自动清理，手动删除 |

（`keep` 字段已移除，见 §3.1 注。）

### 3.7 pressure：压测默认值

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `pass_rate_threshold` | 数值（%） | `95` | 压测用例 PASS 判定阈值：成功率 ≥ 该值判 PASS |

### 3.8 urc_filter：噪声 URC 过滤（重点）

**解决的问题**：部分设备存在持续性主动上报（URC）。典型如 Neoway N58 开启
GPS 循环输出（`AT$MYGPSPOS=<TYPE>,1`）后，`$MYGPSPOS:...` 行每秒主动到达
AT 口。这些行插队在命令应答之前/之间，混入交付给断言的响应文本，使严格
字节级断言（首行 equals、contains 位置等）误判失败。

**配置形式**（正则字符串列表，作用于所有端口）：

```yaml
urc_filter:
  - '^\$MYGPSPOS:'
```

**精确语义**：

1. 匹配方式：对 **strip 后的整行内容**做 `re.search`——正则不必覆盖整行，
   行首锚定 `^` 由使用者按需控制。
2. 命中行的两条去向（关键：**URC 事件不丢失**）：
   - 照常派发给 URC 订阅者——wait_urc 监控、URC 统计不受影响；
   - 从**交付给断言的响应文本**中**整段剥离**（连同紧邻空行），字节级还原
     该命令应答的原始样貌。
3. 默认空列表 = 不剥离（存量行为；URC 行仍按前缀识别正常派发）。
4. 列表项必须是字符串，否则加载报 `'urc_filter' 必须是字符串列表`；正则
   编译合法性在连接构造时统一校验，非法正则在连接阶段报错。

**wait_urc 目标行豁免**：用例步骤 `wait_urc` 声明的**目标行不受 filter
影响**——逐命令的期待响应声明优先于全局噪声声明。因此即使 `^\$MYGPSPOS:`
在 filter 中，`AT$MYGPSPOS=0,1` 循环上报用例仍可照常 wait_urc 并断言目标行。

**完整示例**（真机 GPS 循环上报开启时，见 `examples/atprobe-com5.yaml`）：

```yaml
ports:
  - COM5:115200:8N1          # Neoway N58 真实模组，USB-TTL
urc_filter:
  - '^\$MYGPSPOS:'           # 剥离每秒到达的 GPS 行；URC 事件仍照常派发
```

### 3.9 mcp.allowed_roots：MCP 路径白名单（S-8/S-3）

MCP 工具（list_cases / start_run 等）接受客户端传入的路径参数，安全边界 =
「cases_dir ∪ mcp.allowed_roots」。白名单外路径返回 INVALID_INPUT：

```yaml
mcp:
  allowed_roots:
    - D:\shared-testcases   # 共享用例库根；渲染后的 data 文件路径也受此约束
```

- 空（默认）= 仅 `cases_dir` 可达；
- 每个根**按整棵目录树**放行（路径 `is_relative_to` 判定）——配父目录即扩权
  整棵子树，属管理员语义，配最小必要目录（见 §3.1 注）；
- `data` 步骤引用的文件（含 `{{file_size()}}`）同样受此白名单约束——不可信
  用例不能借 MCP 通道读取白名单外文件。

### 3.10 update：更新下载白名单（S-5/S-6）

应用内更新（CLI `atprobe update` / GUI 检查更新）的下载 URL 强制 HTTPS 且
host 必须在白名单内（防重定向降级到任意识别域）。内置白名单覆盖 GitHub
Release 全链路（github.com、objects.githubusercontent.com、github-releases.
githubusercontent.com、api.github.com）；自建镜像/代理时追加：

```yaml
update:
  allowed_hosts:
    - mirrors.example.com    # 追加（不收窄内置白名单）；必须是 https 可达的 host
```

CLI 侧用 `atprobe update --config <path>` 指定配置文件（定位规则与 run/list
一致：显式 --config > 打包态 exe 同级 > cwd）。发布包完整性另有 minisign
签名校验（`docs/user/update-signing.md`），本段只管 host 白名单。

## 4. env.yaml 完全说明

### 4.1 定位

env.yaml 承载**跨用例共享的全局只读配置**——「环境事实」：设备指纹
（型号/IMEI/软件版本）、FTP/HTTP/TCP/MQTT/云平台服务器地址与账号、FOTA
版本号、短信中心与目标号码等。它区别于用例级变量池（extract 提交值/参数化
注入，随用例生灭）：一次引擎会话内为**同一不可变快照**，suite_setup、
各用例、suite_teardown 全部共享同一实例。

### 4.2 结构与值类型

单一全局文件，**两级 group.param 映射**：顶层键 = 组（职责域），组内扁平
键值对；不支持嵌套组。组与参数名由用户自定义，无 schema 约束，可任意增删。

| 规则 | 合法 | 非法（抛 `EnvConfigError`） |
|---|---|---|
| 根节点 | 映射；空文件 / `---` → 空配置 | 列表根、标量根 |
| 组值 | 映射（键值对） | 标量（如 `ftp: not-a-map`） |
| 参数值类型 | `str / int / float / bool` | 嵌套 dict、list、null |
| 组名/参数名 | 字符串 | 非字符串键 |

值转字符串规则（渲染前归一）：bool → `true`/`false`；整数值的 float →
整数形式（`2.0`→`2`）；其余按 `str()`。

**号码/端口类值建议加引号存为字符串**：`port: '8080'`、`imei: '000...'`、
`dest_number: '13800138000'`——避免 YAML 将长数字解析为 int/float 后丢精度
或变形（如以 0 开头的号码、超长 IMEI）。

`examples/env.yaml` 提供 18 个组的完整样例：`pdp`、`dns`、`tcp`、
`tcp_server`、`ssl`、`http`、`ftp`、`ntp`、`mqtt`、`aliyun`、`aws`、
`ctwing`、`pipecloud`、`fota`、`sms`、`netshare`、`device`、`default`。

### 4.3 default 组的特殊性

`default` 组是**简单名占位符 `{{param}}` 的回退查找域**：简单名未命中用例
变量池时，只在 default 组内查找，**不搜索其它组**。适合放跨域通用兜底值
（如 `default.apn: cmnet`——用例写 `{{apn}}` 且未定义同名变量时取此值）。

### 4.4 占位符语法与查找优先级

占位符正则 `{{\s*name\s*}}`（花括号内允许空白）。两类名字查找路径不同：

| 占位符 | 查找顺序 | 边界 |
|---|---|---|
| 点号名 `{{group.param}}` | **仅查环境配置**对应组的对应参数 | 不被 extract/用例变量覆盖；三级以上路径（`a.b.c`）直接拒绝 |
| 简单名 `{{param}}` | ① 用例级变量池（参数化注入、extract 提交值、内置变量 `port`、压测 `loop_index`）② 未命中回退环境配置 **default 组** | 环境配置只兜底 default 组，不搜全部组 |

无环境配置层（env=None）时，点号名一律按未定义处理。

### 4.5 渲染时机（易错点）

| 使用位置 | 是否渲染 | 说明 |
|---|---|---|
| `command` / `data.inline` / `data.file` | **是** | 每步执行前渲染**一次**；retry/poll 各次尝试复用同一渲染结果；压测每轮重新渲染 |
| `when` / `until` 条件（旧写法 `{{var}}`） | 部分 | 求值前只解析**用例变量池简单名**；写 `{{group.param}}` 会报未定义 |
| `assert` 期望值 | **否** | 用**原始字符串**比较（contains/equals/value 等），占位符不替换 |
| `extract` 正则 | **否** | 用**原始正则**匹配响应，占位符不替换 |

两个「否」是最常见的踩坑点：断言期望值与提取正则里写 `{{...}}` 不会被替换，
会按字面量参与匹配。期望值需直接写死，或先用 extract 提取为用例变量、再在
后续步骤的 `command` 中以简单名引用。

失败语义：未定义引用 → `UndefinedReferenceError`，错误消息区分两种情况——
组缺失（列出全部可用组）与组内参数缺失（列出该组可用参数），便于定位拼写
错误。步骤级渲染失败 → 该步 FAIL，错误消息 `模板渲染失败：<详情>`，按该步
`on_failure` 策略（abort/continue/skip）决策，不硬编码中止。

### 4.6 加载、降级与生效时机

| 场景 | 行为 |
|---|---|
| CLI 加载优先级 | `--env-config PATH`（相对路径按 cwd）> atprobe.yaml 的 `env_config`（工作区锚定） |
| 文件不存在 | **静默降级** env=None，不报错；`{{group.param}}` 将无法替换 |
| 文件存在但解析失败 | CLI：stderr 报 `环境配置加载失败：<详情>` 并 **exit 2** |
| 会话内生效时机 | 引擎 start 时一次性加载 frozen 快照；执行期间不可变 |
| GUI 环境页编辑 | 即时同步内存，但正在运行的会话不受影响；下一次执行才生效 |
| 报告留存 | 默认将全部组值写入执行结果的环境快照区；回看历史报告即可复现当时环境事实 |

## 5. 完整带注释示例

### 5.1 atprobe.yaml（真机 COM5，Neoway N58，含 urc_filter）

```yaml
# ATProbe 配置：COM5（Neoway N58 真实模组，USB-TTL）
# 设备特性（探测所得）：默认回显 ON（ATE0 可关）；+CSQ: 10,99；+CPIN: NO SIM；
# GPS 循环上报开启中（AT$MYGPSPOS=<TYPE>,1）：$MYGPSPOS 行每秒主动到达 AT 口。

ports:                           # 默认端口列表（--port 未指定时使用）
  - COM5:115200:8N1              # 端口:波特率:帧格式（三段均可按 §3.2 省略）

urc_filter:                      # 噪声 URC 过滤：剥离 GPS 循环上报行
  - '^\$MYGPSPOS:'               # URC 事件仍照常派发（监控不丢失）；wait_urc 不受影响

default:
  step_timeout: 5                # 步骤级默认超时（秒）
  baud: 115200                   # 默认波特率（回填无冒号的端口表达式）
  log_level: progress            # progress / debug（输出差异见 §3.3）

cases_dir: ./examples/testcases  # 相对路径锚定工作区根（打包态=exe 同级）
report_dir: ./reports            # HTML 报告输出目录
env_config: ./examples/env.yaml  # 测试环境配置（第 4 章）；不存在则静默降级

console:
  color: true                    # 彩色输出；非终端环境自动忽略
  command_truncate: 40           # 控制台命令显示截断长度

log:
  dir: ./logs                    # 原始日志根目录，按会话留存，手动清理（无 keep 字段）

pressure:
  pass_rate_threshold: 95        # 压测用例 PASS 阈值（成功率 %）

mcp:                             # MCP 服务（仅 serve 形态消费，stdio 忽略；见 mcp-guide.md §7）
  host: 127.0.0.1                # serve 监听地址：默认回环，远程访问需显式 0.0.0.0
  port: 8470                     # serve 监听端口
  # token_file: ./mcp-token.txt  # 可选：serve 的第 4 级 Token 来源（mcp-guide.md §4.2）
  # allowed_roots:               # 可选：MCP 路径白名单追加根（§3.9；管理员语义，配最小目录）
  #   - D:\shared-testcases

update:                          # 应用内更新下载白名单（§3.10；默认仅内置 GitHub 域）
  allowed_hosts: []              # 空列表 = 不追加；自建镜像时填 host，须 https 可达
```

### 5.2 env.yaml（节选带注释，完整 18 组见 examples/env.yaml）

```yaml
device:                          # 被测设备指纹
  model: N58
  imei: '866758050000161'        # 号码/ID 类加引号存字符串，防 YAML 数字化变形
  software_version: V1.0.0

pdp:                             # PDP 上下文接入事实
  apn: cmnet
  cid: '1'                       # 端口/编号类同样建议加引号
  auth_user: card
  auth_password: <占位password>

tcp:                             # TCP 对端服务器
  host: 192.168.1.100
  port: '8080'

http:                            # HTTP 服务器与账号
  host: 192.168.1.200
  url: 192.168.1.200/api/test
  cacert: ca.pem

ftp:                             # FTP 服务器与账号（密码为占位）
  host: 192.168.1.100
  port: '21'
  user: test
  password: <占位password>
  path: /firmware

mqtt:                            # MQTT broker 接入事实
  host: broker.example.com
  port: '1883'
  topic: test/cmd
  keep_alive: '60'

fota:                            # FOTA 升级版本对与包地址
  version_a: V1.0.0
  version_b: V2.0.0
  pkg_ab: fota_V1_to_V2.bin

sms:                             # 短信中心与目标号码
  sca: '+8613800755500'
  dest_number: '13800138000'

default:                         # 简单名 {{param}} 的回退查找域（§4.3）
  apn: cmnet                     # {{apn}} 未命中用例变量池时取此值
```

用例侧引用示例：`AT+CGDCONT={{pdp.cid}},"IP","{{pdp.apn}}"`（command 中
渲染）。注意 `{{pdp.apn}}` 是点号名、只查 env；`{{apn}}` 是简单名、先查用例
变量池再回退 default 组。

## 6. 串口参数补充表

### 6.1 帧格式（ports 第 3 段，紧凑写法）

| 位 | 合法值 | 默认 | 说明 |
|---|---|---|---|
| 数据位 | `5` / `6` / `7` / `8` | `8` | 首字符必须是这四个数字之一 |
| 校验位 | `N` / `E` / `O` / `M` / `S` | `N` | 无/偶/奇/Mark/Space；大小写不敏感 |
| 停止位 | `1` / `1.5` / `2` | `1` | 1.5 停止位写作 `8N1.5`（5 字符紧凑写法，与 3 字符写法同源解析） |

合法示例：`8N1`（默认）、`8N1.5`、`7E1`、`8O2`、`5S1`。

### 6.2 连接级与行为级默认值（PortConfig）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `baudrate` | `115200` | 见 ports 表达式与 default.baud 回填（§3.2） |
| `frame` | `8N1` | 见 §6.1 |
| `flow_control` | `none` | 可选 `rts_cts`（硬件流控）/ `xon_xoff`（软件流控） |
| `terminator` | `CRLF`（`\r\n`） | 命令结束符；仅 `CR`（`\r`）/ `CRLF` 两种 AT 标准枚举 |
| `response_timeout` | `5.0` 秒 | 单条命令等待最终响应的超时（步骤级默认超时的来源） |
| `send_interval_ms` | `0` | 相邻命令发送间隔 |
| `reconnect_interval_s` | `3.0` 秒 | 断线重连尝试间隔 |
| `reconnect_max_retries` | `10` | 重连最大尝试次数 |
| `reconnect_safety_threshold` | `3` | 同用例连续断连安全阀，超过即判失败（防死循环） |

### 6.3 数据流分片默认值（DataStreamSpec，用例 data 级）

`chunk_threshold: 4096`、`chunk_size: 1024`、`chunk_interval_ms: 50`、
`append_terminator: false`——发送数据超过阈值后按块分片、按间隔发送。
