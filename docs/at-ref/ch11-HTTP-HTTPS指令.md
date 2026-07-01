# 第 11 章 HTTP/HTTPS指令

> 来源：《N58 AT 命令手册 v2.0》（2024-12-03）第 11 章
> PDF 提取并结构化重建；命令格式表按坐标分列、参数表按边框重建。

---

### 11.1 AT+HTTPPARA — HTTP 参数设置

设置HTTP 命令参数。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+HTTPPARA=<para>,<para_value><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <para> | http 参数，支持以下参数设置。 |
| --- | --- |
|  | url：目标路径 |
|  | port：目标端口号（未设置缺省值） |
|  | keepalive:设置长连接，HTTP 协议长连接，para value 默认值为0，para value 为 _ _ |
|  | 1 时为长连接。 |
|  | recvmode: 接收模式，para value=0 默认接收模式，一个 HTTP 响应只包含一个 _ |
|  | +HTTPRECV：头表示；para value=1，数据以+HTTPRECV: <length>,<data>形式 _ |
|  | 呈现。 |
|  | 对应<para 的值，其中url 参数值最大为2048 个字节，url 支持域名解析。 |

**示例**

```
AT+HTTPPARA=url,”www.neoway.com.cn/en/index.aspx” 设置URL 为neoway 主页，URL 支持域名解析.
OK
AT+HTTPPARA=url,”121.15.200.97/Service1.asmx/GetNote” 设置URL.
OK
AT+HTTPPARA=url, AT 指令格式错误，参数不完整.
ERROR
AT+HTTPPARA=port,80 设置目标端口号为80.
OK
AT+HTTPPARA=port,8080 设置目标端口号为8080.
OK
```


### 11.2 AT+HTTPSETUP — HTTP 链路建立

建立HTTP 链接。 正确设置目标地址和端口号才能链接成功。  HTTP 链路建立之前要确保PPP 拨号（AT+XIIC=1）成功。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+HTTPSETUP<CR>` | `Or <CR><LF>+HTTPSETUP: FAIL<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 |

**示例**

```
AT+HTTPSETUP 建立HTTP 链接成功.
OK
AT+HTTPSETUP 建立HTTP 链接失败.
+HTTPSETUP: FAIL
```


### 11.3 AT+HTTPACTION — HTTP 发送请求

执行HTTP 请求。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `set>,<size>]<CR> AT+HTTPACTION=<mode>[,<le ` | `Or <CR><LF>+HTTPACTION:SOCKET ID OPEN FAILED<CR><LF> Or <CR><LF>+HTTPSEND: ERROR<CR><LF> <CR><LF>OK<CR><LF>` |
| 执行 | `ngth>[,<type>]]<CR> AT+HTTPACTION=<mode>[,<off ` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

用户自定义报文时需遵循HTTP 协议；  HTTP 请求方式设置为自定义报文模式时，输入报文结尾需要加一个回车换行。 

| <mode> |  | HTTP 请求方式，可取值为0,1,2,99. |
| --- | --- | --- |
|  |  | 0：GET |
|  |  | 1：HEAD |
|  |  | 2：POST |
|  |  | 99：OPEN MODE，用户自己定义报文模式 _ |
| <length> |  | POST 内容长度或自定义报文长度，在<mode>为POST 和OPEN MODE 时必须 _ |
|  |  | 设置，最大长度为2048 |
| <type> |  | POST 请求的数据类型 |
|  |  | 0：x-www-form-urlencoded |
|  |  | 1：text |
|  |  | 2：json |
|  |  | 3：xml |
|  |  | 4：html |
|  | <offset> | 偏移量，通过GET 方式下载文件时，可以指定下载起始位置 |
|  | <size> | 下载长度，通过GET 方式下载文件时，可以指定下载长度 |

**示例**

