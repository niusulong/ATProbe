# 知识库迁出为独立仓库 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将知识库从 `~/.agents/knowledge/` 迁至独立路径 `~/spec-embedded-iot/knowledge/`，用独立 git 仓库管理，并改造 spec-init 实现自动 clone/pull。

**Architecture:** 新建 `~/spec-embedded-iot/` 单层 git 仓库（knowledge 为唯一业务子目录，vector_db 被 gitignore）。spec-init 新增 Step 0 同步知识库。原 spec_v2 仓库里 `KNOWLEDGE_ROOT` 常量（common.py，唯一硬编码点）及 7 个文档文件的路径字面量随之更新。

**Tech Stack:** Git、Python（embed 脚本）、Markdown（SKILL.md = 给 agent 执行的指令文档）

**关联设计:** `skills/docs/superpowers/specs/2026-06-24-knowledge-repo-decoupling-design.md`

---

## 关键概念说明（执行前必读）

1. **两类路径不要混淆**：
   - `~/.agents/skills/...` = 技能代码/脚本位置，**本次不改**（脚本仍在这里）
   - `~/.agents/knowledge/` → 迁到 `~/spec-embedded-iot/knowledge/` = 知识库数据，**本次只改这个**
2. **本项目无单元测试**：SKILL.md 是给 AI agent 的指令文档，不是可单测代码。验证方式 = 实际执行 + grep 检查残留，非 TDD。
3. **路径约定**：计划中 `~` = `C:\Users\20220715012\`（即 `$USERPROFILE`）。
4. **执行仓库**：所有 Task 1-9 的 git 操作在 spec_v2 仓库（`~/.agents/`）。Task 数据迁移在新的 `~/spec-embedded-iot/` 仓库。

---

## Task 0: 新仓库初始化（数据迁移）

**Files:**
- Create: `~/spec-embedded-iot/`（新 git 仓库根）
- Create: `~/spec-embedded-iot/.gitignore`
- Create: `~/spec-embedded-iot/README.md`
- 数据来源: `~/.agents/knowledge/{platform,protocols,knowledge_config.json}`

> **用户手动执行节点**：Task 0 完成本地初始化后，需用户创建 GitHub 远程仓库并推送（Step 7-8）。
>
> **与设计 §5 的时序调整说明**：设计 §5 阶段 A 的 A6 写"创建 .repo_url"，但此时用户尚未创建远程仓库、URL 未知。实际时序：`.repo_url` 推迟到 Task 10（用户拿到真实 URL 后）创建。这是计划对设计的合理修正，已在 Task 10 落实。

- [ ] **Step 1: 创建新仓库目录并初始化 git**

```bash
mkdir -p ~/spec-embedded-iot
cd ~/spec-embedded-iot
git init
git branch -M main
```

- [ ] **Step 2: 拷贝知识库数据（不含 vector_db）**

```bash
mkdir -p ~/spec-embedded-iot/knowledge
cp -r ~/.agents/knowledge/platform ~/spec-embedded-iot/knowledge/
cp -r ~/.agents/knowledge/protocols ~/spec-embedded-iot/knowledge/
cp ~/.agents/knowledge/knowledge_config.json ~/spec-embedded-iot/knowledge/
```

验证拷贝完整性：
```bash
ls ~/spec-embedded-iot/knowledge/platform
# 期望输出: ASR1603 EC626 N58 UIS8850 UIS8852（5 个平台）
```

> **不要拷贝 vector_db/**——28M 二进制向量库，由 embed_indexer.py 本地重建。

- [ ] **Step 3: 创建 .gitignore**

写入 `~/spec-embedded-iot/.gitignore`：
```
knowledge/vector_db/
```

- [ ] **Step 4: 创建 README.md**

写入 `~/spec-embedded-iot/README.md`：
```markdown
# spec-embedded-iot 知识库

嵌入式 IoT 开发跨项目持久化知识库，按芯片平台组织。

## 结构
- `knowledge/platform/{平台}/` — 项目概览、代码总结、bug/需求解决方案
- `knowledge/protocols/` — 协议文档
- `knowledge/knowledge_config.json` — 归档/索引配置

