# 第 6 章 TCP/UDP客户端指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 6 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 6.1 AT+NETAPN — 设置网络APN

设置网络APN。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NETAPN="APN","username","` |  |
| 设置 | `password"<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+NETAPN:` |
| 查询 | `AT+NETAPN?<CR>` | `"APN","username","password" <CR><LF> OK<CR><LF>` |

**参数**

| APN | GPRS 网络接入点 |
| --- | --- |
| username | GPRS 用户名 |
| password | GPRS 密码 |

**示例**

```
AT+NETAPN="CMNET","","" 设置GPRS 网络接入点为“CMNET”，用户名、密码为空
OK
AT+NETAPN=CMNET,, 参数要用双引号
ERROR
AT+NETAPN? 查询当前设置的APN 参数
+NETAPN: "","",""
OK
```


### 6.2 AT+XIIC — 建立PPP 链接

建立PPP 连接，获取IP 地址。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+XIIC=<n><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+XIIC: <state>,<ip>` |
| 查询 | `AT+XIIC? <CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <n> | 0：断开PPP 连接 |
| --- | --- |
|  | 1：激活PPP 连接 |
| <state> | 0：PPP 连接已断开 |
|  | 1：PPP 连接已激活 |
|  | IP 地址 |

**示例**

```
AT+XIIC=1 建立第一个PPP 连接
OK
AT+XIIC? 第一个PPP 链路建立成功，IP 地址是10.107.216.162。 （1 前面有4 个空格）
+XIIC:1, 10.107.216.162
OK
AT+XIIC? PPP 链路还未建立成功， （0 前面有4 个空格）
+XIIC:0, 0.0.0.0
OK
在建立PPP 链路之前，先要使用AT+CGDCONT 设定APN 等参数。如对于中国移动的网络，可使

用如下指令设定APN 等参数：AT+CGDCONT=1,”IP”,”CMNET”；
在使用AT+XIIC=1 建立PPP 连接之前，先要确保模组已经注册上网络。可使用AT+CREG?来判断，

如果返回+CREG: 0,1 或+CREG: 0,5，都表明已注册上网络。
```


### 6.3 AT+TCPSETUP — 建立TCP 连接

建立TCP 连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+TCPSETUP=<n>,<ip>,<port><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**主动上报**

+TCPSETUP: 0,<result>

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <ip> | 目的IP 地址，必须是形如xx.xx.xx.xx 的输入，或者形如www.china.com（域名） |
| <port> | 目的端口号，必须是十进制的ASCII 码。 |
| <result> | 结果码 |
|  | OK 建立成功 |
|  | FAIL 建立失败 |

**示例**

```
AT+TCPSETUP=0,220.199.66.56,6800 在链路0 上建立到 220.199.66.56,6800 的连接，成功
OK
+TCPSETUP: 0,OK
AT+TCPSETUP=0,neowayjsr.oicp.net,60010 在链路0 上建立到 neowayjsr.oicp.net,60010 的连接，成功
OK
+TCPSETUP: 0,OK
+TCPCLOSE: 0,Link Closed
AT+TCPSETUP=1,192.168.20.6,7000 在链路1 上建立到192.168.20.6,7000 的连接失败，失败的原因有 可能是服务器未开通，IP 地址或端口不正确，或者是SIM 卡欠费，等等
OK
+TCPSETUP: 1,FAIL
AT+TCPSETUP=0,neowayjsr.oicp.net,60010 当前链路0 的TCP/UDP 链接已存在
+TCPSETUP: 0,ERROR1
AT+TCPSETUP=6,192.168.20.6,7000 AT 指令参数错误
+TCPSETUP: ERROR
AT+TCPSETUP=0.58.60.184.213.10012 AT 指令参数错误
+TCPSETUP: ERROR
AT+TCPSET=0,58.60.184.213,10012 AT 指令格式错误，指令不完整
ERROR
输入AT 指令后，若指令格式正确，会立即返回OK；若指令参数不正确会返回+TCPSETUP: ERROR；

或者如链路0 已经在使用中会返回+TCPSETUP: 0,ERROR1；
使用前建议先AT+XIIC=1 建立PPP 链接。

```


### 6.4 AT+TCPSEND — 发送TCP 数据

