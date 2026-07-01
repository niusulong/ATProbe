# 第 10 章 FTP指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 10 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 10.1 AT+FTPSCFG — FTPS 配置参数

配置SSL 加密选项

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+FTPSCFG=<type>,<type_name>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `<CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+FTPSCFG:<sslversion>,<authmode>,` |
| 查询 | `AT+FTPSCFG?<CR>` | `<cacert>,<clientcert>,<clientkey> <CR><LF>OK<CR><LF> <CR><LF>+FTPSCFG:<type>,<type_name>` |
| 测试 | `AT+FTPSCFG=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

如果authmode 为0，则不需要设置cacert、clientcert、clientkey 等内容。 sslversion 可配置为4: TLS1.3 时，将不支持SSL3.0，TLS1.0、TLS1.1。

| <type> | 配置SSL 选项。 |
| --- | --- |
|  | sslversion: SSL 协议版本 |
|  | authmode: 安全认证模式 |
|  | cacert: CA 证书 |
|  | clientcert:客户端证书 |
|  | clientkey:客户端密匙 |
| <type name> _ | <type>和<type name>参数的取值，对应关系如下 _ |
|  | sslversion |
|  | 0：SSL3.0 |
|  | 1：TLS1.0 |
|  | 2：TLS1.1 |
|  | 3：TLS1.2 |
|  | 4：TLS1.3 |
|  | authmode |
|  | 0：No authentication |
| 1：Manage server authentication |
| --- |
| 2：Manage server and client authentication if requested by the remote server |
| cacert string，CA 证书 |
| clientcert string，客户端证书文件名 |
| clientkey string，客户端密匙文件名 |

**示例**

```
AT+FTPSCFG=”sslversion”,0 设置SSL 的版本为ssl3.0。
OK
AT+FTPSCFG=”authmode”,0 设置认证方式为不认证。
OK
AT+FTPSCFG=”cacert”,ca.pem 设置CA 证书名称（需提前添加证书）。
OK
AT+FTPSCFG? 查询SSL 的当前配置。
+FTPSCFG: 0,1,ca.pem,cc.pem,ck.pem
OK
AT+FTPSCFG =? 查询指令配置的范围。
+FTPSCFG: <type>,<type name>
_ OK
```


### 10.2 AT+FTPLOGIN — 登陆FTP 服务器

登录 FTP 服务器。 FTP 功能可以与内部协议栈 TCP/UDP 功能同时使用。  FTP 的读、写操作都必须在登陆之后才能进行。  FTP 默认被动模式。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+FTPLOGIN=<ip>,<port>,<user>,` | `Or <CR><LF>OK<CR><LF> <CR><LF>+FTP: Server Control Link Disconnect<CR><LF> Or <CR><LF>ERROR<CR><LF> <CR><LF>OK<CR><LF>` |
| 执行 | `<pwd>[,<ftpmode>][,<ftptype>]<CR>` | `<CR><LF>+FTPLOGIN: <result>` |

**主动上报**

+FTPLOGIN:<result>

**参数**

|  | <ip> | FTP 服务器地址。 |
| --- | --- | --- |
|  | <port> | FTP 服务器端口号，一般为21。 |
| <user> | <user> | 登录 FTP 服务器所需的用户名，长度不能超过100 个 ASCII 码，用户名中不能有 |
|  |  | 逗号（“,”） |
| <pwd> |  | 登录 FTP 服务器所需的密码，长度不能超过 100 个 ASCII 码，密码中不能有逗号 |
|  |  | “,”） |
|  | <ftpmode> | FTP 的模式选择，0：被动模式(PASV), 1：主动模式(PORT),默认被动模式。 |
| <ftptype> | <ftptype> | 是否使用FTPS， |
|  |  | 0：FTP（默认）； |
|  |  | 1：FTPS，显式连接； |
|  |  | 2：FTPS，隐式连接。 |
| <result> |  | 结果码： |
|  |  | 若域名解析过程出现错误导致登录失败，则返回ERROR |
|  |  | 若FTP 已处于登录状态，则返回Have Logged In |
|  |  | 若上一次与FTP 相关的AT 指令未执行完，则返回AT Busy |
|  |  | 若登录成功，则返回User logged in |
|  |  | 若用户名或密码错导致登录失败，则返回530 Not logged in |
|  |  | 未建立PPP 时登录FTP 服务器时提示GPRS DISCONNECTION |
|  |  | SSL 握手失败时提示 SSL HANDSHAKE FAIL |

