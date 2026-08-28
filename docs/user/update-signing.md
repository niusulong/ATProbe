# 更新签名（minisign）——维护者指南

> 对应设计 §5 S-6。本文面向**维护者**（发布/密钥保管者）；最终用户无需任何操作，
> 验签由升级流程自动完成。

## 信任边界：SHA256 与签名各防什么

| 机制 | 防御 | 防不了 |
| --- | --- | --- |
| SHA256 摘要（`.sha256` 资产） | 传输损坏、CDN 缓存污染、等大小误替换 | **Release 源本身失守**（摘要与包同源发布，攻击者拿到 Release 写权限即可同时替换两者） |
| minisign 签名（`.minisig` 资产） | Release 源失守（签名需要离线保管的私钥，GitHub 上的攻击者伪造不出） | 无（在公钥已随更早版本内置的前提下） |

过渡期语义：**旧版本/未内置公钥的版本没有 `.minisig` 资产可用时，仍走 SHA256 校验**
（`.minisig` 是可选资产，旧版 checker 不识别它）。验签能力自本版本起内置；
本仓库**不内置任何公钥**——公钥由维护者生成后随某个正式版本发布（见下）。

## 格式与验证机制

- 算法：Ed25519（minisign 默认 `Ed` 模式，对**文件原始字节**签名，非 prehash 摘要）。
- 公钥文件 `atprobe-update.pub`：首行注释 + 次行 base64（解码 42 字节 =
  `alg(2) || key_id(8) || pk(32)`），放置于 `src/atprobe/resources/`（与
  `app_icon.png` 同目录，经 `atprobe.resources` 包随包分发）。
- 签名文件 `<zip>.minisig`：首行 untrusted comment + 次行 base64（解码 74 字节 =
  `alg(2) || key_id(8) || sig(64)`）+ trusted comment + 注释签名（不参与验证）。
- 客户端实现：`src/atprobe/infra/update/verifier.py`（pynacl `VerifyKey`）；
  Release 资产识别见 `checker.py` 的 `ReleaseInfo.minisig_url`。

## 维护者激活清单（首次启用签名）

1. **生成密钥对**（离线/安全机器上执行）：

   ```
   minisign -G
   ```

   生成 `minisign.key`（私钥）与 `minisign.pub`（公钥）。私钥建议设置保护密码，
   妥善备份（密码管理器/离线介质）——**私钥一旦丢失，只能轮换密钥对**（见下）。

2. **内置公钥**：把 `minisign.pub` 重命名拷贝到仓库：

   ```
   src/atprobe/resources/atprobe-update.pub
   ```

   提交并发版。自该版本起，用户升级后本地即有公钥（打包后位于
   `_internal/atprobe/resources/`，由 PyInstaller `collect_data_files("atprobe")`
   自动收集）。

3. **配置 GitHub secrets**（Settings → Secrets and variables → Actions）：

   - `MINISIGN_PRIVATE_KEY`：私钥文件**全文**（两行：注释 + base64）。
     多行内容建议用 CLI 写入：

     ```
     gh secret set MINISIGN_PRIVATE_KEY < minisign.key
     ```

   - `MINISIGN_KEY_PASSWORD`（可选）：仅当私钥设置了保护密码时配置。
     注意 minisign 官方二进制不支持命令行/环境变量传密码，CI 中经 stdin
     传入（`.github/workflows/release.yml` 的 Sign 步骤已处理）。

4. **发布即自动签名**：此后推送 `v*.*.*` tag，release.yml 会在生成 SHA256
   之后、上传 Release 之前用 minisign 签名，Release 自动多出
   `<zip>.minisig` 资产。**未配置 `MINISIGN_PRIVATE_KEY` 时发布直接失败**
   （显式报错，不静默跳过）。

## 顺序陷阱（务必先读再激活）

公钥是**随版本内置**的：某个已发布版本里有没有公钥，取决于发布它时仓库里是否
存在 `src/atprobe/resources/atprobe-update.pub`。这带来一个切换顺序问题：

- 升级流程的策略（T5 接线）：**Release 带 `.minisig` 资产而本地无公钥** →
  拒绝自动下载（防「验签能力缺失被降级利用」）。因此：

  **错误顺序**：先配 secret 开签名（Release 开始带 `.minisig`）——此时存量用户
  的版本都没有公钥，遇到带 `.minisig` 的 Release 会拒绝自动更新（用户需手动
  下载安装包，SHA256 手工校验仍有效），直到他们装上带公钥的版本。

  **推荐顺序（公钥先行）**：

  1. 先把公钥放入 `src/atprobe/resources/` 发一个版本（此时不开 secret，
     Release 不带 `.minisig`，一切照旧）；
  2. 用户升级到该版本（本地已有公钥）；
  3. 再配置 `MINISIGN_PRIVATE_KEY` secret 开启签名——此后的 Release 带
     `.minisig`，带公钥的版本正常验签，切换完成。

  也可「初期两者并存」：开签名后接受一段时间内未带公钥的存量版本需手动升级
  （公告引导），SHA256 校验全程兜底。

## 密钥轮换

1. 安全机器上 `minisign -G` 生成**新**密钥对；
2. 新公钥替换 `src/atprobe/resources/atprobe-update.pub`，发版（带新公钥的
   版本起，新签名可验；仍用旧公钥的版本验新签名会失败——签名文件与新公钥
   同 Release 发布，正常升级链路先拿到新公钥版本再验新签名，不冲突；
   跨版本的边界情况按「拒绝自动更新 + 提示手动升级」处理）；
3. 更新 GitHub secret 为新私钥；旧公钥作废。

## 私钥泄露应急

1. 立即删除/撤回最近的可疑 Release（GitHub Release 页删除资产或整单）；
2. 撤换 `MINISIGN_PRIVATE_KEY`（及密码）secret——旧私钥立即失效于后续发布；
3. 按上文「密钥轮换」生成新密钥对并发新版本（新版本内置新公钥）；
4. 公告用户升级；已发出的旧签名资产不可再信（旧私钥可伪造）。