发送 TCP 数据的命令，支持buffer 模式与命令模式，支持ASCII 与hex 发送。这条命令发送完毕 后，会接收到大于号">"，这时候请延迟50ms-100ms，然后发送数据。 命令设置参数不保存，每次发送需要设置模式。 在发送TCP 数据之前，必须确保TCP 链路已经建立；  建议在发送数据之前，先使用AT+IPSTATUS 查看可用的buffer 大小。  在命令模式发送ASCII 数据，第三个参数content 长度必须小于等于1024。  Content 内容的逗号个数必须小于15 个，若需要传输大量逗号的数据，建议使用buffer 模式。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `Or Or Or AT+TCPSEND=<n>,<length` | `<CR><LF>><content> <CR><LF>OK<CR><LF> <CR><LF>OK<CR><LF> <CR><LF>+TCPSEND: ERROR<CR><LF> <CR><LF>+TCPSEND: <n>,OPERATION` |
| 执行 | `>[[,<content>][,mode]]<CR> Or Or Or` | `EXPIRED<CR><LF> <CR><LF>+TCPSEND: SOCKET ID OPEN FAILED<CR><LF> <CR><LF>+TCPSEND: DATA LENGTH ERROR<CR><LF> <CR><LF>ERROR<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5，且该链路已建立了TCP 连接。 |
| --- | --- |
| <length> |  | 要发送的数据长度，以字节为单位。length 的范围： |
| --- | --- | --- |
|  |  | buffer 模式发送ASCII 数据：1～4096； |
|  |  | buffer 模式发送HEX 数据：1～2048； |
|  |  | 命令模式发送HEX 数据：1～512； |
|  |  | 命令模式发送ASCII 数据：1～512。 |
|  | <content> | 命令模式下发送的数据，content 长度范围0～1024。 |
| <mode> | <mode> | HEX 发送启用开关。 |
|  |  | 0：ASCII 模式发送（默认） |
|  |  | 1：HEX 模式发送 |

**示例**

```
AT+TCPSEND=0,1 在链路0 上发送1 字节的数据， 成功。
>
OK
+TCPSEND: 0,1
AT+TCPSEND=0,1024,,1 Buffer 模式，HEX 模式，发送1024 长度数据,发送成功。
>
OK
+TCPSEND: 0,1024
AT+TCPSEND=0,6,"123459" 命令模式（只能发送纯文本，不能发送特殊符号，影响AT 命令参数解析），发 送数据,发送成功。
OK
+TCPSEND: 0,6
AT+TCPSEND=0,3,”313233”,1 命令模式，HEX 模式，发送数据,发送成功。
OK
+TCPSEND: 0,3
AT+TCPSEND=0,10 输入发送命令出现“>”后，不输入数据，30 秒后提示超时。
>
+TCPSEND: 0,OPERATION EXPIRED
AT+TCPSEND=0,1 在链路0 上发送1 字节的数据，该链路尚未建立，发送失败。
+TCPSEND: SOCKET ID OPEN FAILED
AT+TCPSEND=0,4097 在链路0 上发送4097 字节的数据，超出长度限制，发送失败。
+TCPSEND: DATA LENGTH ERROR
```


### 6.5 AT+RECVMODE — 设置数据接收模式

设置TCP、UDP 数据接收模式。该命令掉电不保存。 该命令设置时会清空接收缓冲区，因此只需要在初始化时设置一次即可，不建议在通信过程中重复 设置。该指令对UDP 同样适用。 AT+RECVMODE 配置的<mode>参数只对模块做客户端时收到的TCP 和UDP 的数据生效，对于模 块做服务器时收到的TCP 和UDP 的数据不生效。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+RECVMODE=<n>[,<mode>]<CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+RECVMODE: <n>,<mode>` |
| 查询 | `AT+RECVMODE?<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+RECVMODE: (list of supported` |
| 测试 | `AT+RECVMODE=?<CR>` | `<n>s), (list of supported <mode>s) <CR><LF>OK<CR><LF>` |

**参数**

| <n> | 模式选择，范围0-1。 |
| --- | --- |
|  | 0：接收到的TCP、UDP 数据缓存起来，输出来数据提示，需要外部MCU 主动发命 |
|  | 令读取数据。 |
|  | 1：接收到的TCP、UDP 数据直接从串口输出(默认) |
| <mode> | 接收数据是否HEX 上报 |
|  | 0：ASCII 上报（默认） |
|  | 1：HEX 上报 |

**示例**

```
AT+RECVMODE=0 设置数据接收模式
OK
AT+RECVMODE=1,1 命令模式，HEX 上报
OK
AT+RECVMODE=? 查询可以设置的参数范围
+RECVMODE: (0-1),(0-1)
OK
```