```
AT+HTTPPARA=url,”www.neoway.com.cn/en/index.aspx” 设置目标路径，默认端口为80.
OK
AT+HTTPSETUP 建立HTTP 链接.
OK
AT+HTTPACTION=0 GET 方式请求.
OK
+HTTPRECV: 收到HTTP 服务器的响应.
HTTP/1.1 200 OK
Cache-Control: private
Content-Type: text/html; charset=utf-8
Server: Microsoft-IIS/7.5
Set-Cookie: ASP.NET SessionId=rh3fjg554ufzb145aevgzz45; _ path=/; HttpOnly X-AspNet-Version: 2.0.50727 X-Powered-By: ASP.NET X-UA-Compatible: IE=EmulateIE7 Date: Thu, 28 Nov 2013 03: 06: 57 GMT Connection: close Content-Length: 13842 /*neoway 主页内容，html 格式，13842 个字节*/ …….. /* neoway 主页内容*/ +HTTPCLOSED: HTTP Link Closed
主动上报，服务器响应完毕，断开链接.
AT+HTTPPARA=url,”www.neoway.com.cn/en/index.aspx” OK AT+HTTPSETUP OK AT+HTTPACTION=1 OK +HTTPRECV: HTTP/1.1 200 OK Cache-Control: private Content-Length: 13842 Content-Type: text/html; charset=utf-8 Server: Microsoft-IIS/7.5 Set-Cookie: ASP.NET SessionId=znt4fqabqsuclz55pvfufn55; _ path=/; HttpOnly X-AspNet-Version: 2.0.50727 X-Powered-By: ASP.NET X-UA-Compatible: IE=EmulateIE7 Date: Thu, 28 Nov 2013 03: 32: 35 GMT Connection: close +HTTPCLOSED: HTTP Link Closed 设置目标路径，默认端口为80.
建立HTTP 链接.
HEAD 方式请求.
HTTP 服务器响应.
AT+HTTPPARA=url,”121.15.200.97/Service1.asmx/GetNote” 设置URL.
OK
AT+HTTPPARA=port,8080 设置目标端口号为8080.
OK
AT+HTTPSETUP 建立HTTP 链接.
OK
AT+HTTPACTION=2,25 POST 方式请求，POST 发送25 个字节；“>”出
>MAC=NEOWAY&DATA=0123456 现后，输入需要上传的内容.
OK
+HTTPRECV: 收到服务器响应.
HTTP/1.1 200 OK
Cache-Control: private, max-age=0
Content-Type: text/xml; charset=utf-8
Server: Microsoft-IIS/7.5
X-AspNet-Version: 4.0.30319
X-Powered-By: ASP.NET
Date: Thu, 28 Nov 2013 03: 41: 52 GMT
Connection: close
Content-Length: 98
<?xml version="1.0" encoding="utf-8"?>
<string xmlns="http: //wsliu.cn/">NEOWAY+0123456 服务器回复包含上传内容NEOWAY 和0123456
</string> 的xml 文件.
+HTTPCLOSED: HTTP Link Closed 服务器响应完毕主动断开.
设置URL.
默认端口80 进行HTTP 链接.
用户自定义报文方式请求发送76 个字节的报文.
收到服务器响应.
服务器响应完毕主动关闭链路.
AT+HTTPACTION=0 PPP 未打开或SOC 链路出错.
+HTTPACTION:SOCKET ID OPEN FAILED
AT+HTTPACTION=0 数据发送失败.
+HTTPSEND: ERROR
AT+HTTPACTION=2,adasd 其他错误.
ERROR
```


### 11.4 AT+HTTPCLOSE — HTTP 链路主动关闭

关闭HTTP 链接。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `Or <CR><LF>ERROR<CR><LF>` |
| 执行 | `AT+HTTPCLOSE<CR>` | `<CR><LF>OK<CR><LF>` |

**主动上报**

+HTTPCLOSE: <result>

**参数**

执行+HTTPCLOSE 命令，在关闭HTTP 链路的同时，会清除+HTTPPARA 命令设置的参数；  当HTTP 链路处于未连接状态执行关闭仅返回OK，无主动上报关闭回码。 

| <result> | HTTP Link Closed 链路已关闭。 |
| --- | --- |

**示例**

```
AT+HTTPCLOSE 关闭HTTP 链路.
OK
+HTTPCLOSE: HTTP Link Closed
AT+HTTPCLOSE 执行命令返回OK.
OK
```


### 11.5 +HTTPRECV — HTTP 数据接收

主动上报HTTP 链路接收的数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `<CR><LF>+HTTPRECV: <datas>` |  |

**主动上报**

<CR><LF>+HTTPRECV: <length>,<datas>

**参数**

| <length> | 数据长度。 |
| --- | --- |
| <datas> | HTTP 链路接收到的数据。 |

**示例**

```
+HTTPRECV: HTTP/1.1 200 OK 主动上报HTTP 链路接收到数据。
Cache-Control: private
Content-Length: 13842
Content-Type: text/html; charset=utf-8
Server: Microsoft-IIS/7.5
Set-Cookie: ASP.NET SessionId=pvlaai3fizxg44eyvyqsyenk; path=/;
_ HttpOnly
X-AspNet-Version: 2.0.50727
X-Powered-By: ASP.NET
X-UA-Compatible: IE=EmulateIE7
Date: Thu, 28 Nov 2013 05:40:24 GMT
Connection: close
+HTTPCLOSED: HTTP Link Closed
+HTTPRECV: 803,HTTP/1.1 206 Partial Content RECVMODE 设为1 时，接收数据的格 式。
Cache-Control: no-cache
Connection: Keep-Alive
Content-Length: 10
Content-Range: bytes 0-9/14615
Content-Type: text/html
Date: Tue, 10 Jul 2018 00:55:30 GMT
Etag: "5b3c3650-3917"
Last-Modified: Wed, 04 Jul 2018 02:52:00 GMT
P3p: CP=" OTI DSP COR IVA OUR IND COM "
Pragma: no-cache
Server: BWS/1.1
Set-Cookie: BAIDUID=F18E6894A34321D8CF9AAF28C14FACC9:FG=1;
expires=Thu, 31-Dec-37 23:55:55 GMT; max-age=2147483647; path=/;
domain=.baidu.com
Set-Cookie: BIDUPSID=F18E6894A34321D8CF9AAF28C14FACC9;
expires=Thu, 31-Dec-37 23:55:55 GMT; max-age=2147483647; path=/;
domain=.baidu.com
Set-Cookie: PSTM=1531184130; expires=Thu, 31-Dec-37 23:55:55 GMT;
max-age=2147483647; path=/; domain=.baidu.com
Vary: Accept-Encoding
X-Ua-Compatible: IE=Edge,chrome=1
<!DOCTYPE
```


