# 第 16 章 标准MQTT指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 16 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 16.1 AT+MQTTMUX — 允许MQTT 支持多路

允许MQTT 支持多路。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+MQTTMUX=<n><CR> Or` | `<CR><LF>ERROR<CR><LF> <CR><LF>+MQTTMUX:<n>` |
| 查询 | `AT+MQTTMUX?<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+MQTTMUX:<n>` |
| 测试 | `AT+MQTTMUX=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <n> | 0：使用单路MQTT（默认） |
| --- | --- |
|  | 1：使用多路MQTT |

**示例**

```
AT+MQTTMUX=1 设置为使用多路MQTT
OK
开启多路MQTT 后，其他标准MQTT 相关指令需要在AT 指令的第一个参数添加<sid>

参数，范围0-5。
示例：

单路MQTT（AT+MQTTMUX=0）

设置MQTT 参数

AT+MQTTCONNPARAM=”1”,"neoway","password"（没有sid 参数）

多路MQTT（AT+MQTTMUX=1）

设置MQTT 参数

AT+MQTTCONNPARAM=0,"1","neoway","password"（有sid 参数，sid 为0）

```


### 16.2 AT+MQTTTLS — TLS 参数配置

MQTT TLS 参数配置。 通过AT+CERTADD 导入证书。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTTLS=<type>,<typ e_name><CR>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `Or 当MQTTMUX=1 时 AT+MQTTTLS=<sid><type >,<type_name><CR> 当MQTTMUX=0 时 AT+MQTTTLS?<CR>` | `<CR><LF>ERROR<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTTLS: <sslmode>,<authmode>, <rootca_name>,<clientcert_name>,<clientkey_name>,< sslversion> <CR><LF>OK<CR><LF>` |
| 查询 | `当MQTTMUX=1 时 AT+MQTTTLS?<CR> 当MQTTMUX=0 时 AT+MQTTTLS=?<CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTTLS: <sid>,<sslmode>,<authmode>, <rootca_name>,<clientcert_name>,<clientkey_name>,< sslversion> 当MQTTMUX=0 时 <CR><LF>+MQTTTLS: <type>,<value> <CR><LF>OK<CR><LF>` |
| 测试 | `当MQTTMUX=1 时 AT+MQTTTLS=?<CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTTLS: <sid>,<type>,<value> <CR><LF>OK<CR><LF>` |

**参数**

|  | <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- | --- |
| <type> | <type> | 配置参数类型。 |
|  |  | sslmode: 是否开启认证模式 |
|  |  | authmode: 安全认证模式 |
|  |  | rootca: CA 证书 |
|  |  | clientcert: 客户端证书 |
|  |  | clientkey:客户端秘钥 |
|  |  | sslversion: SSL 协议版本 |
| <type name> _ |  | 配置参数值。 |
|  |  | <type>和<type name>参数的取值，对应关系如下： _ |
|  |  | sslmode  |
|  |  | 0：不开启认证模式 |
|  |  | 1：开启认证模式 |
|  |  | authmode  |
|  |  | 0：verify optional(单向认证) |
|  |  | 1：verify required(双向认证) |
|  |  | 注意：在sslmode=1 时设置此参数生效 |
|  |  | rootca:string: CA 证书  |
|  |  | clientcert:string，客户端证书文件名  |
|  |  | clientkey: string，客户端密匙文件名  |
|  |  | sslversion: 默认为3  |
|  |  | 0：SSL3.0 |
|  |  | 1：TLS1.0 |
|  |  | 2：TLS1.1 |
|  |  | 3：TLS1.2 |

**示例**

```
AT+MQTTTLS=authmode,1 设置认证方式为必须认证。
OK
AT+MQTTTLS? 查询SSL 的当前配置。
+MQTTTLS: 1,1,ca.pem,cc.pem,ck.pem,3
OK
AT+MQTTTLS=? 查询指令配置的范围。
+MQTTTLS: <type>,<type name>
_ OK
```


### 16.3 AT+MQTTCONNPARAM — 用户参数设置

