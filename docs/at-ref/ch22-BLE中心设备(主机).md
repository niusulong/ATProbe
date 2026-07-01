# 第 22 章 BLE中心设备(主机)

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 22 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 22.1 AT+NWBLESCAN — BLE 扫描周边BLE 设备

此命令用于扫描周边BLE 设备。 当扫描到的BLE 设备为中文名称时可能显示乱码。 扫描数量和当前BLE 设备信号强度有关。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLESCAN=<scan_ti` | `<CR><LF>OK` |
| 设置 | `Or me><CR>` | `<CR><LF>ERROR<CR><LF> <CR><LF>+NWURCBLESCAN:` |

**主动上报**

+NWURCBLESCAN <CR><LF><name>,<mac>,<addr_type><CR><LF> ...

**参数**

| <scan time> _ |  | 扫描时间 |
| --- | --- | --- |
|  |  | 参数类型：整数 |
|  |  | 取值范围：3~60s |
|  | <name> | 远端BLE 设备名称 |
|  | <mac> | 远端BLE 设备MAC 地址 |
| <addr type> _ | <addr type> _ | 地址类型 |
|  |  | 0： public address |
|  |  | 1： random address |
|  |  | 2： RPA public address |
|  |  | 3： RPA random address |

**示例**

```
AT+NWBLESCAN=50 设置50s 扫描周边设备，超时停止扫描 主动上报扫描结果
OK
+NWURCBLESCAN:
Honor V10,38:37:8b:71:28:c6,0
Shitou,5c:c3:07:16:dc:ce,0
```


### 22.2 AT+NWBLESCANEXT — BLE 扫描周边BLE 设备

此命令用于扫描周边BLE 设备。 当扫描到的ble 设备为中文名称时可能显示乱码。 扫描数量和当前BLE 设备信号强度有关。 注意：仅N58-CA(021/011 子型号) 标准版本支持该指令

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLESCANEXT=<sca` | `<CR><LF>OK<CR><LF>` |
| 设置 | `Or n_time><CR> AT+NWBLESCANEXT=?<C` | `<CR><LF>ERROR<CR><LF> <CR><LF>+NWBLESCANEXT: (range of supported` |
| 测试 | `R>` | `<scan_time>) <CR><LF>OK<CR><LF> <CR><LF>+NWURCBLESCANEXT:<CR><LF> <CR><LF><name>,<mac>,<rssi><data_len><adv_data>` |

**主动上报**

+NWURCBLESCANEXT <CR><LF> ...

**参数**

| <scan time> _ | 扫描时间 |
| --- | --- |
|  | 参数类型：整数 |
|  | 取值范围：3~60s |
|  | 0：立即停止扫描 |
|  | 99：一直扫描，直到主动停止扫描 |
|  | 远端BLE 设备名称 |
| <mac> <rssi> | 远端BLE 设备MAC 地址 |
| --- | --- |
|  | 信号强度(dBm) |
| <data len> _ <adv data> _ | 广播包数据长度 |
|  | 广播包数据(HEX 格式) |

**示例**

```
AT+NWBLESCANEXT=50 设置50s 扫描周边设备，超时停止扫描 主动上报扫描结果
OK
+NWURCBLESCANEXT:
HUAWEI FreeBuds Pro 2,24:81:48:20:51:14,-
83,23,16084855415745492046726565427564732050726F2032
mobike,1d:59:cd:6a:40:e4,-
75,31,02010607096D6F62696B6513FFB30402B4E4406ACD591D999999999
9000000
AT+NWBLESCANEXT=? 查询指令可设置参数范围
+NWBLESCANEXT: <3-60>|0|99
OK
```


### 22.3 AT+NWBLECCON — 建立BLE 连接

此命令用于建立BLE 与BLE 设备的连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBLECCON=<addr_type>,<mac><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLECCON:<CR><LF> <CR><LF><index>,<mac><CR><LF>` |
| 查询 | `AT+NWBLECCON?<CR>` | `<CR><LF>OK<CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| <addr_type> | 地址类型。 参数类型：整数类型。 取值范围：由+NWURCBLESCAN 上报中获得。 |
| <mac> | BLE 设备的MAC 地址。 参数类型：字符串。 取值范围：由+NWURCBLESCAN 上报中获得。 |
| <index> | 远端设备索引。 |

