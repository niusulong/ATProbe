# 第 17 章 AWS MQTT指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 17 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 17.1 AT+AWSTLSCFG — AWS TLS 参数配置

AWS TLS 参数配置。 通过AT+CERTADD 导入证书。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+AWSTLSCFG=<type>,<` | `<CR><LF>OK<CR><LF>` |
| 设置 | `Or value><CR>` | `<CR><LF>ERROR<CR><LF> <CR><LF>+AWSTLSCFG: <authmode>,<rootca_name>,<clientcert_name>,<clien` |
| 查询 | `AT+AWSTLSCFG?<CR>` | `tkey_name> <CR><LF>OK<CR><LF> <CR><LF>+AWSTLSCFG: <type>,<value>` |
| 测试 | `AT+AWSTLSCFG=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <type> | 配置参数类型 |
| --- | --- |
| <value> | 配置参数值 |
| <authmode> | 安全认证模式 |
|  | 0：verify optional |
|  | 1：verify required |
| <rootca> | string，CA 证书 |
| <clientcert> | string，客户端证书 |
| <clientkey> | string，客户端密钥 |

**示例**

```
AT+AWSTLSCFG=authmode,1 设置认证方式为必须认证。
OK
AT+AWSTLSCFG? 查询SSL 的当前配置。
+AWSTLSCFG: 1,ca.pem,cc.pem,ck.pem
OK
AT+AWSTLSCFG=? 查询指令配置的范围。
+AWSTLSCFG: <type>,<value>
OK
```


### 17.2 AT+AWSAUTHPARAM — 用户参数设置

设置ID、用户名、密码参数。 当前版本2.3.0 暂不需要username 和password，可不设置。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+AWSAUTHPARAM=<cliendID>,<username>,<` | `<CR><LF>OK<CR><LF>` |
| 设置 | `password><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <cliendID> | 设备ID，最大长度128 |
| --- | --- |
| <username> | 用户名，最大长度512 |
| <password> | 密码，最大长度256 |

**示例**

```
AT+AWSAUTHPARAM=1234567890,test,test 参数设置成功。
OK
```


### 17.3 AT+AWSCONNPARAM — 设置AWS 连接参数

设置AWS 连接参数。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+AWSCONNPARAM=<host>,<enable_reconnect>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <host> | 服务器地址（url:port） |
| --- | --- |
| <enable reconnect> _ | 是否允许掉线重连使能，数字类型 |
|  | 0-不允许 |
|  | 1-允许 |

**示例**

```
AT+AWSCONNPARAM=a1epg1vh6w7hlk.iot.us-east-2.amazonaws.com:443,1 连接参数设置成功。
OK
```


### 17.4 AT+AWSCONN — 连接命令

连接MQTT 服务器。 当前SDK 2.3.0 仅支持clean =1，version=4。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+AWSCONN=<keepAlive>,<clean>,<version><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <keepAlive> | keepAlive 时间设置，必需指定，范围30~1200 秒，默认60s。 |
| --- | --- |
| <clean> | 是否清除session，数字类型，0-不清除 1-清除 |
| <version> | MQTT 版本4 = 3.1.1 |

**示例**

```
AT+AWSCONN=60,1,4 连接成功。
OK
```


### 17.5 AT+AWSSUB — 订阅主题

订阅主题。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+AWSSUB=<topicname>,<qos><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <topicname> | 订阅的主题，最大长度128 |
| --- | --- |
| <qos> | 服务质量，目前仅支持Qos=0 和1 |

**示例**

```
AT+AWSSUB=nwy test/01,1 主题订阅成功。
_ OK
```


### 17.6 AT+AWSUNSUB — 取消订阅

取消订阅，指定topicname 内容。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+AWSUNSUB=<topicname><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <topicname> | 取消订阅的主题，最大长度128。 |
| --- | --- |

**示例**

```
AT+AWSUNSUB=nwy test/01 取消订阅。
_ OK
```


### 17.7 AT+AWSPUB — 发布主题

主题发布。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `Or AT+AWSPUB=<retained>,<qos>,` | `<CR><LF>> <CR><LF>OK<CR><LF> <CR><LF>>` |
| 执行 | `<topicname>,<length><CR> Or` | `<CR><LF>OK <CR><LF>+AWSPUB: OK<CR><LF> <CR><LF>+AWSPUB: ERROR<CR><LF><CR><LF>` |