设置ID、用户名、密码参数。 没有用户名密码时可以为空。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTCONNPARAM=<”clientdID” >,<”username”>,<”password”><CR>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTCONNPARAM=<sid>,<”clie ntdID”>,<”username”>,<”password”>< CR> 当MQTTMUX=0 时 AT+MQTTCONNPARAM?<CR>` | `Or <CR><LF>ERROR<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTCONNPARAM: <"clientID">,<"username">,<"password"> <CR><LF>OK<CR><LF>` |
| 查询 | `当MQTTMUX=1 时 AT+MQTTCONNPARAM?<CR> 当MQTTMUX=0 时 AT+MQTTCONNPARAM=?<CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTCONNPARAM: <sid><"clientID">,<"username">,<"password"> <CR><LF>OK<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTCONNPARAM: <cliendid>,<username>,<password> <CR><LF>OK<CR><LF>` |
| 测试 | `当MQTTMUX=1 时 AT+MQTTCONNPARAM=?<CR>` | `当MQTTMUX=0 时 <CR><LF>+MQTTCONNPARAM: <sid>,<cliendid>,<username>,<password> <CR><LF>OK<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <clientID> | 设备ID，最大长度256。 |
| <username> | 用户名，最大长度512。 |
| <password> | 密码，最大长度256。 |

**示例**

```
AT+MQTTCONNPARAM="C 201801021127","lixytest/thing01","0 参数设置成功
_ lSoY/eYnlSqUeAsbAKKQ/ACmipZwEw9H7Ff0h1kOps="
OK
```


### 16.4 AT+MQTTWILLPARAM — 遗嘱设置

设置遗嘱信息。 在MQTT 已经连接的情况下设置参数无效，掉电后参数需重新设置。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTWILLPARAM=<retained>, <qos>,<”topicname”>,<”message”>< CR>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTWILLPARAM=<sid>,<retai ned>,<qos>,<”topicname”>,<”messa ge”><CR> 当MQTTMUX=0 时 AT+MQTTWILLPARAM?<CR>` | `<CR><LF>OK<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTWILLPARAM: <retained>,<qos>,<"topicname">,<"message"> <CR><LF>OK<CR><LF>` |
| 查询 | `当MQTTMUX=1 时 AT+MQTTWILLPARAM?<CR> 当MQTTMUX=0 时 AT+MQTTWILLPARAM=?<CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTWILLPARAM: <sid>,<retained>,<qos>,<"topicname">,<"message "> <CR><LF>OK<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTWILLPARAM: <retained>,<qos>,<topicname>,<message> <CR><LF>OK<CR><LF>` |
| 测试 | `当MQTTMUX=1 时 AT+MQTTWILLPARAM=?<CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTWILLPARAM: <sid>,<retained>,<qos>,<topicname>,<message>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <retained> | 保留标志，数字类型。 |
| <qos> | 服务质量，目前仅支持Qos=0 和1。 |
| <”topicname”> | 遗嘱主题，最大长度128。 |
| <”message”> | 遗嘱消息，最大长度1024。 |

**示例**

```
AT+MQTTWILLPARAM=0,1,"neoway02",”byby” 遗嘱设置成功。
OK
```


### 16.5 AT+MQTTWILLMSG — 长遗嘱消息设置

设置长遗嘱或者非字符串遗嘱消息，指定retained、qos、topic、message length。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTWILLMSG=<retained>,<qos>,<”topic”>,<ms g_length><CR>` | `<CR><LF>> <CR><LF>OK<CR><LF>` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTWILLMSG=<sid>,<retained>,<qos>,<”topic” >,<msg_length><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <retained> | 保留标志，数字类型，0 和1。 |
| <qos> | 发布消息的QoS 等级。 |
| <”topic”> | 发布的主题，最大128 字节。 |
| <willmsg length> _ | 消息体长度，最大10240 字节，提示>后输入<length>指定的长度的消息内容。 |

**示例**

```
AT+MQTTWILLMSG =1,1,"neoway02",10 遗嘱消息设置成功。
>
OK
AT+MQTTWILLMSG=1,1,"neoway02",10 遗嘱消息设置失败，写入超时。
>
+MQTTWILLMSG: Timeout!
```


### 16.6 AT+MQTTCONN — 连接命令

连接MQTT 服务器。 在连接的过程中等待连接返回值，没有返回值的情况下，不能再次进行连接操作。 当连接成功后，没有主动断开情况下如果模组主动上报+MQTTDISCONNED: Link Closed，需手动 进行连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTCONN=<"host">,<clean>, <keep_alive><CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTCONN: <sid>,<host>,<clean>,<keep_alive> <CR><LF>OK<CR><LF> <CR><LF>OK<CR><LF>` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTCONN=<sid>,<"host">,<cl ean>,<keep_alive><CR> 当MQTTMUX=0 时 AT+MQTTCONN?<CR>` | `Or <CR><LF>ERROR<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTCONN: <ip>,<port>,<clean>,<keep_alive> <CR><LF>OK<CR><LF>` |
| 查询 | `当MQTTMUX=1 时 AT+MQTTCONN?<CR> 当MQTTMUX=0 时 AT+MQTTCONN=?<CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTCONN: <sid>,<ip>,<port>,<clean>,<keep_alive> <CR><LF>OK<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTCONN:` |
| 测试 | `当MQTTMUX=1 时 AT+MQTTCONN=?<CR>` | `<host>,<clean>,<keep_alive> <CR><LF>OK<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <"host"> | 服务器地址（url:port）。 |
| <clean> | 是否清除session，数字类型 |
|  | 0-不清除（默认） |
|  | 1-清除 |
| <keep alive> _ | keepAlive 时间设置，取值范围[20,180]，单位s。 |

