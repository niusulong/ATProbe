# env 参数清单（全指令集）

测试用例里所有"会随环境变化"的参数（服务器地址/端口/域名/鉴权/平台 ID 等）必须用
`{{group.param}}` 引用环境配置，**禁止硬编码**。本文件是这些参数的**权威清单**——按业务分组
列出每个功能块需要哪些 env 参数、字段语义、占位值，供生成用例时查表。

> **本文件是「清单/模板」，不含真实值。** 真实地址/密钥/端口在**项目自己的 env.yaml**
> （由配置文件 `env_config` 指向）。这里只有占位值（example.com / 192.168.x.x / 占位 ID）。
> 生成用例时，从项目 env.yaml 取真实值；缺项则按本清单命名规则新增（见 SKILL.md
> 「env 参数对齐」工作流）。

## 通用约定

- `host` / `port` 是几乎所有网络业务的通用字段（服务器地址 / 端口）。
- `port` **一律用引号字符串**（`'1883'`），避免 YAML 把纯数字端口误解析。
- 业务专属字段（topic、product_id、url、cert 文件名等）只放对应业务组，不进通用组。
- 敏感值（password / secret / 密钥）用 `<占位...>` 标注，真实值只在项目 env.yaml，不进版本库的明文。
- 章节号对应 `docs/at-ref/chXX-*.md`（以实际文档章节为准）。

---

## 参数对齐工作流（生成用例时执行）

生成用例前对齐环境参数，确保用例里的地址/端口/鉴权用 `{{group.param}}` 引用而非硬编码：

1. **查参数清单**：读本文件下方「按业务分组的参数清单」，掌握本次涉及的功能块需要哪些 env 参数组与字段。
2. **读项目 env.yaml**：读取目标工作区的 env 配置（配置 `env_config` 指向，如 `examples/env.yaml`），
   掌握已有参数组与真实值。
3. **比对、记增量**：逐个用例需要的 env 项，对照项目 env.yaml：
   - **已在 env.yaml** → 用例直接用 `{{group.param}}` 引用真实值。
   - **不在 env.yaml，但清单有** → 按清单命名（组名.字段名）在用例里引用，记入「待补充 env 项清单」。
   - **清单也没有（全新业务）** → 按 `<业务>.<字段>` 约定命名（host/port 等通用名复用），引用并记入待补充；
     同时提示用户：本清单需新增该业务组——**由用户决定是否把新增项同步回 skill 参考文档**。
4. **输出**：生成结束时输出「env.yaml 待补充项清单」（只列缺失项，不覆盖已有值，不含真实值），供用户补到项目 env.yaml：
   ```
   本次生成用到以下 env 项，请确认项目 env.yaml 已定义（缺失的需补充真实值）：
     ctwing.host          # 已存在 ✓
     ctwing.product_id    # 已存在 ✓
     ctwing.device_secret # 缺失，需补充（设备密钥）
     ssl.cacert           # 缺失，需补充（CA 证书文件名）
   ```

> skill **不直接改写项目 env.yaml 的真实值**。env-params.md（占位清单）与项目 env.yaml（真实值）分离。
> 生成后可用 `scripts/validate-cases.py --env <env.yaml>` 一键校验 env 引用是否存在。

---

## 网络接入层

### `pdp` — PDP/PPP 拨号与鉴权（注网前置）

许多数据业务（TCP/MQTT/HTTP/FTP）需先 `AT+XIIC=1` 拨号建 PPP，鉴权参数随运营商/卡变化。

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `apn` | 接入点名（`AT+CGDCONT` / `AT+NETAPN`） | ch04 §4.20, ch06 §6.1 | `cmnet` |
| `pdp_type` | PDP 类型：IP/IPV6/IPV4V6/PPP | ch04 §4.20 | `IP` |
| `cid` | PDP 上下文编号（1-7） | ch04 §4.20 | `'1'` |
| `auth_type` | 鉴权：0NONE/1PAP/2CHAP（`AT+XGAUTH`） | ch04 §4.21 | `'1'` |
| `auth_user` | 拨号用户名（联通卡常为 `card`） | ch04 §4.21 | `card` |
| `auth_password` | 拨号密码 | ch04 §4.21 | `<占位password>` |

### `dns` — DNS 服务器

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `dns1` | 首选 DNS（`AT+DNSSERVER=1,<ip>`） | ch06 §6.16 | `114.114.114.114` |
| `dns2` | 备选 DNS（`AT+DNSSERVER=2,<ip>`） | ch06 §6.16 | `8.8.8.8` |
| `query_domain` | DNS 解析测试域名（`AT+NWDNS`） | ch04 §4.28 | `example.com` |

