# 第 4 章 通用 AT 指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 4 章
> 本文件由 PDF 提取并结构化重建，命令格式/参数/示例对照原书排版整理。

本章覆盖模组最常用的一组通用 AT 指令：厂商/版本/信号查询、网络注册与选择、SIM/IMEI/IMSI、波特率与功能设置、PDP 格式、休眠与信号灯、扩展信号与域名解析等。

---

## 4.1 ATI — 获取模组厂商信息

获取模组厂商信息，包括厂家、型号和版本。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `ATI<CR>` | `<CR><LF><manufacturer>`<br>`<CR><LF><module_version>`<br>`<CR><LF><soft_version>`<br>`<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<manufacturer>` | 模组厂商信息、产品名称、版本号 |
| `<module_version>` | 模组型号 |
| `<soft_version>` | 模组软件版本 |

**示例**

```
ATI
NEOWAY              ← 厂家信息
N58                 ← 模组型号
V001                ← 版本号
OK
```

---

## 4.2 AT+GMR — 查询版本信息

查询软件版本信息。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+GMR<CR>` | `<CR><LF>+GMR: <reversion>`<br>`<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<reversion>` | 模组软件版本信息 |

**示例**

```
AT+GMR
+GMR: N58-R04-STD-BZ-03      ← 查询软件版本
OK
```

---

## 4.3 AT+CSQ — 获取信号强度

查询接收信号强度 `<rssi>`。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CSQ<CR>` | `<CR><LF>+CSQ: <signal>,<ber>`<br>`<CR><LF>OK<CR><LF>` |

**参数**

`<signal>`：以下为 signal(CSQ) 与 rssi 对应关系：

| signal | rssi |
| --- | --- |
| 0 | < -107 dBm 或未知 |
| 1 | < -93 dBm |
| 2 | < -81 dBm |
| 3 | < -69 dBm |
| 4 | < -57 dBm |
| 5 | ≥ -57 dBm |

`<ber>`（误码率）：

| ber | 说明 |
| --- | --- |
| 0…7 | 参考 GSM 05.08 8.2.4 章节表格中 RXQUAL 的取值 |
| 99 | 误码率无法测量 |

**示例**

```
AT+CSQ
+CSQ: 19,2       ← 查询信号强度
OK
```

---

## 4.4 AT+CREG — 查询网络注册状态

查询模组的当前网络注册状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CREG=[<n>]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>`<br>或 `<CR><LF>+CREG:<stat>[,<lac>,<ci>[,<Act>]]<CR><LF>` |
| 查询 | `AT+CREG?<CR>` | `<CR><LF>+CREG: <n>,<stat>`<br>`<CR><LF>OK<CR><LF>` |
| 测试 | `AT+CREG=?<CR>` | `<CR><LF>+CREG: range of supported <n>`<br>`<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<n>` | 0：禁止网络注册主动提供结果代码（默认设置）<br>1：允许网络注册主动提供结果代码<br>2：允许网络注册主动提供所在地讯息（CELL ID、LOCAL ID） |
| `<stat>` | 0：未注册，终端当前并未在搜寻新的运营商<br>1：已注册本地网络<br>2：未注册，终端正在搜寻基站<br>3：注册被拒绝<br>4：未知代码<br>5：已注册，处于漫游状态<br>6：ltesms only home<br>7：ltesms only roaming<br>8：EMER SVCE ONLY<br>9：CSFB NOT PREFER HOME<br>10：CSFB NOT PREFER ROAMING |
| `<lac>` | 字符串型，2 字节十六进制位置区代码 |
| `<ci>` | 字符串型，4 字节十六进制小区编号 |
| `<Act>` | 0：GSM；1：GSM compact；2：UTRAN；3：GSM w/EGPRS；4：UTRAN w/HSDPA；5：UTRAN w/HSUPA；6：UTRAN w/HSDPA AND w/HSUPA；7：E-UTRAN；8：UTRAN w/HSPA+ |

**示例**

```
AT+CREG=1                    ← 允许模组主动提供网络注册代码
OK
AT+CREG?                     ← 查询模组当前网络注册状态信息
+CREG: 0,1
OK
AT+CREG=?                    ← 查询模组网络注册状态值范围
+CREG: (0-2)
OK
```

---

## 4.5 AT+CEREG — 获取 EPS 网络注册状态

查询 EPS 网络注册状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CEREG=[<n>]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>+CEREG: <n>,<stat>[,[<tac>],[<ci>],[<AcT>][,,[,[<Active-Time>],[<Periodic-TAU>]]]]<CR><LF>` |
| 查询 | `AT+CEREG?<CR>` | `<CR><LF>+CEREG:<n>,<stat>[,[<tac>],[<ci>],[<AcT>][,,[,[<Active-Time>],[<Periodic-TAU>]]]]<CR><LF>`<br>`<CR><LF>OK<CR><LF>` |
| 测试 | `AT+CEREG=?<CR>` | `<CR><LF>+CEREG: (list of supported <n>s)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<n>` | 0：禁止网络注册主动提供结果代码（默认设置）<br>1：允许网络注册主动提供结果代码<br>2：允许网络注册主动提供所在地信息（CELL ID、LOCAL ID）<br>4：允许网络注册主动提供 Active-Time 和 Periodic-TAU |
| `<stat>` | 0：未注册，终端当前并未在搜寻新的运营商<br>1：已注册本地网络<br>2：未注册，终端正在搜寻基站<br>3：注册被拒绝<br>4：未知代码<br>5：已注册，处于漫游状态 |
| `<tac>` | 字符串型，2 字节十六进制位置区代码 |
| `<ci>` | 字符串型，4 字节十六进制小区编号 |
| `<AcT>` | 0：GSM；1：GSM compact；2：UTRAN；3：GSM w/EGPRS；4：UTRAN w/HSDPA；5：UTRAN w/HSUPA；6：UTRAN w/HSDPA and HSUPA；7：E-UTRAN |

