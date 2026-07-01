# 第 23 章 DTMF功能指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 23 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 23.1 AT+VTS — 发送DTMF 音

发送DTMF 信号。 此指令通话中设置有效，电信卡仅支持(0-9,*,#)。 格式 <CR><LF>OK<CR><LF> 执行 AT+VTS=<DTMF><CR> Or <CR><LF>ERROR<CR><LF> <CR><LF>+VTS: (value range of <DTMF>) 测试 AT+VTS=?<CR> <CR><LF>OK<CR><LF>

**参数**

| <DTMF> | 参数为ASCII：0-9, #, *, A-D |
| --- | --- |
| <TONE> | 参数范围为1-10，单位为tone*100ms |

**示例**

```
AT+VTS=? 查询模组DTMF 信号范围。
+VTS: (0-9,*,#,A,B,C,D),(1-10)
OK
AT+VTS=1 通话中设置。
OK
AT+VTS=1 非通话中设置。
ERROR
```