### 6.6 +TCPRECV — 接收到TCP 数据

指示接收到的TCP 数据。

**主动上报**

+TCPRECV: <n>,<length>,<data><CR>

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <length> | 接收到的数据长度。 |
| <data> | 接收到的数据，尾部追加0x0d 0x0a；用户可根据<length>参数来判断结尾。 |

**示例**

```
+TCPRECV: 0,10,1234567890 在链路0 上收到10 字节的数据，数
据为1234567890
```


### 6.7 AT+TCPREAD — 读取TCP 数据

读取TCP 数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+TCPREAD=<n>,<length><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <length> | 本次允许读取的最大数据长度，范围1-2048 字节。 |

**示例**

```
+TCPRECV: 0 RECVMODE=0
AT+TCPREAD=0,100 在链路0 上收到数据
+TCPREAD: 0,10,1234567890 读取数据
OK 读取到10 个数据为1234567890
需要通过+RECVMODE 指令选择接收模式。
```


### 6.8 AT+TCPCLOSE — 关闭TCP 连接

关闭TCP 连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+TCPCLOSE: <n>,OK<CR><LF>` |
| 执行 | `AT+TCPCLOSE=<n><CR>` | `Or <CR><LF>+TCPCLOSE: ERROR<CR><LF>` |

**主动上报**

+TCPCLOSE: 0,Link Closed

**参数**

| <n> | 链路编号，0~5。 |
| --- | --- |

**示例**

```
AT+TCPCLOSE=1 主动关闭：关闭链路1 的TCP 连接成功
+TCPCLOSE: 1,OK
AT+TCPCLOSE=2 链路号错误，失败
+TCPCLOSE: ERROR
+TCPCLOSE: 0,Link Closed
```


### 6.9 AT+UDPSETUP — 建立UDP 连接

建立UDP 连接。 使用前需要使用AT+XIIC=1 建立PPP 链接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `Or Or 若参数有误，会返回+UDPSETUP: ERROR；  或者如链路0 已经在使用中会返回+UDPSETUP: 0,ERROR1。  AT+UDPSETUP=<n>,<ip>,` | `<CR><LF>ERROR<CR><LF> <CR><LF>+UDPSETUP: ERROR<CR><LF> <CR><LF>OK<CR><LF>` |
| 执行 | `<port><CR>` | `<CR><LF>+UDPSETUP: <n>,<result><CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <ip> | 目的IP 地址，必须是形如xx.xx.xx.xx 的输入，或者形如www.china.com（域名） |
| <port> | 目的端口号，必须是十进制的ASCII 码。 |
| <result> | 结果码 |
|  | OK 成功 |
|  | FAIL 失败 |
|  | ERROR1 当前链路上的连接已存在。 |

**示例**

```
AT+UDPSETUP=1,220.199.66.56,7000 在链路1 上建立到220.199.66.56,7000 的连接，成功。
OK
+UDPSETUP: 1,OK
AT+UDPSETUP=0,neowayjsr.oicp.net,60010 在链路0 上建立到，neowayjsr.oicp.net,60010 的连接，成功。
OK
+UDPSETUP: 0,OK
AT+UDPSETUP=0,58.60.184.213,11008 当前链路0 的TCP/UDP 连接已存在。
+UDPSETUP: 0, ERROR1
AT+UDPSETUP=1,192.168.20.6,7000 在链路1 上建立到192.168.20.6,7000 的连接，失败。
OK
+UDPSETUP: 1,FAIL
AT+UDPSETUP=6,192.168.20.6,6800 链路号错误
+UDPSETUP: ERROR
AT+UDPSETUP=0.58.60.184.213.10012 标点错误
+UDPSETUP: ERROR
AT+UDPSET=0,58.60.184.213,10012 AT 指令格式错误，指令不完整
ERROR
```


### 6.10 AT+UDPSEND — 发送UDP 数据