---

## 数据业务（传输层）

### `tcp` — TCP/UDP 客户端 + 透传

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `host` | 测试服务器 IP/域名（`AT+TCPSETUP` / `AT+UDPSETUP`） | ch06 §6.3/§6.9, ch08 | `192.168.1.100` |
| `port` | 服务器端口 | ch06 §6.3/§6.9, ch08 | `'8080'` |

### `tcp_server` — 模组做 TCP/UDP 服务器

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `listen_port` | 模组侦听端口（`AT+TCPLISTEN` / `AT$UDPLISTEN`） | ch07, ch09, ch32 | `'6800'` |
| `client_host` | 测试客户端 IP（断言 Connect 上报的 ClientAddr） | ch07, ch09 | `192.168.1.50` |
| `client_port` | 测试客户端源端口 | ch07, ch09 | `'50000'` |

### `ssl` — SSL TCP（加密 TCP，需 TLS 握手/证书）

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `host` | SSL TCP 服务器（`AT+SSLTCPSETUP`） | ch14 §14.2 | `192.168.1.100` |
| `port` | 端口（常见 4451） | ch14 §14.2 | `'4451'` |
| `sslversion` | 0SSL3.0/1TLS1.0/2TLS1.1/3TLS1.2 | ch14 §14.1 | `'3'` |
| `authmode` | 0不认证/1认证服务器/2双向 | ch14 §14.1 | `'0'` |
| `cacert` | CA 根证书文件名（authmode≠0 需要） | ch14 §14.1 | `ca.pem` |
| `client_cert` | 客户端证书文件名（双向认证） | ch14 §14.1 | `cc.pem` |
| `client_key` | 客户端密钥文件名（双向认证） | ch14 §14.1 | `ck.pem` |

---

## 应用层协议

### `http` — HTTP / HTTPS

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `host` | HTTP 服务器地址 | ch11 §11.1 | `192.168.1.200` |
| `port` | 端口（默认 80） | ch11 §11.1 | `'8080'` |
| `url` | 完整 URL（`AT+HTTPPARA=url`，最长 2048，含域名） | ch11 §11.1 | `192.168.1.200/api/test` |
| `base_url` | 基础路径（拼 url 用） | ch11 §11.1 | `/api` |
| `https_url` | HTTPS 路径（`AT+HTTPSPARA=url`） | ch11 §11.11 | `example.com/secure/api` |
| `https_port` | HTTPS 端口（一般 443） | ch11 §11.11 | `'443'` |
| `cacert` | HTTPS CA 证书文件名（authmode≠0） | ch11 §11.10 | `ca.pem` |

### `ftp` — FTP / FTPS

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `host` | FTP 服务器（`AT+FTPLOGIN`） | ch10 §10.2 | `192.168.1.100` |
| `port` | 端口（一般 21） | ch10 §10.2 | `'21'` |
| `user` | 用户名（最长 100） | ch10 §10.2 | `testuser` |
| `password` | 密码（最长 100） | ch10 §10.2 | `<占位password>` |
| `path` | 服务器目录 | ch10 §10.4 | `/firmware` |
| `filename` | 测试文件名（`AT+FTPGET` / `AT+FTPGETF`） | ch10 §10.4, ch31 §31.39 | `test.txt` |
| `ftps_mode` | 0FTP/1显式FTPS/2隐式FTPS | ch10 §10.2 | `'0'` |
| `ftp_mode` | 0被动/1主动 | ch10 §10.2 | `'0'` |

### `ntp` — 网络时间同步（授时）

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `host` | 授时服务器 IP/域名（`AT+UPDATETIME`） | ch25 §25.1 | `time.windows.com` |
| `port` | 端口（NTP 一般 123） | ch25 §25.1 | `'123'` |
| `timeout` | 同步超时秒数（1-30，必填参数） | ch25 §25.1 | `'10'` |
| `timezone` | 时区（`E8` / `W5` 等，影响 AT+CCLK? 校验） | ch25 §25.1 | `E8` |

---

## IoT 云平台

### `mqtt` — 标准 MQTT broker（自有/第三方）

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `host` | broker 地址，`url:port` 合体格式（`AT+MQTTCONN`） | ch16 §16.6 | `broker.example.com:1883` |
| `port` | 端口（host 拆开填时用） | ch16 §16.6 | `'1883'` |
| `client_id` | 设备 ID（最长 256） | ch16 §16.3 | `atprobe_test_01` |
| `username` | 用户名（最长 512，可空） | ch16 §16.3 | `atprobe_user` |
| `password` | 密码（最长 256，可空） | ch16 §16.3 | `<占位password>` |
| `topic` | 订阅/发布主题（最长 128） | ch16 §16.7/§16.9 | `atprobe/cmd` |
| `keep_alive` | keepAlive 秒数（20-180） | ch16 §16.6 | `'60'` |

