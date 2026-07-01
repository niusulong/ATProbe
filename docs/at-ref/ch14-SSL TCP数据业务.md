# 第 14 章 SSL TCP数据业务

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 14 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 14.1 AT+SSLTCPCFG — SSL TCP 配置参数

配置SSL 加密选项。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+SSLTCPCFG=<type>,` | `<CR><LF>OK<CR><LF>` |
| 设置 | `Or <type_name><CR>` | `<CR><LF>ERROR<CR><LF> <CR><LF>+SSLTCPCFG:<sslversiontype_name>,<authmo detype_name>,<cacerttype_name>,<clientcerttype_name>,<` |
| 查询 | `AT+SSLTCPCFG?<CR>` | `clientkeytype_name> <CR><LF>OK<CR><LF> <CR><LF>+SSLTCPCFG: <type>,<type_name>` |
| 测试 | `AT+SSLTCPCFG=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <type> | 配置SSL 选项。 |
| --- | --- |
|  | sslversion: SSL 协议版本 |
|  | authmode: 安全认证模式 |
|  | cacert: 根证书 |
|  | clientcert: 客户端证书 |
|  | clientkey: 客户端密匙 |
|  | <type>和<type name>参数的取值，对应关系如下： _ |
|  | sslversion  |
|  | 0：SSL3.0 |
|  | 1：TLS1.0 |
|  | 2：TLS1.1 |
|  | 3：TLS1.2 |
|  | authmode  |
|  | 0：No authentication，不需要设置cacert、clientcert、clientkey 等内容。 |
| 1：Manage server authentication |
| --- |
| 2：Manage server and client authentication if requested by the remote server |
| cacert 根证书文件名  |
| clientcert 客户端证书文件名  |
| clientkey 客户端密匙文件名  |

**示例**

```
AT+SSLTCPCFG=”sslversion”,0 设置ssl 的版本为ssl3.0。
OK
AT+SSLTCPCFG=”authmode”,0 设置认证方式为不认证。
OK
AT+SSLTCPCFG? 查询SSL 的当前配置。
+SSLTCPCFG:0,1,ca.pem,cc.pem,ck.pem
OK
AT+SSLTCPCFG=? 查询指令配置的范围。
+SSLTCPCFG: <type>,<type name>
_ OK
```


### 14.2 AT+SSLTCPSETUP — 建立SSLTCP 连接

