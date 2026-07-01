# 附录 E ATV 设置及回码

> 来源：《N58 AT 命令手册 v2.0》附录 E（p.358）
> 参考 3GPP TS 27.007 Table B.1: Result codes。

| ATV1 | ATV0 | 描述 |
| --- | --- | --- |
| OK | 0 | 执行命令的正确确认 |
| CONNECT | 1 | 连接已经建立，DCE 从命令状态切换为数据状态 |
| RING | 2 | DCE 已经检测到一个来自网络的呼叫 |
| NO CARRIER | 3 | 连接中断或尝试建立连接失败 |
| ERROR | 4 | 命令不能被识别，超出命令行的最大长度，参数值无效或命令进程中的其他问题 |
| NO DIALTONE | 6 | 无法检测到拨号音 |
| BUSY | 7 | 检测到忙音信号（占线） |
| NO ANSWER | 8 | 若 "@" 拨号修改量被使用，则紧跟 5 秒静默时间的远程振铃没有在定时器（S7）超时前检测到，即无应答 |
| PROCEEDING | 9 | 一条 AT 命令正在被处理 |
| CONNECT \<text\> | manufacturer specific | 与 CONNECT 相同，但包含制造商特殊需求定义的文本，该文本可以是指定的 DTE 速率、行速度、错误控制、数据压缩或其他状态 |