## 使用
通过 spec-init 自动 clone/pull：
```bash
# 设置仓库 URL（首次 clone 前）
export SPEC_KNOWLEDGE_REPO_URL=<本仓库远程地址>
# 或写入 ~/spec-embedded-iot/.repo_url（clone 后随仓库就位）
```

`knowledge/vector_db/` 为本地 ChromaDB 向量索引，不入 git，由 embed_indexer.py 重建。

## 同步规则
- 拉取（clone/pull）：spec-init 自动处理
- 推送：由 spec-knowledge-archiver 归档后，用户显式 `git push`
```

- [ ] **Step 5: 首次提交**

```bash
cd ~/spec-embedded-iot
git add -A
git commit -m "init: 知识库从 spec_v2 迁出独立"
```

- [ ] **Step 6: 确认未误纳入 vector_db**

```bash
cd ~/spec-embedded-iot
git ls-files | grep vector_db
# 期望: 无输出（vector_db 被 gitignore）
git ls-files | head -20
# 期望: knowledge/knowledge_config.json, knowledge/platform/..., knowledge/protocols/...
```

- [ ] **Step 7:【用户手动】创建 GitHub 远程仓库**

用户在 GitHub 创建空仓库（不勾选 README/gitignore）。获得 URL，例如：
`https://github.com/niusulong/spec-embedded-iot.git`

- [ ] **Step 8:【用户手动】关联远程并推送**

```bash
cd ~/spec-embedded-iot
git remote add origin <Step 7 获得的 URL>
git push -u origin main
```

验证推送成功：在 GitHub 网页确认能看到 knowledge/platform/ 目录。

---

## Task 1: 改造 common.py 的 KNOWLEDGE_ROOT（唯一硬编码点）

**Files:**
- Modify: `~/.agents/skills/spec-knowledge-archiver/scripts/common.py:17-20`

- [ ] **Step 1: 确认当前定义**

```bash
sed -n '17,20p' ~/.agents/skills/spec-knowledge-archiver/scripts/common.py
```

期望输出（旧）：
```python
KNOWLEDGE_ROOT = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    ".agents", "knowledge"
)
```

- [ ] **Step 2: 替换为新路径**

将 common.py 第 17-20 行替换为：
```python
KNOWLEDGE_ROOT = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "spec-embedded-iot", "knowledge"
)
```

精确查找替换对（用 Edit 工具）：
- old_string: `    ".agents", "knowledge"`
- new_string: `    "spec-embedded-iot", "knowledge"`

- [ ] **Step 3: 验证常量解析正确**

```bash
cd ~/.agents/skills/spec-knowledge-archiver/scripts
python -c "from common import KNOWLEDGE_ROOT, VECTOR_DB_PATH, CONFIG_FILE; print(KNOWLEDGE_ROOT); print(VECTOR_DB_PATH); print(CONFIG_FILE)"
```

期望输出：
```
C:\Users\20220715012\spec-embedded-iot\knowledge
C:\Users\20220715012\spec-embedded-iot\knowledge\vector_db
C:\Users\20220715012\spec-embedded-iot\knowledge\knowledge_config.json
```

若 `spec-embedded-iot/knowledge` 尚不存在会报 ImportError 吗？不会——常量只是字符串拼接，不访问文件系统。路径暂时不存在是正常的（vector_db 重建后才创建）。

- [ ] **Step 4: 暂不提交**

common.py 改动将与 Task 2-6 的文档改动一起提交（Task 8）。

---

## Task 2: 改造 spec-init SKILL.md（新增 Step 0 知识库同步）

**Files:**
- Modify: `~/.agents/skills/spec-init/SKILL.md`

这是本次改造最大的改动。在现有 "Step 1：检查环境状态" **之前**插入新的 Step 0，原 Step 1/2/3 顺延为 Step 1/2/3/4。

- [ ] **Step 1: 在 SKILL.md 的 "## 执行流程" 之后、"### Step 1：检查环境状态" 之前插入 Step 0**

