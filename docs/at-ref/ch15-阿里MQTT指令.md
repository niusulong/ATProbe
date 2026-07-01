# 第 15 章 阿里MQTT指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 15 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 15.1 AT+CLOUDAUTHMODE — 设备鉴权模式

不设置该指令时，默认为一机一密的认证方式。 该指令在鉴权连接之前设置有效。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+CLOUDAUTHMODE=<mode><CR>` | `Or <CR><LF>+CMDERROR <CR><LF> <CR><LF>+CLOUDAUTHMODE: <mode>` |
| 查询 | `AT+CLOUDAUTHMODE?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <mode> | 设备认证方式 0：一机一密（默认） 1：一型一密 2：x509 加密连接需要添加证书 3：直连 4~99：预留 |
| --- | --- |

**示例**

```
AT+ CLOUDAUTHMODE=1 设置为一型一密
OK
AT+CLOUDAUTHMODE? 查询参数
+CLOUDAUTHMODE: 1
OK
```


### 15.2 AT+CLOUDCFG — 阿里MQTT 证书配置

配置SSL 加密选项，目前只有在X509 连接时需要设置此指令。 配置证书前，需要添加证书。 通过AT+CERTADD 导入证书。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+CLOUDCFG` | `<CR><LF>OK<CR><LF>` |
| 设置 | `=<type>,<type_name><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+CLOUDCFG: <sslversiontype_name>,<authmodetype_name>,<` |
| 查询 | `AT+CLOUDCFG?<CR>` | `clientcerttype_name>,<clientkeytype_name><CR> <LF>OK<CR><LF> <CR><LF>+CLOUDCFG:` |
| 测试 | `AT+CLOUDCFG=?<CR>` | `<type>,<type_name><CR><LF>OK<CR><LF>` |

**参数**

| <type> | 配置SSL 选项。 |
| --- | --- |
|  | sslversion: SSL 协议版本 |
|  | authmode: 安全认证模式 |
|  | clientcert: 客户端证书 |
|  | clientkey: 客户端密匙 |
|  | <type>和<type name>参数的取值，对应关系如下： _ |
|  | sslversion  |
|  | 1：TLS1.0 |
|  | 2：TLS1.1 |
|  | 3：TLS1.2 |
|  | authmode  |
|  | 1：一型一密认证 |
|  | 2：X509 认证 |
|  | clientcert 客户端证书文件名  |
|  | clientkey 客户端密匙文件名  |

**示例**

```
AT+CLOUDCFG=”sslversion”,0 设置SSL 的版本为ssl3.0。
OK
AT+CLOUDCFG=”authmode”,2 设置X509 认证方式认证。
OK
AT+CLOUDCFG? 查询SSL 的当前配置。
+CLOUDCFG: 1,2,cc.pem,ck.pem
OK
AT+CLOUDCFG=? 查询指令配置的范围。
+CLOUDCFG: <type>,<type name>
_ OK
AT+CLOUDCFG="clientkey","key.pm" 配置证书。
OK
```


### 15.3 AT+CLOUDSETSRVURL — 设置MQTT 鉴权站点

设置MQTT 鉴权链接站点。 需连接之前设置该参数。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+CLOUDSETSRVURL=<”url”><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+CLOUDSETSRVURL: <”url”>` |
| 查询 | `AT+CLOUDSETSRVURL?<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>OK<CR><LF>` |
| 执行 | `AT+CLOUDSETSRVURL<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <”url”>：站点地址，字符串类型，长度最大支持512 字节。 |
| --- |

**示例**

```
AT+CLOUDSETSRVURL="iot-cn- 设置站点地址。 查询当前设置。 重置回默认上海华东2 站点。
nif1y7hvl13.mqtt.iothub.aliyuncs.com"
OK
AT+CLOUDSETSRVURL?
+CLOUDSETSRVURL: "iot-cn-
nif1y7hvl13.mqtt.iothub.aliyuncs.com"
OK
AT+CLOUDSETSRVURL
OK
```


### 15.4 AT+CLOUDHDAUTH — 设备鉴权信息（华东2 站点）

设备鉴权信息。 使用参数鉴权成功后，<productKey>,<deviceName>,<deviceSecret>三组参数保存在NV 区域，下 次可直接使用AT+CLOUDHDAUTH 进行鉴权。 一型一密时，参数<deviceSecret>改填为ProductSecret。 三个参数同事为空时，会清除掉本地保存的信息。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+CLOUDHDAUTH=<productKey` | `<CR><LF>OK <CR><LF>+CLOUDHDAUTH: OK<CR><LF>` |
| 设置 | `>,<deviceName>,<deviceSecret>]< CR>` | `Or <CR><LF>OK<CR><LF> <CR><LF>+CLOUDHDAUTH:FAIL <CR><LF> <CR><LF>ProductKey=产品key <CR><LF>DeviceName=设备名字` |
| 查询 | `AT+CLOUDHDAUTH?<CR>` | `<CR><LF>DeviceSecret=设备秘钥 <CR><LF>OK<CR><LF>` |

