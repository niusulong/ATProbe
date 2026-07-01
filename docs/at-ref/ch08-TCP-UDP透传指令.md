# 第 8 章 TCP/UDP透传指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 8 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 8.1 AT+TCPTRANS — 建立TCP 透传连接

建立TCP 透传连接。 建立TCP 透传链接成功后，向服务器发送数据，串口不显示发送的数据；  使用“+++”指令（不带回车换行）切换到命令模式,切换回命令模式后会返回“OK”；“ATO”指令  切换到数据模式； 透传指令与其他非透传数据业务冲突，使用透传指令不要建立非透传数据业务；  来电、来短信会自动退出透传方式链接（只适用非volte 版本，volte 版本不会自动退出）；  建议透传方式一次最多收发2048 字节数据；  cfgt 与cfgp 需要同时设置，方可生效；  建立TCP 透传链接返回回码+TCPTRANS:OK 后，即可进行TCP 透传数据收发。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF> <CR><LF>+TCPTRANS:` |
| 设置 | `AT+TCPTRANS=<ip>,<port>[,<cfgt>,cfgp]<CR>` | `<result><CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

|  | <ip> | 目的IP 地址，必须是形如xx.xx.xx.xx 的输入，或者形如www.china.com（域名） | 。 |
| --- | --- | --- | --- |
| <port> <cfgt> <cfgp> | <port> | 目的端口号，必须是十进制的ASCII 码。 |  |
|  | <cfgt> | 没报数据发送等待时间，取值1-65535，默认100，单位ms |  |
|  | <cfgp> |  |  |
|  |  | 数据包被发送门限值，取值1-2048，默认2048 |  |
| <result> |  | 结果码 |  |
|  |  | OK 建立成功 |  |
| FAIL 建立失败 |
| --- |

**示例**

```
AT+TCPTRANS=neowayjsr.oicp.net,60010 建立到 neowayjsr.oicp.net,60010 的连接，成功。
OK
+TCPTRANS: OK
AT+TCPTRANS=220.199.66.56,6800 建立到 220.199.66.56,6800 的连接，失败。
OK
+TCPTRANS: FAIL
AT+TCPTRANS=220.199.66.56,6800 若已建立透传（TCP、UDP、TCP 服务器）链接，再发送该指令会返回：
ERROR ERROR。
AT+TCPTRANS=220.199.66.56, AT 指令格式错误。
+TCPTRANS: ERROR
+TCPTRANS: Link Closed 连接被动断开上报格式。
```


### 8.2 AT+UDPTRANS — 建立UDP 透传连接

建立UDP 透传连接。 建立UDP 透传链接后，向服务器发送数据，串口不显示发送的数据；  使用“+++”指令（不带回车换行）切换到命令模式,切换回命令模式后会返回“OK”；“ATO”指令  切换到数据模式； 透传指令与其他非透传数据业务冲突，使用透传指令不要建立非透传数据业务。  来电、来短信会自动退出透传方式链接；  建议透传方式一次最多收发2048 字节数据；  cfgt 与cfgp 需要同时设置，方可生效；  建立UDP 透传链接返回回码+UDPTRANS:OK 后，即可进行UDP 透传数据收发。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+UDPTRANS=<ip>,<port>[,<cfgt>,` | `<CR><LF>OK<CR><LF> <CR><LF>+UDPTRANS: <result><CR><LF>` |
| 设置 | `cfgp]<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

|  | <ip> | 目的IP 地址，必须是形如xx.xx.xx.xx 的输入，或者形如www.china.com（域名） | 。 |
| --- | --- | --- | --- |
| <port> <cfgt> <cfgp> | <port> | 目的端口号，必须是十进制的ASCII 码。 |  |
|  | <cfgt> | 没报数据发送等待时间，取值1-65535，默认100，单位ms |  |
|  | <cfgp> |  |  |
|  |  | 数据包被发送门限值，取值1-2048，默认2048 |  |
|  | <ip> | 目的IP 地址，必须是形如xx.xx.xx.xx 的输入，或者形如www.china.com（域名） | 。 |
| <result> | <result> | 结果码 |  |
|  |  | OK 建立成功 |  |
|  |  | FAIL 建立失败 |  |

**示例**