发送UDP 数据的命令。 在发送UDP 数据之前，必须确保UDP 链路已经建立；命令设置参数不保存。每次发送需要设置 模式。Buffer 模式下，且这条命令发送完毕后，会接收到大于号">"，这时候请延迟50ms-100ms，然 后发送数据。 buffer 模式HEX 数据最大支持2048 字节，ASCII 最大支持4096 字节；  建议每次发送数据不大于1472 字节，可降低丢包概率；  转义模式，通过反斜杠实现转义，命令模式的字符串中想要发送单双引号或者反斜杠，可以通过下述  方式进行，具体见示例； 可省略mode 设置参数，默认为ASCII 支持转义模式；  在命令模式发送ASCII 数据，第三个参数content 长度必须小于等于102 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+UDPSEND=<n>,<length>[[,<content>` | `<CR><LF>> <CR><LF>OK<CR><LF> <CR><LF>+UDPSEND: <n>,<length> Or` |
| 执行 | `][,mode]]<CR>` | `<CR><LF>+UDPSEND: <n>, OPERATION EXPIRED<CR><LF> Or <CR><LF>+UDPSEND: DATA LENGTH ERROR<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5，且该链路已建立了UDP 连接。 |
| --- | --- |
| <length> | 要发送的数据长度，以字节为单位。 |
|  | length 的范围： |
|  | buffer 模式发送HEX 数据：1～2048； |
|  | buffer 模式发送ASCII 数据：1～4096； |
|  | 命令模式发送HEX 数据：1～512； |
|  | 命令模式发送ASCII 数据：1～512。 |
| <content> | 命令模式下发送的数据，content 长度范围0～1024 |
| Content 内容的英文逗号个数必须小于15 个，若需要传输大量英文逗号的数据，建 |
| --- |
| 议使用buffer 模式。 |
| HEX 发送启用开关 |
| 0：ASCII 模式发送 |
| 1：HEX 模式发送 |

**示例**

```
AT+UDPSEND=0,1024,,1 Buffer 模式，hex 模式，发送1024 长度数据，发送成功。
>
OK
+UDPSEND: 0,1024
AT+UDPSEND=0,10,"DEGHHRFRRD",0 命令模式，发送ASCII 模式数据成功。
OK
+UDPSEND: 0,10
AT+UDPSEND=0,4097 在链路0 上发送4097 字节的数据，超出长度限制，发送失败。
+UDPSEND: DATA LENGTH ERROR
AT+UDPSEND=1,6,”313233343536”,1 命令模式，HEX 模式，发送数据成功。
OK
+UDPSEND: 0,6
AT+UDPSEND=0,10 输入发送命令出现“>”后，延时30 秒提示的超时提示。
>
+UDPSEND: 0,OPERATION EXPIRED
```


### 6.11 +UDPRECV — 接收到UDP 数据

接收到UDP 数据。

**主动上报**

+UDPRECV: <n>,<length>[,<data>]<CR>

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <length> | 接收到的数据长度。 |
| <data> | 接收到的数据。尾部追加0x0d 0x0a。用户可根据<length>参数来判断结尾。 |

**示例**

```
+UDPRECV: 0,10,1234567890 在链路0 上收到10 字节的数据，为1234567890
```


### 6.12 AT+UDPREAD — 读取UDP 数据

读取UDP 数据。需要通过+RECVMODE 指令选择接收模式。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+UDPREAD: <n>,<length>,<data> <CR><LF>OK<CR><LF> Or` |
| 执行 | `AT+UDPREAD=<n>[,<length>]<CR>` | `<CR><LF>+UDPREAD:SOCKET ID OPEN FAILED<CR><LF> Or <CR><LF>+UDPREAD: ERROR<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <length> | 本次允许读取的最大数据长度，范围1-1024 字节。 |
| <data> | 读取到的UDP 数据。 |

**示例**

```
+UDPRECV: 0 在链路0 上收到数据 读取数据 读取到10 个数据为1234567890
AT+UDPREAD=0,100
+UDPREAD: 0,10,1234567890
OK
AT+UDPREAD=1,100 1 号链路未建立
+UDPREAD: SOCKET ID OPEN FAILED
AT+UDPREAD=0,0 参数错误
+UDPREAD: ERROR
```


### 6.13 AT+UDPCLOSE — 关闭UDP 连接

关闭UDP 连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+UDPCLOSE: <n>,OK<CR><LF>` |
| 执行 | `AT+UDPCLOSE=<n><CR>` | `Or <CR><LF>+UDPCLOSE: ERROR<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |

**示例**

```
AT+UDPCLOSE=1 关闭链路1 的UDP 连接，成功
+UDPCLOSE: 1,OK
AT+UDPCLOSE=6 链路号错误
+UDPCLOSE: ERROR
```


### 6.14 AT+IPSTATUS — 查询TCP/UDP 透传链路状态