**示例**

```
AT+FTPLOGIN=219.134.179.52,21,user1,pwd2009 登录服务器。
OK
+FTPLOGIN: User logged in
AT+FTPLOGIN=183.239.240.40,12150,pp,123 用户名或密码错误，登录失败。
OK
+FTPLOGIN: 530 Not logged in
AT+FTPLOGIN=58.60.184.213,21,neoway,neoway 登录FTP 服务器，指令执行超时，登录失 败。
OK
+FTPLOGIN: FAIL
+FTP:Server Control Link Disconnect FTP 控制链路断开提示。
+FTP: Server Data Link Disconnect FTP 数据链路断开。
AT+FTPLOGIN=240e:980:9900::e1d:f8a9,21,neoway ftp test,neoway
_ _ admin
OK
+FTPLOGIN: ERROR 登录FTP 服务器失败
```


### 10.3 AT+FTPLOGOUT — 从FTP 服务器注销

从FTP 服务器注销。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+FTPLOGOUT: User logged out <CR><LF>OK<CR><LF>` |
| 执行 | `AT+FTPLOGOUT<CR> Or` | `<CR><LF>+CME ERROR: INVALID SOCKET ID<CR><LF> <CR><LF>ERROR<CR><LF>` |

**示例**

```
AT+FTPLOGOUT 退出FTP 服务器。
+FTPLOGOUT: User logged out
OK
AT+FTPLOGOUT FTP 不在线时退出FTP 服务器提示。
+CME ERROR: INVALID SOCKET ID
ERROR
```


### 10.4 AT+FTPGET — 从FTP 服务器下载数据

从FTP 服务器下载数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `Info>[,offset[,lenth]] <CR> Or Or Or AT+FTPGET=<dir&filenam` | `<CR><LF>+FTPGET: Error TimeOut<CR><LF> <CR><LF>+FTPGET: <length>,<data><CR><LF> <CR><LF>+FTPGET: OK.total length is <n><CR><LF> <CR><LF>ERROR<CR><LF> <CR><LF>+FTPGET: Error Not Login<CR><LF>` |
| 执行 | `e>,<type>,<Content or Or` |  |

**主动上报**

+FTPSTATE: <result>

**参数**

|  | <dir&filename> | 需要读取的文件路径和文件名，文件路径是相对于FTP 的根路径而言的。 |
| --- | --- | --- |
| <type> | <type> | 文件传输的模式。 |
|  |  | 1：ASCII |
|  |  | 2：Binary |
| <Content or Info> |  | 指明需要得到的是文件内容还是文件（指定路径）的信息： |
|  |  | 1：获取文件内容 |
|  |  | 2：获取文件长度 |
|  | <offset> | 文件内容的偏移量 |
|  | <lenth> | 本次读取文件内容的长度，取值范围1～8192 字节。 |
|  | <length> | 数据长度 |
|  | <data> | 数据内容 |
|  | <n> | 数据读取成功，读取数据长度为n。 |

**示例**

```
AT+FTPGET=,1,2 获取根目录下的信息。
OK
+FTPGET: 446,drw-rw-rw- 1 user
group 0 Apr 14 15:55 .
drw-rw-rw- 1 user group 0
Apr 14 15:55 ..
-rw-rw-rw- 1 user group 1238528
Jan 14 10:36 1M.doc
-rw-rw-rw- 1 user group 10
Jan 15 15:01 test.txt
+FTPGET: OK.total length is 446
+FTP: Server Data Link Disconnect
AT+FTPGET=test.txt,1,2 获取文件test.txt 的信息。
OK
+FTPGET: 65,-rw-rw-rw- 1 user group
10 Jan 15 15:01 test.txt
+FTPGET: OK.total length is 65
+FTP: Server Data Link Disconnect
AT+FTPGET=123.txt,1,1 文件不存在。
+FTPGET: File Not Found
AT+FTPPUT=test.txt,1,2,10 上传10 字节数据。
>
+FTPPUT: OK,10
AT+FTPGET=test.txt,1,1 读取全部数据。
+FTPGET: 10,0123456789
+FTPGET: OK.total length is 10
+FTP:Server Data Link Disconnect
AT+FTPGET=test.txt,1,1,2 从第二个字节开始，读取后面的全部数据。
+FTPGET: 8,23456789
+FTPGET: OK.total length is 8
+FTP: Server Data Link Disconnect
AT+FTPGET=test.txt,1,1,2,4 从第二个字节开始，读取4 个字节数据。
+FTPGET: 4,2345
+FTPGET: OK.total length is 4
+FTP: Server Data Link Disconnect
```


### 10.5 AT+FTPPUT — 向FTP 服务器上传数据

向FTP 服务器上传数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | ` 透传模式中，可以通过输入+++（不带回车换行），随时结束本次上传流程  AT+FTPPUT=<filename>,<type>,` | `Or <CR><LF>+FTPPUT: Delete File OK<CR><LF> Or <CR><LF>ERROR<CR><LF> 透传模式中，数据传输完成后，通过输入+++（不带回车换行），结束本次上传流程 非透传模式返回值 <CR><LF>+FTPPUT: OK,<size><CR><LF> 透传模式返回值 <CR><LF>CONNECT <CR><LF>+FTPPUT: OK,<size><CR><LF> Or <CR><LF>+FTPPUT:Error Not Login<CR><LF> Or` |
| 执行 | `<mode>[,<size>]<CR>` | `<CR><LF>+FTPPUT:Error Path Not Exist<CR><LF> Or <CR><LF>+FTPPUT:AT Busy<CR><LF> Or <CR><LF>+FTPPUT:SIZE Error（非透传模式） Or <CR><LF>+FTPPUT:OK,<n><CR><LF>` |

**参数**

若上一次与 FTP 相关的 AT 指令未执行完，则返回+FTPPUT:AT Busy  +++（不带回车换行）指令退出透传模式，结束上传流程；  若上传文件较大，采用透传模式，会导致端口一直被占用。影响其他命令的收发。建议采用buffer 模  式进行传输，大文件情况下，采用APPE 模式，进行分包上传。

| <filename> |  | 需要上传文件的文件名，支持路径。 |
| --- | --- | --- |
|  |  | 文件路径是相对于FTP 的根路径而言的。 |
|  |  | 如不带路径则上传到服务器根路径。 |
|  |  | 如路径不存在需要用AT+NWFTPMKDIR 指令创建路径。 |
| <type> |  | 文件传输模式 |
|  |  | 1：ASCII |
|  |  | 2：Binary |
| <mode> |  | 操作模式 |
|  |  | 1：STOR 模式。在服务器上创建文件将数据写入，如果文件已存在，则覆盖原文件 |
|  |  | 2：APPE 模式。在服务器上创建文件将数据写入，如果文件已存在，则将数据附件在 |
|  |  | 文件尾部。 |
|  |  | 3：DELE 模式。删除一个文件 |
|  | <size> | 数据长度，最大长度不得超过8192 最小不能小于1，省略后为透传模式。 |
|  | <n> | 发送文件的长度。 |

**示例**

```
AT+FTPPUT=test.txt,1,1,10 说明：上传文件 test.txt,长度 10，文件传输模式为 ASCII 方式，操作模
> 1234567890 式为 STOR 模式。
+FTPPUT: OK,10
AT+FTPPUT=test.txt,1,2,10 上传文件 test.txt,长度 10，文件传输模式为 ASCII 方式，操作模
> 1234567890 式为 APPE 模式。
+FTPPUT: OK,10
AT+FTPPUT=test.txt,1,3,0 删除 test.txt 文件。
+FTPPUT: Delete File OK
AT+FTPPUT=test.txt,1,1 透传模式，上传文件 test.txt,长度 10，文件传输模式为 ASCII 方式，操作模 式为 STOR 模式。
CONNECT
1234567890
+FTPPUT: OK,10
AT+FTPPUT=test.txt,1,2 透传模式，上传文件 test.txt,长度 10，文件传输模式为 ASCII 方式，操作模 式为APPE 模式。
CONNECT
1234567890
+FTPPUT: OK,10
AT+FTPPUT=test.txt,1,3 透传模式，删除 test.txt 文件。
+FTPPUT: Delete File OK
```


### 10.6 AT+FTPSIZE — 获取FTP 文件大小

查询FTP 服务器上的指定文件的大小。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+FTPSIZE: <size> <CR><LF>OK<CR><LF> Or` |
| 执行 | `AT+FTPSIZE=<filename><CR>` | `<CR><LF>+FTPSIZE: File Not Found<CR><LF> Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <filename> <size> | 需要查询文件大小的文件名，支持路径。 |
| --- | --- |
|  | 文件路径是相对于FTP 的根路径而言的。 |
|  | 如不带路径则表示服务器根路径下的文件。 |
|  | 文件实际大小。 |

**示例**

```
AT+TPSIZE=test 500k.txt 查询到文件大小为512000 字节。
_ +FTPSIZE:512000
OK
AT+FTPSIZE =test.txt 需要查询的文件不存在。
+FTPSIZE:File Not Found
AT+FTPSIZE=test 500.txt,100 指令格式不正确。
_ ERROR
```


### 10.7 AT+FTPSTATUS — 查询FTP 链路状态

查询FTP 链路状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
| 执行 | `AT+FTPSTATUS<CR>` | `<CR><LF>+FTPSTATUS: <status>,<ip>,<port><CR><LF>` |

**参数**

| <status> |  | 0：表示未连接FTP |
| --- | --- | --- |
|  |  | 1：表示连接了FTP |
|  | <ip> | FTP 服务器IP |
|  | <port> | FTP 服务器端口 |

**示例**

```
AT+FTPSTATUS 查询FTP 链路状态
+FTPSTATUS: 1,119.139.221.66,21 建立了FTP 的连接，显示服务器的IP 和端口号
AT+FTPSTATUS 查询FTP 链路状态
+FTPSTATUS: 0,0.0.0.0,21 未建立FTP 的连接
```


### 10.8 AT+FILEFTPGET — 文件系统内下载文件

下载文件到文件系统，支持偏移量下载。 下载时，需确保文件系统内有足够空间，可使用AT+FSLS 命令，查询剩余空间大小。 下载前，先通过+FTPLOGIN 指令建立FTP 链接。 下载后，可通过+FTPLOGOUT 指令断开FTP 链接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<percentage> <CR><LF>+FILEFTPSTAT:1,<total> Or <CR><LF>ERROR<CR><LF>` |
| 查询 | `AT+FILEFTPGET?<CR>` | `<CR><LF>OK<CR><LF>` |
| 测试 | `AT+FILEFTPGET=?<CR> AT+FILEFTPGET=<dir&filename>[,local_na` | `<CR><LF>OK<CR><LF> <CR><LF>OK<CR><LF>` |
| 执行 | `me,<offset>[,<length>]]<CR>` | `<CR><LF>+FILEFTPGETF:` |