精确插入点（用 Edit 工具）：
- old_string:
```
## 执行流程

### Step 1：检查环境状态
```
- new_string:
```
## 执行流程

### Step 0：同步中央知识库（独立仓库）

中央知识库已迁至独立 git 仓库 `~/spec-embedded-iot/`，独立于技能代码（`~/.agents/`）。本步确保知识库 clone/pull 到最新。

**0.1 读取仓库 URL**

按优先级读取 `$KNOWLEDGE_REPO_URL`：
1. 环境变量 `SPEC_KNOWLEDGE_REPO_URL`（最高优先级）
2. 配置文件 `~/spec-embedded-iot/.repo_url`（单行纯文本，随 clone 自动就位）
3. 都没有 → **报错并中止**，输出引导信息：

```
✗ 未配置知识库仓库 URL。

请用以下任一方式设置后重试：
  方式 A（环境变量，适合首次 clone）：
    set SPEC_KNOWLEDGE_REPO_URL=https://github.com/<user>/spec-embedded-iot.git
  方式 B（配置文件，clone 后随仓库就位）：
    写入 ~/spec-embedded-iot/.repo_url（单行 URL）
```

**0.2 检查 ~/spec-embedded-iot/ 状态并同步**

```
路径不存在
  → git clone $URL ~/spec-embedded-iot/
      成功 → 进入 0.3
      失败 → 报错（网络/权限/URL），中止

路径存在
  → 检查 .git 是否存在
      是 git 仓库
        → git -C ~/spec-embedded-iot pull
            成功 → 进入 0.3
            冲突/失败（本地有改动）
              → 询问用户：
                  [1] stash 后 pull（推荐）
                  [2] 跳过 pull（保留本地改动）
                  [3] 中止
      非 git 仓库且非空
        → 报错：目录已存在且非 git 仓库，询问是否备份后重新 clone
      存在且为空
        → git clone $URL 到临时目录，再移动内容到 ~/spec-embedded-iot/
```

**0.3 检查 vector_db（向量索引）**

clone/pull 成功后，检查 `~/spec-embedded-iot/knowledge/vector_db/` 是否存在且非空：

- 存在且非空 → 沿用本地索引，跳过
- 不存在或为空 → 询问用户是否现在重建：
  ```
  知识库已同步，但向量索引（vector_db）尚未构建。
  重建后才能使用语义检索（spec-bug-analyzer 等）。
  是否现在构建？（首次约需 X 分钟，需下载 ~450MB 嵌入模型）
    [1] 现在构建
    [2] 跳过（可稍后手动运行 spec-knowledge-archiver）
  ```
  选"现在构建"则执行：
  ```bash
  python ~/.agents/skills/spec-knowledge-archiver/scripts/embed_indexer.py build
  ```

**0.4 同步结果汇总**

Step 0 完成后输出一行汇总（例如）：
```
✓ 知识库已同步（clone/pull）：~/spec-embedded-iot/knowledge/（5 个平台，向量索引：已就绪）
```

### Step 1：检查环境状态
```

- [ ] **Step 2: 更新 Step 3（输出报告）中的"中央知识库"段落**

原 Step 3 报告里"中央知识库"段需反映新路径。定位现有报告段落：
- old_string:
```
中央知识库（跨项目持久化）：
  ~/.agents/knowledge/platform/{平台名}/
  ├── 项目概览.md
  └── code-summary/  (模块代码总结，按需创建)
```
- new_string:
```
中央知识库（独立仓库，已同步）：
  仓库：$KNOWLEDGE_REPO_URL
  路径：~/spec-embedded-iot/knowledge/
  ├── platform/{平台名}/
  │   ├── 项目概览.md
  │   └── code-summary/  (模块代码总结，按需创建)
  ├── protocols/
  └── vector_db/         (向量索引：已就绪 / 待重建)
```

- [ ] **Step 3: 更新 SKILL.md 顶部"中央知识库"说明段（第 35-40 行附近）**