建立SSL TCP 连接。 建立透传时会与其他非透传数据业务冲突，使用透传指令不要建立非透传数据业务。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF> <CR><LF>+SSLTCPSETUP:` |
| 测试 | `AT+SSLTCPSETUP=? Or Or AT+SSLTCPSETUP=<n>,<ip>,<` | `<socket_id>,<ip>,<port>,<mode><CR><LF> <CR><LF>OK<CR><LF> <CR><LF>+SSLTCPSETUP: <n>,<status> <CR><LF>CONNECT` |
| 执行 | `port>,<mode><CR> Or Or` | `<CR><LF>+SSLTCPSETUP: ERROR <CR><LF>+SSLTCPSETUP: GPRS DISCONNECTION <CR><LF>ERROR<CR><LF> <CR><LF>+SSLTCPSETUP: <socket_id>,<ip>, <port>,<mode>` |
| 查询 | `AT+SSLTCPSETUP?` | `[<CR><LF>+SSLTCPSETUP: <socket_id>,<ip>, <port>,<mode>]…` |

**参数**

|  | <n> | 链路号，范围0-5，用来区分与服务器的连接 |
| --- | --- | --- |
|  | <ip> | 服务器的IP 地址/域名 |
|  | <port> | 服务器的端口 |
| <mode> | <mode> | 传输模式 |
|  |  | 0：非透传 |
|  |  | 1：透传 |
| <status> |  | OK |
|  |  | ERROR1 |
|  |  | AUTHFAIL |
|  |  | FAIL |

**示例**

```
AT+SSLTCPSETUP=0,183.239.240.45,4451,0 在socket 0 上连接服务器，服务器IP 为183.239.240.45，端口 为4451，传输模式为非透传。
OK
+SSLTCPSETUP: 0,OK
AT+SSLTCPSETUP=0,183.239.240.45,4451,1 在socket 0 上连接服务器，服务器IP 为183.239.240.45，端口
CONNECT 为4451，传输模式为透传。
AT+SSLTCPSETUP=0,183.239.240.45,4451,0 在socket 0 上连接服务器，服务器IP 为183.239.240.45，端口 为4451，传输模式为非透传。 建立连接失败，失败原因是连接服务器超时。
OK
+SSLTCPSETUP: 0,FAIL
AT+SSLTCPSETUP=0,183.239.240.45,4451,0 在socket 0 上连接服务器，服务器IP 为183.239.240.45，端口 为4451，传输模式为非透传。 建立连接失败，失败原因是认证不通过。
OK
+SSLTCPSETUP: 0,AUTHFAIL
AT+SSLTCPSETUP? 查询连接情况。 在socket 0、socket1 上有TCP 连接，传输方式为非透传。
+SSLTCPSETUP: 0,183.239.240.45,4451,0
+SSLTCPSETUP: 1,183.239.240.45,4452,0
OK
```


### 14.3 AT+SSLTCPCLOSE — SSL TCP 关闭连接指令

关闭SSL TCP 连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+SSLTCPCLOSE: <socket_id>,<result>` |
| 执行 | `AT+SSLTCPCLOSE=<socket_id>` | `Or <CR><LF>+SSLTCPCLOSE: ERROR` |

**主动上报**

+SSLTCPCLOSE: <socket_id>,Link Closed

**参数**

| <n> | 链路号 0~5 |
| --- | --- |
| <result> | OK |
|  | ERROR |
|  | Link Closed |

**示例**

```
AT+SSLTCPCLOSE=0 关闭socket 0 上的连接。
+SSLTCPCLOSE: 0,OK
AT+SSLTCPCLOSE=0 链路0 被动断开。
+SSLTCPCLOSE: ERROR
+SSLTCPCLOSE: 0,Link Closed
```


### 14.4 AT+SSLTCPSEND — SSL TCP 数据发送