**参数**

| <productKey> | 产品key，必需，字符串类型，最大长度11Byte |  |
| --- | --- | --- |
| <deviceName> | 设备名字，必需，字符串类型，最大长度32Byte |  |
| <deviceSecret> | 设备秘钥，必需，字符串类型，最大长度32Byte（一型一密此参数填ProductSecret | ） |

**示例**

```
AT+CLOUDHDAUTH=kfOZFbrf,Ndevice T1,BdPNgkKXcMP6WnCQucnL _ XigThPn5i9fr OK +CLOUDHDAUTH: OK AT+CLOUDHDAUTH? ProductKey=J5VSBJMed74 DeviceName=TEST 0 _ DeviceSecret=AchwwtoDacnYdyq5hoi21fO6IQXYke10 OK 鉴权成功。
设置鉴权成功后，鉴权参数将保存至NV,查询时返
回鉴权参数。
AT+CLOUDHDAUTH="","","" 清除保存的鉴权信息。
OK
AT+CLOUDHDAUTH="kfOZFbrf","Ndevice T1","BdPNgkKXcMP6WnC _
QucnLXigThPn5i9fr" OK
+CLOUDHDAUTH: OK
```


### 15.5 AT+CLOUDCONN — 配置MQTT 连接参数命令

配置MQTT 连接参数，包括MQTT 和服务端的保活时间、cleansession 信息、MQTT 版本信息。 连接成功后，可以直接调用+CLOUDSUB 指令去注册每个设备默认的topic：/pk/${deviceName}/get 及其他自定义topic。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+CLOUDCONN=<keepAlive>,<clean>,<version><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <keepAlive> | keepAlive 时间设置，必需指定，范围60~180 秒。 |
| --- | --- |
| <clean> | 是否清除session，数字类型，0-不清除 1-清除 |
| <version> | MQTT 版本3 = 3.1；4 = 3.1.1。 |

**示例**

```
AT+CLOUDCONN=60,0,4 连接MQTT 服务器成功.
OK
```


### 15.6 AT+CLOUDSUB — 订阅消息命令

订阅消息，目前只支持一次增加一个订阅。 订阅失败时，返回+CMD ERROR: <code>，会自动断开MQTT 连接，需要重新使用+CLOUDCONN 建立新的连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK <CR><LF>+CLOUDSUBACK: <OK><CR><LF> Or` |
| 设置 | `AT+CLOUDSUB=<topic>,<qos><CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+CMD ERROR: <code><CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <topic> | 申请订阅的topic，字符串类型，长度应不超过128 Byte。 |
| --- | --- |
| <qos> | 该topic 对应的qos 等级，数字类型，0-1。 |
| <code> | Code: -1 MQTT 设备指针不存在 |
|  | Code: -2 MQTT SUB/PUB/UNSUB 失败 |
|  | Code: -3 MQTT 等待ACK 超时 (Qos>0) |
|  | Code: -4 MQTT 发布无效topic 的消息 |
|  | Code: -5 接收的MQTT publish 报文过大 |

**示例**

```
AT+CLOUDSUB=”/1000146090/Ndevice T1/neo001”,1 _ OK +CLOUDSUBACK: <OK> 订阅topic 成功。
AT+CLOUDSUB=”/1000146090/Ndevice T1/neo001”,1 订阅topic 失败，ACK 返回超时。
_ OK
+CMD ERROR: <-3>
AT+CLOUDSUB=”/1000146090/Ndevice T1/neo001”
_
ERROR
```


### 15.7 +CLOUDPUBLISH — PUBLISH 数据接收

订阅之后的topic 收到publish 数据的上报。

**主动上报**

+CLOUDPUBLISH:<packId>,<”topic”>,<msg_len>,<msg>

**参数**

| <packId> | 数据包ID |
| --- | --- |
| <topic> | 接收到的topic 名字 |
| <msg len> _ | 接收到的消息长度 |
| <msg> | 接收到的消息内容 |

**示例**

```
+CLOUDPUBLISH:24761,”/1000146090/Ndevice T1/neo001”,5,hello _ 收到publish 消息（使用+CLOUDSUB 订阅
topic 后）。
```


### 15.8 AT+CLOUDPUB — 发布消息命令