**参数**

| <dir&filename> |  | 需要读取的文件路径和文件名。 |
| --- | --- | --- |
|  |  | 文件路径是相对于 FTP 的根路径而言的 |
| <local name> _ |  | 本地缓存文件的名称，支持路径，文件或路径不存在则创建。 |
|  |  | 文件路径加文件名不要超过120 字节。 |
|  |  | 文件路径是相对于用户目录而言的。 |
|  |  | 参数缺省则存储在用户盘根目录。 |
| <offset> |  | 文件内容的偏移量 |
|  |  | 0-2097152 |
|  | <length> | 本次读取文件内容的长度，字节，取值范围1～20480 |
|  |  | 省略<offset>和<lenth>参数，为全文件下载 |
|  | <percentage> | 进度百分比 |
|  | <total> | 文件总大小 |

**示例**

```
AT+FILEFTPGET="FTP TEST 64KB.txt" 下载 FTP TEST 64KB.txt 文件，并以 _ _ FTP TEST 64KB.txt 存储 _ _
_ _ OK
+FILEFTPGETF:10%
+FILEFTPGETF:20%
+FILEFTPGETF:30%
+FILEFTPGETF:40%
+FILEFTPGETF:50%
+FILEFTPGETF:60%
+FILEFTPGETF:70%
+FILEFTPGETF:80%
+FILEFTPGETF:90%
+FILEFTPGETF:100%
+FILEFTPSTAT: 1,65536
AT+FILEFTPGET=text.txt 下载text.txt 文件，命令执行成功，开始下载 下载失败
OK
+FILEFTPSTAT: 0,0
```