**示例**

```
AT+CEREG?                    ← 查询终端的注册结果
+CEREG: 0,1                  ← 已注册本地网络
OK
AT+CEREG=1                   ← 允许网络注册主动提供结果代码
OK
AT+CEREG=?                   ← 查询参数设置范围
+CEREG: (0-2,4)
OK
```

---

## 4.6 AT+COPS — 网络选择

查询网络。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+COPS=[<mode>[,<format>[,<oper>[,<AcT>]]]]<CR>` | `<CR><LF>OK<CR><LF>` |
| 查询 | `AT+COPS?<CR>` | `<CR><LF>+COPS: <mode>[,<format>,<oper>[,<AcT>]]<CR><LF>OK<CR><LF>` |
| 测试 | `AT+COPS=?<CR>` | `<CR><LF>+COPS: [list of supported (<stat>,long alphanumeric <oper>,short alphanumeric <oper>,numeric <oper>[,<AcT>])s][,,(list of supported <mode>s),(list of supported <format>s)]<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<mode>` | 用来设置自动选择网络还是手动选择网络。0：自动选择网络（忽略参数 `<oper>`）；1：手动选择网络；2：从网络侧撤销注册；3：只设置 `<format>`；4：先手动选择网络后自动选择网络（若手动选择网络不成功，就进入自动选择网络） |
| `<format>` | 0：长字母 `<oper>`（默认设置）；1：短格式字母 `<oper>`；2：数字 `<oper>` |
| `<oper>` | 在 `<format>` 中被赋值，可以是 16 个符的长字母格式、8 个符的短字母格式及 5 个符的数字格式（MCC/MNC） |
| `<AcT>` | 显示无线接入技术，取值如下：0：GSM；1：GSM compact；3：GSM w/EGPRS；7：E-UTRAN |

**示例**

```
AT+COPS=0,0                  ← 自动选择网络，长字母模式
OK
AT+COPS=0,2                  ← 设置成数字模式
OK
AT+COPS?                     ← 中国移动
+COPS: 0,0,"CHINAMOBILE",7
OK
AT+COPS?                     ← 如果是设置成数字模式，那么得到的是数字 46000
+COPS: 0,2,"46000",7
OK
AT+COPS=2                    ← 注销网络
OK
```

> 中国联通（CHINA UNICOM，数字 46001）、中国电信（CHINA TELECOM，数字 46011）同理。

---

## 4.7 AT+CIMI — 查询国际移动用户识别码

获取国际移动用户识别码 IMSI（international mobile subscriber identification）。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CIMI<CR>` | `<CR><LF>+CIMI: <IMSI><CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<IMSI>` | 国际移动用户识别码。该识别码为 15 位数字，以 3 位 MCC 和 2 位 MNC 开头，用来对 SIM 卡进行鉴权 |

**示例**

```
AT+CIMI                      ← 查询国际移动用户识别码
+CIMI: 460020188385503       ← IMSI：460022201575463
OK
AT+CIMI                      ← 不插 SIM 卡，返回 ERROR
ERROR
```

---

## 4.8 AT+CGSN — 获取通信模组 IMEI 号

获取模组的产品序列号，也就是 IMEI 号（International Mobile Equipment Identity）。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CGSN<CR>` | `<CR><LF>+CGSN: <IMEI><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<IMEI>` | 模组的产品序列号 |

**示例**

```
AT+CGSN                      ← 读取指令
+CGSN: 355897043139120
OK
```

> 3GPP2 网络下，返回码为 8 位的 ESN。

---

## 4.9 AT+GSN — 获取通信模组 IMEI 号

获取模组的产品序列号，也就是 IMEI 号（International Mobile Equipment Identity）。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+GSN<CR>` | `<CR><LF>+GSN: <IMEI><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<IMEI>` | 模组的产品序列号，为 15 位数字 |

