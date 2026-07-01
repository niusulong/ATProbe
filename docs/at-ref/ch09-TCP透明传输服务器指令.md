# 第 9 章 TCP透明传输服务器指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 9 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 9.1 AT+TCPSRVTRANS — 透传方式TCP 侦听

设置服务器透传方式侦听功能。 服务器透传方式发送TCP 数据之前，必须先与主站建立socket 连接； 使用“+++”指令，切换到命令模式,切换回命令模式后会返回“OK”；“ATO”指令切换到数据模 式； 使用联通卡或者移动的专网卡可以进行调试使用，移动的公网卡不能作为服务器调试； 透传指令与其他非透传数据业务冲突，使用透传指令不要建立非透传数据业务。 只允许一个TCP 客户端连接到以透传方式建立的服务器，这个TCP 客户端可以是透传方式或非透 传方式的； cfgt 与cfgp 需要同时设置，方可生效； 来电、来短信会自动断开主站链接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+TCPSRVTRANS=<port>[[,<cfgt>]` |  |
| 设置 | `[,cfgp]]<CR>` | `<CR><LF>+TCPSRVTRANS: <status><CR><LF>` |
| 查询 | `AT+TCPSRVTRANS?<CR>` | `<CR><LF>+TCPSRVTRANS: <status><CR><LF>` |

**参数**

| <port> <cfgt> <cfgp> | 端口号 |
| --- | --- |
|  | 没报数据发送等待时间，取值1-65535，默认500，单位ms |
|  | 数据包被发送门限值，取值1-2048，默认2048 |
| <status> | Listening… |
|  | bind error |
|  | not listening |
|  | listening status |
| OK |
| --- |
| GPRS DISCONNECTION |

**示例**

```
AT+TCPSRVTRANS=6800 侦听端口号6800
+TCPSRVTRANS: OK 服务器透传方式侦听开始启动
AT+TCPSRVTRANS=6800 绑定失败
+TCPSRVTRANS:bind error
AT+TCPSRVTRANS=6800 如果已经设置了侦听，再设置的话，会提示
+TCPSRVTRANS:Listening... +TCPSRVTRANS:Listening...
AT+TCPSRVTRANS? 查询侦听状态，表示当前处于侦听
+TCPSRVTRANS:listening status
AT+TCPSRVTRANS? 查询侦听状态，表示当前没有侦听
+TCPSRVTRANS:not listening
AT+TCPSRVTRANS=5000 PDP 未激活
+TCPSRVTRANS:GPRS DISCONNECTION
Connect
AcceptSocket=1,ClientAddr=119.123.77.133,ClientPort=8000
收到主站连接请求，其中AcceptSocket 是主站跟模组建立的socket，
119.123.77.133 是主站的IP 地址，8000 是主站的端口号
```


### 9.2 AT+CLIENTSTATUS — 查询透传主站链路的状态

查询透传主站链路的状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+CLIENTSTATUS: <state>,<type>, <send-` |
| 执行 | `AT+CLIENTSTATUS<CR>` | `buffer-size><CR><LF>` |

**参数**

| <state> | 链路状态 |
| --- | --- |
|  | CONNECT 该链路为链接状态 |
|  | DISCONNECT 该链路为断开状态 |
| <type> | 链路类型 |
|  | 链路类型，取值为TCP |
|  | 模组内部可用的send buffer 的大小，十进制ASCII 码表示，单位为字节 |

**示例**

```
AT+CLIENTSTATUS 已建立TCP 透传方式连接，可用buffer 为61440 字节
+CLIENTSTATUS: CONNECT,TCP,61440
AT+CLIENTSTATUS 未建立TCP 透传方式连接，可用buffer 为61440 字节
+CLIENTSTATUS:DISCONNECT,TCP,
61440
```