**示例**

```
AT+NWBLECCON=0,”58:86:ed:28:bb:5a” 与指定ble 设备建立连接
OK
+NWURCBLESTAT: 1,58:86:ED:28:BB:5A 若连接成功，则上报<status>[,<mac>]
注意：主动上报指令为+NWURCBLESTAT
AT+NWBLECCON? 查询BLE 的连接，并显示<index>,<mac>
+NWBLECCON: 若未建立连接，则不显示<index>,<mac>
1,58:86:ED:28:BB:5A
OK
```


### 22.4 AT+NWBLECDISCON — 断开BLE 连接

此命令用于断开BLE 与BLE 设备的连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+NWBLECDISCON<CR> Or` | `<CR><LF>ERROR<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 |

**示例**

```
AT+NWBLECDISCON OK 断开特定地址的BLE 设备
```


### 22.5 AT+NWBLEQSRV — 发现BLE 设备服务

此命令用于发现BLE 设备服务。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | … | `<CR><LF>+NWBLEQSRV: <CR><LF><srv_id>,<srv_uuid>,<srv_type>` |
| 执行 | `AT+NWBLEQSRV<CR> Or` | `<CR><LF>OK<CR><LF> <CR><LF>ERROR<CR><LF>` |

**参数**

| <srv id> _ | 服务序号，整数类型，从0 起始递增。 |
| --- | --- |
| <srv uuid> _ | 服务的UUID |
| <srv type> _ | 服务的类型： |
|  | 0：次要服务 |
|  | 1：主要服务 |

**示例**

```
AT+NWBLEQSRV 开始发现服务 发现到的服务： 序号为0，服务UUID 为0x1808，属性类型为1（主要） 序号为1，服务UUID 为0x1811，属性类型为0（次要）
+NWBLEQSRV:
0,0x1808,1
1,0x1811,0
...
OK
```


### 22.6 AT+NWBLEQCHAR — 发现BLE 设备服务特征