**示例**

```
AT+MQTTCONN="121.43.166.63:1883",0,60 连接成功。
OK
```


### 16.7 AT+MQTTSUB — 订阅命令

订阅主题。 当SUB 失败后，查询MQTT 和网络状态再进行操作。当网络不佳的情况下，返回值较慢。 查询指令只有连接情况下才能查询到，只能查询到当前最后一次订阅的qos 和topic。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+MQTTSUB?<CR> 当MQTTMUX=0 时 AT+MQTTSUB=?<CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTSUB: <sid>,<topicname>,<qos> <CR><LF>OK<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTSUB: <topicname>,<qos> <CR><LF>OK<CR><LF>` |
| 测试 | `当MQTTMUX=1 时 AT+MQTTSUB=?<CR> 当MQTTMUX=0 时 AT+MQTTSUB=<"topicname"> ,<qos><CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTSUB: <sid>,<topicname>,<qos> <CR><LF>OK<CR><LF> <CR><LF>OK<CR><LF>` |
| 设置 | `Or 当MQTTMUX=1 时 AT+MQTTSUB=<sid>,<"topicn ame">,<qos><CR> 当MQTTMUX=0 时` | `<CR><LF>ERROR<CR><LF> 当MQTTMUX=0 时` |
| 查询 | `AT+MQTTSUB?<CR> 当MQTTMUX=1 时` | `<CR><LF>+MQTTSUB: <topicname>,<qos> <CR><LF>OK<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <"topicname"> | 订阅的主题，最大长度128。 |
| <qos> | 服务质量，目前支持Qos=0,1 和2 |

**示例**

```
AT+MQTTSUB="neoway02",1 主题订阅成功，同时服务器下发上次保留的topic。
OK
+MQTTSUB: 9,"neoway02",11,neoway mqtt
AT+MQTTSUB= neoway02,1 主题订阅成功。
OK
```


### 16.8 AT+MQTTUNSUB — 取消订阅

取消订阅，指定topicname 内容。 UNSUB 取消订阅失败，查询网络状态。当网络不佳的情况下，返回值较慢。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTUNSUB=<"topicname"><CR>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTUNSUB=<sid>,<"topicname">< CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <"topicname"> | 取消订阅的主题，最大长度128。 |

**示例**

```
AT+MQTTUNSUB="neoway02" 取消订阅。
OK
```


### 16.9 AT+MQTTPUB — 发布主题

主题发布。 当网络不佳的情况下，返回值较慢。 字符反斜杠‘\’是转义字符，建议使用长消息AT+MQTTPUBS 发送带有转移符‘\’的消息。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTPUB=<retained>,<qos>,<"topic name">,<"message"><CR>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTPUB=<sid>,<retained>,<qos>, <"topicname">,<"message"><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <retained> | 保留标志，数字类型，0 和1。 |
| <qos> | 服务质量，目前仅支持Qos=0，1 和2。 |
| <"topicname"> | 发布的主题，最大长度128。 |
| <"message"> | 发布的消息，最大长度1024。 |

**示例**

```
AT+MQTTPUB=1,1,"neoway02",”neoway mqtt” topic 发布成功。
OK
AT+MQTTPUB=1,1,"neoway02",”neoway mqtt”
OK
+MQTTSUB:5,"neoway02",11, neowaymqtt
```