原：
```
**中央知识库**（跨项目持久化，独立于代码仓库）：
```
~/.agents/knowledge/platform/{平台名}/
  ├── 项目概览.md                        -- 由 spec-project-overview 生成
  └── code-summary/{模块名}/代码总结.md   -- 由 spec-code-summary 生成
```
```
改为：
```
**中央知识库**（跨项目持久化，独立 git 仓库 `~/spec-embedded-iot/`，由 Step 0 自动 clone/pull）：
```
~/spec-embedded-iot/knowledge/platform/{平台名}/
  ├── 项目概览.md                        -- 由 spec-project-overview 生成
  └── code-summary/{模块名}/代码总结.md   -- 由 spec-code-summary 生成
```
```

- [ ] **Step 4: 验证 SKILL.md 无残留旧路径（知识库路径）**

```bash
grep -n "agents/knowledge\|agents.*knowledge" ~/.agents/skills/spec-init/SKILL.md
```

期望：无输出（`~/.agents/skills/` 脚本路径不在此文件出现）。

---

## Task 3: 更新 spec-knowledge-archiver SKILL.md

**Files:**
- Modify: `~/.agents/skills/spec-knowledge-archiver/SKILL.md:5,136`

- [ ] **Step 1: 更新 description 里的路径（第 5 行）**

- old_string: `  持久化知识库 (~/.agents/knowledge/platform/{平台}/)。支持单个归档、批量归档、`
- new_string: `  持久化知识库 (~/spec-embedded-iot/knowledge/platform/{平台}/)。支持单个归档、批量归档、`

- [ ] **Step 2: 更新配置文件路径（第 136 行）**

- old_string: `路径: `~/.agents/knowledge/knowledge_config.json``
- new_string: `路径: `~/spec-embedded-iot/knowledge/knowledge_config.json``

- [ ] **Step 3: 验证无残留知识库旧路径**

```bash
grep -n "agents/knowledge" ~/.agents/skills/spec-knowledge-archiver/SKILL.md
```

期望：无输出。

注意：文件中 `~/.agents/skills/...` 脚本路径引用（如 embed_indexer.py 命令）**保持不变**。

---

## Task 4: 更新 spec-code-summary SKILL.md

**Files:**
- Modify: `~/.agents/skills/spec-code-summary/SKILL.md:81,117`

- [ ] **Step 1: 更新输出路径（第 81 行）**

- old_string: `3. 知识库输出路径：`~/.agents/knowledge/platform/{平台名}/code-summary/{模块名}/代码总结.md``
- new_string: `3. 知识库输出路径：`~/spec-embedded-iot/knowledge/platform/{平台名}/code-summary/{模块名}/代码总结.md``

- [ ] **Step 2: 更新输出路径（第 117 行）**

- old_string: `- **输出路径**：`~/.agents/knowledge/platform/{平台名}/code-summary/{模块名}/代码总结.md``
- new_string: `- **输出路径**：`~/spec-embedded-iot/knowledge/platform/{平台名}/code-summary/{模块名}/代码总结.md``

- [ ] **Step 3: 验证无残留**

```bash
grep -n "agents/knowledge" ~/.agents/skills/spec-code-summary/SKILL.md
```

期望：无输出（第 129 行 `~/.agents/skills/` 脚本路径不在匹配范围，因匹配的是 `agents/knowledge`）。

---

## Task 5: 更新 spec-project-overview SKILL.md

**Files:**
- Modify: `~/.agents/skills/spec-project-overview/SKILL.md:38,39`

- [ ] **Step 1: 更新路径（第 38 行）**

- old_string: `  `C:\Users\<用户>\.agents\knowledge\platform\<平台名>\项目概览.md``
- new_string: `  `C:\Users\<用户>\spec-embedded-iot\knowledge\platform\<平台名>\项目概览.md``

- [ ] **Step 2: 更新 bash 等价路径（第 39 行）**

- old_string: `  （在 bash 里等价于 `~/.agents/knowledge/platform/<平台名>/项目概览.md`）`
- new_string: `  （在 bash 里等价于 `~/spec-embedded-iot/knowledge/platform/<平台名>/项目概览.md`）`