### 11.6 AT+HTTPGET — HTTP 下载文件

HTTP 下载文件。 该命令为异步命令，执行完后返回OK，下载、解压、校验过程均为后台进行；  当省略<check_type>,<check_value>两个参数时，下载完成后，不进行任何校验动作；  当设置<dir_mode>时，<check_type>,<check_value>可留空处理。需要先用+NWYSPIFLASH 初始  化外部flash。 下载、校验、解压结果上报，通过+HTTPGETSTAT 命令上报，详情见该命令定义。  该指令为华创北斗设计，为了节省模组空间，使用该指令会删除上一次使用该指令下载到flash 的文  件。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+HTTPGET=<type>[,<check_ty` | `<CR><LF>OK<CR><LF>` |
| 执行 | `pe>,<check_value>[,<dir_mode>]] <CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| <type> |  | 解压方式 |
| --- | --- | --- |
|  |  | 0：不解压（默认） |
|  |  | 1：zip（暂不支持） |
|  |  | 2~99 预留 |
| <check type> _ |  | 压缩包完整性校验类型 |
|  |  | 0： MD5 （默认） |
|  |  | 1~99 预留 |
|  | <check value> _ | 校验码，配合<check type>中选定的校验类型一起使用。 _ |
| <dir mode> _ | <dir mode> _ | 保存位置选择 |
|  |  | 0：保存到本地存储(默认) |
|  |  | 1：保存到外挂flash 中 |

**示例**

```
AT+HTTPPARA=url,120.86.64.161/0.2M.txt 下载文件。
OK
AT+HTTPPARA=port,10141
OK
AT+HTTPSETUP
OK
AT+HTTPGET=0
OK
+HTTPGETRPT: 10
+HTTPCLOSED: HTTP Link Closed
AT+HTTPGET=0,0,eaf84487e190bc79af55c972bbc63e3f
OK 下载成功，默认下载到内部存储
+HTTPGETRPT: 30,303
AT+HTTPGET=0,0,eaf84487e190bc79af55c972bbc63e3f 校验失败
OK
+APHTTPGETRPT: 31
AT+HTTPGET=0,,,1 下载到外部flash，下载成功，不校验
OK
+HTTPGETRPT: 10
```


### 11.7 +HTTPGETRPT — 主动上报下载结果

主动上报HTTP GET 结果。 该命令指示AT+HTTPGET 命令的运行结果，根据命令的不同阶段，进行结果指示主动上报。  下载、校验、解压，不同的阶段，上报不同的结果码。 

**主动上报**

<CR><LF>+ HTTPGETRPT: <state_type>[,<err_code>]<CR><LF>

**参数**

| <state type> _ | 状态类型 |
| --- | --- |
|  | 10：下载成功 |
|  | 11：下载失败 |
|  | 20：解压成功 |
|  | 21：解压失败 |
|  | 30：校验成功 |
|  | 31：校验失败 |
| <err code> _ | HTTP GET 过程中遇到的错误响应。 |
|  | 413 请求实例太大 |

**示例**

```
AT+HTTPPARA=url, mybank.icbc.com.cn/icbc/perbank/index.jsp 下载文件
AT+HTTPGET=0
OK
+HTTPGETRPT: 10
AT+HTTPGET=1
OK
+HTTPGETRPT: 20
AT+HTTPGET=1,0,eaf84487e190bc79af55c972bbc63e3f
OK
+HTTPGETRPT: 30
AT+APHTTPGET=1,0,eaf84487e190bc79af55c972bbc63e3f
OK
+APHTTPGETRPT: 31
```


### 11.8 AT+HTTPGETSTAT? — 查询下载结果