### 16.10 AT+MQTTPUBS — 发布长消息命令

发布长消息或者非字符串消息，指定retained，qos，topic，message length。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTPUBS=<retained>,<qos>,<”topic ”>,<msg_length><CR>` | `<CR><LF>> <CR><LF>OK<CR><LF> Or` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTPUBS=<sid>,<retained>,<qos>, <”topic”>,<msg_length><CR>` | `<CR><LF>><CR><LF> <CR><LF>+MQTTPUBS: Timeout!<CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <retained> | 保留标志，数字类型，0 和1 |
| <qos> | 发布消息的QoS 等级 |
| <”topic”> | 发布的主题 |
| <msg length> _ | 消息体长度，最大10240 字节，提示>后输入<length>指定的长度的消息内容 |

**示例**

```
AT+MQTTPUBS=1,1,"lixytopic",10 Pub 消息成功。
>
OK
AT+MQTTPUBS=0,1,"lixytopic",12 Pub 消息失败，写入超时。
>
+MQTTPUBS: Timeout!
```


### 16.11 AT+MQTTDISCONN — 关闭MQTT 连接

关闭MQTT 连接。 终端主动断开和服务端的连接，然后释放MQTT 资源，参数设置也会释放，如果需要pub 消息， 需要重新发起参数设置再连接设备。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时` | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+MQTTDISCONN<CR> 当MQTTMUX=1 时` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>OK<CR><LF>` |
| 设置 | `AT+MQTTDISCONN=<sid><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5,参数仅在当MQTTMUX=1 时生效 |
| --- | --- |

**示例**

```
AT+MQTTDISCONN 关闭MQTT 连接。
OK
```


### 16.12 +MQTTSUB — 接收主题内容

收到服务器发过来的主题内容。当网络不佳的情况下，返回值较慢。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时` | `+MQTTSUB:<message_id>,<"topicname">,<message_len>,<message><CR>` |

**主动上报**

当MQTTMUX=1 时 +MQTTSUB:<sid>,<message_id>,<"topicname">,<message_len>,<message><CR>

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <message id> _ | 消息ID。 |
| <"topicname"> | 主题，使用双引号括起来。 |
| <message len> _ | 接收到的数据长度。 |
| <message> | 接收到的数据。 |

**示例**

```
+MQTTSUB:1,"neoway02",5,12345 收到主题。
```


### 16.13 AT+MQTTSTATE — MQTT 连接状态查询

查询MQTT 连接状态。 设置指令掉电不保存，每次建立MQTT 后，需要进行主动上报开启设置。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `当MQTTMUX=0 时 AT+MQTTSTATE?<CR>` | `当MQTTMUX=0 时 <CR><LF>+MQTTSTATE: <state> <CR><LF>OK<CR><LF>` |
| 查询 | `当MQTTMUX=1 时 AT+MQTTSTATE?<CR> 当MQTTMUX=0 时 AT+MQTTSTATE=<sid><CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTSTATE: <sid>,<state> <CR><LF>OK<CR><LF> 当MQTTMUX=0 时 <CR><LF>+MQTTSTATE: <state> <CR><LF>OK<CR><LF>` |
| 设置 | `当MQTTMUX=1 时 AT+MQTTSTATE=<sid><CR>` | `当MQTTMUX=1 时 <CR><LF>+MQTTSTATE: <sid>,<state> <CR><LF>OK<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <state> | 重连状态。 |
| --- | --- |
|  | 0 MQTT 已断开 |
|  | 1 MQTT 已连接 |

**示例**

```
AT+MQTTSTATE? MQTT 连接状态查询。 1 表示当前MQTT 已连接上。
+MQTTSTATE: 1
OK
AT+MQTTSTATE? MQTT 连接状态查询。 0 表示当前MQTT 已断开连接。
+MQTTSTATE: 0
OK
AT+MQTTSTATE=0 MQTT 连接状态查询。 0 表示当前MQTT 已断开连接。
+MQTTSTATE: 0
OK
AT+MQTTMUX=1 MQTT 连接状态查询。 0 表示第2 路MQTT 已断开连接。
OK
AT+MQTTSTATE=2
+MQTTSTATE: 2,0
OK
当MQTTMUX=0 时，AT+MQTTMUX=<sid>的sid 只能设置为0。

当MQTTMUX=1 时，AT+MQTTMUX?只能查询第0 路MQTT 的连接状态。

```