**参数**

| <retained> |  | 保留标志，数字类型，0 和1 |
| --- | --- | --- |
|  |  | 当前SDK 2.3.0 仅支持retained=0 |
|  | <qos> | 服务质量，目前仅支持Qos=0 和1 |
|  | <topicname> | 发布的主题，最大长度128 |
|  | <length> | 发布的消息长度，最大长度10240，提示>后输入<length>指定的长度的消息内容 |

**示例**

```
AT+AWSPUB=1,1,"nwy test/01",11 topic 发布成功。
_ >
OK
AT+AWSPUB=1,1,"nwy test/01",11 topic 发布成功，同时服务器下发该topic。
_ >
OK
+AWSPUB: OK
+AWSSUBRECV: 5,"nwy test/01",11,12332HELLO!
_
```


### 17.8 AT+AWSDISCONN — 断开AWS

关闭AWS 连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+AWSDISCONN<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 |

**示例**

```
AT+AWSDISCONN 关闭MQTT 链路。
OK
```


### 17.9 +AWSSUBRECV — 接收主题内容

收到服务器发过来的主题内容。

**主动上报**

+AWSSUBRECV: <message_id>,<"topicname">,<message_len>,<message>

**参数**

| <message id> _ | 消息ID |
| --- | --- |
| <topicname> | 主题 |
| <message len> _ | 接收到的数据长度 |
| --- | --- |
| <message> | 接收到的数据 |

**示例**

```
+AWSSUBRECV: 5,"nwy test/01",5,12345 收到主题。
```


### 17.10 AT+AWSSTATE — MQTT 连接状态查询

查询MQTT 连接状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+AWSSTATE: <n>` |
| 执行 | `AT+AWSSTATE?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <n> | 连接状态 |
| --- | --- |
|  | 0：已断开 |
|  | 1：已连接上 |

**示例**

```
AT+AWSSTATE? MQTT 连接状态查询。 1 表示当前MQTT 已连接上。
+AWSSTATE: 1
OK
AT+AWSSTATE? MQTT 连接状态查询。 0 表示当前MQTT 已断开连接。
+AWSSTATE: 0
OK
```


### 17.11 AT+AWSWILLPARAM — 遗嘱设置

设置遗嘱信息。 在MQTT 已经连接的情况下设置参数无效，掉电后参数需重新设置。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+AWSWILLPARAM=<retained>,<` |  |
| 设置 | `qos>,<”topicname”>,<”message”><C R>` | `<CR><LF>OK<CR><LF> <CR><LF>+AWSWILLPARAM:<retained>,<qos>,<` |
| 查询 | `AT+ AWSWILLPARAM?<CR>` | `topicname>,<message> <CR><LF>OK<CR><LF> <CR><LF>+AWSWILLPARAM:` |
| 测试 | `AT+ AWSWILLPARAM =?<CR>` | `<retained>,<qos>,<topicname>,<message> <CR><LF>OK<CR><LF>` |

**参数**

| <retained> | 保留标志，数字类型。 |
| --- | --- |
| <qos> | 服务质量，目前仅支持Qos=0 和1。 |
| <”topicname”> | 遗嘱主题，最大长度128。 |
| <”message”> | 遗嘱消息，最大长度1024。 |

**示例**

```
AT+AWSWILLPARAM=0,1,"neoway02",”byby” 遗嘱设置成功。
OK
```


### 17.12 AT+AWSWILLMSG — 长遗嘱消息设置

设置长遗嘱或者非字符串遗嘱消息，指定retained、qos、topic、message length。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+AWSWILLMSG=<retained>,<qos>,<”topic”>,<msg` | `<CR><LF>> <CR><LF>OK<CR><LF>` |
| 设置 | `_length><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <sid> | 对应的MQTT 链路，范围0-5 |
| --- | --- |
| <retained> | 保留标志，数字类型，0 和1。 |
| <qos> | 发布消息的QoS 等级。 |
| <”topic”> | 发布的主题。 |
| <willmsg length> _ | 消息体长度，最大10240 字节，提示>后输入<length>指定的长度的消息内容。 |

**示例**

```
AT+AWSWILLMSG=1,1,"neoway02",10 遗嘱消息设置成功。
>
OK
AT+AWSWILLMSG=1,1,"neoway02",10 遗嘱消息设置失败，写入超时。
>
+AWSWILLMSG: Timeout!
```