- [ ] **Step 3: 验证无残留**

```bash
grep -n "agents/knowledge" ~/.agents/skills/spec-project-overview/SKILL.md
```

期望：无输出。

---

## Task 6: 更新 spec-using-agents SKILL.md

**Files:**
- Modify: `~/.agents/skills/spec-using-agents/SKILL.md:62`

- [ ] **Step 1: 更新 Path 行（第 62 行）**

- old_string: `**Path:** `~/.agents/knowledge/platform/{platform}/``
- new_string: `**Path:** `~/spec-embedded-iot/knowledge/platform/{platform}/``

- [ ] **Step 2: 验证无残留**

```bash
grep -n "agents/knowledge" ~/.agents/skills/spec-using-agents/SKILL.md
```

期望：无输出。

---

## Task 7: 更新根目录 AGENTS.md / CLAUDE.md

**Files:**
- Modify: `~/.agents/AGENTS.md:28,31`
- Modify: `~/.agents/CLAUDE.md:7,14,58`

- [ ] **Step 1: AGENTS.md 第 28 行（搜索命令里的脚本路径——确认不改）**

注意：AGENTS.md 第 28 行 `python ~/.agents/skills/spec-knowledge-archiver/scripts/embed_search.py` 是**脚本路径，不改**。只需改第 31 行的知识库路径。

- [ ] **Step 2: AGENTS.md 第 31 行**

- old_string: `Knowledge base path: `~/.agents/knowledge/platform/{platform}/``
- new_string: `Knowledge base path: `~/spec-embedded-iot/knowledge/platform/{platform}/``

- [ ] **Step 3: CLAUDE.md 第 7 行（知识库根路径）**

- old_string: `路径：`~/.agents/knowledge/platform/{平台名}/``
- new_string: `路径：`~/spec-embedded-iot/knowledge/platform/{平台名}/``

- [ ] **Step 4: CLAUDE.md 第 14 行（向量索引路径）**

- old_string: `| 向量索引 | `~/.agents/knowledge/vector_db/` | ChromaDB 语义检索 |`
- new_string: `| 向量索引 | `~/spec-embedded-iot/knowledge/vector_db/` | ChromaDB 语义检索 |`

- [ ] **Step 5: CLAUDE.md 第 58 行（工作目录约定表）**

- old_string: `| `~/.agents/knowledge/` | 跨项目持久化知识库 |`
- new_string: `| `~/spec-embedded-iot/knowledge/` | 跨项目持久化知识库（独立仓库） |`

- [ ] **Step 6: 验证无残留**

```bash
grep -n "agents/knowledge\|agents.*knowledge" ~/.agents/AGENTS.md ~/.agents/CLAUDE.md
```

期望：无输出。

---

## Task 8: 提交阶段 B 全部改动（spec_v2 仓库）

**Files:**
- Commit in: `~/.agents/`（spec_v2 仓库）

- [ ] **Step 1: 确认改动文件清单**

```bash
cd ~/.agents
git status --short
```

期望修改文件（8 个）：
```
M skills/spec-knowledge-archiver/scripts/common.py
M skills/spec-init/SKILL.md
M skills/spec-knowledge-archiver/SKILL.md
M skills/spec-code-summary/SKILL.md
M skills/spec-project-overview/SKILL.md
M skills/spec-using-agents/SKILL.md
M AGENTS.md
M CLAUDE.md
```

- [ ] **Step 2: 全局复查无遗漏的知识库旧路径**

```bash
cd ~/.agents
grep -rn "agents/knowledge\|agents\\\\knowledge\|\.agents.knowledge" --include="*.md" --include="*.py" skills/ AGENTS.md CLAUDE.md | grep -v "spec-project-overview-workspace" | grep -v "docs/superpowers"
```

期望：无输出。
> 排除 `spec-project-overview-workspace`（迭代历史快照，按设计不改）和 `docs/superpowers`（本计划/设计文档）。

