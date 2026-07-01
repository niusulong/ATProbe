# 第 20 章 BLE功能通用指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 20 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 20.1 AT+NWBLEROLE — 设置BLE 模式

此命令用于设置BLE 的模式（主机和从机的切换），需在蓝牙关闭状态下设置。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBLEROLE=<ble_role><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEROLE: <ble_role> <CR><LF>OK<CR><LF>` |
| 查询 | `AT+NWBLEROLE?<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <ble role> _ | 模式选择，整数类型，取值定义如下： |
| --- | --- |
|  | 0：从机模式，默认模式 |
|  | 1：主机模式 |

**示例**

```
AT+NWBLEROLE=1 设置为主机模式。 查询模式。
OK
AT+NWBLEROLE?
+NWBLEROLE: 1
OK
```


### 20.2 AT+NWBLEADV — BLE 广播参数设置

用于设置BLE 广播参数。 广播报文会在固定的37，38，39 信道上发送报文。  执行该命令前需关闭广播后设置。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBLEADV=<min>,<max><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEADV: <min>,<max>` |
| 查询 | `AT+NWBLEADV?<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+NWBLEADV: range of supported(<min>-<max>),range of supported` |
| 测试 | `AT+NWBLEADV=?<CR>` | `(<min>-<max>) <CR><LF>OK<CR><LF>` |

**参数**

其真正的广播间隔=（min/max） * 0.625ms，其广播间隔范围为（20ms ~ 10.28s）。

|  | <min> |  | 广播最小间隔，整数类型，取值范围32-16384。 |
| --- | --- | --- | --- |
| <max> | <max> | 广播最大间隔，整数类型，取值范围32-16384。 | 广播最大间隔，整数类型，取值范围32-16384。 |

**示例**

```
AT+NWBLEADV=100,5000 OK 设置广播参数。
AT+NWBLEADV? READ 当前广播参数。
+NWBLEADV: 100,5000
OK
AT+NWBLEADV=? READ 参数列表。
+NWBLEADV: (32-16384),(32-16384)
OK
```


### 20.3 AT+NWBLEADVEN — BLE 广播使能

用于设置BLE 广播使能。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBLEADVEN=<enable><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBLEADVEN: <enable>` |
| 查询 | `AT+NWBLEADVEN?<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+NWBLEADVEN: (range of supported` |
| 测试 | `AT+NWBLEADVEN=?<CR>` | `<enable>) <CR><LF>OK<CR><LF>` |

**参数**

| <enable> | 整数类型，取值范围0-1。 |
| --- | --- |
|  | 0：关闭BLE 广播 |
|  | 1：使能BLE 广播 |

**示例**

```
AT+NWBLEADVEN=1 使能BLE 广播。
OK
AT+NWBLEADVEN? READ 当前广播状态。
+NWBLEADVEN: 1
OK
AT+NWBLEADVEN=? READ 参数列表。
+NWBLEADVEN: (0-1)
OK
BLE 从机打开后，默认为广播打开，有设备连接后自动关闭广播。

主机模式下不支持广播开关操作。

```


### 20.4 +NWURCBLESTAT — BLE 状态主动上报

上报当前BLE 状态。

**主动上报**

+NWURCBLESTAT: <status>[,<mac>]<CR><LF>

**参数**

| <status> |  | 0：连接断开 |
| --- | --- | --- |
|  |  | 1：连接成功 |
| <mac> | 连接设备的MAC 地址 | 连接设备的MAC 地址 |

**示例**

```
+NWURCBLESTAT: 1,2A:02:0A:72:C8:53 BLE 连接成功。
+NWURCBLESTAT: 0 BLE 断开成功。
```