**示例**

```
AT+GSN                       ← 查询 IMEI 号
+GSN: 355897043139120
OK
```

---

## 4.10 AT+CCID — 获取 SIM 卡标识

获取 SIM 卡的 ICCID。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CCID<CR>` | `<CR><LF>+CCID: <ICCID><CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<ICCID>` | Integrate circuit card identity 集成电路卡识别码，即所插入卡的识别码，ICCID 为 20 位 |

**示例**

```
AT+CCID                      ← 读取指令
+CCID: 89860002190810001367
OK
AT+CCID                      ← 不插 SIM 卡时，返回 ERROR
ERROR
```

---

## 4.11 AT+CGMM — 查询模组型号

查询模组型号。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CGMM<CR>` | `<CR><LF>+CGMM: <model><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<model>` | 模组型号 |

**示例**

```
AT+CGMM                      ← 查询模组型号
+CGMM: N58
OK
```

---

## 4.12 AT+GMM — 查询模组型号

查询模组型号。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+GMM<CR>` | `<CR><LF>+GMM: <model><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<model>` | 模组型号 |

**示例**

```
AT+GMM                       ← 查询模组型号
+GMM: N58
OK
```

---

## 4.13 AT+IPR — 设置模组波特率

设置模组波特率，掉电不保存。若波特率查询返回为 0，表示模组波特率自适应。默认为波特率自适应。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+IPR=<baud rate><CR>` | `<CR><LF>OK<CR><LF>` |
| 查询 | `AT+IPR?<CR>` | `<CR><LF>+IPR: <baud rate><CR><LF>OK<CR><LF>` |
| 测试 | `AT+IPR=?<CR>` | `<CR><LF>+IPR: list of supported <baud rate>s<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<baud rate>` | 波特率，取值：0, 1200, 2400, 4800, 9600, 14400, 19200, 28800, 33600, 38400, 57600, 115200, 230400, 460800, 921600, 2166666 |

**示例**

```
AT+IPR=115200                ← 设置波特率为 115200bps
OK
AT+IPR?                      ← 波特率查询
+IPR: 115200
OK
AT+IPR=?                     ← 查询波特率设置范围
+IPR: 0,1200,2400,4800,9600,14400,19200,28800,33600,38400,57600,115200,230400,460800,921600,2166666
OK
AT+IPR=100                   ← 模组波特率设为不允许的值
ERROR                        ← 出错
```

---

## 4.14 AT+CFUN — 设置模组功能

通过设置 `<fun>` 来选择模组的功能。`<fun>` 只支持某些值。设置该参数后，掉电不保存。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CFUN=[<fun>[,<rst>]]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+CFUN?<CR>` | `<CR><LF>+CFUN: <fun><CR><LF>OK<CR><LF>` |
| 测试 | `AT+CFUN=?<CR>` | `<CR><LF>+CFUN: (list of supported <fun>s),(range of supported <rst>)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<fun>` | 0：最小功能（turn off radio）<br>1：全功能（默认）<br>4：关闭模组的发送和接收射频电路（飞行模式） |
| `<rst>` | 0：do not reset the MT before setting it to `<fun>` power level<br>1：reset the MT before setting it to `<fun>` power level |

**示例**

```
AT+CFUN=1                    ← 设置模组为全功能状态工作
OK
AT+CFUN?                     ← 查询当前功能状态，全功能状态
+CFUN: 1
OK
AT+CFUN=?                    ← 查询指令可设置参数范围
+CFUN: (0,1,4),(0,1)
OK
```

---

## 4.15 AT+CMUX — 串口多路复用指令

启用通信模组串口多路复用功能。基于一个物理通信串口，通过规范协议虚拟出两个甚至多个串口，一般虚拟三个串口，一个串口进行外部协议栈拨号上网，另外两个收发 AT 指令。建议使用 `AT+CMUX=0` 启用串口多路复用功能。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CMUX=<mode>[,<subset>[,<port_speed>[,<N1>[,<T1>[,<N2>[,<T2>[,<T3>[,<k>]]]]]]]]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 测试 | `AT+CMUX=?<CR>` | `<CR><LF>+CMUX: (list of supported <mode> values),(list of supported <subset> values),(value range of <port_speed>),(value range of <N1>),(value range of <T1>),(value range of <N2>),(value range of <T2>),(value range of <T3>),(value range of <k>)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<mode>` | 整数类型，MUX 打开状态下的模式，本规范中至少需要支持基本模式。0：基本模式（默认值）；1：增强模式（目前不支持） |
| `<subset>` | 整数类型，帧格式子集。0：UIH frames used only（默认值）；1：UI frames used only（目前不支持） |
| `<port_speed>` | 整数类型，串口速率。1：9600 bit/s；2：19200 bit/s；3：38400 bit/s；4：57600 bit/s；5：115200 bit/s（默认值）；6：230400 bit/s |
| `<N1>` | 整数类型，最大帧长，1~32768；目前仅支持的设置范围为 1~2048。基本模式下默认值 31，增强模式下默认值 64 |
| `<T1>` | 整数类型，接收确认定时器，1~255，1 代表 10ms，默认值为 10（100ms） |
| `<N2>` | 整数类型，最大重连次数，0~100，默认值为 3，目前仅支持 0~5 |
| `<T2>` | 整数类型，多路控制通道响应定时器，2~255，2 代表 20ms，默认值为 30（300ms） |
| `<T3>` | 整数类型，唤醒响应定时器，1~255，1 代表 1s，默认值为 10（10s）（目前不支持该参数，读命令时返回 0 值） |
| `<k>` | 整数类型，窗口大小，1~7，默认值为 2，用于支持错误恢复的增强模式（目前不支持该参数，读命令时返回 0 值） |

> `<T2>` 必须大于 `<T1>`。

**示例**

```
AT+CMUX=0                            ← 基本模式，其它参数使用默认值
OK
AT+CMUX=2                            ← 指令参数超出可设置范围，返回 ERROR
ERROR
AT+CMUX=0,0,,512,254,5,255           ← 基本模式，帧格式子集为 UIH，速率为默认值，最大帧长为 255，接收确认定时器为 2540ms，最大重连次数为 5 次，多路控制通道响应定时器为 2550ms
OK
AT+CMUX=1,0,,512,254,5,255           ← 增强模式
OK
AT+CMUX=?                            ← 查询指令参数可设置范围
+CMUX: (0,1),(0),(1-6),(1-2048),(1-255),(0-100),(2-255),(1-255),(1-7)
OK
AT+CMUX?                             ← 指令格式错误，返回 ERROR
ERROR
```

---

## 4.16 AT+CCLK — 时钟管理

设置和查询模组的实时时钟。设置的时间掉电不保存；默认时钟为 0 时区，使用 1/4 时区。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+CCLK=<time><CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+CCLK?<CR>` | `<CR><LF>+CCLK: <time><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<time>` | 字符串，格式为 `"yy/MM/dd,hh:mm:ss[TZ]"`，指示年、月、日、小时、分钟、秒。TZ 为 2 位数字表示当地时间与 GMT 之间时差，该信息可选，只有当网络支持时该信息才显示 |