- [ ] **Step 3: 提交**

```bash
cd ~/.agents
git add skills/spec-knowledge-archiver/scripts/common.py skills/spec-init/SKILL.md skills/spec-knowledge-archiver/SKILL.md skills/spec-code-summary/SKILL.md skills/spec-project-overview/SKILL.md skills/spec-using-agents/SKILL.md AGENTS.md CLAUDE.md
git commit -m "refactor(knowledge): 知识库路径迁出 .agents → spec-embedded-iot

- common.py KNOWLEDGE_ROOT 改为 ~/spec-embedded-iot/knowledge
- spec-init 新增 Step 0：知识库仓库 clone/pull 同步
- 7 个 SKILL.md / AGENTS.md / CLAUDE.md 路径字面量更新
- 知识库数据迁至独立仓库 spec-embedded-iot（见收尾 Task 10）"
```

> **暂不 push**——先完成 Task 9 验证，确认新路径下功能正常，再 Task 10 清理 + 一起 push。

---

## Task 9: 验证新路径功能正常

**前置条件**：Task 0 已完成（新仓库已 clone/存在于 `~/spec-embedded-iot/`）。

- [ ] **Step 1: 重建 vector_db 到新路径**

```bash
cd ~/.agents/skills/spec-knowledge-archiver/scripts
python embed_indexer.py build
```

期望：脚本读取 `~/spec-embedded-iot/knowledge/` 下的 platform/protocols，输出"向量数据库: ...spec-embedded-iot\knowledge\vector_db"，构建各 collection 索引。

> 首次构建需下载 ~450MB 嵌入模型，耗时较长。

- [ ] **Step 2: 验证搜索可用**

```bash
cd ~/.agents/skills/spec-knowledge-archiver/scripts
python embed_search.py "PPP 拨号" --top 3
```

期望：返回历史 bug/需求案例结果（从新路径的 vector_db 检索）。

- [ ] **Step 3: 验证 spec-init Step 0 幂等 pull**

模拟已存在场景（此时 `~/spec-embedded-iot/` 已存在）：
```bash
export SPEC_KNOWLEDGE_REPO_URL=<Task 0 Step 7 的真实 URL>
# 手动执行 spec-init 的 Step 0 逻辑（或调用 spec-init 技能）
git -C ~/spec-embedded-iot pull
```

期望：`Already up to date.` 或正常更新，无报错。

- [ ] **Step 4: 验证 spec-init 首次 clone 分支（可选，需临时目录）**

```bash
# 备份后删除，测试 clone 分支
mv ~/spec-embedded-iot ~/spec-embedded-iot.bak
export SPEC_KNOWLEDGE_REPO_URL=<真实 URL>
git clone $SPEC_KNOWLEDGE_REPO_URL ~/spec-embedded-iot
# 验证内容
ls ~/spec-embedded-iot/knowledge/platform
# 期望: ASR1603 EC626 N58 UIS8850 UIS8852
# 恢复 vector_db（clone 没有它，从备份拷贝）
cp -r ~/spec-embedded-iot.bak/knowledge/vector_db ~/spec-embedded-iot/knowledge/ 2>/dev/null
rm -rf ~/spec-embedded-iot.bak
```

---

## Task 10: 创建 .repo_url（用户提供真实 URL 后）

**Files:**
- Create: `~/spec-embedded-iot/.repo_url`

> **用户手动执行节点**：需要 Task 0 Step 7 创建仓库后获得的真实 URL。

- [ ] **Step 1: 写入 .repo_url**

将 `<真实仓库 URL>` 写入 `~/spec-embedded-iot/.repo_url`（单行，无多余内容）：
```
https://github.com/niusulong/spec-embedded-iot.git
```

- [ ] **Step 2: 提交并推送（新仓库）**

```bash
cd ~/spec-embedded-iot
git add .repo_url
git commit -m "chore: 添加 .repo_url 供 spec-init 读取"
git push
```

> 此后任何人 clone 这个仓库，`.repo_url` 随之就位，spec-init pull 无需再设环境变量。

---