### `aliyun` — 阿里云物联网平台（ch15）

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `srv_url` | MQTT 鉴权站点 URL（`AT+CLOUDSETSRVURL`） | ch15 §15.3 | `iot-cn-example.mqtt.iothub.aliyuncs.com` |
| `product_key` | 产品 Key（最长 11，`AT+CLOUDHDAUTH`） | ch15 §15.4 | `a1Example01` |
| `device_name` | 设备名（最长 32） | ch15 §15.4 | `device001` |
| `device_secret` | 设备秘钥 / ProductSecret（最长 32） | ch15 §15.4 | `<占位secret32>` |
| `auth_mode` | 0一机一密/1一型一密/2x509/3直连 | ch15 §15.1 | `'0'` |
| `keep_alive` | MQTT keepAlive（60-180 秒） | ch15 §15.5 | `'120'` |

### `aws` — AWS IoT（ch17，证书强制）

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `endpoint` | AWS IoT 端点，`url:port`（`AT+AWSCONNPARAM`） | ch17 §17.3 | `a1example.iot.us-east-2.amazonaws.com:443` |
| `client_id` | 设备 ID（最长 128） | ch17 §17.2 | `atprobe_aws_01` |
| `topic` | 订阅/发布主题（最长 128） | ch17 §17.5/§17.7 | `nwy_test/01` |
| `keep_alive` | keepAlive（30-1200，默认 60） | ch17 §17.4 | `'60'` |
| `ca_cert` | CA 证书文件名 | ch17 §17.1 | `ca.pem` |
| `client_cert` | 客户端证书文件名 | ch17 §17.1 | `cc.pem` |
| `client_key` | 客户端密钥文件名 | ch17 §17.1 | `ck.pem` |

### `ctwing` — 电信天翼物联网平台（手册外，外部生态预留）

> 本指令集手册无独立 CTM2M/ctwing 章节，但生态测试常接电信天翼平台，按外部平台预留。

| 字段 | 语义 | 占位值 |
|---|---|---|
| `host` | 平台接入地址 | `mqtt.ctwing.cn` |
| `port` | 接入端口 | `'1883'` |
| `product_id` | 产品 ID | `'00000000'` |
| `device_name` | 设备名称 | `device001` |
| `device_secret` | 设备密钥（敏感） | `<占位secret>` |

### `pipecloud` — 有方管道云（ch33）

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `server_url` | 管道云域名/IP（`AT+MYPIPECLOUDCFG`） | ch33 §33.2 | `iot.example.com` |
| `server_port` | 端口（默认 1883） | ch33 §33.2 | `'1883'` |

---

## 其它业务

### `fota` — 远程升级

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `version_a` | 升级前版本号（断言比对） | ch04 §4.2, ch31 §31.3 | `V1.0.0` |
| `version_b` | 升级后版本号 | ch04 §4.2, ch31 §31.3 | `V2.0.0` |
| `http_url` | HTTP FOTA 差分包路径（`AT+NWFOTA`，最长 1024） | ch31 §31.26 | `fota.example.com/http/fota.bin` |
| `http_port` | HTTP FOTA 端口 | ch31 §31.26 | `'80'` |
| `https_url` | HTTPS FOTA 路径 | ch31 §31.26 | `fota.example.com/https/fota.bin` |
| `https_port` | HTTPS FOTA 端口 | ch31 §31.26 | `'443'` |
| `pkg_ab` | A→B 升级包文件名（FTP FOTA） | ch31 §31.26/§31.39 | `fota_V1_to_V2.bin` |
| `pkg_ba` | B→A 回退包文件名 | ch31 §31.26/§31.39 | `fota_V2_to_V1.bin` |

### `sms` — 短消息

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `sca` | 短信中心号码（`AT+CSCA`，需带引号，随运营商变） | ch05 §5.12 | `+8613800755500` |
| `dest_number` | 测试收发目标号码（`AT+CMGS`） | ch05 §5.8 | `13800138000` |

### `netshare` — 网络共享（RNDIS/ECM，ch26）

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `apn` | 共享网络 APN | ch26 §26.2 | `ctnet` |
| `username` | 拨号用户名（最长 64） | ch26 §26.2 | `card` |
| `password` | 拨号密码（最长 64） | ch26 §26.2 | `<占位password>` |
| `auth_type` | 0NONE/1PAP/2CHAP | ch26 §26.2 | `'1'` |
| `share_mode` | 0RNDIS/1ECM | ch26 §26.1 | `'0'` |