**示例**

```
AT+CCLK="18/07/01,14:54:01"          ← 设置模组时间为 18 年 7 月 1 日，14 时 54 分 01 秒，时区为东八区
OK
AT+CCLK?                              ← 查询模组当前的时钟
+CCLK: "18/07/01,14:54:10+32"
OK
AT+CCLK=14/07/02,10:48:50             ← 设置时间必须为字符串格式
ERROR
```

---

## 4.17 AT+CPIN — 输入 PIN 码

查询 PIN 状态以及输入 PIN 码。若要输入 PIN 码，需锁定当前 SIM 卡（`AT+CLCK="SC",1,"1234"`）后，重启模组才能输入 PIN 码；输入三次错误的 PIN 码后，会要求输入 PUK 码才能解锁。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CPIN=<pin>[,<newpin>]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+CPIN?<CR>` | `<CR><LF>+CPIN: <code><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<pin>`, `<newpin>` | 字符串类型 |
| `<code>` | READY：不需要输入任何密码；SIM PIN：需要输入 PIN 码；SIM PUK：需要输入 PUK 码；SIM PIN2：需要输入 PIN2 码；SIM PUK2：需要输入 PUK2 码 |

**示例**

```
AT+CPIN?                              ← 查询是否需要输入 PIN 码
+CPIN: READY                          ← 不需要输入任何密码
OK
AT+CPIN?                              ← 查询是否需要输入 PIN 码
+CPIN: SIM PIN                        ← 需要输入 PIN 码
OK
AT+CPIN="1234"                        ← 输入正确的 PIN 码
OK
+PBREADY                              ← 卡解锁
AT+CPIN?                              ← 输入错误的 PIN 码三次以上，需要输入 PUK 码来解锁
+CPIN: SIM PUK
OK
AT+CPIN="12345678","4321"             ← 输入 PUK 码，并输入新的 PIN 码
OK
+PBREADY                              ← 卡解锁
```

---

## 4.18 AT+CLCK — PIN 使能与查询功能指令

锁、解锁以及查询 MT 和网络设备。设置该参数，重启模组后生效。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+CLCK=<fac>,<mode>[,<passwd>[,<class>]]<CR>` | 当 `<mode>` 等于 2：`<CR><LF>+CLCK:<status>[,<class1>[<CR><LF>+CLCK:<status>,<class2>[...]]<CR><LF>OK<CR><LF>` 或 `<CR><LF>ERROR<CR><LF>`；当 `<mode>` 不等于 2：`<CR><LF>OK<CR><LF>` 或 `<CR><LF>ERROR<CR><LF>` |
| 测试 | `AT+CLCK=?<CR>` | `<CR><LF>+CLCK: (list of supported <fac> values)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<fac>` | 需带双引号 `""`。"OI"：呼出国际电话；"SC"：SIM 卡；"AO"：呼出电话；"OX"：除了归属地外所有呼出国际电话；"FD"：SIM 卡固定拨号空间 |
| `<mode>` | 0：解锁；1：锁定；2：查询状态 |
| `<status>` | 0：not active；1：active |
| `<passwd>` | 密码或操作码，字符串类型，需带双引号 `""` |
| `<classx>` | 1：语音服务类型；2：数据服务类型；4：fax 服务类型；8：短消息；16：同步数据业务；32：异步数据业务；64：专用包接入；128：专用数据包装拆器接入 |