发布消息，指定topic，qos，message 内容。 Pub 消息失败时，返回+CMD ERROR: <code>，会自动断开MQTT 连接，需要重新使用 +CLOUDCONN 建立新的连接。 字符反斜杠‘\’是转义字符，建议使用长消息AT+CLOUDPUBMSG 发送带有转移符‘\’的消息。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK <CR><LF>+CLOUDPUBACK: <OK><CR><LF> Or` |
| 执行 | `AT+CLOUDPUB=<topic>,<qos>,<message><CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+CMD ERROR: <code><CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <topic> | 发布的主题。 |
| --- | --- |
| <qos> | 发布消息的QoS 等级，取值为0-1，暂不支持QoS2。 |
| <msg> | 消息体内容，长度最大1024 字节。 |

**示例**

```
AT+CLOUDPUB=“/1000146090/Ndevice T1/neo001”,1,hello Pub 消息成功。
_ OK
+CLOUDPUBACK: <OK>
AT+CLOUDPUB=“/1000146090/Ndevice T1/neo001”,1,hello Pub 消息失败，ACK 返回超时。
_ OK
+CMD ERROR: <-3>
AT+CLOUDPUB=“/1000146090/Ndevice T1/neo001”,1 参数个数错误。
_ ERROR
```


### 15.9 AT+CLOUDPUBMSG — 发布长消息命令

发布长消息或者非字符串消息，指定topic，qos，message length。 Pub 消息失败时，返回+CMD ERROR: <code>，会自动断开MQTT 连接，需要重新使用 +CLOUDCONN 建立新的连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+CLOUDPUBMSG=<”topic”>,<qos>,<` | `<CR><LF>> <CR><LF>OK <CR><LF>+CLOUDPUBACK: <OK><CR><LF> Or <CR><LF>>` |
| 设置 | `msg_length><CR>` | `<CR><LF>OK <CR><LF>+CMD ERROR: <code><CR><LF> Or <CR><LF>> <CR><LF>+CLOUDPUBMSG: Timeout!<CR><LF>` |

**参数**

| <topic> | 发布的主题。 |
| --- | --- |
| <qos> | 发布消息的QoS 等级。 |
| <msg length> _ | 消息体长度，最大10240 字节，提示>后输入<length>指定的长度的消息内容。 |

**示例**

```
AT+CLOUDPUBMSG=”/J5VSBJMed74/TEST 0/neo00”,1,10 Pub 消息成功。
_ >
OK
+CLOUDPUBACK: <OK>
+CLOUDPUBLISH: 42069,”/J5VSBJMed74/TEST 0/neo00”,10,7777777777
_ AT+CLOUDPUBMSG=”/J5VSBJMed74/TEST 0/neo00”,1,10 Pub 消息失败，写入超时。
_ >
+CLOUDPUBMSG: Timeout!
```


### 15.10 AT+CLOUDUNSUB — 取消订阅命令

取消订阅，目前只支持一次取消一个订阅。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK <CR><LF>+CLOUDNSUBACK: <OK><CR><LF>` |
| 执行 | `AT+CLOUDUNSUB=<topic><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <topic> | 申请取消订阅的topic，字符串类型。 |
| --- | --- |

**示例**

```
AT+CLOUDUNSUB=”/1000146090/Ndevice T1/neo001” 取消订阅topic 成功。
_ OK
+CLOUDUNSUBACK: <OK>
AT+CLOUDUNSUB 参数个数错误。
ERROR
```


### 15.11 AT+CLOUDDISCONN — 断开MQTT 连接并做资源释

放 关闭MQTT 连接。 终端主动断开和服务端的连接，然后做MQTT 资源释放。断开连接后，如果需要pub 消息，需要 重新做设备连接操作。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+CLOUDDISCONN<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 |

**示例**

```
AT+CLOUDDISCONN 关闭MQTT 链路并释放资源。
OK
```


### 15.12 AT+CLOUDSTATE — MQTT 连接状态查询

查询MQTT 连接状态。 终端默认会发送ping 包保持连接在线，如果检测到服务器未回复ping 包的ACK，则会启用自动重 连的机制，客户也可以使用该指令定时检测连接状态，当查询到连接断开时可自行决定是否重连。 客户在查询到MQTT 的连接状态为断开想手动重连时，则需要先使用+CLOUDDISCONN 做资源 释放，并重新使用+CLOUDCONN 建立新的连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+CLOUDSTATE: <n>` |
| 执行 | `AT+CLOUDSTATE?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <n> | 状态 |
| --- | --- |
|  | 0：当前MQTT 为断开状态 |
|  | 1：当前MQTT 为在线状态 |

**示例**

```
AT+CLOUDSTATE? 查询到当前MQTT 连接为在线状态。
+CLOUDSTATE: 1
OK
```