查询HTTP GET 过程与结果。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+HTTPGETSTAT:` |
| 查询 | `AT+HTTPGETSTAT?<CR>` | `<state_type>[,<err_code>]<CR><LF>` |

**参数**

| <state type> _ | 状态类型 |
| --- | --- |
|  | 0：未知结果 |
|  | 10：下载成功 |
|  | 11：下载失败 |
|  | 20：解压成功 |
|  | 21：解压失败 |
|  | 30：校验成功 |
|  | 31：校验失败 |
| <err code> _ | HTTP GET 过程中遇到的错误响应。 |
|  | 413 请求实例太大 |

**示例**

```
AT+HTTPGET=0
OK
AT+HTTPGETSTAT?
+HTTPGETSTAT: 10
OK
AT+APHTTPGET=1
+HTTPGETSTAT: 30
OK
```


### 11.9 +HTTPCLOSED — HTTP 链路被动关闭

关闭HTTP 链接。

**主动上报**

<CR><LF>+HTTPCLOSED: HTTP Link Closed<CR><LF>

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 由于执行完HTTP 请求后，任务被占用以处理数据接受，AT+HTTPCLOSE 执行之后不能立即响 应，而是等待数据接受处理完成之后才会响应 |

**示例**

```
+HTTPCLOSED: HTTP Link Closed 主动上报HTTP 链路断开。
```


### 11.10 AT+HTTPSCFG — HTTPS 配置参数

配置SSL 加密选项

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+HTTPSCFG=<type>,<type_name>` | `<CR><LF>OK<CR><LF>` |
| 设置 | `<CR>` | `Or <CR><LF>ERROR<CR><LF> <CR><LF>+HTTPSCFG:<sslversion>,<authmode` |
| 查询 | `AT+HTTPSCFG?<CR>` | `>,<cacert>,<clientcert>,<clientkey>,<sni> <CR><LF>OK<CR><LF> <CR><LF>+HTTPSCFG: <type>,<type_name>` |
| 测试 | `AT+HTTPSCFG=?<CR>` | `<CR><LF>OK<CR><LF>` |

**参数**

如果authmode 为0，则不需要设置cacert、clientcert、clientkey 等内容。 sslversion 可配置为4: TLS1.3 时，将不支持SSL3.0，TLS1.0、TLS1.1。

| <type> | 配置SSL 选项。 |
| --- | --- |
|  | sslversion: SSL 协议版本 |
|  | authmode: 安全认证模式 |
|  | cacert: CA 证书 |
|  | clientcert:客户端证书 |
|  | clientkey:客户端密匙 |
|  | sni:TLS 的扩展 |
| <type name> _ | <type>和<type name>参数的取值，对应关系如下 _ |
|  | sslversion |
|  | 0：SSL3.0 |
|  | 1：TLS1.0 |
|  | 2：TLS1.1 |
|  | 3：TLS1.2 |
|  | 4：TLS1.3 |
|  | authmode |
|  | 0：No authentication |
|  | 1：Manage server authentication |
|  | 2：Manage server and client authentication if requested by the remote server |
|  | cacert string，CA 证书 |
|  | clientcert string，客户端证书文件名 |
|  | clientkey string，客户端密匙文件名 |
|  | sni |
|  | 0：关闭 |
|  | 1：开启 |

**示例**

```
AT+HTTPSCFG=”sslversion”,0 设置SSL 的版本为ssl3.0。
OK
AT+HTTPSCFG =”authmode”,0 设置认证方式为不认证。
OK
AT+HTTPSCFG=”cacert”,ca.pem 设置CA 证书名称（需提前添加证书）。
OK
AT+HTTPSCFG? 查询SSL 的当前配置。
+HTTPSCFG:0,1,ca.pem,cc.pem,ck.pem,sni
OK
AT+HTTPSCFG=? 查询指令配置的范围。
+HTTPSCFG: <type>,<type name>
_ OK
```


### 11.11 AT+HTTPSPARA — HTTPS 参数设置