**示例**

```
AT+CLCK="SC",2
+CLCK:0
OK
AT+CLCK=?                             ← 查询模组相关网络信息
+CLCK:("SC","FD","AO","OX","OI")
OK
AT+CLCK="SC",1,"1234"                 ← 锁定 SIM 卡，其中 "1234" 为当前 SIM 卡的 PIN 码
OK
AT+CLCK="SC",0,"1234"                 ← 解锁 SIM 卡，其中 "1234" 为当前 SIM 卡的 PIN 码
OK
AT+CLCK="SC",1,"2222"                 ← PIN 码错误
ERROR
```

---

## 4.19 AT+CPWD — 修改密码指令

修改模组锁功能的密码。若需修改 PIN 码，需锁定 SIM 卡（`AT+CLCK="SC",1,"1234"`）后才能修改。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+CPWD=<fac>,<oldpwd>,<newpwd><CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 测试 | `AT+CPWD=?<CR>` | `<CR><LF>+CPWD: (list of supported (<fac>,<pwdlength>)s)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<fac>` | 需带双引号 `""`。"P2"：SIM PIN2；"SC"：SIM 卡 |
| `<oldpwd>` | 需带双引号 `""`，旧密码或操作码，字符串类型 |
| `<newpwd>` | 需带双引号 `""`，新密码或操作码，字符串类型 |

**示例**

```
AT+CPWD=?                             ← 查询模组允许锁功能密码的业务范围
+CPWD: ("SC",8),("P2",8)
OK
AT+CPWD="SC","1234","0000"            ← 修改当前 SIM 卡的 PIN 码，其中 1234 为旧的 PIN 码，0000 为新的 PIN 码
OK
AT+CPWD=SC,1234,0000                  ← 指令格式错误，需带双引号 ""
ERROR
```

---

## 4.20 AT+CGDCONT — 设置 PDP 格式

