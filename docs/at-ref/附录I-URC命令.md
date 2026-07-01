# 附录 I URC 命令

> 来源：《N58 AT 命令手册 v2.0》附录 I（p.369-371）
> URC（Unsolicited Result Code，主动上报）汇总。条件列指触发该上报的设置。

| No. | URC 显示 | 含义 | 条件 |
| --- | --- | --- | --- |
| 1 | `+CREG: <stat>` | 启用网络注册自动上报结果代码 `+CREG:<stat>` | `AT+CREG=1` |
| 2 | `+CREG: <stat>[,[<lac>],[<ci>],[<AcT>]]` | 启用自动上报网络注册和位置信息结果代码 | `AT+CREG=2` |
| 3 | `+CGREG: <stat>` | 启用网络注册自动上报结果代码 `+CGREG:<stat>` | `AT+CGREG=1` |
| 4 | `+CGREG: <stat>[,<[lac>,]<[ci>],[<AcT>],[<rac>]]` | 启用自动上报网络注册和位置信息结果代码 | `AT+CGREG=2` |
| 5 | `+CEREG: <stat>` | 启用网络注册自动上报结果代码 `+CGREG:<stat>` | `AT+CEREG=1` |
| 6 | `+CEREG: <stat>[,[<tac>],[<ci>],[<AcT>]]` | 启用自动上报网络注册和位置信息结果代码 | `AT+CEREG=2` |
| 7 | `+CEREG: <stat>[,[<tac>],[<ci>],[<AcT>][,<cause_type>,<reject_cause>]]` | 启用网络注册、位置信息和 EMM 原因值信息自动上报结果代码 | `AT+CEREG=3` |
| 8 | `+C5GREG: <stat>` | 允许网络注册主动上报结果代码 | `AT+C5GREG=1` |
| 9 | `+C5GREG: <stat>[,[<tac>],[<ci>],[<AcT>],[<Allowed_NSSAI_length>],[<Allowed_NSSAI>]]` | 允许网络注册主动上报网络注册结果 | `AT+C5GREG=2` |
| 10 | `+C5GREG: <stat>[,[<tac>],[<ci>],[<AcT>],[<Allowed_NSSAI_length>],[<Allowed_NSSAI>][,<cause_type>,<reject_cause>]]` | 允许网络注册主动上报网络注册结果、位置信息和 5GMM 原因码 | `AT+C5GREG=3` |
| 11 | `+CMTI: "MT",<index>` | 上报短信的存储位置和存储序列号 | 设置短信内容存贮而不直接显示，通过设置 `+CNMI` 指令的 `<mt>` 参数为 1 |
| 12 | `+CMT: <oa>,<scts>,<tooa>,<lang>,<encod>,<priority>[,<cbn>],<length><CR><LF><data>` | 直接上报短信的内容，短信不存储 | 设置短信内容直接显示而不存贮，通过设置 `+CNMI` 指令的 `<mt>` 参数为 2 |
| 13 | `+CBMI: "BC",<index>` | 上报小区广播的存储位置和存储序列号 | 设置小区广播被存贮，通过设置 `+CNMI` 指令的 `<bm>` 参数为 1 |
| 14 | `+CBM: <oa>,[<alpha>,]<scts>[,<tooa>,<length>] <CR><LF><data>` | 直接上报小区广播的内容，小区广播不存储 | 设置小区广播内容直接显示而不存贮，通过设置 `+CNMI` 指令的 `<bm>` 参数为 2 |
| 15 | `+CDS: <fo>,<mr>,[<ra>],[<tora>],<scts>,<dt>,<st>` | 直接上报短信状态报告的内容，短信状态报告不存储 | 设置短信发送的状态报告显示而不存贮，通过设置 `+CNMI` 指令的 `<ds>` 参数为 1 |
| 16 | `+CDSI: <mem>,<index>` | 上报短信状态报告的存储位置和存储序列号 | 设置短信发送的状态报告被存贮，通过设置 `+CNMI` 指令的 `<ds>` 参数为 2 |
| 17 | `+C5GUSMS <sms_available>,<sms_allowed>` | 上报 5G NAS 短信的支持情况 | `AT+C5GUSMS=2` 设置打开上报 |
| 18 | `+NWURCFOTA: <status>` | FOTA 升级状态 | 下发 FOTA 升级指令 |
| 19 | `$MYURCSYSINFO: <SysMode>,<mnc>` | 上报网络运行制式 | `AT$MYSYSINFOURC=1` 或者 `AT$MYURCSYSINFO=1` |
| 20 | `+NETREJCAUSE: <reject_cause>,<string_cause>` | 在 3GPP 网络注册或者拨号失败时，上报被网络侧拒绝的原因 | `AT+NETREJURC=1` |
| 21 | `$MYURCACT: <channel>,<type>,<IP>` | 内部协议栈拨号已激活或断开 | `AT$MYNETURC=1` 打开主动上报，`AT$MYNETACT` 激活网络连接 |
| 22 | `$MYURCREAD: <SocketID>` | 模组接收到了数据 | `AT$MYNETURC=1`，服务器给模组发送数据 |
| 23 | `$MYURCCLOSE: <SocketID>` | SocketID 对应的链接已断开 | `AT$MYNETURC=1`，断开 SocketID 对应的链接 |
| 24 | `$MYURCCLIENT: <SocketID>,<IP>,<port>` | 提示客户端连接 | `AT$MYNETURC=1`，模组建立 TCP Server |
| 25 | `$MYURCSRVPORT: <PortNum>` | 模组作为客户端连接服务器成功 | `AT$MYNETURC=1`，模组作为客户端连接服务器 |
| 26 | `$MYURCFTP: <Status>` | FTP 连接状态 | `AT$MYNETURC=1`，开启 FTP 服务 |
| 27 | `$MYURCUSBACT: <channel>,<type>,<IP>` | USB 共享激活或者断开 | `AT$MYUSBNETURC=1` 打开主动上报，`AT$MYUSBNETACT` 激活网络连接 |