设置HTTPS 命令参数。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 设置 | `AT+HTTPSPARA=<para>,<para_value><CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

新的HTTPS 请求需要设置新的HTTPS PARAMETER。  若执行+HTTPSCLOSE，链路关闭的同时，HTTPS 参数不会被清空。 

| <para> | https 参数，支持两个参数设置。 |
| --- | --- |
|  | url：目标路径 |
|  | port：目标端口号 |
|  | keepalive: 设置长连接 |
|  | recvmode: 接收模式，para value=0 默认接收模式，一个 HTTP 响应只包含一个 _ |
|  | +HTTPRECV：头表示；para value=1，数据以+HTTPRECV: <length>,<data>形式 _ |
|  | 呈现。 |
|  | 对应<para>的值，其中URL 参数值最大为512 个字节，URL 支持域名解析。 |

**示例**

```
AT+HTTPSPARA=url,mybank.icbc.com.cn/icbc/perbank/index.jsp 设置目标路径为工商银行网银登陆，
OK url 支持域名解析。
AT+HTTPSPARA=url,132.188.73.13/prodreg/beginRegistration.action 设置目标路径为132.188.73.13。
OK
AT+HTTPSPARA=port,443 设置目标端口号为443。
OK
```


### 11.12 AT+HTTPSSETUP — HTTPS 链路建立

建立HTTPS 链接。 正确设置目标地址和端口号才能连接成功；  HTTPS 链路建立之前要确保PPP 拨号（AT+XIIC=1）成功。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+HTTPSSETUP<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无。 |

**示例**

```
AT+HTTPSSETUP 建立HTTPS 链接
OK 成功
AT+HTTPSSETUP
+HTTPSSETUP: OK
AT+HTTPSSETUP 建立HTTPS 链接
ERROR 成功
```


### 11.13 AT+HTTPSACTION — HTTPS 发送请求

执行HTTPS 请求。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+HTTPSACTION=<mode>[,<length>[,<type>]<C` | `<CR><LF>OK<CR><LF>` |
| 执行  | `R> AT+HTTPSACTION=<mode>[,<offset>,<size>]<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

用户自定义报文时需遵循HTTP 协议；  用户在自定义报文的时候注意使用的工具里头是否会自带回车和换行这些字符。 

| <mode> |  | HTTP 请求方式，可取值为0,1,2,99。 |
| --- | --- | --- |
|  |  | 0：GET |
|  |  | 1：HEAD |
|  |  | 2：POST |
|  |  | 99：OPEN MODE，用户自己定义报文模式 _ |
| <length> |  | POST 内容长度或自定义报文长度，在<mode>为POST 和OPEN MODE 时必须 _ |
|  |  | 设置，最大长度为2048。 |
| <type> |  | POST 请求的数据类型。 |
|  |  | 0：x-www-form-urlencoded |
|  |  | 1：text |
|  |  | 2：json |
|  |  | 3：xml |
|  |  | 4：html |
|  | <offset> | 偏移量，通过GET 方式下载文件时，可以指定下载起始位置。 |
|  | <size> | 下载长度，通过GET 方式下载文件时，可以指定下载长度。 |

**示例**

```
AT+HTTPSPARA=url,support.cdmatech.com/login/ 设置目标路径。
OK
AT+HTTPSPARA=port,443 设置目标端口为443。
OK 建立HTTPS 链接。 GET 方式请求。 收到HTTPS 服务器的响应。 主动上报，服务器响应完毕，断开链接。
AT+HTTPSSETUP
OK
AT+HTTPSACTION=0
OK
+HTTPSRECV:
HTTP/1.1 200 OK
Server: QUALCOMM
X-Powered-By: Servlet/2.5 JSP/2.1
Content-Type: text/html; charset=ISO-8859-1
Date: Sat, 15 Feb 2014 05:58:54 GMT
Content-Length: 7630
Connection: close
Set-Cookie:
JSESSIONID=8V1dS1CpzlPcyNl2LzJZLQgDxWclpMJzP3FHZhVhpGb83G
VM02sn!1955538012; path=/; HttpOnly
/*主页内容，html 格式*/
……..
/*主页内容*/
+HTTPSCLOSED: HTTPS Link Closed
AT+HTTPSPARA=url,support.cdmatech.com/login/ 设置目标路径。 设置目标端口为443。 建立HTTPS 链接。 HEAD 方式请求。 HTTPS 服务器响应。
OK
AT+HTTPSPARA=port,443
OK
AT+HTTPSSETUP
OK
AT+HTTPSACTION=1
OK
+HTTPSRECV:
HTTP/1.1 200 OK
Server: QUALCOMM
X-Powered-By: Servlet/2.5 JSP/2.1
Content-Type: text/html; charset=ISO-8859-1
Date: Sat, 15 Feb 2014 06:05:39 GMT
Content-Length: 0
Connection: close
Set-Cookie:
JSESSIONID=qyNVS1DSmnjS9cvh72yW1xz1jtjBBRj0yv0zTmMy2LVyBG
7HK02b!1955538012; path=/; HttpOnly
+HTTPSCLOSED: HTTPS Link Closed
AT+HTTPSPARA=url,mybank.icbc.com.cn/icbc/perbank/index.js OPEN MODE，用户自己定义报文模式，注意长 _ 度包括用户自定义的头部内容。
p
OK
AT+HTTPSPARA=port,443
OK
AT+HTTPSSETUP
OK
AT+HTTPSACTION=99,500
>POST /icbc/perbank/index.jsp HTTP/1.1<CRLF> /*自定义头信息
*/
Connection: close<CRLF> /*自定义头信息*/
Host: mybank.icbc.com.cn<CRLF> /*自定义头信息*/
Content-Length: 10<CRLF> /*自定义头信息*/
Content-Type: application/x-www-form-urlencoded<CRLF> /*自
定义头信息*/
<CRLF><CRLF>
/*要发送的内容*/
……
+HTTPSRECV:
/*主页内容，html 格式*/
……..
/*主页内容*/
+HTTPSCLOSED: HTTPS Link Closed
```


### 11.14 AT+HTTPSCLOSE — HTTPS 链路主动关闭

关闭HTTPS 链接。 执行AT+HTTPSCLOSE 命令，在关闭HTTPS 链路的同时，AT+HTTPSPARA 命令设置的参数会 保留。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>OK<CR><LF>` |
| 执行 | `AT+HTTPSCLOSE<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**主动上报**

+HTTPSCLOSE: <state>

**参数**

| <state> | HTTPS Link Closed | HTTPS 链路关闭 |
| --- | --- | --- |

**示例**

```
AT+HTTPSCLOSE 关闭HTTPS 链路。
OK
+HTTPSCLOSE: HTTPS Link Closed
```


### 11.15 +HTTPSRECV — HTTPS 数据接收

主动上报HTTPS 链路接收的数据。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `<CR><LF>+HTTPSRECV: <CR><LF><datas>` |  |

**主动上报**

<CR><LF>+HTTPSRECV: <length>,<datas>

**参数**

| <datas> | HTTP 链路接收到的数据。 |
| --- | --- |
| <length> | 接收到的数据长度。 |

**示例**

```
+HTTPSRECV: 上报HTTPS 链路接收的数据。
HTTP/1.1 200 OK
Cache-Control: private
Content-Length: 13842
Content-Type: text/html; charset=utf-8
Server: Microsoft-IIS/7.5
Set-Cookie: ASP.NET SessionId=pvlaai3fizxg44eyvyqsyenk;
_ path=/; HttpOnly
X-AspNet-Version: 2.0.50727
X-Powered-By: ASP.NET
X-UA-Compatible: IE=EmulateIE7
Date: Thu, 28 Nov 2013 05:40:24 GMT
Connection: close
+HTTPSCLOSED: HTTPS Link Closed
+HTTPSRECV: 832,HTTP/1.1 206 Partial Content RECVMODE 设为1 时，接收数据 的格式。
Server: Tengine/2.1.0
Date: Tue, 10 Jul 2018 01:09:25 GMT
Content-Type: text/html; charset=utf-8
Content-Length: 10
Connection: keep-alive
x-server-id: 40-5005
request-id: 0bea4b2215311849654971530e6674
Accept-Ranges: bytes
set-cookie: ctoken=MBHI38pHhdL6q0ltGFqjkviz; path=/;
domain=.alipay.com; secure
set-cookie:
ALIPAYJSESSIONID=jMi6e4Q2JmIN8HRk68wm53KXisfnB5H0homeproxy;
path=/; domain=.alipay.com
x-frame-options: SAMEORIGIN
x-xss-protection: 1; mode=block
x-content-type-options: nosniff
x-download-options: noopen
strict-transport-security: max-age=31536000
Content-Range: bytes 0-9/21651
x-readtime: 2
Set-Cookie: ssl upgrade=0;path=/;secure;
Set-Cookie:
spanner=aGuTtGMbvBcOy1dCyZ/e4JI97JSiPcR1Xt2T4qEYgj0=;path=/;
secure;
Via: spanner-internet-g2-35.em14[206]
```


### 11.16 AT+HTTPSGET — HTTPS 下载文件

HTTPS 下载文件。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+HTTPSGET=<type>[,<check_type>` | `<CR><LF>OK<CR><LF>` |
| 执行 | `,<check_value>]<CR>` | `Or <CR><LF>ERROR<CR><LF>` |