### 10.9 AT+FILEFTPPUT — 向FTP 服务器上传文件

向FTP 服务器上传本地文件。 OK 与ERRER 返回时间300ms。上传结果异步上报，根据文件大小和网络状态返回时间不定。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+FILEFTPPUT=<filename>[,<o` | `OK <CR><LF>+FILEFTPSTAT:<result>,<len><CR><` |
| 执行 | `ffset> [,<length>][,<serverpath>]]<CR> 上传文件需确认本地文件是否存在。  可用AT+FSLIST？查看本地文件列表。 ` | `LF> Or ERROR<CR><CF>` |

**参数**

|  | <filename> | 需要上传文件的本地文件名，支持路径。最大长度120 字节 |
| --- | --- | --- |
| <offset> | <offset> | 文件偏移量 |
|  |  | 0-2097152 |
| <length> |  | 发送文件长度 |
|  |  | 1-8192 |
| <serverpath> |  | 指定文件在服务器上的存储路径。最大长度120 字节。 |
|  |  | 文件路径是相对于FTP 的根路径而言的。 |
|  |  | 参数缺省则上传到服务器根路径。 |
|  |  | 如路径不存在需要用AT+NWFTPMKDIR 指令创建路径。 |
| <result> |  | 上传结果 |
|  |  | 0：失败 |
|  |  | 1：成功 |
|  | <len> | 已上传的文件长度 |

**示例**

```
AT+FILEFTPPUT="test.txt" 上传本地的test.txt 文件 上传成功，共计51000 字节
OK
+FILEFTPSTAT: 1,51000
AT+FILEFTPPUT="test.bin" 上传test.bin 文件，上传失败，已上传1024 字节
OK
+FILEFTPSTAT: 0,1024
AT+FILEFTPPUT="1111" 上传失败，本地文件不存在或者参数错误，FTP 未登录等
ERROR
AT+FILEFTPPUT=test.txt,100,100 上传偏移量为100，大小为100 的test.txt 文件
OK
+FILEFTPSTAT: 1,100
```


### 10.10 AT+NWFTPRENAME — 重命名FTP 服务器文件或文

件夹 该命令用于重命名FTP 服务器文件或文件夹。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+NWFTPRENAME=<old_name>,<ne` | `<CR><LF>OK<CR><LF> <CR><LF>+NWFTPRENAME: <err>,<protocol_error><CR><LF>` |
| 执行 | `w_name><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWFTPRENAME: <err>,<protocol_error><CR><LF>` |