设置 GPRS 的 PDP（Packet Data Protocol，分组数据协议）格式。注意，参数 `<PDP_type>`：网络不支持 PPP 模式，设置 PPP 时模组会默认切换为 IPV4。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+CGDCONT=<cid>[,<PDP_type>[,<APN>[,<PDP_addr>[,<d_comp>[,<h_comp>]]]]]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+CGDCONT?<CR>` | `<CR><LF>+CGDCONT: <cid>,<PDP_type>,<APN>,<PDP_addr>,<d_comp>,<h_comp><CR><LF>OK<CR><LF>` |
| 测试 | `AT+CGDCONT=?<CR>` | `<CR><LF>+CGDCONT: [list of supported (<cid>,<PDP_type>,<d_comp>,<h_comp>)]<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<cid>` | (PDP Context Identifier) 一个数字参数，指定一个 PDP 上下文定义，这个参数是当地的 TE-MT 接口并且被应用到其他 PDP 上下文相关的命令当中，使用查询命令可以查询到允许的值（最小值为 1） |
| `<PDP_type>` | (Packet Data Protocol type) 字符串参数，用于指定分组数据协议的类型。"IP" 网络协议（Internet Protocol）（IETF STD 5） |
| `<APN>` | (Access Point Name) 字符串形式，是一个逻辑名称，用来选择 GGSN 或者外部分组数据网，支持的字符范围参考 TS 23003 9.1.1 |
| `<PDP_address>` | 字符串形式，用来在地址空间中区分 MT。如果不写这个参数，则在 PDP 的启动过程当中由 TE 提供这个值。如果 TE 提供失败，就请求动态地址，即使在 PDP 的启动过程当中分配了地址，在使用这条指令查询的时候仍然会返回空 |
| `<d_comp>` | 数字参数用来控制 PDP 数据压缩（仅适用于 SNDCP）。0 - off（缺省情况下默认值） |
| `<h_comp>` | 数字参数用来控制 PDP 头部压缩。0 - off（缺省情况下默认值） |
| `<pd1>`, … `<pdN>` | 0 到 N，字符串类型，意义与 `<PDP_type>` 有关 |

**示例**

```
AT+CGDCONT=1,"IP","CMNET"             ← 设置 PDP 格式，PDP 类型为 IP，APN 名称为 CMNET
OK
AT+CGDCONT?                            ← 查询当前 PDP 格式
+CGDCONT: 1,"IP","CMNET"," IPV4:0.0.0.0",0,0
OK
AT+CGDCONT=?                           ← 查询设置 PDP 格式的取值范围
+CGDCONT: (1-7),(IP,IPV6,IPV4V6,PPP,Non-IP),(0-3),(0-4)
OK
```

---

## 4.21 AT+XGAUTH — 用户认证

PDP 认证。该指令要放在 `AT+CGDCONT` 这条指令后面。目前在专网中各个地方逐渐增加了用户身份认证需求，使用内部协议栈，需要使用到这条指令，因此，请在代码流程上加上这条指令。联通卡默认用户名和密码是 "card" 和 "card"。`<cid>` 对应 `+CGDCONT` 中的 `<cid>`。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+XGAUTH=<cid>,<auth>[,<name>,<pwd>]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 测试 | `AT+XGAUTH=?<CR>` | `<CR><LF>+XGAUTH: (list of supported <cid>),(value range of <auth>),(length of <name>),(length of <pwd>)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<cid>` | (PDP Context Identifier) 一个数字参数，指定一个 PDP 上下文定义。`<cid>` 对应 `+CGDCONT` 中的 `<cid>` |
| `<auth>` | 鉴权类型，默认为 1。0：NONE；1：PAP；2：CHAP。鉴权类型为非 NONE 时，需带 `<name>` 和 `<pwd>` 参数 |
| `<name>` | 用户名 |
| `<pwd>` | 密码 |

**示例**

```
AT+XGAUTH=1,1,"gsm","1234"            ← 设置第一个 PDP 认证
OK
AT+XGAUTH=?                            ← 查询参数值范围
+XGAUTH: (1-7),(0-2),32,32
OK
```

---

## 4.22 AT+CGATT — 设置 GPRS 附着和分离

该指令用来查询、设置 GPRS 附着和分离。掉电不保存。模组默认情况下，会主动进行 GPRS 附着。进行 PPP 连接之前要确保 GPRS 是处于附着状态，AT 流程增加查询指令 `AT+CGATT?`：如果返回值是 1，则可以直接进行 PPP 连接；如果返回值是 0，则需进行手动附着，即 `AT+CGATT=1`。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+CGATT=<state><CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>GPRS DISCONNECTION<CR><LF>`<br>或 `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+CGATT?<CR>` | `<CR><LF>+CGATT: <state><CR><LF>OK<CR><LF>` |
| 测试 | `AT+CGATT=?<CR>` | `<CR><LF>+CGATT: (value range of <state>)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<state>` | 取值范围（0~1）。0：表示分离；1：表示附着 |

**示例**

```
AT+CGATT=1                             ← GPRS 附着成功
OK
AT+CGATT=0                             ← GPRS 分离成功
OK
AT+CGATT=0                             ← 在建立 PPP 链接（AT+XIIC=1）后，使用该指令的返回值
OK
GPRS DISCONNECTION
AT+CGATT=0                             ← 不插 SIM 时，返回 ERROR
ERROR
AT+CGATT?                              ← 查询 GPRS 状态
+CGATT: 0
OK
AT+CGATT=?                             ← 查询指令支持参数
+CGATT: (0-1)
OK
```

---

## 4.23 ATE1/ATE0 — 打开 & 关闭回显

打开（或关闭）模组 AT 指令回显功能。该模组默认回显功能为打开状态。该指令设置后掉电不保存。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `ATE[<value>]<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<value>` | 回显开关。0：关闭回显（默认）；1：打开回显。ATE 等同于 ATE0 |

**示例**

```
ATE1                                   ← 打开模组 AT 指令回显功能
OK
AT                                     ← 发送 AT，串口工具显示 "AT" 及 "OK"
OK
ATE0                                   ← 关闭模组 AT 指令回显功能
OK
AT                                     ← 发送 AT，串口工具只显示 "OK"
OK
```

---

## 4.24 ATD*99# — GPRS

使用外部协议栈，进行 GPRS 拨号连接。进行拨号之前一定要确保 CREG 已经注册成功，并且设置了 APN。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `ATD*99#<CR>` | `<CR><LF>CONNECT<CR><LF>` |

**参数**

无。

**示例**

```
ATD*99#                                ← 开始拨号连接
CONNECT                                ← 拨号成功的返回值
```

---

## 4.25 AT+ENPWRSAVE — 休眠（Sleep）设置

