# 第 19 章 BT/BLE通用基础AT指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 19 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 19.1 AT+NWBTBLEPWR — BT/BLE 电源开关

打开/关闭BT/BLE 模组电源，运行/关闭蓝牙协议栈，完成数据传输的初始化功能。 上电开机之后默认为关闭状态，打开之后BT/BLE 为可发现可连接模式。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+NWBTBLEPWR=<status><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWBTBLEPWR: <status>` |
| 查询 | `AT+NWBTBLEPWR?<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+NWBTBLEPWR: (range of supported` |
| 测试 | `AT+NWBTBLEPWR=?<CR>` | `<status>) <CR><LF>OK<CR><LF>` |

**参数**

| <status> | 整数类型，取值范围0 ~ 1 |
| --- | --- |
|  | 0：关闭蓝牙 |
|  | 1：打开蓝牙 |

**示例**

```
AT+NWBTBLEPWR=1 打开蓝牙/BLE 模组。
OK
AT+NWBTBLEPWR? READ 当前蓝牙/BLE 状态，打开状态。
+NWBTBLEPWR: 1
OK
AT+NWBTBLEPWR=?
+NWBTBLEPWR: (0-1)
OK
```


### 19.2 AT+NWBTBLENAME — BT/BLE 名称设置

设置/查看当前BT/BLE 设备名称。 蓝牙名称仅在蓝牙关闭时才可以修改。 该设置掉电保存。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 设置 | `AT+NWBTBLENAME=<name><CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+NWBTBLENAME: <name>` |
| 测试 | `AT+NWBTBLENAME=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <name> | 本地蓝牙名称，字符串类型，不支持中文，长度范围1-24。 |
| --- | --- |

**示例**

```
AT+NWBTBLENAME=”Neoway” 设置BT/BLE 名称为Neoway。
OK
AT+NWBTBLENAME? READ 当前BT/BLE 模组名称。
+NWBTBLENAME: Neoway
OK
AT+NWBTBLENAME=? READ 参数列表。
+NWBTBLENAME: <name>
OK
```


### 19.3 AT+NWBTBLEMAC — BT/BLE MAC 地址READ 设置

查看当前BT/BLE 设备的MAC 地址。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| READ | `AT+NWBTBLEMAC?<CR>` | `<CR><LF>+NWBTBLEMAC: <mac> <CR><LF>OK<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无。 |

**示例**

```
AT+NWBTBLEMAC? READBT/BLE MAC 地址为12:7B:59:96:96:1B。
+NWBTBLEMAC: 12:7B:59:96:96:1B
OK
```