**参数**

| <old name> _ | 字符串类型。FTP(S)服务器旧文件名或旧文件夹名称，支持路径。最 |
| --- | --- |
|  | 大长度为255 字节。 |
| <new name> _ | 字符串类型。FTP(S)服务器新文件名或新文件夹名称，支持路径。最 |
|  | 大长度为255 字节。 |
| <err> | 0 表示操作成功，其他值表示错误。详细信息可参考附录 D 中的结果 |
|  | 码。 |
| <protocol error> _ | 整型。表示 FTP(S)服务器原始错误码。该错误码在 FTP(S)协议中定 |
|  | 义，仅供参考。详细信息可参考附录 E 中的协议错误码。若为 0，则 |
| 无效。 |
| --- |

**示例**

```
AT+NWFTPRENAME="old name.txt","new name.txt" 修改FTP 上的文件名
_ _ OK
+NWFTPRENAME: 0,200
AT+NWFTPRENAME="test/old test.txt","test/new test.txt" 修改FTP 上的路径下文件名
_ _ OK
+NWFTPRENAME: 0,200
AT+NWFTPRENAME="test old dir","test new dir" 修改FTP 上的文件夹名
_ _ _ _ OK
+NWFTPRENAME: 0,200
```


### 10.11 AT+NWFTPMKDIR — 创建FTP 服务器文件夹

