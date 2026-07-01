# 第 7 章 TCP服务器指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 7 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 7.1 AT+NWTCPSRVCFG — 服务器功能参数配置

配置TCP 服务器非透传模式下扩展选项，配合TCPLISTEN 使用。 该功能掉电不保存。 单栈拨号下侦听占用1 个socket，双栈拨号下占用2 个，当前最多可用4 个socket 资源用于侦听。 若当前有socket 处于侦听状态，不支持设置该指令，会返回+NWTCPSRVCFG: Listening...。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF> Or <CR><LF>+NWTCPSRVCFG:` |
| 设置 | `AT+NWTCPSRVCFG=<option>,<param><CR>` | `<status><CR><LF> Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWTCPSRVCFG:` |
| 查询 | `AT+NWTCPSRVCFG?<CR>` | `<option>,<param><CR><LF> OK<CR><LF> <CR><LF>+NWTCPSRVCFG:` |
| 测试 | `AT+NWTCPSRVCFG=?<CR>` | `"srvlistenmode",(0,1)<CR><LF>` |

**参数**

| <option> | 扩展功能选项，为字符串类型。 |
| --- | --- |
|  | "srvlistenmode"，设置服务器的侦听模式（single port or multiple port）。若设 |
|  | 置为多端口模式，双栈拨号支持两个端口，单栈拨号支持四个端口。 |
| <param> | 扩展功能关联参数，整形。 |
|  | <option>为srvlistenmode 时，param 0 关闭 1 打开 |
|  | Listening… 当前有socket 处于侦听状态，不支持设置该指令 |

**示例**

```
AT+NWTCPSRVCFG="srvlistenmode",1 设置srvlistenmode 为多端口侦听模式
OK
AT+NWTCPSRVCFG? 查询当前设置，已启用多端口侦听
+NWTCPSRVCFG: "srvlistenmode",1
OK
AT+NWTCPSRVCFG=? 当前支持的option 和param 范围
+NWTCPSRVCFG: "srvlistenmode",(0,1)
OK
AT+TCPLISTEN=6800 侦听6800，6801，6802，6803，单栈拨号下最多支持侦听四个端口
+TCPLISTEN: 0,OK
AT+TCPLISTEN=6801
+TCPLISTEN: 1,OK
AT+TCPLISTEN=6802
+TCPLISTEN: 2,OK
AT+TCPLISTEN=6803 建立第五路时会提示Listening
+TCPLISTEN: 3,OK
AT+TCPLISTEN=6804
+TCPLISTEN: Listening...
多端口侦听下，客户端接入主动上报会额外上报ListenPort
Connect
AcceptSocket=4,ClientAddr=192.168.62.14,
ClientPort=50177,ListenPort=6800
Connect
AcceptSocket=5,ClientAddr=192.168.62.14,
ClientPort=50178,ListenPort=6801
Connect
AcceptSocket=6,ClientAddr=192.168.62.14,
ClientPort=50179,ListenPort=6802
Connect
AcceptSocket=7,ClientAddr=192.168.62.14,
ClientPort=50180,ListenPort=6803
```


### 7.2 AT+TCPLISTEN — 设置服务器侦听功能

设置服务器侦听功能。 使用联通卡或者移动的专网卡可以进行调试使用，移动的公网卡不能作为服务器调试。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+TCPLISTEN: <socket>,OK Or` |
| 设置 | `AT+TCPLISTEN=<port><CR>` | `<CR><LF>+TCPLISTEN: <status><CR><LF> Or <CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+TCPLISTEN?<CR>` | `<CR><LF>+TCPLISTEN: <status><CR><LF>` |

**参数**

| <port> | 端口号 |
| --- | --- |
| <socket> | socket 号 |
| <status> | Listening… |
|  | bind error |
|  | not listening |
|  | listening status |

**示例**

```
AT+TCPLISTEN=6800 侦听端口号6800
+TCPLISTEN: 0,OK 服务器侦听开始启动
AT+TCPLISTEN=6800 侦听端口号6800
+TCPLISTEN: bind error 绑定失败
AT+TCPLISTEN=6800 如果已经设置了侦听，再设置的话，会提示Listening...
+TCPLISTEN: Listening...
AT+TCPLISTEN? 查询侦听状态，表示当前处于侦听。
+TCPLISTEN: listening status
AT+TCPLISTEN? 查询侦听状态，表示当前没有侦听。
+TCPLISTEN: not listening
Connect 收到主站连接请求，其AcceptSocket 是主站跟模组建立的socket， 119.123.77.133 是主站的IP 地址，8000 是主站的端口号。
AcceptSocket=1,ClientAddr=119.123.77.133
,ClientPort=8000
```


### 7.1 AT+CLOSELISTEN — 关闭侦听链接

