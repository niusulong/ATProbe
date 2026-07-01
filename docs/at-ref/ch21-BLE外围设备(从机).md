# 第 21 章 BLE外围设备(从机)

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 21 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 21.1 AT+NWBLEPSRV — 创建服务

创建服务。 创建服务时需关闭蓝牙。 现支持创建2 个服务，每个服务下可添加10 个特征。 该命令掉电不保存。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLEPSRV=<app_id>,<uuid>,` | `<CR><LF>OK<CR><LF>` |
| 设置 | `<num>,<p><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEPSRV: <app>,<uuid>,range` |
| 测试 | `AT+NWBLEPSRV=?<CR>` | `of supported<num>,range of supported<p> <CR><LF>OK<CR><LF>` |

**主动上报**

+NWBLEPSRV: <srv_id><CR><LF>

**参数**

| 参数 | 说明 |
| --- | --- |
| <app_id> | 要添加在哪个app 的app 编号，必须是已经创建的应用（可用NWBLEREG?READ） 暂不支持注册应用，app_id 填0。 |
| <uuid> | 创建的UUID 号。可添加16 位uuid 和128 位uuid。例如：16 位uuid 是0x180D。128 位uuid 输入格式为8-4-4-4-12，例如：123e4567-e89b-12d3-a456-426655440000。 |
| <uuid> | 要添加的特征数量，整数类型，取值范围1-10。 |
| <p> | 是否为主要服务（请务必在每个应用下创建一个主要服务），整数类型，取值范围0-1。 |

**示例**

```
AT+NWBLEPSRV=0,”0x1808”,2,1 在0 编号的app 下创建0x1808（葡萄糖）服务，2 个特征，是主要的服务。
OK
+NWBLEPSRV: 1
AT+NWBLEPSRV=? READ 参数列表。
+NWBLEPSRV: <0>,<uuid>,<1-10>,<0-1>
OK
```


### 21.2 AT+NWBLEPCRT — 向服务添加特征

添加16 位特征。 添加特征时需关闭蓝牙。 该命令掉电不保存。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLEPCRT=<app_id>,<srv_id>,` | `<CR><LF>OK<CR><LF>` |
| 设置 | `<uuid>,<slt>,<per>,<cp><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEPCRT: <app>,range of supported<srv>,<uuid>,range of` |
| 测试 上报 | `AT+NWBLEPCRT=?<CR> +NWBLEPCRT: <crt_id><CR><LF>` | `supported<slt>,range of supported<per>,range of supported<cp> <CR><LF>OK<CR><LF>` |

**参数**

| <app id> _ | 要添加在哪个app 的编号,由NWBLEREG 上报。 |
| --- | --- |
|  | 暂不支持注册应用，app id 填0。 _ |
| <srv id> _ |  |
|  | 要在哪个服务下添加特征uuid 号，由NWBLEPSRV 上报。 |
| <uuid> |  |
|  | 本特征的uuid。 |
| <slt> |  |
|  | 是否选择描述，整数类型，取值范围0-1。 |
|  | 0：不用选择 |
|  | 1：选择描述 |
| <per> | 读写权限，整数类型，取值范围0-2。 |
|  | 0：只读 |
| <cp> | 1：只写 |
| --- | --- |
|  | 2：读写 |
|  | 特征特性，整数类型，取值范围0-4。 |
|  | 0：写 |
|  | 1：读 |
|  | 2：通知 |
|  | 3：显示 |
|  | 4：以上都具备 |

**示例**

```
AT+NWBLEPCRT=0,1,”0x9999”,0,2,4 在0 编号的app 下，向0x1808 服务添加0x9999 特征，不选择 描述，读写权限，写|读|通知|显示。
OK
+NWBLEPCRT: 0
AT+NWBLEPCRT=? READ 参数列表。
+NWBLEPCRT: <0>,<1-2>,<uuid>,<0-1>,<0-2>,<0-4>
OK
```


### 21.3 AT+NWBLEPCRTEX — 向服务添加特征*