该命令用于创建FTP 服务器文件夹。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF> <CR><LF>+NWFTPMKDIR: <err>,<protocol_error><CR><LF>` |
| 执行 | `AT+NWFTPMKDIR=<folder_name><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWFTPMKDIR: <err>,<protocol_error><CR><LF>` |

**参数**

| <folder name> _ | 字符串类型。需要创建的 FTP 服务器文件夹名称。最大长度为 |
| --- | --- |
|  | 255 字节。 |
| <err> | 0 表示操作成功，其他值表示错误。详细信息可参考附录D 中的 |
|  | 结果码。 |
| <protocol error> _ | 整型。表示 FTP(S)服务器原始错误码。该错误码在FTP(S)协议 |
|  | 中定义，仅供参考。细信息可参考附录E 中的协议错误码。若为 |
|  | 0，则无效。 |

**示例**

```
AT+NWFTPMKDIR="test dir" 在ftp 服务器上新增文件夹
_ OK
+NWFTPMKDIR: 0,200
```


### 10.12 AT+NWFTPRMDIR — 删除FTP 服务器文件夹

该命令用于删除FTP 服务器文件夹。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF> <CR><LF>+NWFTPRMDIR: <err>,<protocol_error><CR><LF>` |
| 执行 | `AT+NWFTPRMDIR=<folder_name><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWFTPRMDIR: <err>,<protocol_error><CR><LF>` |

**参数**

| <folder name> _ | 字符串类型。需要删除的FTP 服务器文件夹名称。最大长度为255 |
| --- | --- |
|  | 字节。 |
| <err> | 0 表示操作成功，其他值表示错误。详细信息可参考附录D 中的结 |
|  | 果码。 |
| <protocol error> _ | 整型。表示FTP(S)服务器原始错误码。该错误码在FTP(S)协议中 |
|  | 定义，仅供参考。详细信息可参考附录E 中的协议错误码。若为0 |
|  | 则无效。 |

**示例**

```
AT+NWFTPRMDIR="test dir" 删除FTP 服务器上的文件夹
_ OK
+NWFTPRMDIR: 0,200
```


### 10.13 AT+NWFTPDEL — 删除FTP 服务器文件

该命令用于删除FTP 服务器文件。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF> <CR><LF>+NWFTPDEL: <err>,<protocol_error><CR><LF>` |
| 执行 | `AT+NWFTPDEL=<file_name><CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+NWFTPDEL: <err>,<protocol_error><CR><LF>` |

**参数**

|  | <file name> _ | 字符串类型。需要删除的FTP 服务器文件名称。最大长度为255 字节 | 。 |
| --- | --- | --- | --- |
| <err> |  | 0 表示操作成功，其他值表示错误。详细信息可参考附录 D 中的结果 |  |
|  |  | 码。 |  |
| <protocol error> _ |  | 整型。表示FTP(S)服务器原始错误码。该错误码在FTP(S)协议中定义 | ， |
|  |  | 仅供参考。详细信息可参考附录E 中的协议错误码。若为0，则无效。 |  |

**示例**

```
AT+NWFTPDEL="test.txt" 删除FTP 服务器上的文件
OK
+NWFTPDEL: 0,200
```