**参数**

该命令为异步命令，执行完后返回OK，下载、解压、校验过程均为后台进行。  当省略<check_type>,<check_value>两个参数时，下载完成后，不进行任何校验动作。  当设置<dir_mode>时，<check_type>,<check_value>可留空处理。需要先用+NWYSPIFLASH 初始  化外部flash。 下载、校验、解压结果上报，通过+HTTPSGETSTAT 命令上报，详情见该命令定义。 

| <type> | 解压方式 |
| --- | --- |
|  | 0：不解压（默认） |
|  | 1：zip（暂不支持） |
|  | 2~99 预留 |
| <check type> _ | 压缩包完整性校验类型 |
|  | 0： MD5 （默认） |
|  | 1~99 预留 |
|  | 校验码，配合<check type>中选定的校验类型一起使用。 _ |

**示例**

```
AT+HTTPSPARA=url, mybank.icbc.com.cn/icbc/perbank/index.jsp 下载文件。
OK
AT+HTTPSGET=0
OK
+HTTPSGETRPT: 10
AT+HTTPSGET=0,0,eaf84487e190bc79af55c972bbc63e3f
OK
+HTTPSGETRPT: 30,303
AT+HTTPSGET=0,0,eaf84487e190bc79af55c972bbc63e3f
OK
+APHTTPSGETRPT: 31
```


### 11.17 +HTTPSGETRPT — 主动上报下载结果

主动上报HTTPS GET 结果。 该命令指示AT+HTTPSGET 命令的运行结果，根据命令的不同阶段，进行结果指示主动上报。  下载、校验、解压，不同的阶段，上报不同的结果码。 

**主动上报**

<CR><LF>+ HTTPSGETRPT: <state_type>[,<err_code>]<CR><LF>

**参数**