SSL TCP 数据发送。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+SSLTCPSEND=<socket_id>,<data_l` | `<CR><LF>> <CR><LF>+SSLTCPSEND: <socket_id>,<result>` |
| 执行 | `ength>` | `Or <CR><LF>+SSLTCPSEND: Data length error<CR><LF> <CR><LF>+SSLTCPSEND: (value range` |
| 测试 | `AT+SSLTCPSEND=?` | `of<n>),(value range of<data_length>)<CR><LF>` |

**参数**

| <socket> | 范围0-5，用来区分与服务器的连接,与SSLTCPSETUP 指令socket 值保持一致。 |
| --- | --- |
| <data length> _ | 要发送的数据长度，取值范围 1-4096。 |
| <result> | OK |
|  | FAIL |

**示例**

```
AT+SSLTCPSEND=0,20 通过socket 0 发送20 字节内容到服务器。
>
+SSLTCPSEND: 0,OK
AT+SSLTCPSEND=0,1024 发送失败。
>
+SSLTCPSEND: 0,FAIL
AT+SSLTCPSEND=0,4097 通过socket 0 发送4097 字节内容到服务器,长度太大导致发送失
+SSLTCPSEND: Data length error 败。
AT+SSLTCPSEND=? 查询发送指令参数设置范围。
+SSLTCPSEND: (0-5),(1-4096)
OK
```


### 14.5 +SSLTCPRECV — 接收到SSL TCP 数据

SSL TCP 数据接收。

**主动上报**

<CR><LF>+SSLTCPRECV: <socket_id>,<data_length>,<data><CR><LF>

**参数**

| <socket id> _ | 范围0-5，用来区分与服务器的连接，与SSLTCPSETUP 指令socket 值保持一致。 |
| --- | --- |
| <data length> _ | 接收到的数据长度。 |
| <data> | 接收到的数据内容。 |

**示例**

```
+SSLTCPRECV: 1,20,12345678901234567890 在链路 1 上接收到20 个字节内容。
```


### 14.6 AT+NWCERTEENABLE — 配置加密证书

向模组写入证书。 写入过程可以通过“+++”中断。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWCERTEENABLE=<type>,<en` | `<CR><LF>OK<CR><LF>` |
| 执行 | `able><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**备注**

目前只支持AWSMQTT 指令的证书加密功能

**参数**

| <type> | 1 AWS 证书 |
| --- | --- |
|  | 2 TCPS 证书 |
|  | 3 HTTPS 证书 |
| <enabble> | 0 不加密证书 |
|  | 1 加密证书 |

**示例**

```
AT+NWCERTEENABLE=1,1 开启AWSMQTT 证书加密
OK
```


### 14.7 AT+CERTADD — 添加SSL 证书

向模组写入证书。 写入过程可以通过“+++”中断。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+CERTADD=<file_name>,<length` | `<CR><LF>CONNECT <CR><LF>+CERTADD: <length>,OK<CR><LF><CR><LF>` |
| 执行 | `>[,<type>]<CR>` | `Or <CR><LF>+CERTADD: ERROR<CR><LF> Or <CR><LF>ERROR<CR><LF> 目前只支持AWSMQTT 指令的证书加密功能，且加密证书必须携带第三个参数才会被加密` |

**备注**

首先设置AT+NWCERTEENABLE=1,1 加密配置后，添加的AWS 证书才会被加密

**参数**

| <file name> _ | 写入模组的证书名称 |
| --- | --- |
| <length> | 写入的长度 |
| <type> | 1 AWS 证书 |
|  | 2 TCPS 证书 |
|  | 3 HTTPS 证书 |

**示例**

```
AT+CERTADD=ca cert.pem,1428 向模组写入ca cert.pem 证书，长度1428。 _
_ CONNECT
+CERTADD: 1428,OK
AT+CERTADD=client cert.pem,1938 向模组写入client cert.pem 证书，长度1938。 _
_ CONNECT
+CERTADD: 1938,OK
AT+CERTADD=client key.pem,1097 向模组写入client key.pem 证书，长度1097。 _
_ CONNECT
+CERTADD: 1097,OK
```


### 14.8 AT+CERTCHECK — SSL 证书确认

检查证书。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+CERTCHECK: <file_name>,OK` |
| 执行 | `AT+CERTCHECK=<file_name><CR>` | `Or <CR><LF>+CERTCHECK: ERROR <CR><LF><file_name>` |
| 查询 | `AT+CERTCHECK?<CR>` | `[<CR><LF><file_name>] <CR><LF>OK<CR><LF>` |

**参数**

| <file name> _ | 要确认的证书名称。 |
| --- | --- |

**示例**

```
AT+CERTCHECK=ca cert.pem 检测ca cert.pem 证书。 _
_ +CERTCHECK: ca cert.pem,OK
_ AT+CERTCHECK=client cert.pem 检测client cert.pem 证书。 _
_ +CERTCHECK: client cert.pem,OK
_ AT+CERTCHECK=client key.pem client key.pem 证书不存在。 _
_ +CERTCHECK: ERROR
AT+CERTCHECKT? 查询已添加的文件。
cacert.pem
keycert.pem
OK
```


### 14.9 AT+CERTDEL — 删除SSL 证书

删除证书。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+CERTDEL[=<file_name>]<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <file name> _ | 要删除的证书名称 |
| --- | --- |

**示例**

```
AT+CERTDEL=ca cert.pem 删除ca cert.pem 证书。 _
_ OK
AT+CERTDEL=client cert.pem 删除client cert.pem 证书。 _
_ OK
AT+CERTDEL=client key.pem 删除client key.pem 证书。 _
_ OK
AT+CERTDEL 删除全部已添加文件。
OK
```


### 14.10 AT+SSLTCPCFGA — SSL TCP 配置参数

配置SSL 加密选项。 证书需要提前导入才能设置，导入证书指令参见 AT+CERTADD；证书可设置为空。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+SSLTCPCFGA=<sslversion>,<` | `<CR><LF>OK<CR><LF>` |
| 设置 | `authmode>,<cacert>,<clientcert>,< clientkey><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+SSLTCPCFGA: <sslversion>,<authmode>,<cacert>,<clientcert>,` |
| 查询 | `AT+SSLTCPCFGA?<CR>` | `<clientkey> <CR><LF>OK<CR><LF> <CR><LF>+SSLTCPCFGA: <sslversion>,<authmode>,<cacert>,<clientcert>,` |
| 测试 | `AT+SSLTCPCFGA=?<CR>` | `<clientkey> <CR><LF>OK<CR><LF>` |