---

## 设备/默认

### `device` — 被测模组/卡信息

| 字段 | 语义 | 出处 | 占位值 |
|---|---|---|---|
| `model` | 期望型号（断言 `AT+CGMM` / `ATI`） | ch04 §4.1/§4.11 | `N58` |
| `test_number` | 本机号码（拨测/收发短信用） | ch12, ch05 | `13800138000` |
| `imei` | 期望 IMEI（断言 `AT+CGSN`） | ch04 §4.8 | `000000000000000` |
| `software_version` | 期望软件版本（断言 `AT+GMR`） | ch04 §4.2 | `V1.0.0` |

### `default` — 通用默认

| 字段 | 语义 | 占位值 |
|---|---|---|
| `apn` | 通用默认 APN（与 `pdp.apn` 别名，择一用） | `cmnet` |

---

## 不需要 env 组的功能块（确认）

以下章节无可配服务器/鉴权参数，用例无需 env 引用（地址类参数由模组内部固化或运行时动态 extract）：
ch02 LOG、ch03 命令格式、ch13 Wi-Fi、ch18 GPS、ch19-22 BT/BLE、ch23 DTMF、ch24 基站定位、
ch27 流量统计、ch28 文件系统、ch29 录音、ch30 SIM 卡。

---

## env.yaml 模板（全占位值，供新项目初始化参考）

> 复制此模板到项目 `env.yaml`（或配置 `env_config` 指向的文件），替换占位值为真实值。
> **真实值不进 skill 版本库明文**；敏感值（password/secret）建议用占位或环境变量注入。

```yaml
pdp:
  apn: cmnet
  pdp_type: IP
  cid: '1'
  auth_type: '1'
  auth_user: card
  auth_password: '<占位password>'

dns:
  dns1: 114.114.114.114
  dns2: 8.8.8.8
  query_domain: example.com

tcp:
  host: 192.168.1.100
  port: '8080'

tcp_server:
  listen_port: '6800'
  client_host: 192.168.1.50
  client_port: '50000'

ssl:
  host: 192.168.1.100
  port: '4451'
  sslversion: '3'
  authmode: '0'
  cacert: ca.pem
  client_cert: cc.pem
  client_key: ck.pem

http:
  host: 192.168.1.200
  port: '8080'
  url: 192.168.1.200/api/test
  base_url: /api
  https_url: example.com/secure/api
  https_port: '443'
  cacert: ca.pem

ftp:
  host: 192.168.1.100
  port: '21'
  user: testuser
  password: '<占位password>'
  path: /firmware
  filename: test.txt
  ftps_mode: '0'
  ftp_mode: '0'

ntp:
  host: time.windows.com
  port: '123'
  timeout: '10'
  timezone: E8

mqtt:
  host: broker.example.com:1883
  port: '1883'
  client_id: atprobe_test_01
  username: atprobe_user
  password: '<占位password>'
  topic: atprobe/cmd
  keep_alive: '60'

aliyun:
  srv_url: iot-cn-example.mqtt.iothub.aliyuncs.com
  product_key: a1Example01
  device_name: device001
  device_secret: '<占位secret32>'
  auth_mode: '0'
  keep_alive: '120'

aws:
  endpoint: a1example.iot.us-east-2.amazonaws.com:443
  client_id: atprobe_aws_01
  topic: nwy_test/01
  keep_alive: '60'
  ca_cert: ca.pem
  client_cert: cc.pem
  client_key: ck.pem

ctwing:
  host: mqtt.ctwing.cn
  port: '1883'
  product_id: '00000000'
  device_name: device001
  device_secret: '<占位secret>'

pipecloud:
  server_url: iot.example.com
  server_port: '1883'

fota:
  version_a: V1.0.0
  version_b: V2.0.0
  http_url: fota.example.com/http/fota.bin
  http_port: '80'
  https_url: fota.example.com/https/fota.bin
  https_port: '443'
  pkg_ab: fota_V1_to_V2.bin
  pkg_ba: fota_V2_to_V1.bin

sms:
  sca: '+8613800755500'
  dest_number: '13800138000'

netshare:
  apn: ctnet
  username: card
  password: '<占位password>'
  auth_type: '1'
  share_mode: '0'

default:
  apn: cmnet

device:
  model: N58
  test_number: '13800138000'
  imei: '000000000000000'
  software_version: V1.0.0
```