此命令用于发现BLE 设备服务特征。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEQCHAR:<CR><LF> <CR><LF><srv_id>,<char_id>,<char_uuid>,<char_prop>< CR><LF>` |
| 执行 | `AT+NWBLEQCHAR<CR> … Or AT+NWBLEQCHAR=<srv_id>` | `<CR><LF>OK<CR><LF> <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEQCHAR:<CR><LF> <CR><LF><srv_id>,<char_id>,<char_uuid>,<char_prop>< CR><LF>` |
| 设置 | `<CR> … Or` | `<CR><LF>OK<CR><LF>` |

**参数**

| <srv id> _ |  | 服务序号。 |
| --- | --- | --- |
|  |  | 参数类型：整数。 |
|  |  | 取值范围：由AT+NWBLEQSRV 返回中获得。 |
|  | <char id> _ | 服务特征的序号，整数类型，从0 起始递增。 |
|  | <char uuid> _ | 服务特征的UUID。 |
| <char prop> _ | <char prop> _ | 服务特征属性，具体包含如下： |
|  |  | Broadcast 0x01 |
|  |  | Read 0x02 |
|  |  | Write without response 0x04 |
|  |  | Write 0x08 |
|  |  | Notify 0x10 |
|  |  | Indicate 0x20 |
|  |  | Authenticated Signed Write 0x40 |
|  |  | Extended Properties 0x80 |

**示例**

```
AT+NWBLEQCHAR=0 获取指定服务序号0 的特征信息。 获取到的指定服务特征信息： 服务序号0，特征序号为0，特征UUID 为0x2906,服务特征属性0xff（全部支持） 服务序号0 特征序号为1，特征UUID 为0x2906,服务特征属性0xef（只有Extended Properties 不支持） ... 获取所有服务特征信息。 获取到的所有服务特征信息： 服务序号0，特征序号为0，特征UUID 为0x2906,服务特征属性0xff 服务序号1，特征序号为0，特征UUID 为0x2906,服务特征属性0xff
+NWBLEQCHAR:
0,0,0x2906,0xff
0,1,0x2907,0xef
...
OK
AT+NWBLEQCHAR
+NWBLEQCHAR:
0,0,0x2906,0xff
0,1,0x2907,0xef
1,0,0x2906,0xff
1,1,0x2907,0xef
...
OK
```


### 22.7 AT+NWBLECSEND — 发送数据

此命令用于BLE 主机向BLE 设备发送数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLECSEND=<srv_id>,<char_id>,<mode>,` | `<CR><LF>><CR><LF> <CR><LF>OK<CR><LF> Or <CR><LF>+NWBLECSEND:` |
| 设置 | `<len><CR>` | `OPERATION EXPIRED<CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**主动上报**

<CR><LF>+NWBLECSEND: <state><CR><LF>

**参数**

| <srv id> _ | 服务序号。 |
| --- | --- |
|  | 参数类型：整数 |
|  | 取值范围：由AT+NWBLEQSRV 或AT+NWBLEQCHAR 返回中获得 |
| <char id> _ | 服务特征序号 |
|  | 参数类型：整数 |
|  | 取值范围：由AT+NWBLEQCHAR 返回中获得 |
| <mode> | 发送模式，整数类型，取值范围0-1，取值定义如下： |
|  | 0：HEX 发送 |
|  | 1：ASCII 发送，默认模式 |
| <len> | 数据长度。 |
|  | 参数类型：整数 |
|  | 取值范围：1~1024 |
| <state> | 0:发送失败 |
|  | 1:发送成功 |

**示例**

```
AT+NWBLECSEND=1,1,1,5 设置发送数据参数。
>hello 在“>”后，输入需要发送的数据；
OK 当已建立连接，且发送缓冲区未满，则返回OK；
Or
ERROR +NWBLECSEND:1 如果连接尚未建立、异常关闭，或参数不正确、发送缓冲区已满，则返回ERROR 主动上报：数据发送成功。
AT+NWBLECSEND=5,0,1,10 输入发送命令出现“>”后，输入数据长度小于10，30 秒后提示超时。
>
+NWBLECSEND: OPERATION
EXPIRED
```


### 22.8 +NWURCBLECRECV — 接收数据上报

此命令用于BLE 主机接收数据上报。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+NWURCBLECRECV: <srv_id>,<crt_id>,<len>,<data><CR><LF>` |

**参数**

| <data> | 数据内容 |
| --- | --- |
| <len> | 数据长度 |
| <srv id> _ | 服务序号 |
| <char id> _ | 服务特征序号 |

**示例**

```
+NWURCBLECRECV:3,0,3,123 服务序号为3，服务特征序号为0 的特征接收到数据长度为3，内容为123， ASCII 格式。
数据接收格式默认ASCII 模式，如需修改使用AT+NWBLERCVMODE 通用指令。
```


### 22.9 AT+NWBLECREAD — 读取特征数据

此命令用于BLE 主机读取从机特征数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLECREAD=<srv_id>,<char_id>,<mode>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `<CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLECREAD:range of supported<srv_id>,range of` |
| 测试 | `AT+NWBLECREAD=?<CR> 主动上报 +NWURCBLECREAD:<data_len>,<data>` | `supported<crt_id>,range of supported<mode> <CR><LF>OK<CR><LF>` |

**参数**

|  | <srv id> _ |  | 服务序号，整数类型，0-9。 |
| --- | --- | --- | --- |
| <char id> _ | <char id> _ | 服务特征序号，整数类型，0-9。 | 服务特征序号，整数类型，0-9。 |
| <mode> |  |  | 数据格式，整数类型，取值范围0-1，取值定义如下： |
|  |  |  | 0：HEX |
|  |  |  | 1：ASCII |
| <data len> _ |  | 数据长度 | 数据长度 |
| <data> |  | 数据内容 |  |

**示例**

```
AT+NWBLECREAD=4,0,0 读取服务序号为4，服务特征序号为0 的特征数据，数据格式为HEX。
OK
+NWURCBLECREAD:
245,33363636000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
000000000000000000000000000000000000000000
00000000000000000000000000000000
AT+NWBLECREAD=? READ 参数列表。
+NWBLECREAD: <0-9>,<0-9>,<0-1>
OK
```