设置是否允许模组进入休眠（Sleep）模式。该命令设置掉电不保存。模组 DTR 信号默认为低电平：发送允许进入休眠模式指令之后，且模组 DTR 信号为低（或高）电平，模组内部各个部分的电路都允许进入休眠状态模组才能进入休眠。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+ENPWRSAVE=<n>[,<usb>]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+ENPWRSAVE?<CR>` | `<CR><LF>+ENPWRSAVE: <n>,<usb><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<n>` | 0：不允许进入休眠模式（默认）；1：允许进入休眠模式（DTR 信号低电平进入休眠，高电平退出休眠）；2：允许进入休眠模式（DTR 信号高电平进入休眠，低电平退出休眠） |
| `<usb>` | 0：不允许 USB 远程休眠唤醒（缺省）；1：使能 USB 远程休眠唤醒（USB 主机挂起 USB 总线模组才能进入休眠，USB 主机恢复 USB 总线会唤醒模组，有网络下行事件（数据、短信、电话）时模组会通过 USB 总线唤醒 USB 主机） |

**示例**

```
AT+ENPWRSAVE=1,1                       ← 设置允许模组进入休眠模式，允许 USB 远程休眠唤醒
OK
AT+ENPWRSAVE?                          ← 查询模组休眠模式使能状态
+ENPWRSAVE: 1,0
OK
```

---

## 4.26 AT+SIGNAL — 设置模组信号灯的状态

设置信号灯不同的闪烁状态。参数如果没有设置过，默认为状态 7；休眠模式下，来电或者短信，在 0-6 模式下网络灯保持常灭；设置该参数后，掉电保存；8、9、10 模式掉电不保存。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+SIGNAL=<value><CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+SIGNAL?<CR>` | `<CR><LF>+SIGNAL: <value><CR><LF>OK<CR><LF>` |
| 测试 | `AT+SIGNAL=?<CR>` | `<CR><LF>+SIGNAL: (value range of <value>)<CR><LF>OK<CR><LF>` |

**参数**

`<value>`：整型，取值范围 0~11，各模式含义如下：

| value | 说明 |
| --- | --- |
| 0 | 一种状态，正常状态一秒闪烁一次，异常状态都不亮或者常亮 |
| 1 | 一种状态，连接上 GPRS 数据业务每秒闪烁一次，其他情况不亮 |
| 2 | 两种状态（快闪和慢闪），GPRS 数据业务 250 毫秒闪烁一次（快闪），其他正常状态 1 秒闪烁一次（慢闪） |
| 3 | 连接上 GPRS 数据业务灯常亮，其他情况每秒闪烁一次 |
| 4 | 连接上 GPRS 数据业务灯常亮，其他情况不亮 |
| 5 | 开机后检查不到 SIM 卡时灯灭，检查到 SIM 卡灯每秒闪烁一次，连接上 GPRS 数据业务灯常亮 |
| 6 | 四种闪灯状态：(1) 无卡、未注册网络时，指示灯按 1S 周期闪烁，亮 0.1S；(2) 已注册网络，指示灯按 3S 周期闪烁，亮 0.1S；(3) 连接上 GPRS 数据业务时，按 250mS 周期闪烁，亮 0.1S；(4) 通话时常亮 |
| 7 | 四种闪灯状态：(1) 无卡、未注册网络时，指示灯灭；(2) 已注册网络，指示灯常亮；(3) 获取 IP 地址以后，灯亮 0.2 秒，灭 1.8 秒（慢闪）；(4) 连接服务器以后，灯亮 1.8 秒，灭 0.2 秒（快闪） |
| 8 | 常灭 |
| 9 | 常亮 |
| 10 | 自定义亮灭时间，亮灭时间由 `<low_interval>`、`<high_interval>` 决定 |
| 11 | 没有注册网络，长灭；正在搜网，灯亮 100ms，灭 800ms；注册上网：灯亮 100ms，灭 3000ms；拨号成功：亮 100ms，灭 300ms |

| 参数 | 说明 |
| --- | --- |
| `<low_interval>` | 仅模式 10 生效，灭时间，范围 10-65535 ms |
| `<high_interval>` | 仅模式 10 生效，亮时间，范围 10-65535 ms |

**示例**

```
AT+SIGNAL?                             ← 查询当前信号灯状态为 2
+SIGNAL: 2
OK
AT+SIGNAL=3                            ← 设置当前信号灯状态为 3
OK
AT+SIGNAL=100                          ← 指令参数设置错误，超出范围
ERROR
AT+SIGNAL=?                            ← 可设置的信号灯状态范围为 0-11
+SIGNAL: (0-11)
OK
```

---

## 4.27 AT+CESQ — 扩展信号强度