查询TCP/UDP 透传链路状态。 由于UDP 的特点，该指令仅能查询是否已经通过指令建立链接，并不代表链接的真实情况。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+IPSTATUS: <n>,<CONNECT or DISCONNECT >[,<TCP or UDP>,<send-buffer-size>] <CR><LF>OK<CR><LF>` |
| 执行 | `AT+IPSTATUS=<n><CR> Or Or` | `<CR><LF>+IPSTATUS: 1,DISCONNECT<CR><LF> <CR><LF>ERROR<CR><LF>` |

**参数**

|  | <STATUS> | 该链路的状态，取值为 CONNECT 或者 DISCONNECT。 |
| --- | --- | --- |
| <CONNECT or DISCONNECT> | <CONNECT or DISCONNECT> | 该链路的状态，取值为 CONNECT 或者 DISCONNECT 或 CONNECTING 或DISCONNECTING。 |
|  | <TCP or UDP> | 链路类型，取值为 TCP 或者 UDP。 |
| --- | --- | --- |
| <send-buffer-size> | <send-buffer-size> | 模组内部可用的 send buffer 的大小，十进制 ASCII 码表示， |
|  |  | 单位为字节。 |

**示例**

```
AT+IPSTATUS=0 链路0，已建TCP 连接，可用buffer 为4096 字节
+IPSTATUS: 0,CONNECT,TCP,4096
AT+IPSTATUS=0 链路0，已建UDP 连接
+IPSTATUS: 0,CONNECT,UDP,0
AT+IPSTATUS=1 链路1，未建立任何“TCP/UDP”连接
+IPSTATUS: 1,DISCONNECT
AT+IPSTATU AT 指令格式错误，指令不完整
ERROR
AT+IPSTATUS=6 指令链路编号错误
ERROR
UDP 链路上不支持查询<send-buffer-size>参数。
```


### 6.15 AT+TCPACK — 查询TCP 链路发送数据状态

查询TCP 链路发送成功的数据大小、接收方成功接收该链路的数据大小。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `<CR><LF>+TCPACK: Or` | `<n>,<data_sent>,<acked_recv><CR><LF> <CR><LF>ERROR<CR><LF>` |
| 执行 | `AT+TCPACK<CR> Or Or` | `<CR><LF>+TCPACK: <n>,DISCONNECT<CR><LF> <CR><LF>+TCPACK: NO TCP LINK<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <data sent> _ | 该链路发送成功的链路数据大小，无符号64 位整型数，十进制ASCII 码表示，单位 |
|  | 为字节。 |
| --- | --- |
| <acked recv> _ | 接收方成功接收的链路数据大小，无符号64 位整型数，十进制ASCII 码表示，单位 |
|  | 为字节。 |

**示例**

```
AT+TCPACK=0 链路0，发送成功20 个字节数据，接收方成功接收20 个字节数据
+TCPACK: 0,20,20
AT+TCPACK=0 链路0，发送成功128 个字节数据，接收方成功接收120 个字节数据
+TCPACK: 0,128,120
AT+TCPACK=1 链路1，未建立任何连接
+TCPACK: 1,DISCONNECT
AT+TCPACK=2 链路2 建立的是UDP 连接
+TCPACK: NO TCP LINK
AT+TCPACK=6 指令链路编号错误
ERROR
```


### 6.16 AT+DNSSERVER — 设置DNS 服务器

查询/设置DNS 服务器。 一般来说，用户可以不手动设置 DNS 服务器，在 PPP 协商阶段，基站控制器会给分配DNS 服 务器。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+DNSSERVER=<n>,<dns-ip><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+DNSSERVER: dns1:<dns-` |
| 查询 | `AT+DNSSERVER?<CR>` | `ip1>,dns2: <dns-ip2><CR><LF>` |

**参数**

| <n> | DNS 服务器编号，取值服务器编号，取值 1-2，1 为首选DNS，2 为备选DNS。 |
| --- | --- |
| <dns-ip> | DNS 服务器 IP 地址。 |

**示例**

```
AT+DNSSERVER=1,114.114.114.114 设置DNS 服务器
OK
AT+DNSSERVER? 查询DNS 服务器
+DNSSERVER: dns1:114.114.114.114,dns2:0.0.0.0
```


### 6.17 AT+PDPKEEPALIVE — 设置PDP 心跳

设置PDP 保活心跳。 若设置域名参数，需要先建立PPP 链接。 需激活PDP，心跳起作用。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+PDPKEEPALIVE=<onoff>,<inerval><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+PDPKEEPALIVE:` |
| 查询 | `AT+PDPKEEPALIVE?<CR>` | `<onoff>,<inerval> <CR><LF>OK<CR><LF>` |