**参数**

| <sslversion> | ssl 协议版本 |
| --- | --- |
|  | 0：SSL3.0 |
|  | 1：TLS1.0 |
|  | 2：TLS1.1 |
| --- | --- |
|  | 3：TLS1.2 |
| <authmode> | 安全认证模式 |
|  | 0：不认证服务器 |
|  | 1：需要认证服务器 |
|  | 2：双向认证 |
| <cacert> | CA 证书 |
| <clientcert> | 客户端证书 |
| <clientkey> | 客户端密钥 |

**示例**

```
AT+SSLTCPCFGA=3,1,"ca.pem","","" OK 设置TLS1.2。
需要认证服务器。
设置CA 证书为ca.pem。
其它证书为空。
AT+SSLTCPCFGA? 查询SSL 的当前配置。
+SSLTCPCFGA: 0,1,ca.pem,cc.pem,ck.pem
OK
```


### 14.11 AT+SSLTCPREAD — SSL TCP 数据读取

读取SSL TCP 数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+SSLTCPREAD=<n>,<length>` | `<CR><LF>+SSLTCPREAD: <id>,<len>,<data> <CR><LF>OK<CR><LF>` |
| 执行 | `<CR><LF>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <n> | 链路编号，只能为0~5。 |
| --- | --- |
| <length> | 读取数据长度，1-2048。 |
| <len> | 读取到的数据长度。 |
| <data> | 读取到的数据。 |

**示例**

```
AT+SSLTCPSETUP=0,58.60.184.213,12004,0 在链路0 上收到数据。 读取数据。 读取到10 个数据为1234567890。
OK
+SSLTCPSETUP: 0,OK
AT+SSLTCPSEND=0,10
>
+SSLTCPSEND: 0,OK
+SSLTCPRECV: 0
AT+SSLTCPREAD=0,2048
+SSLTCPREAD: 0,10,1111111111
OK
```


### 14.12 AT+SSLCIPHERSET — SSLTCP 去除弱算法

去除弱算法。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+SSLCIPHERSET=<enable><CR><LF>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+SSLTCPCFGA:` |
| 查询 | `AT+SSLCIPHERSET?<CR>` | `<enable><CR><LF>OK<CR><LF>` |
| 测试 | `AT+ SSLCIPHERSET=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <enable> | 整数类型，取值0-1 |
| --- | --- |
|  | 0：关闭去除弱算法开关（默认） |
|  | 1：使能去除弱算法开关 |

**示例**

```
AT+SSLCIPHERSET=1 使能去除弱算法开关成功。
OK
AT+SSLCIPHERSET? 查询当前设置。
+SSLCIPHERSET: 1
OK
跟客户端模式的接收格式不同，多了符号“(S)”；

跟客户端的参数有所区别，请注意。

```