```
AT+UDPTRANS=220.199.66.56,6800 建立UDP 透传链接，成功。
OK
+UDPTRANS: OK
AT+UDPTRANS=neowayjsr.oicp.net,60010 用域名建立UDP 透传链接，成功。
OK
+UDPTRANS: OK
AT+UDPTRANS=220.199.66.56, AT 指令格式错误。
ERROR
AT+UDPTRANS=220.199.66.56,6800 若已建立透传（TCP、UDP、TCP 服务器）链接，再发送该指令会返回：
ERROR ERROR。
```


### 8.3 AT+TCPACK — 查询TCP 透传链路发送数据状态

查询TCP 透传链路发送成功的数据大小、接收方成功接收该链路的数据大小。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+TCPACK: <data_sent>,<acked_recv><CR><LF> Or <CR><LF>ERROR<CR><LF>` |
| 执行 | `AT+TCPACK<CR>` | `Or <CR><LF>+TCPACK: DISCONNECT<CR><LF> Or <CR><LF>+TCPACK: NO TCP LINK<CR><LF>` |

**参数**

| <data send> _ | 该链路发送成功的透明传输数据大小，为无符号 64 位整型数，十进制 ASCII 码表 |
| --- | --- |
|  | 示，单位为字节。 |
| <acked recv> _ | 接收方接收成功的透明传输数据大小，为无符号 64 位整型数，十进制 ASCII 码表 |
|  | 示，单位为字节。 |

**示例**

```
AT+TCPACK TCP 透明传输方式，发送成功1024 字节数据，对方接收成功
+TCPACK: 1024,1024 1024 字节数据
AT+TCPACK 未建立任何透明传输方式连接
+TCPACK: DISCONNECT
AT+TCPACK 建立的是UDP 透明传输方式连接
+TCPACK: NO TCP LINK
```


### 8.4 +IPSTATUS — 查询TCP/UDP 链路状态

查询TCP/UDP 透传链路状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `size>]<CR><LF>` | `<CR><LF>+IPSTATUS: <state>[,<type>,<send-buffer-` |
| 执行 | `AT+IPSTATUS<CR> Or <CR><LF>ERROR<CR><LF>` |  |

**参数**

| <state> |  | 链路状态 |
| --- | --- | --- |
|  |  | CONNECT 链路为链接状态 |
|  |  | DISCONNECT 链路为断开状态 |
|  |  | CONNECTING 连接中 |
|  |  | DISCONNECTING 断开连接中 |
| <type> |  | 链路类型（可选） |
|  |  | TCP |
|  |  | UDP |
|  | <send-buffer- | 模组内部可用的send buffer 的大小，十进制ASCII 码表，单位为字节（可选） |
|  | size> |  |

**示例**

```
AT+IPSTATU AT 指令格式错误，指令不完整
ERROR
AT+IPSTATUS 已建立TCP 透明传输方式连接，可用buffer 为61440 字节
+IPSTATUS: CONNECT,TCP,61440
AT+IPSTATUS 已建立UDP 透明传输方式连接，可用buffer 为61440 字节
+IPSTATUS: CONNECT,UDP,61440
AT+IPSTATUS 未建立任何透明传输方式连接
+IPSTATUS: DISCONNECT
```


### 8.5 AT+TRANSCLOSE — 关闭透传方式链接

关闭透明传输方式链接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+TRANSCLOSE: <n>,OK<CR><LF> Or <CR><LF>ERROR<CR><LF>` |
| 执行 | `AT+TRANSCLOSE<CR>` | `Or <CR><LF>+UDPTRANS: <n>,local link closed Or <CR><LF>+TCPTRANS: <n>,local link closed` |

**参数**

| <n> | Socket id _ |
| --- | --- |

**示例**

```
AT+TRANSCLOSE 主动关闭TCP 透传方式链接，成功
+TRANSCLOSE: 0,OK
AT+TRANSCLOSE 未建立TCP/UDP 透传方式链接，失败
ERROR
AT+TRANSCLOSE
+TRANSCLOSE: 0,OK 主动关闭UDP 透传方式链接，成功
+TCPSRVTRANS: 0,local link closed 被动关闭TCP 透传方式链接
+UDPSRVTRANS: 0,local link closed 被动关闭UDP 透传方式链接
```

