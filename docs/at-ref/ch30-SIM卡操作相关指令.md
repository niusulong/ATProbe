# 第 30 章 SIM卡操作相关指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 30 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 30.1 AT+SIMCROSS — 双卡单待切换功能

操作模组在双卡之间切换，第一次开机默认使用卡槽1。 目前仅支持双卡单待。如果实际使用时只有一张卡（确保卡可以正常使用），且此时出现无法注册网 络情况，建议使用+SIMCROSS?查询，如果返回值与当前SIM 卡实际插入卡槽不一致，则请尝试使用 指令切换到另一个卡槽上网。 如果只插入一张卡，先使用本指令查询有效卡槽，卡插入对应卡槽使用，否则无法正常注册网络。 由当前使用卡切换到另一张卡时，指令设置完需重启模组方可生效。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+SIMCROSS=<sim_id><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+SIMCROSS: <sim_id>` |
| 查询 | `AT+SIMCROSS?<CR>` | `<CR><LF>OK<CR><LF> <CR><LF>+SIMCROSS: (range of <sim_id> value)` |
| 测试 | `AT+SIMCROSS=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

| <sim id> _ | SIM 卡标识 |
| --- | --- |
|  | 1：SIM 卡1（首次开机默认值） |
|  | 2：SIM 卡2 |

**示例**

```
AT+SIMCROSS=1 模组切换到使用SIM 卡1。需重启模组生效。
OK
AT+SIMCROSS=? 查询SIM 卡选择的范围。
+SIMCROSS: (1-2)
OK
AT+SIMCROSS?
+SIMCROSS: 1
OK
```