AT+NWBLEPCRT 的扩展指令，支持添加16 位和128 位 UUID 特征。 添加特征时需关闭蓝牙。 该命令掉电不保存。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLEPCRTEX=<app_id>,<srv_i` | `<CR><LF>OK<CR><LF>` |
| 设置 | `d>,<uuid>,<slt>,<per>,<cp><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEPCRTEX:<app_id>,range of supported<srv>,<uuid>,range of` |
| 测试 上报 | `AT+NWBLEPCRTEX=?<CR> <CR><LF>+NWBLEPCRTEX: <crt_id><CR><LF>` | `supported<slt>,range of supported<per>,range of supported<cp> <CR><LF>OK<CR><LF>` |

**参数**

| <app id> _ | 要添加在哪个app 的编号,由NWBLEREG 上报。 |
| --- | --- |
|  |  | 暂不支持注册应用，app id 填0。 _ |  |
| --- | --- | --- | --- |
|  | <srv id> _ | 要在哪个服务下添加特征uuid 号，由NWBLEPSRV 上报。 |  |
|  | <uuid> |  |  |
|  |  | 本特征的 uuid。可添加16 位uuid 和128 位uuid。例如：16 位uuid 是0x180D。 |  |
|  |  | 128 位 uuid 输入格式 为 8-4-4-4-12 ，例如： 123e4567-e89b-12d3-a456- |  |
|  |  | 426655440000。 |  |
|  |  | 是否选择描述，整数类型，取值范围0-1。 |  |
|  | <slt> |  |  |
|  |  | 0：不用选择 |  |
|  |  | 1：选择描述 |  |
| <per> | <per> | 读写权限，整数类型，取值范围0-2047。支持不同权限组合，将不同权限值累加设 |  |
|  |  | 置。例如设置读写权限取值为3 |  |
|  |  | READABLE | 1 |
|  |  | WRITEABLE | 2 |
|  |  | R AUTHENT REQUIRED _ _ | 4 |
|  |  | R AUTHORIZE REQUIRED _ _ | 8 |
|  |  | R ENCRYPTION REQUIRED _ _ | 16 |
|  |  | R AUTHENT MITM REQUERED _ _ _ | 32 |
|  |  | W AUTHENT REQUIRED _ _ | 64 |
|  |  | W AUTHORIZE REQUIRED _ _ | 128 |
|  |  | W ENCRYPTION REQUIRED _ _ | 256 |
|  |  | W AUTHENT MITM REQUERED _ _ _ | 512 |
|  |  | BR ACCESS ONLY _ _ | 1024 |
| <cp> |  | 特征特性，整数类型，取值范围0-255。支持不同特征组合，将不同特征值累加设置 |  |
|  |  | 例如设置读写特征取值为10 |  |
|  |  | BROADCAST | 1 |
|  |  | READ | 2 |
|  |  | WWP | 4 |
|  |  | WRITE | 8 |
|  |  | NOTIFY | 16 |
|  |  | INDICATE | 32 |
|  |  | ASW | 64 |
|  |  | EX PROP _ | 128 |

**示例**

```
AT+NWBLEPCRTEX=0,1,"0x1001",0,3,24 在0 编号的app 下，向0x9999 服务添加0x1001 特征，不选择 描述，读写权限，写和通知特征。
OK
+NWBLEPCRTEX: 0
AT+NWBLEPCRTEX=? READ 参数列表。
+NWBLEPCRTEX: <0>,<1-2>,<uuid>,<0-1>,<0-
2047>,<0-255>
OK
```


### 21.4 AT+NWBLEPSTR — 启动服务

启动服务。 启动服务时需关闭蓝牙。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBLEPSTR=<app_id>,<srv_id><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEPSTR: <app_id>,range` |
| 测试 | `AT+NWBLEPSTR=?<CR>` | `of supported<srv_id> <CR><LF>OK<CR><LF>` |

**参数**

| <app id> _ <srv id> _ | 要添加在哪个app 的app 编号，必须是已经创建的应用, 由NWBLEPREG 上报。 |
| --- | --- |
|  | 暂不支持注册应用，app id 填0。 _ |
|  | 要开始哪个服务，服务的uuid 号，由NWBLEPSRV 上报。 |

**示例**

```
AT+NWBLEPSTR=0,1 在0 编号的app 下，开始0x1808（葡萄糖）服务。
OK
AT+NWBLEPSTR=? READ 参数列表。
+NWBLEPSTR: <0>,<1-2>
OK
```


### 21.5 AT+NWBLEPSEND — 发送数据

用于向中心设备发送数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `d>,<op>,<mode>, len<CR> 在响应“>”后，输入 需要发送的数据` | `<输入数据> 如果已建立连接，且发送缓冲区未满， 回应： <CR><LF>OK<CR><LF> 如果30s 内输入的数据长度小于len，回应： <CR><LF>+NWBLEPSEND: OPERATION EXPIRED<CR><LF> 如果连接尚未建立、异常关闭、或 参数不正确、发送缓冲区已满，响应： <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEPSEND:` |
| 测试 | `AT+NWBLEPSEND=?<CR>` | `<srv_id>,<crt_id>,<op>,<mode>,<len> <CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBLEPSEND=<srv_id>,<crt_i` | `<CR><LF>>` |

