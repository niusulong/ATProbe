# 第 13 章 Wi-Fi功能

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 13 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 13.1 AT+WIFIAPSCAN — Wi-Fi 热点扫描

该指令用于扫描模组周围的Wi-Fi 热点。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+WIFIAPSCAN: <MAC Address>,<rssi>,<channel>` |
| 执行 | `AT+WIFIAPSCAN<CR>` | `<CR><LF>OK<CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <MAC Address> | 物理地址 |
| --- | --- |
| <rssi> | 信号强度 |
| <channel> | 通道号 |

**示例**

```
AT+WIFIAPSCAN 开始扫描，并输出所有的扫描结果。
+WIFIAPSCAN: ec6c9f4be889,-93,1
+WIFIAPSCAN: ec6c9f4be880,-99,1
+WIFIAPSCAN: ec6c9f4be87a,-96,1
OK
```


### 13.2 AT+WIFIGSMLOC — Wi-Fi 定位

该指令用于Wi-Fi 定位。 先进行Wi-Fi 扫描，拨号。再进行定位。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+WIFIGSMLOC: <fail_string><CR><LF> Or <CR><LF>+WIFIGSMLOC: {<result_string>} <CR><LF>+WIFIGSMLOC: OK<CR><LF> Or` |
| 执行 | `AT+WIFIGSMLOC =<n><CR>` | `<CR><LF><code> <CR><LF>+WIFIGSMLOC: FAIL<CR><LF> Or <CR><LF>OK <CR><LF>+WIFIGSMLOC: TIMEOUT<CR><LF>` |

**参数**

| <n> |  | 0:关闭wifi 定位 |
| --- | --- | --- |
|  |  | 1：打开wifi 定位 |
| <fail string> _ |  | GPRS DISCONNECTION |
|  |  | ERROR |
|  |  | LINK NOT FREE |
|  | <result string> _ | 包含经纬度的字符串 |
| <code> | <code> | 401：没有权限访问 |
|  |  | 400：请求在解析过程中出错 |
|  |  | 404：请求合法，但是所查基站未被收录，因此无法计算出结果 |
|  |  | 408：服务器解析超时 |
|  |  | 500：服务器内部错误 |

**示例**

```
AT+WIFIGSMLOC=1 输出定位结果。
+WIFIGSMLOC:
{"location":{"lat":34.2060764,"lng":108.8360664},"accuracy":50.0}
+WIFIGSMLOC: OK
```