**参数**

| <onoff> | 心跳开关。 |
| --- | --- |
|  | 0：关闭(默认) |
|  | 1：打开 |
|  | 心跳间隔，单位s，范围1-65535。 |

**示例**

```
AT+PDPKEEPALIVE? 查询心跳设置
+PDPKEEPALIVE: 1,5
OK
AT+PDPKEEPALIVE=1,60 打开心跳，间隔为60s
OK
```


### 6.18 AT+PDPSTATUS — 查询PDP 状态

查询PDP 状态。 PDP 心跳打开时，查询状态可立即返回。 PDP 心跳未打开时，查询状态会有一些延时，200ms~10000ms，与网络环境有关。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+PDPSTATUS<CR>` | `<CR><LF>+PDPSTATUS: <status><CR><LF>` |

**参数**

| <status> | CONNET 连接状态，在CONNET 后有2 个回车换行 |
| --- | --- |
|  | DISCONNECT 未连接状态，在DISCONNECT 后只有一个回车换行 |
|  | PSEUDO CONNECT _ |

**示例**

```
AT+PDPSTATUS PDP 正常状态
+PDPSTATUS: CONNECT
AT+PDPSTATUS PDP 未激活状态 PDP 已激活，但处于假连接状态
+PDPSTATUS: DISCONNECT
AT+PDPSTATUS
+PDPSTATUS: PSEUDO CONNECT
_
```


### 6.19 AT+TCPKEEPALIVE — TCP 心跳包设置

TCP 持续在线功能。 该指令参数掉电不保存。需要在TCP 建立之前设置，对所有链路均有效，不要在建立TCP 连接之 后使用这条指令。 该功能会额外产生一些流量，请谨慎使用。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+TCPKEEPALIVE=<mode>[,<time>[,` | `<CR><LF>OK<CR><LF>` |
| 设置 | `<interval>[,<keepcount>]]]<CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+TCPKEEPALIVE:` |
| 查询 | `AT+TCPKEEPALIVE? <CR>` | `<mode>,<time>,<interval>,<keepcount> <CR><LF>OK<CR><LF> <CR><LF>+TCPKEEPALIVE: (range of supported <mode>),(range of supported` |
| 测试 | `AT+TCPKEEPALIVE=?<CR>` | `<time>),(range of supported <interval>),(range of supported < keepcount>) <CR><LF>OK<CR><LF>` |

**参数**

不同网络环境下对心跳包发送时间要求不同，请根据网络环境合理设置。若<time>设置时间过长，终  端可能会出现假连接，<interval>时间超过< time>将不会重发；若<time>、<interval>设置时间太短， 终端可能会断开连接，这是由于模组空口存在休眠机制，间隔太短时，若多个心跳包都在休眠期发送， 心跳包会在唤醒后连在一起发送出去，接收侧认为粘包数据无效而不回复确认信息，多次收不到确认 信息终端就认为连接已无效从而主动断开连接。 推荐设置范围：< time>：120 ~ 300，<interval>：40 ~ 100。 

| <mode> | 开启/关闭模式，取值范围0~1,默认值为0。 |
| --- | --- |
|  | 0：关闭 |
|  | 1：开启 |
| <time> | 空闲时间间隔（即TCP 空闲多久后发送KEEPALIVE 数据包给远端服务器）， |
|  | 取值30S~7200S,默认值120。 |
| <interval> | 重发间隔（即TCP 发送KEEPALIVE 数据包后多长时间内没有收到远端服 |
|  | 务器的回复，则重新发送KEEPALIVE 数据包），取值1S~1800S，默认值75。 |
|  | 重发次数（重新发送KEEPALIVE 数据包的次数），取值1-15，默认值9 |

**示例**

```
AT+TCPKEEPALIVE=1 OK 打开KEEPALIVE 功能
AT+TCPKEEPALIVE=1,120,75,9 打开并设置KEEPALIVE 参数
OK
AT+TCPKEEPALIVE=0 关闭KEEPALIVE 功能
OK
AT+TCPKEEPALIVE? 读取当前KEEPALIVE 参数
+TCPKEEPALIVE: 1,120,75,9
OK
AT+TCPKEEPALIVE=?
+TCPKEEPALIVE: (0-1),(30-7200),(1-1800),(1-15)
OK
```