**主动上报**

+NWBLEPSEND +NWBLEPSEND:<state><CR><LF>

**参数**

| <srv id> _ <crt id> _ <op> <mode> <len> <state> | 要发送在哪个服务的srv 编号，必须是已经创建的服务,由NWBLEPSRV 上报。 |
| --- | --- |
|  | 向哪个特征发送，特征编号，由NWBLEPCRT 上报。 |
|  | 整数类型，取值范围0-1。 |
|  | 0：发送通知 |
|  | 1：发送指示 |
|  | 整数类型，取值范围0-1。 |
|  | 发送模式，0：HEX 发送，1：ASCII 发送。 |
|  | 数据长度，整数类型，取值范围1-1024。 |
|  | 0:发送失败 |
|  | 1:发送成功 |

**示例**

```
AT+NWBLEPSEND=0,0,0,1,5 在0 编号的app 下，向0 号特征发送通知，通知内容为hello，发 送成功。
>hello
OK
+NWBLEPSEND:1
AT+NWBLEPSEND=? READ 参数列表。
+NWBLEPSEND: <0-2>,<0-9>,<0-1>,<0-1>,<1-
1024>
OK
模组自带的uuid 为0xFEE0 的服务srv_id 为0，uuid 为0xFEE1 的特征crt_id 为0。

数据是否发送成功取决于特征是否具有对应读写。通知/指示权限。

支持数据长度为1-1024。

```


### 21.6 +NWURCBLEPRECV — 接收数据上报

用于接收数据上报，数据信息主动上报至AT 通路。

**主动上报**

<CR><LF>+NWURCBLEPRECV:<srv_id>,<crt_id>,<len>,<data><CR><LF>

**参数**

| <data> | 数据内容 |
| --- | --- |
| <len> | 数据长度 |
| <srv id> _ | 服务id 号 |
| <crt id> _ | 特征值id 号 |

**示例**

```
+NWURCBLEPRECV: 0,0,3,123 接收到数据，内容为123， ASCII 格式。
+NWURCBLEPRECV:0,0,5,3132333435 hex 格式显示。
```


### 21.7 AT+NWBLEPWRITE — 写入数据

用于向特征写入数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLEPWRITE=<srv_id>,` | `supported<srv_id>,range of supported<crt_id>,range of supported<mode>,<data> <CR><LF>OK<CR><LF> <CR><LF>OK<CR><LF>` |
| 设置 | `Or <crt_id>,<mode>, <data><CR>` | `<CR><LF>ERROR<CR><LF>` |
| 测试 | `AT+NWBLEPWRITE=?<CR>` | `<CR><LF>+NWBLEPWRITE: range of` |

**参数**

| 参数 | 说明 |
| --- | --- |
| <srv_id> | 服务序号，整数类型，取值范围0-2。 |
| <crt_id> | 服务特征序号，整数类型，取值范围0-9。 |
| <mode> | 数据格式，整数类型，取值范围：0-1。 0：HEX 1：ASCII |
| <data> | 数据内容 |

**示例**

```
AT+NWBLEPWRITE=1,0,0,33363636 向服务序号为1，服务特征序号为0 的特征写入十六进制数据33363636。
OK
AT+NWBLEPWRITE=? READ 参数列表。
+NWBLEPWRITE: <0-2>,<0-9>,<0-1>,<data>
OK
```


### 21.8 AT+NWBLERCVMODE — 设置接收数据格式

设置接收数据格式。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+NWBLERCVMODE=<mode><CR>` | `<CR><LF>OK<CR><LF> <CR><LF>NWBLERCVMODE: <mode>` |
| 查询 | `AT+NWBLERCVMODE?` | `<CR><LF>OK<CR><LF> <CR><LF>+NWBLERCVMODE: range<mode>` |
| 测试 | `AT+NWBLERCVMODE=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <mode> | 整数类型，取值范围0-1 |
| --- | --- |
|  | 0：HEX 模式 |
| 1：ASCII 模式，默认模式 |
| --- |

**示例**

```
AT+NWBLERCVMODE=1 设置接收模式。
OK
AT+NWBLERCVMODE=? READ 参数列表。
+NWBLERCVMODE: <0-1>
OK
```


### 21.9 AT+NWBLEDISCON — 查询/断开BLE 连接

查询当前连接信息；与指令已连接的BLE 远端设备断开连接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+NWBLEDISCON<CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEDISCON: <CR><LF><index>,<name>,<mac> <CR><LF><index>,<name>,<mac>` |
| 查询 | `AT+NWBLEDISCON?` | `... <CR><LF><index>,<name>,<mac> ... <CR><LF>OK<CR><LF>` |