关闭侦听链接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | Or | `<CR><LF>+TCPSRVTRANS: All remote link closed<CR><LF> <CR><LF> +TCPSRVTRANS: <socket_id>, remote link closed<CR><LF> <CR><LF> +TCPSRVTRANS: <socket_id>, local link closed<CR><LF> <CR><LF>+CLOSECLIENT: All remote link closed<CR><LF> <CR><LF> +CLOSECLIENT: <socket_id>, remote link closed<CR><LF> <CR><LF>` |
| 执行 | `AT+CLOSELISTEN<CR> Or Or Or` | `+CLOSELISTEN: <socket_id>, local link closed<CR><LF> <CR><LF>+TCPSRVTRANS: All remote link closed<CR><LF> <CR><LF> +TCPSRVTRANS: <socket_id>, local link closed<CR><LF> <CR><LF>+CLOSECLIENT: All remote link closed<CR><LF> <CR><LF> +CLOSELISTEN: <socket_id>, local link closed<CR><LF> <CR><LF>OK<CR><LF>` |

**主动上报**

+CLOSELISTEN:<socket_id>,local link closed

**参数**

| <socket id> _ | socket 号 |
| --- | --- |

**示例**

```
+CLOSELISTEN: 0,local link closed 主站关闭链接或网络异常时，会主动上报该回码。
AT+CLOSELISTEN 如果建立了透传服务器，没有客户端连接时关闭侦听时的回码如下
+TCPSRVTRANS: All remote link closed
+TCPSRVTRANS: 0,local link closed
AT+CLOSELISTEN 如果建立了非透传服务器，没有客户端连接时关闭侦听时的回码如下
+CLOSECLIENT: All remote link closed
+CLOSELISTEN: 0,local link closed
AT+CLOSELISTEN 如果建立了透传服务器，有客户端连接时关闭侦听时的回码如下
+TCPSRVTRANS: All remote link closed
+TCPSRVTRANS: 1,remote link closed
+TCPSRVTRANS: 0,local link closed
AT+CLOSELISTEN 如果建立了非透传服务器，有客户端连接时关闭侦听时的回码如下
+CLOSECLIENT: All remote link closed
+CLOSECLIENT: 1,remote link closed
+CLOSELISTEN: 0,local link closed
AT+TCPSRVTRANS? 当前未侦听时，关闭返回失败。 多端口侦听，关闭侦听时代码返回如下
+TCPSRVTRANS: not listening
AT+CLOSELISTEN
ERROR
AT+CLOSELISTEN
+CLOSECLIENT: All remote link closed
+CLOSECLIENT: All remote link closed
+CLOSECLIENT: All remote link closed
+CLOSECLIENT: All remote link closed
+CLOSELISTEN: 0,local link closed
+CLOSELISTEN: 1,local link closed
+CLOSELISTEN: 2,local link closed
+CLOSELISTEN: 3,local link closed
模块做服务器的时候，客户端连接到服务器，使用AT+CLOSELISTEN 关闭服务器，有几个客户端
断开就会上报对应的socketid 和断开的回码，建立非透传服务器后主动关闭侦听的回码和建立透传服务
器后主动关闭侦听的回码有区别，可以参考上面的示例。
```


### 7.2 AT+CLOSECLIENT — 关闭主站链接