查询扩展信号强度。如果当前注册的不是 2G 网络，`<rxlev>`、`<ber>` 值为 99；不支持 3G，`<rscp>`、`<ecno>` 值为 255；如果当前注册的不是 4G，`<rsrq>`、`<rsrp>` 值为 255；不支持 5G 网络，`<ss_rsrq>`、`<ss_rsrp>`、`<ss_sinr>` 不显示；详细对应规则见 3GPP TS 27.007 8.69。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CESQ<CR>` | `<CR><LF>+CESQ: <rxlev>,<ber>,<rscp>,<ecno>,<rsrq>,<rsrp>,<ss_rsrq>,<ss_rsrp>,<ss_sinr><CR><LF>OK<CR><LF>` |
| 测试 | `AT+CESQ=?<CR>` | `<CR><LF>+CESQ: (list of supported <rxlev>s),(list of supported <ber>s),(list of supported <rscp>s),(list of supported <ecno>s),(list of supported <rsrq>s),(list of supported <rsrp>s),(list of supported <ss_rsrq>s),(list of supported <ss_rsrp>s),(list of supported <ss_sinr>s)<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<rxlev>` | 信号接收功率 |
| `<ber>` | 误码率 |
| `<ecno>` | 下行载波干扰比率 |
| `<rsrq>` | 参考信号质量 |
| `<rsrp>` | 参考信号接收功率 |
| `<ss_rsrq>` | 参考信号指令（基于同步信号） |
| `<ss_rsrp>` | 参考信号接收功率（基于同步信号） |
| `<ss_sinr>` | 信噪比（基于信号同步） |

**示例**

```
AT+CESQ                                ← 查询信号强度
+CESQ: 99,99,255,255,16,47
OK
AT+CESQ=?                              ← 信号显示范围
+CESQ: (0-62,99),(0-7,99),(255),(255),(0-34,255),(0-97,255)
OK
```

---

## 4.28 AT+NWDNS — 域名解析

内置协议栈拨号后，查询 DNS 解析结果。先使用 `AT+XIIC` 命令拨号成功后，才能执行该命令。域名填入不校验正确性，需保证填入内容的正确性。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+NWDNS=<hostname><CR>` | `<CR><LF>+NWDNS: <Sign>,<IP><CR><LF><CR><LF>+NWDNS: <Sign>,<IP><CR><LF><CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+NWDNS?<CR>` | `<CR><LF>+NWDNS: <Sign>,<IP><CR><LF><CR><LF>+NWDNS: <Sign>,<IP><CR><LF><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<hostname>` | 字符串，域名，最大长度 128 |
| `<IP>` | 字符串，IP 地址 |
| `<Sign>` | 字符串，IP 类型，IPV4，IPV6 |

**示例**

```
AT+NWDNS="WWW.BAIDU.COM"               ← 拨号后，查询百度域名，返回结果，没有 IPV6 的地址，所以为空
+NWDNS: IPV4,"220.181.112.244"
+NWDNS: IPV6,""
OK
AT+NWDNS="www.google.com"              ← 查询 google 域名超时
ERROR
AT+NWDNS="www.google.com"              ← 未拨号，查询 DNS 解析结果，返回 PDP 未激活
ERROR
AT+NWDNS?                              ← 查询获取到的 IP
+NWDNS: IPV4,"220.181.112.244"
+NWDNS: IPV6,""
OK
```

---

## 4.29 AT+CGREG — 查询网络注册状态

查询模组的当前 GPRS 网络注册状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CGREG=[<n>]<CR>` | `<CR><LF>OK<CR><LF>`<br>或 `<CR><LF>ERROR<CR><LF>`<br>或 `<CR><LF>+CGREG:<stat>[,<lac>,<ci>[,<Act>]]<CR><LF>` |
| 查询 | `AT+CGREG?<CR>` | `<CR><LF>+CGREG: <n>,<stat><CR><LF>OK<CR><LF>` |
| 测试 | `AT+CGREG=?<CR>` | `<CR><LF>+CGREG: range of supported <n><CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| `<n>` | 0：禁止网络注册主动提供结果代码（默认设置）；1：允许网络注册主动提供结果代码；2：允许网络注册主动提供所在地讯息（CELL ID、LOCAL ID） |
| `<stat>` | 0：未注册，终端当前并未在搜寻新的运营商；1：已注册本地网络；2：未注册，终端正在搜寻基站；3：注册被拒绝；4：未知代码；5：已注册，处于漫游状态；6：ltesms only home；7：ltesms only roaming；8：EMER SVCE ONLY；9：CSFB NOT PREFER HOME；10：CSFB NOT PREFER ROAMING |
| `<lac>` | 字符串型，2 字节十六进制位置区代码 |
| `<ci>` | 字符串型，4 字节十六进制小区编号 |
| `<Act>` | 0：GSM；1：GSM compact；2：UTRAN；3：GSM w/EGPRS；4：UTRAN w/HSDPA；5：UTRAN w/HSUPA；6：UTRAN w/HSDPA AND w/HSUPA；7：E-UTRAN；8：UTRAN w/HSPA+ |

**示例**

```
AT+CGREG=1                             ← 允许模组主动提供网络注册代码
OK
AT+CGREG?                              ← 查询模组当前 GPRS 网络注册状态信息
+CGREG: 0,1
OK
AT+CGREG=?                             ← 查询模组 GPRS 网络注册状态值范围
+CGREG: (0-2)
OK
```