**参数**

| <index> <name> <mac> | 远端设备索引。 |
| --- | --- |
|  | 远端设备名。 |
|  | 远端设备的MAC 地址（必须是READ 列表中的MAC 地址）。 |

**示例**

```
AT+NWBLEDISCON 与设备断开连接。
OK
AT+NWBLEDISCON? READ 当前连接列表。
+NWBLEDISCON:
1,65:7F:49:B2:21:6D
OK
```


### 21.10 AT+NWBLESRVRM — 移除指定服务

移除指定服务。 移除服务时需关闭BLE。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBLESRVRM=<app_id>,<srv_id><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLESRVRM:` |
| 测试 | `AT+NWBLESRVRM=?<CR>` | `<app_id>,range of supported<srv_id> <CR><LF>OK<CR><LF>` |

**参数**

| <app id> _ |  | 应用ID 号（创建成功后主动上报返回的） |
| --- | --- | --- |
|  |  | 暂不支持注册应用，app id 填0 _ |
|  | <srv id> _ | 服务ID 号（特征创建成功后主动返回的） |

**示例**

```
AT+NWBLESRVRM=0,1 移除0 号应用下的1 号服务。
OK
READ 参数列表。
AT+NWBLESRVRM=?
+NWBLESRVRM: <0>,<1-2>
OK
```


### 21.11 AT+NWBLECRTRM — 移除指定特征

移除指定特征。 移除特征时需关闭BLE。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWBLECRTRM=<app_id>,<srv_id>,<cr` | `<CR><LF>OK<CR><LF>` |
| 设置 | `t_id><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLECRTRM: <app_id>,value range of <srv_id>,value` |
| 测试 | `AT+NWBLECRTRM=?<CR>` | `range of <crt_id> <CR><LF>OK<CR><LF>` |

**参数**

| <app id> _ <srv id> _ <crt id> _ | 应用ID 号（创建成功后主动上报返回的） |
| --- | --- |
|  | 暂不支持注册应用，app id 填0 _ |
|  | 服务ID 号，取值范围为1-2（创建成功后主动上报返回的） |
|  | 特征ID 号，取值范围为0-9（特征创建成功后主动返回的） |

**示例**

```
AT+NWBLECRTRM=0,0,0 移除0 号应用下0 号服务的0 号特征。
OK
READ 参数列表。
AT+NWBLESRVRM=?
+NWBLESRVRM:<0>,<1-2>,<0-9>
OK
```


### 21.12 AT+NWIBEACON — ibeacon 功能

ibeacon 功能。 设置ibeacon 参数时需关闭广播。 重启蓝牙会关闭ibeacon。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+NWIBEACON:` |
| 测试 | `AT+NWIBEACON=?<CR>` | `<uuid>,<major>,<minor>,<txpwr> <CR><LF>OK<CR><LF> <CR><LF>+NWIBEACON: <uuid>,<major>,<minor>,<txpwr>` |
| 查询 | `AT+NWIBEACON?<CR> AT+NWIBEACON=<uuid>,<major>,` | `<CR><LF>OK<CR><LF> Or <CR><LF>OK<CR><LF>` |
| 设置 | `<minor>[,<txpwr>]<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
| <uuid> | UUID 值，16 个字节，十六进制。 <major> major 值，2 个字节，十六进制。 <minor> minor 值，2 个字节，十六进制。 |
| <txpwr> | 1m 处的rssi，单位dBm，参数范围：-127-20。默认值：-59 |

**示例**

```
AT+NWIBEACON=B9007F30F5F8466EAFF925556B57FE55,1 设置iBeacon 参数。
234,0001
OK
READ 参数列表。
AT+NWIBEACON=?
+NWIBEACON: <uuid>,<major>,<minor>,<txpwr>
OK
AT+NWIBEACON? 查询iBeacon 参数。
+NWIBEACON:
B9007F30F5F8466EAFF925556B57FE55,1234,0001,-59
OK
```


### 21.13 AT+NWBLEADVDATA — 设置广播数据

在打开BLE 之后设置。 按照广播数据协议设置(datalen+advType+advdata)，否则会造成广播数据异常

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+NWBLEADVDATA=<len>,<data><CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <len> <data> | 数据长度。长度范围0-28 字节 |
| --- | --- |
|  | 数据内容，HEX |

**示例**

```
AT+NWBLEADVDATA=20,0503F6FEF5FE0DFFAA00660E4608 设置广播数据。
0FFFFF210100
OK
```