| <state type> _ | 状态类型 |
| --- | --- |
|  | 10：下载成功 |
|  | 11：下载失败 |
|  | 20：解压成功 |
|  | 21：解压失败 |
|  | 30：校验成功 |
|  | 31：校验失败 |
| <err code> _ | HTTP GET 过程中遇到的错误响应。 |
|  | 413 请求实例太大 |

**示例**

```
AT+HTTPSPARA=url, mybank.icbc.com.cn/icbc/perbank/index.jsp 下载文件。
OK
AT+HTTPSGET=0
OK
+APHTTPSGETRPT: 10
AT+HTTPSGET=1
OK
+HTTPSGETRPT: 20
AT+HTTPSGET=1,0,eaf84487e190bc79af55c972bbc63e3f
OK
+HTTPSGETRPT: 30
AT+HTTPSGET=1,0,eaf84487e190bc79af55c972bbc63e3f
OK
+HTTPSGETRPT: 31
```


### 11.18 AT+HTTPSGETSTAT? — 查询下载结果

查询HTTPS GET 过程与结果。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+HTTPSGETSTAT:` |
| 执行 | `AT+HTTPSGETSTAT?<CR>` | `<state_type>[,<err_code>]<CR><LF>` |

**参数**

| <state type> _ | 状态类型 |
| --- | --- |
|  | 0：未知结果 |
|  | 10：下载成功 |
|  | 11：下载失败 |
|  | 20：解压成功 |
|  | 21：解压失败 |
|  | 30：校验成功 |
|  | 31：校验失败 |
| <err code> _ | HTTP GET 过程中遇到的错误响应。 |
|  | 413 请求实例太大 |

**示例**

```
AT+HTTPSGET=0
OK
AT+HTTPSGETSTAT?
+HTTPSGETSTAT: 10
OK
AT+APHTTPSGET=1
OK
+HTTPSGETSTAT: 30
OK
```


### 11.19 AT+FILEHTTPACTION — 文件系统内HTTP 请求

文件系统内HTTP 请求。 执行前，需要先建立HTTP 连接。  HTTP GET 前，需要先确定文件系统内有足够的剩余空间。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+FILEHTTPACTION=<mode>,<len gth>,<type>,<dir&filename><CR>` | `<CR><LF>OK<CR><LF> Or AT+CMEE=0 <CR><LF>ERROR<CR><LF>` |
| 执行 | `AT+FILEHTTPACTION=<mode>,<offs et>,<size>[,dir&filename]<CR>` | `Or AT+CMEE=1 <CR><LF>+CME ERROR:<errcode><CR><LF> Or <CR><LF>+CME ERROR:<errtext><CR><LF>` |

**参数**

| <mode> | HTTP 请求方式，可取值为0,1。 |
| --- | --- |
|  | 0：GET |
|  | 1：POST |
|  | <length> | POST 内容长度最大支持2048 字节。 |
| --- | --- | --- |
| <type> | <type> | POST 请求数据类型 |
|  |  | 0：x-www-form-urlencoded |
|  |  | 1：text |
|  |  | 2：json |
|  |  | 3：xml |
|  |  | 4：html |
|  | <offset> | 偏移量，通过GET 方式下载文件时，可以指定下载起始位置。 |
| <size> | <size> | 下载长度，通过GET 方式下载文件时，可以指定下载长度，最大2166720 字节， |
|  |  | 仅在外挂FLASH 的情况下支持2166720 字节，一般情况为524288 字节。 |
| <dir&filename> |  | 需要的文件路径和文件名。 |
|  |  | 当mode=0 时，可以指定本地保存的文件名。 |
| <errcode> |  | 取值<errcode>与<errtext>对应关系如下： |
|  |  | 49 -- The execute command not support 操作不支持 |
|  |  | 51 -- no memory 申请内存失败 |
|  |  | 53 -- parameters are invalid 参数错误 |
|  |  | 66 -- file too large 文件名太长 |
|  |  | 300 -- netif is error 网络异常 |
|  |  | 301 -- HTTP 请求失败 |
|  |  | 303 -- HTTPPARA CID invalid CID 无效 |
|  |  | 303 -- HTTPPARA CID invalid CID 无效 |
|  |  | 1001 -- PDP NOT ACTIVE PDP 未激活 |
|  |  | 1413 – 文件大小超过flah 剩余空间 |
|  |  | 1416 -- HTTP 下载服务器不存在的文件 |
|  | <errtext> | 见<errcode>说明。 |

**示例**

```
AT+FILEHTTPACTION=0,0,524288 从第一个字节开始，下载512KB 数据。 HTTP GET 成功，文件长度512KB。
OK
+FILEHTTPSTAT: 0,1,524288
AT+FILEHTTPACTION=1,2048,0,text.txt 采用 x-www-form-urlencoded 类型，POST text.txt 文件，命令
OK 执行成功，开始POST。
+FILEHTTPSTAT: 1,1,2048 POST 成功，文件长度2048。
AT+FILEHTTPACTION=0,0,524288 下载文件，命令执行失败，错误码1001，代表pdp not active。 下载文件，命令执行失败，错误码1001，代表pdp not active。
+CME ERROR: 1001
```


