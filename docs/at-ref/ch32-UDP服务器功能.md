# 第 32 章 UDP服务器功能

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 32 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 32.1 AT$UDPLISTEN — 设置服务器UDP 侦听

设置服务器侦听功能，支持最多14 个主站链接。 该指令必须在建立PPP 连接成功之后才能生效。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT$UDPLISTEN=<port>[,<re` | `<CR><LF>$UDPLISTEN: <socket>,OK<CR><LF> <CR><LF>$UDPLISTEN: listening status…<CR><LF>` |
| 设置 | `cv_mode>]<CR> Or` | `<CR><LF>$UDPLISTEN: not listening<CR><LF> <CR><LF>$UDPLISTEN: listening status <CR><LF>OK<CR><LF>` |
| 查询 | `AT$UDPLISTEN?<CR> Or` | `<CR><LF>$UDPLISTEN: not listening <CR><LF>OK<CR><LF> <CR><LF>$UDPLISTEN: (range of supported` |
| 测试 | `AT$UDPLISTEN=?<CR>` | `<port>),(range of supported <recv_mode>) <CR><LF>OK<CR><LF>` |

**参数**

| <port> | 端口号，端口号取值范围1~65535 |
| --- | --- |
| <recv mode> _ | 接收数据模式，缺省值为0 |
|  | 0：表示链路接收到数据后直接输出 |
|  | 1：表示接收到数据先保存在缓冲区，用户需要时可以执行命令$IPNETREAD 来读 |
|  | 取 |

**示例**

```
AT$UDPLISTEN=6000 侦听端口号6000 绑定失败
$UDPLISTEN: 0,OK
Or
$UDPLISTEN: bind error
AT$UDPLISTEN=6000 没有建立PPP 连接之前设置服务器侦听
ERROR
AT$UDPLISTEN=6000 如果已经设置了侦听，再设置的话，会提示 Listening…
Listening…
AT$UDPLISTEN=? 查询侦听端口的取值范围
$UDPLISTEN: (1-65535),(0-1)
OK
AT$UDPLISTEN? 查询侦听状态，表示当前处于侦听
$UDPLISTEN: listening status
OK
AT$UDPLISTEN? 查询侦听状态，表示当前没有侦听
$UDPLISTEN: not listening
OK
```


### 32.2 AT$CLOSEUDPLISTEN — 关闭侦听链接

关闭对应channel 上的侦听连接，同时会关闭侦听到主站的连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>$CLOSEUDPCLIENT: <socket>,remote link closed<CR><LF>` |
| 执行 | `AT$CLOSEUDPLISTEN<CR>` | `<CR><LF>$CLOSEUDPLISTEN: <socket>,local link closed<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 |

**示例**

```
AT$CLOSEUDPLISTEN 如果有主站连接，也同时会被关闭。
$CLOSEUDPLISTEN: 0,local link
closed
$CLOSEUDPCLIENT: 1,remote link
closed
```


### 32.3 AT$CLOSEUDPCLIENT — 关闭主站连接

使用本指令后，指令链路被关闭，此链路关闭后可以做其他连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>$CLOSEUDPCLIENT:` |
| 执行 | `AT$CLOSEUDPCLIENT[=[,<socket>]]<CR>` | `<socket>,remote link closed<CR><LF>` |

**参数**

| <Socket> | SOCKET 号 |
| --- | --- |

**示例**

```
AT$CLOSEUDPCLIENT 不带参数，多个关闭
$CLOSEUDPCLIENT: 1,remote link
closed
$CLOSEUDPCLIENT: 2,remote link
closed
AT$CLOSEUDPCLIENT=1 带参数，单个关闭
$CLOSEUDPCLIENT: 1,remote link
closed
AT$CLOSEUDPCLIENT=1 链路不存在远程客户端
ERROR
AT$CLOSEUDPCLIENT 所有远程客户端已关闭
$CLOSEUDPCLIENT: All remote
link closed
32.4 $UDPRECV(S)–接收到主站的数据
接收到主站的数据。
```

**命令格式**

| 类型 | 格式 |
| --- | --- |

**主动上报**

$UDPRECV(S): <socket>,<length>,<data>

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 |