## Task 11: 清理旧仓库（spec_v2）的知识库数据

**前置条件**：Task 9 全部验证通过（新路径功能正常），Task 8 改动已确认无误。

- [ ] **Step 1: 删除旧知识库数据**

```bash
cd ~/.agents
git rm -r knowledge/platform knowledge/protocols knowledge/knowledge_config.json
# vector_db 若被 git 跟踪也删除；若本就在 gitignore 则无需 git rm
git rm -r --ignore-unmatch knowledge/vector_db
```

- [ ] **Step 2: 创建迁移说明 README**

写入 `~/.agents/knowledge/README.md`：
```markdown
# 知识库已迁移

本目录的知识库内容已迁至独立仓库：`~/spec-embedded-iot/knowledge/`

- 管理仓库：见 `~/spec-embedded-iot/.repo_url`
- 同步方式：使用 spec-init 自动 clone/pull
- 迁移日期：2026-06-24

技能代码（skills/）仍保留在本仓库（spec_v2），仅知识库数据迁出。
```

- [ ] **Step 3: 提交清理**

```bash
cd ~/.agents
git add knowledge/README.md
git commit -m "refactor(knowledge): 清理旧路径数据，保留迁移说明

知识库已迁至独立仓库 spec-embedded-iot。
旧 knowledge/{platform,protocols,knowledge_config.json,vector_db} 删除，
保留 README 指引新位置。"
```

- [ ] **Step 4: 推送 spec_v2 仓库**

```bash
cd ~/.agents
git push
```

---

## Task 12: 最终验收（对照设计 §6 验证清单）

逐项核对设计文档的 V1-V10：

- [ ] **V1 spec-init 首次 clone**：删除 `~/spec-embedded-iot/` 后跑 spec-init，能 git clone 并拉到 platform/protocols（Task 9 Step 4 已验证）
- [ ] **V2 spec-init 幂等 pull**：已存在时再跑，走 pull 分支无报错（Task 9 Step 3 已验证）
- [ ] **V3 spec-init pull 冲突**：手动制造本地改动后 pull，spec-init 询问 stash/跳过/中止
- [ ] **V4 spec-init URL 缺失**：清空环境变量和 .repo_url，spec-init 报错并给设置指引
- [ ] **V5 vector_db 缺失提示**：clone 后 vector_db 不存在，spec-init 询问是否重建（Task 9 Step 1 流程）
- [ ] **V6 搜索可用**：`embed_search.py` 在新路径搜出历史案例（Task 9 Step 2 已验证）
- [ ] **V7 归档可用**：`knowledge_archiver.py` 归档测试文档到新路径（手动跑一次）
- [ ] **V8 code-summary 输出**：`spec-code-summary` 产出写入新路径（手动或下次实跑验证）
- [ ] **V9 project-overview 输出**：`spec-project-overview` 产出写入新路径（手动或下次实跑验证）
- [ ] **V10 旧仓库已清理**：`~/.agents/knowledge/` 仅剩 README.md（Task 11 已完成）

- [ ] **全局残留检查**

```bash
grep -rn "agents/knowledge\|agents\\\\knowledge" --include="*.md" --include="*.py" ~/.agents/ | grep -v "spec-project-overview-workspace" | grep -v "docs/superpowers" | grep -v "knowledge/README.md"
```

期望：无输出。

---

## 执行顺序与依赖

```
Task 0（新仓库初始化 + 用户创建远程 + push）
   │
   ├─ Task 1-7（代码/文档改动，可并行）
   ├─ Task 8（提交阶段 B，依赖 1-7 完成）
   │
   ├─ Task 9（验证，依赖 Task 0 + Task 8）
   ├─ Task 10（.repo_url，依赖用户拿到 URL）
   ├─ Task 11（清理旧仓库，依赖 Task 9 验证通过）
   └─ Task 12（最终验收，依赖 Task 11）
```

**关键约束**：Task 11（清理旧数据）必须在 Task 9 验证通过后执行。一旦旧路径数据删除，若新路径未就位会造成断档。