关闭主站链接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+CLOSECLIENT: <socket>,remote link closed<CR><LF> Or` |
| 执行 | `AT+CLOSECLIENT[=<socket>]<CR>` | `<CR><LF>ERROR<CR><LF> Or <CR><LF>+CLOSECLIENT: All remote link closed<CR><LF><CR><LF>` |

**参数**

| <socket> | socket 号。 |
| --- | --- |

**示例**

```
AT+CLOSECLIENT 不带参数，多个关闭。
+CLOSECLIENT: 1,remote link closed
+CLOSECLIENT: 2,remote link closed
AT+CLOSECLIENT=1 带参数，单个关闭。
+CLOSECLIENT: 1,remote link closed
AT+CLOSECLIENT=1 1 链路不存在远程客户端。
ERROR
AT+CLOSECLIENT 所有远程客户端已关闭。
+CLOSECLIENT: All remote link closed
7.3 +TCPRECV(S)–接收到主站的数据
接收到主站的数据。
```

**主动上报**

+TCPRECV(S): <n>,<length>,<data><CR>

**参数**

| <n> | 链路编号，只能为0~5 |
| --- | --- |
| <length> | 接收到的数据长度 |
| --- | --- |
| <data> | 接收到的数据。尾部追加0x0d 0x0a。用户可根据<length>参数来判断结尾 |

**示例**

```
+TCPRECV(S): 1,10,1234567899 链路1 接收到主站发过来的10 个字节的数据，接收字符格式为字符类型
跟客户端模式的接收格式不同，多了符号“(S)”；
跟客户端的参数有所区别，请注意。
```


### 7.4 AT+TCPREADS — 读取到主站的数据

读取到主站的数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF> +TCPREADS:<n>,<length>,<content>` |
| 执行 | `AT+TCPREADS=<n>,<length><CR>` | `<CR><LF>OK<CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <length> | 本次允许读取的最大数据长度，范围1-2048 字节。 |
| <content> | 读取到的数据。 |

**示例**

```
+TCPRECV(S): 1 RECVMODE=0 链路1 接收到主站发过来的10 个字节的数据
AT+TCPREADS=1,100
+TCPREADS: 1,10,1234567890
OK
```


### 7.5 AT+TCPSENDS — 发送给主站的数据

发送给主站的数据。 在发送TCP 数据之前，必须确保TCP 链路已经建立。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `<CR><LF>> Or <CR><LF>> AT+TCPSENDS=<socket>` | `<CR><LF>OK<CR><LF> <CR><LF>+TCPSENDS:<socket>[,<length>]<CR><LF> <CR><LF>+TCPSENDS: Buffer not` |
| 执行 | `[,<length>]<CR> Or Or` | `enough,439<CR><LF> <CR><LF>+TCPSENDS: <socket> is not link<CR><LF> <CR><LF>+TCPSENDS: <socket>, OPERATION EXPIRED<CR><LF>` |

**参数**

| <socket> |  | 侦听到的AcceptSocket 值，即主站跟模组的建立的socket，参考AT+TCPLISTEN 指 |
| --- | --- | --- |
|  |  | 令的说明。 |
|  | <length> | 要发送的数据长度，以字节为单位，取值范围1~4096。 |

**示例**

```
AT+TCPSENDS=0,10 在sokcet 0 上发送10 字节的数据（如：1234567890，发送成功。
>
OK
+TCPSENDS: 0,10
AT+TCPSENDS=0 在链路 0 上发送21 字节的数据（如：012345678901234567890），发送成功。 (不带数据长度时以Ctrl+Z 为结束标志，最长不能超过4096)
>
OK
+TCPSENDS: 0,21
AT+TCPSENDS=0,5 输入发送命令出现“>”后，不输入数据，30 秒后提示超时。
>
+TCPSENDS: 0,OPERATION
EXPIRED
```


### 7.6 AT+CLIENTSTATUS — 查询主站链路的状态

查询主站链路的状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+CLIENTSTATUS:` |
| 执行 | `AT+CLIENTSTATUS=<cid><CR>` | `<cid>,<CONNECTor DISCONNECT>,<TCP orINVALID>, <send-buffer-size><CR><LF>` |

**参数**

链路类型为INVALID 表示该链路不是侦听到的TCP 连接，可能为TCP/UDP 客户端或者服务器侦 听链路。

| <cid> | 特定PDP 上下文定义的数字参数。 |
| --- | --- |
| <CONNECT or | 该链路的状态，取值为CONNECT 或者DISCONNECT。 |
| DISCONNECT> |  |
| <TCP or INVALID> | 链路类型，取值为TCP 或者INVALID。 |
| <send-buffer-size> | 模组内部可用的send buffer 的大小，十进制ASCII 码表示，单位为字节。 |

**示例**

```
AT+CLIENTSTATUS=0 主站socket 0，已建立TCP 连接，可用buffer 为61440 字节。
+CLIENTSTATUS: 0,CONNECT,TCP,61440
AT+CLIENTSTATUS=4 Socket 4，没有建立连接。
+CLIENTSTATUS: 4,DISCONNECT
AT+CLIENTSTATUS=1 Socket 1 作为服务器侦听，链路类型返回INVALID。
+CLIENTSTATUS: 1,CONNECT,INVALID
```


### 7.7 AT+TCPACKS — 查询TCP 服务器发送数据状态

查询TCP 服务器链路发送成功的数据大小、接收方成功接收该链路的数据大小。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | Or | `<CR><LF>+TCPACKS: <socket>,<data_sent>,<acked_recv>` |
| 执行 | `AT+TCPACKS=<socket><CR> Or` | `<CR><LF>+TCPACKS: <socket>,<DISCONNECT> <CR><LF>ERROR<CR><LF>` |

**参数**

<data_sent>、<acked_recv>为无符号64 位整型数，十进制ASCII 码表示，单位为字节。

| <socket> | 侦听到的AcceptSocket 值，即主站跟模组的建立的socket，只能为0~5。 |
| --- | --- |
| <data sent> _ | 模组给主站发送成功的数据大小。 |
| <acked recv> _ | 主站成功接收的数据大小。 |

**示例**

```
AT+TCPACKS=0 模组给Socket 0 主站发送成功20 个字节数据，主站成功接收20 个字节数据。
+TCPACKS: 0,20,20
AT+TCPACKS=0 模组给Socket 0 主站发送成功128 个字节数据，主站成功接收120 个字节数据。
+TCPACKS:0,128,120
AT+TCPACKS=1 链路1，未建立任何连接。
+TCPACKS: 1,DISCONNECT
AT+TCPACKS=6 Socket 错误。
ERROR
```

