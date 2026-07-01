# 附录 G 结果码

> 来源：《N58 AT 命令手册 v2.0》附录 G（p.361-363）
> 扩展指令（FTP/HTTP/SSL 等）返回的结果码 `<err>` 定义。

| `<err>` | 英文含义 | 中文含义 |
| --- | --- | --- |
| 0 | Operation successful | 操作成功 |
| 601 | Unknown error | 未知错误 |
| 602 | FTP(S) server blocked | FTP(S) 服务器不可用 |
| 603 | FTP(S) server busy | FTP(S) 服务器繁忙 |
| 604 | DNS parse failed | DNS 解析错误 |
| 605 | Network error | 网络错误 |
| 606 | Control connection closed | 控制连接关闭 |
| 607 | Data connection closed | 数据连接关闭 |
| 608 | Socket closed by peer | 对端关闭 Socket |
| 609 | Timeout error | 超时错误 |
| 610 | Invalid parameter | 无效参数 |
| 611 | Failed to open file | 文件打开失败 |
| 612 | File position invalid | 文件位置无效 |
| 613 | File error | 文件错误 |
| 614 | Service not available, closing control connection | 服务不可用，关闭控制连接 |
| 615 | Open data connection failed | 数据连接打开失败 |
| 616 | Connection closed; transfer aborted | 连接关闭，传输中止 |
| 617 | Requested file action not taken | 文件操作请求失败 |
| 618 | Requested action aborted: local error in processing | 请求中止：本地错误处理中 |
| 619 | Requested action not taken: insufficient system storage | 请求失败：系统空间不足 |
| 620 | Syntax error, command unrecognized | 语句错误，无法命令识别 |
| 621 | Syntax error in parameters or arguments | 语句错误，参数出错 |
| 622 | Command not implemented | 未执行命令 |
| 623 | Bad sequence of commands | 命令顺序有误 |
| 624 | Command parameter not implemented | 未输入命令参数 |
| 625 | Not logged in | 未登录 |
| 626 | Need account for storing files | 需要能存储文件的账号 |
| 627 | Requested action not taken | 请求失败 |
| 628 | Requested action aborted: page type unknown | 请求中止：未知网页类型 |
| 629 | Requested file action aborted | 文件操作请求失败 |
| 631 | SSL authentication failed | SSL 鉴权失败 |
