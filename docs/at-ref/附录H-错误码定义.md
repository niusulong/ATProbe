# 附录 H 错误码定义

> 来源：《N58 AT 命令手册 v2.0》附录 H（p.363-368）

以下自定义错误码，参考 3GPP 27.007 9.2 章节进行定义。根据 `AT+CMEE` 的设置，结果码可以显示为 "ERROR"、"+CME ERROR: `<err code>`" 或 "+CME ERROR: `<err strings>`"。根据 `AT+CMEE` 的设置，短信相关的 AT 命令，结果码可以显示为 "ERROR"、"+CMS ERROR: `<err code>`" 或 "+CMS ERROR: `<err strings>`"。

## H.1 +CME ERROR

所有低于 256 的值均保留：0-100 范围内的值保留用于一般错误；101-150 范围内的值保留供 GPRS 和 EPS 使用；151-170 范围内的值保留供 VBS/VGCS 和 eMLPP 使用；GPRS 或 EPS 可以使用 171-256 范围内的值。

| Numeric error code | Description |
| --- | --- |
| 0 | phone failure |
| 1 | no connection to phone |
| 2 | phone-adaptor link reserved |
| 3 | operation not allowed |
| 4 | operation not supported |
| 5 | PH-SIM PIN required |
| 6 | PH-FSIM PIN required |
| 7 | PH-FSIM PUK required |
| 10 | SIM not inserted（See NOTE 1） |
| 11 | SIM PIN required |
| 12 | SIM PUK required |
| 13 | SIM failure（See NOTE 1） |
| 14 | SIM busy（See NOTE 1） |
| 15 | SIM wrong（See NOTE 1） |
| 16 | incorrect password |
| 17 | SIM PIN2 required |
| 18 | SIM PUK2 required |
| 20 | memory full |
| 21 | invalid index |
| 22 | not found |
| 23 | memory failure |
| 24 | text string too long |
| 25 | invalid characters in text string |
| 26 | dial string too long |
| 27 | invalid characters in dial string |
| 30 | no network service |
| 31 | network timeout |
| 32 | network not allowed - emergency calls only |
| 40 | network personalization PIN required |
| 41 | network personalization PUK required |
| 42 | network subset personalization PIN required |
| 43 | network subset personalization PUK required |
| 44 | service provider personalization PIN required |
| 45 | service provider personalization PUK required |
| 46 | corporate personalization PIN required |
| 47 | corporate personalization PUK required |
| 48 | hidden key required（See NOTE 2） |
| 49 | EAP method not supported |
| 50 | Incorrect parameters |
| 51 | command implemented but currently disabled |
| 52 | command aborted by user |
| 53 | not attached to network due to MT functionality restrictions |
| 54 | modem not allowed - MT restricted to emergency calls only |
| 55 | operation not allowed because of MT functionality restrictions |
| 56 | fixed dial number only allowed - called number is not a fixed dial number（refer 3GPP TS 22.101 [147]） |
| 57 | temporarily out of service due to other MT usage |
| 58 | language/alphabet not supported |
| 59 | unexpected data value |
| 60 | system failure |
| 61 | data missing |
| 62 | call barred |
| 63 | message waiting indication subscription failure |
| 100 | unknown |

> NOTE 1：此错误码也适用于 UICC。
> NOTE 2：访问隐藏电话簿条目时需要此密钥。

## H.2 +CMS ERROR

| Numeric error code | Description |
| --- | --- |
| 0...127 | 3GPP TS 24.011 [6] clause E.2 values |
| 128...255 | 3GPP TS 23.040 [3] clause 9.2.3.22 values |
| 300 | ME failure |
| 301 | SMS service of ME reserved |
| 302 | operation not allowed |
| 303 | operation not supported |
| 304 | invalid PDU mode parameter |
| 305 | invalid text mode parameter |
| 310 | (U)SIM not inserted |
| 311 | (U)SIM PIN required |
| 312 | PH-(U)SIM PIN required |
| 313 | (U)SIM failure |
| 314 | (U)SIM busy |
| 315 | (U)SIM wrong |
| 316 | (U)SIM PUK required |
| 317 | (U)SIM PIN2 required |
| 318 | (U)SIM PUK2 required |
| 320 | memory failure |
| 321 | invalid memory index |
| 322 | memory full |
| 330 | SMSC address unknown |
| 331 | no network service |
| 332 | network timeout |
| 340 | no +CNMA acknowledgement expected |
| 500 | unknown error |
| ...511 | other values in range 256...511 are reserved |
| 512... | manufacturer specific |

## H.3 自定义错误码

### H.3.1 内置协议栈拨号错误

| Error code | Description |
| --- | --- |
| 900 | 用户名和密码拨号被网络侧拒绝（APN 错误，SIM 卡欠费，SIM 卡不支持该类型网络、业务等） |
| 901 | PDP 没有激活 |
| 902 | 此 PDP 已经激活 |

### H.3.2 TCP 错误码

| Error code | Description |
| --- | --- |
| 910 | TCP 连接被对方拒绝 |
| 911 | TCP 连接超时，可能 IP 和端口不正确 |
| 912 | Socket 连接已经存在 |
| 913 | Socket 连接不存在 |
| 914 | 缓冲区已满，需要重试发送 |
| 915 | 发送数据超时 |
| 916 | 域名不存在 |
| 917 | 域名解析超时 |
| 918 | 域名解析未知错误 |

### H.3.3 其他错误码

| Error code | Description |
| --- | --- |
| 980 | 输入参数不合法 |
| 981 | 其他错误 |

### H.3.4 FTP(S) 协议错误码

| `<protocol_error>` | 英文含义 | 中文含义 |
| --- | --- | --- |
| 0 | Invalid result | 无效结果 |
| 200 | Command okay | 命令确定 |
| 421 | Service not available, closing control connection | 服务不可用，关闭控制连接 |
| 425 | Open data connection failed | 打开数据连接失败 |
| 426 | Connection closed; transfer aborted | 连接关闭；传输中止 |
| 450 | Requested file action not taken | 文件操作请求失败 |
| 451 | Requested action aborted: local error in processing | 请求中间：本地错误处理中 |
| 452 | Requested action not taken: insufficient system storage | 请求失败：系统空间不足 |
| 500 | Syntax error, command unrecognized | 语句错误，无法命令识别 |
| 501 | Syntax error in parameters or arguments | 参数语句错误 |
| 502 | Command not implemented | 未执行命令 |
| 503 | Bad sequence of commands | 命令顺序有误 |
| 504 | Command parameter not implemented | 未输入参数 |
| 530 | Not logged in | 未登录 |
| 532 | Need account for storing files | 需要能存储文件的账号 |
| 550 | Requested action not taken: file unavailable | 请求失败：文件不可用 |
| 551 | Requested action aborted: page type unknown | 请求中止：未知网页类型 |
| 552 | Requested file action aborted: exceeded storage allocation | 文件操作请求中止：存储空间分配过量 |
| 553 | Requested action not taken: file name not allowed | 请求失败：不允许的文件名 |
