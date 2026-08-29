# 0.10.0 发布说明与迁移清单

本次版本是全量代码审计（2026-08-27）后的整改发布：P0/P1/P2 全量修复、安全专项
加固（S-1~S-8）、结构债清理与约 45 项工程卫生修正。功能行为有少量**破坏性变化**，
升级前请过一遍下方清单。

## 破坏性变化（升级必读）

1. **`data` 步骤语义：路径 → 内容**（P0-1）
   旧版把 `data: {file: ./x.bin}` 的**文件路径字符串**当 AT 命令发送；现在读取文件
   **内容**按字节流发送（分块/间隔可配）。既有用例若有 `data` 步骤，行为会变——
   旧用法本来就非预期（路径不该发给模组）。
2. **退出码变化**
   - 用户主动取消（Ctrl+C / 取消下载）：`1` → **`0`**（主动取消不是错误）；
   - `run` 过滤后无可用用例：`1` → **`2`**（输入问题与执行失败区分）；
   - `list` 目录不存在/未知 target：`1` → **`2`**；
   - **suite_setup 失败：`0` → `1`**（套件前置没跑成是真实失败，不再被
     summary 全零掩盖）；HTML 报告的 exit 徽标与 CLI 退出码共用同一决策点。
   脚本若依赖旧退出码请相应调整。
3. **`console.color` 等配置项严格类型**：`"false"`（带引号）不再被强转为 `true`，
   而是报配置错误。布尔项一律 YAML 裸写 `true/false`。
4. **MCP 事件/订阅上限**：URC 订阅上限 256 个（30 分钟未轮询自动回收）；作业事件
   环形缓冲丢弃量以 `events_truncated` 字段显式暴露；`list_cases`/`list_suites`
   扫描深度 4 层 / 2000 文件封顶。
5. **压测/重试等行为对齐**：压测轮统计以"轮完成"提交（中断轮不计入失败）；
   warmup ≥ count 解析期报错；`contains: ""` 恒真断言解析期拒绝；
   parameters/extract 使用保留字 `timestamp`/`port` 解析期拒绝。

## 新能力

- **两阶段发送完整支持**：`expect`（附加完成正则，如 `\r\n>` 提示符命中即完成）、
  `interval`（发送前延迟 ms）、`inline_hex`（十六进制数据流）、
  `{{file_size("路径")}}`（指令声明长度 = 数据长度场景）。
- **`wait_urc` 模式下 ERROR 立即完成**（原为等到超时）。
- **凭据脱敏开关**（默认关）：`console.mask_credentials: true` 后，呈现层
  （控制台/HTML 报告/GUI 进度/MCP 事件）掩 `AT+CPIN=` 等密码类命令参数段；
  rawlog 原始字节日志永不脱敏（字节核对用途）。
- **新配置项**：`mcp.allowed_roots`（MCP 路径白名单，管理员语义）、
  `update.allowed_hosts`（更新下载 host 追加白名单）——见 config-reference
  §3.9/§3.10。
- **更新链安全**：下载强制 HTTPS+host 白名单+重定向防降级；minisign 签名验签
  框架就绪（见 update-signing.md；签名发布激活前自动走 SHA256 校验，客户端
  无需操作）。
- **CLI 启动提速**：非 run 子命令不再加载引擎/报告栈（~340ms → ~100ms）。

## 数据路径信任边界（S-8）

`data.file` 与 `{{file_size()}}` 的渲染后路径必须位于「用例文件所在目录 ∪
cases_dir ∪ mcp.allowed_roots」内，越界报错。共享/不可信用例不能借 data 步骤
读取任意路径文件。既有用例若引用用例目录外的数据文件，把它移入用例目录或配置
`mcp.allowed_roots`。

## 用例编写注意

- 单行业务码的 extract 正则用排除字符类 `([^\r\n]+)`，不要贪婪 `.+`（会吞行尾
  `\r`）——testcase-guide §5.1。
- `inline_hex` 含 `{{` 占位符时十六进制校验延迟到引擎层（渲染后复核，执行期
  报错而非解析期）。
- 浮点期望值 `eq` 按字符串比较且整值归一（`3.0` 提取为 `"3"`）——口径见
  testcase-guide §4.2。

## 文档

- `docs/user/testcase-guide.md`：expect/interval/inline_hex/file_size/保留字/
  正则排除字符类/脱敏开关全部更新。
- `docs/user/config-reference.md`：新配置段 §3.9/§3.10、console 严格 bool、
  8N1.5 帧格式。
- `docs/user/update-signing.md`：minisign 信任边界与维护者激活步骤。