### 11.20 AT+FILEHTTPSACTION — 文件系统内HTTPS 请求

文件系统内HTTPS 请求。 执行前，需要先建立HTTP 连接。  HTTP GET 前，需要先确定文件系统内有足够的剩余空间。 

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  | `AT+FILEHTTPSACTION=<mode>,<le ngth>,<type>,<dir&filename><CR>` | `<CR><LF>OK<CR><LF> Or AT+CMEE=0 <CR><LF>ERROR<CR><LF> Or` |
| 执行 | `AT+FILEHTTPSACTION=<mode>,<of fset>,<size><CR>` | `AT+CMEE=1 <CR><LF>+CMEERROR:<errcode><CR><LF> Or AT+CMEE=2 <CR><LF>+CME ERROR:<errtext><CR><LF>` |

**参数**

| <mode> |  | HTTP 请求方式，可取值为0,1。 |
| --- | --- | --- |
|  |  | 0：GET |
|  |  | 1：POST |
|  | <length> | POST 内容长度最大支持2048 字节。 |
| <type> | <type> | POST 请求数据类型 |
|  |  | 0：x-www-form-urlencoded |
|  |  | 1：text |
|  |  | 2：json |
|  |  | 3：xml |
|  |  | 4：html |
|  | <offset> | 偏移量，通过GET 方式下载文件时，可以指定下载起始位置。 |
| <size> | <size> | 下载长度，通过 GET 方式下载文件时，可以指定下载长度，最大 size 524288 字 |
|  |  | 节。 |
|  | <dir&filename> | 需要的文件路径和文件名。文件路径是相对于文件系统的根路径而言的。 |
|  | <errcode> | 取值<errcode>与<errtext>对应关系如下： |
|  |  | 49 -- The excute command not support 操作不支持 |
|  |  | 51 -- no memory 申请内存失败 |
|  |  | 53 -- parameters are invalid 参数错误 |
|  |  | 66 -- file too large 文件名太长 |
|  |  | 300 -- netif is error 网络异常 |
| <errtext> | 301 – HTTP 请求失败 |
| --- | --- |
|  | 303 -- HTTPPARA CID invalid CID 无效 |
|  | 1001 -- PDP NOT ACTIVE PDP 未激活 |
|  | 见<errcode>说明。 |

**示例**

```
AT+FILEHTTPSACTION=0,0,524288 从第一个字节开始，下载512KB 数据。 HTTPS GET 成功，文件长度512KB。
OK
+FILEHTTPSTAT: 0,1,524288
AT+FILEHTTPSACTION=1,2048,0,text.txt 采用 x-www-form-urlencoded 类型，POST text.txt 文
OK 件，命令执行成功，开始POST。
+FILEHTTPSTAT: 1,1,2048 POST 成功，文件长度2048。
AT+FILEHTTPSACTION=0,0,524288 下载文件，命令执行失败，错误码1001，代表pdp not
+CME ERROR: 1001 active。
```


### 11.21 +FILEHTTPSTAT — 文件系统内HTTP(S)结果状态上

报 主动上报文件系统HTTP(S)上传/下载结果状态。

**命令格式**

| 类型 | 命令 | 响应格式 |
| --- | --- | --- |
|  |  | `<CR><LF>+FILEHTTPSTAT: <mode>,<stat>[,<length>]<CR><LF>` |

**主动上报**

<CR><LF>+FILEHTTPSTAT: <stat>,<errcode><CR><LF>

**参数**

| <mode> | HTTP(S)请求类型 |
| --- | --- |
|  | 0：HTTP(S) GET |
|  | 1：HTTP(S) POST |
| <stat> | 下载/上传结果码 |
|  | 0：下载/上传失败 |
|  | 1：下载/上传成功 |
|  | 下载/上传长度，单位字节 |

**示例**

```
AT+FILEHTTPSACTION=0,0,524288 从第一个字节开始，下载512KB 数据。 HTTPS GET 成功，文件长度512KB。
OK
+FILEHTTPSTAT: 0,1,524288
AT+FILEHTTPSACTION=1,2048,0,text.txt 采用x-www-form-urlencoded 类型，POST text.txt 文件，命令
OK 执行成功，开始POST。
+FILEHTTPSTAT: 1,1,2048 POST 成功，文件长度2048。
```


### 11.22 +HTTPSCLOSED — HTTPS 链路被动关闭

关闭HTTPS 链接。

**主动上报**

<CR><LF>+HTTPSCLOSED: Link Closed <CR><LF>

**参数**

| 参数 | 说明 |
| --- | --- |
|  | 无 |

**示例**

```
+HTTPSCLOSED: HTTPS Link Closed 主动上报HTTPS 链路断开
```