**示例**

```
$UDPRECV(S): 1,10,1234567890 1 链路接收到主站的数据，内容为：1234567890
32.5 AT$UDPSEND(S)–发送给主站的数据
发送给主站的数据。
如果格式错误返回$UDPSENDS: ERROR。
初次发送数据，需客户端先给服务器发送数据，服务器才能在收到数据的链路回发数据。
```

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>$UDPSENDS=<socket>,<le` |
| 执行 | `AT$UDPSENDS=<socket>,<length><CR>` | `ngth><CR><LF> <CR><LF>OK<CR><LF>` |

**参数**

| <socket> | 侦听到的AcceptSocket 值，即主站跟模组建立的socket。 |
| --- | --- |
| <lenght> | 要发送的数据长度，以字节为单位，取值范围建议在1~1024 之间。 |

**示例**

```
AT$UDPSENDS=0,10 在socket 0 上发送10 字节的数据，发送成功
>1234567890
OK
$UDPSENDS: 0,10
AT$UDPSENDS=0,10 Socket 0 没有建立任何连接
$UDPSENDS: SOCKET ID NOT
ACTIVE
AT$UDPSENDS=0,10 0 链路没有侦听建立的UDP 连接，但有可能建立了其他的连接
$UDPSEND: ERROR
AT$UDPSENDS=0,10 超时未输入数据报错
>
$UDPSENDS: Error!TimeOut
AT$UDPSENDS=0,0,5120 发送长度错误
$UDPSENDS: DATA LENGTH ERROR
```


### 32.6 AT$UDPCLIENTSTATUS — 查询主站链路的状态

查询主站链路状态。 链路类型为INVALID 表示该链路不是侦听到的UDP 连接，可能为TCP/UDP 客户端或者服务器侦 听链路。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+UDPCLIENTSTATUS:<socke t>,<CONNECTor DISCONNECT>,<UDP` |
| 执行 | `AT$UDPCLIENTSTATUS=<socket><CR>` | `orINVALID> <CR><LF>OK<CR><LF>` |

**参数**

| <CONNECT or | 侦听到的AcceptSocket 值，即主站跟模组建立的socket |  |
| --- | --- | --- |
| DISCONNECT> |  |  |
| <UDP or INVALID > |  | 链路类型，取值为UDP 或者INVALID。 |

**示例**

```
AT$UDPCLIENTSTATUS=0 主站socket 0 ,已建立UDP 连接
$UDPCLIENTSTATUS:
0,CONNECT,UDP
OK
AT$UDPCLIENTSTATUS=,4 Socket 4 没有建立连接
$UDPCLIENTSTATUS: 4,DISCONNECT
OK
AT$UDPCLIENTSTATUS=1 Socket 1 作为服务器侦听，链路类型返回INVALID
$UDPCLIENTSTATUS:
1,CONNECT,INVAL ID
OK
```


### 32.7 AT$IPNETREAD — 读取UDP 服务器接收缓存数据

读取UDP 服务器接收缓存数据。 以自动接收数据方式建立的链路不支持该指令读取数据  如果len 大于一个数据包长度则按包实际大小读取数据  每条链路的缓冲区大小为10K。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>$IPURCREAD:<channel>,<len>,< data> <CR><LF>OK<CR><LF> Or <CR><LF>ERROR<CR><LF>` |
| 执行 | `AT$IPNETREAD=<n>[,<len>]<CR>` | `Or <CR><LF>$IPURCREAD: ERROR Or <CR><LF>$IPURCREAD: SOCKET ID OPEN FAILED` |

**参数**

| <n> | 链路编号，0~14。 |
| --- | --- |
| <len> | 要读取的长度，范围为1~2048。 |

**示例**

```
$IPURCREAD: 0 提示链路0 号接收到数据 读取5 字节内容
AT$IPNETREAD=0,5
$IPNETREAD: 0,5
12345
OK
AT$IPNETREAD=0,1024 链路0 接收缓存已没有数据
$IPNETREAD: 0,0
OK
AT$IPNETREAD=1,10 执行错误，链路未建立或者接收数据方式不为手动读取
ERROR
```

