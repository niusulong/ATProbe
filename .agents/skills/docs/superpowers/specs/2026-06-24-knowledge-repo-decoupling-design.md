# 设计：知识库从 .agents 剥离为独立仓库

- **日期**：2026-06-24
- **作者**：niusulong
- **状态**：待批准
- **关联**：brainstorming → writing-plans

## 背景与动机

当前知识库位于 `~/.agents/knowledge/`（`C:\Users\20220715012\.agents\knowledge\`），与技能代码（`~/.agents/skills/`）、CLAUDE.md、AGENTS.md 等**同处一个 git 仓库**（`https://github.com/niusulong/spec_v2.git`）。

问题：
1. `~/.agents/` 是 OpenCode 等工具公用的技能存放位置，知识库混在其中语义不清。
2. 知识库与技能代码耦合在一个仓库，无法独立版本管理、独立 push/pull。
3. 初始化时无自动同步机制——新机器/新用户需手动拷贝 85M 知识库。

## 目标

1. 将知识库迁至独立路径 `~/spec-embedded-iot/knowledge/`。
2. 用独立 git 仓库管理，仓库根为 `~/spec-embedded-iot/`。
3. 改造 `spec-init`：启动时检查路径 → 不存在则 `git clone` → 存在则 `git pull` 到最新。
4. spec-init **只负责拉取，不负责推送**（推送由 spec-knowledge-archiver 等技能或用户显式触发）。

## 已定参数

| 决策点 | 选择 |
|--------|------|
| 新路径 | `~/spec-embedded-iot/knowledge/`（即 `C:\Users\20220715012\spec-embedded-iot\knowledge\`） |
| 仓库边界 | `~/spec-embedded-iot/` 是独立 git 仓库根，`knowledge/` 是唯一业务子目录（方案 A：单层仓库） |
| 远程 URL | 稍后由用户创建，设计文档用 `$KNOWLEDGE_REPO_URL` 占位符 |
| vector_db | 不入 git，本地重建 |
| 历史迁移 | 拷贝当前 `knowledge/{platform,protocols,knowledge_config.json}` 到新仓库作为首次提交 |
| spec-init 职责 | 只拉取（clone/pull），不推送 |
| 旧仓库处理 | 删除旧文件 + 留 README 迁移说明 |

## §1 架构与新路径布局

### 1.1 新布局（方案 A：单层仓库）

```
C:\Users\20220715012\
└── spec-embedded-iot/              ← 独立 git 仓库根
    ├── .git/
    ├── .gitignore                  ← 忽略 knowledge/vector_db/
    ├── README.md                   ← 仓库说明
    ├── .repo_url                   ← 单行纯文本，仓库 URL（供 spec-init 读取）
    └── knowledge/                  ← 知识库业务内容（唯一业务子目录）
        ├── knowledge_config.json
        ├── platform/               ← ASR1603 / EC626 / N58 / UIS8850 / UIS8852
        ├── protocols/
        └── vector_db/              ← 本地生成，被 .gitignore 忽略
```

### 1.2 新仓库的 .gitignore（根目录）

```
knowledge/vector_db/
```

仅此一行。vector_db 为 ChromaDB 二进制向量库（当前 28M），可由 `embed_indexer.py` 从 `platform/*.md` 重建，不入 git 避免仓库膨胀。

### 1.3 旧仓库（spec_v2）的清理

迁移并验证完成后，`~/.agents/knowledge/` 下删除：`platform/`、`protocols/`、`knowledge_config.json`、`vector_db/`。

新增 `~/.agents/knowledge/README.md`（迁移说明）：

```markdown
# 知识库已迁移

本目录的知识库内容已迁至独立仓库：`~/spec-embedded-iot/knowledge/`
管理仓库：$KNOWLEDGE_REPO_URL
使用 spec-init 可自动 clone/pull。
```

## §2 路径常量与配置

### 2.1 KNOWLEDGE_ROOT 改定义

`skills/spec-knowledge-archiver/scripts/common.py:17` 是所有脚本的唯一硬编码点：

```python
# 旧（删除）:
KNOWLEDGE_ROOT = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    ".agents", "knowledge"
)

# 新:
KNOWLEDGE_ROOT = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "spec-embedded-iot", "knowledge"
)
```

`VECTOR_DB_PATH`、`CONFIG_FILE` 由 `os.path.join(KNOWLEDGE_ROOT, ...)` 派生，**无需改动**，自动跟随。

### 2.2 spec-init 的仓库 URL 配置

采用**环境变量优先 + 配置文件兜底**：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | 环境变量 `SPEC_KNOWLEDGE_REPO_URL` | 最高优先级，方便 CI/临时覆盖 |
| 2 | 配置文件 `~/spec-embedded-iot/.repo_url` | 仓库根下的纯文本文件，单行 URL，随仓库走 |
| 3 | 都没有 | 报错并给出设置指引，中止 spec-init |

> URL 不写进 SKILL.md 硬编码：仓库创建前 URL 未定，且未来可能变更。

**首次 clone 的引导**：`~/spec-embedded-iot/` 尚未 clone 时，`.repo_url` 也不会存在。因此首次 clone 必须靠环境变量 `SPEC_KNOWLEDGE_REPO_URL`，或由用户手动在 `~/spec-embedded-iot/.repo_url` 写入 URL（此时父目录需先创建）。clone 完成后，仓库内的 `.repo_url` 随之就位，后续 pull 无需再设环境变量。spec-init 在 URL 缺失时报错信息应明确给出这两种设置方式。

## §3 spec-init 改造（核心）

### 3.1 新增 Step 0：知识库仓库同步

在现有 Step 1（检查 .spec 目录）**之前**插入，原 Step 1/2/3 顺延。

### 3.2 Step 0 决策流程

```
spec-init 启动
   │
   ├─ 读取仓库 URL（环境变量 → .repo_url）
   │     └─ 都没有 → 报错并给出设置指引，中止
   │
   ├─ 检查 ~/spec-embedded-iot/ 是否存在
   │     │
   │     ├─【不存在】→ git clone $URL ~/spec-embedded-iot/
   │     │              ├─ 成功 → 检查 vector_db（见 3.3）→ 进入 Step 1
   │     │              └─ 失败 → 报错（网络/权限/URL），中止
   │     │
   │     └─【存在】→ 检查是否 git 仓库（.git 是否存在）
   │           │
   │           ├─【是 git 仓库】→ git -C ~/spec-embedded-iot pull
   │           │     ├─ 成功 → 检查 vector_db → 进入 Step 1
   │           │     └─ 冲突/失败 → 报告本地有改动，询问用户：
   │           │           - stash 后 pull（推荐）
   │           │           - 跳过 pull
   │           │           - 中止
   │           │
   │           ├─【存在但非 git 仓库且非空】→ 报错并询问：
   │           │       目录已存在且非 git 仓库，是否备份后重新 clone？
   │           │
   │           └─【存在且为空】→ 询问：是否在此初始化为克隆？
   │                       git clone $URL 到临时目录再 mv 内容进来
```

### 3.3 vector_db 重建检查

clone/pull 成功后，检查 `~/spec-embedded-iot/knowledge/vector_db/` 是否存在或为空：

```
vector_db 存在且非空 → 跳过（沿用本地索引）
vector_db 不存在/为空 → 询问用户是否现在重建：
    是 → python skills/spec-knowledge-archiver/scripts/embed_indexer.py
    否 → 跳过（用户可后续手动运行，搜索功能暂不可用）
```

> 不强制重建（首次构建耗时）。搜索类 skill（spec-bug-analyzer）在发现 vector_db 缺失时提示重建。

### 3.4 spec-init 输出报告新增段

```
✓ Spec 环境初始化完成

知识库（独立仓库，已同步）：
  仓库：$KNOWLEDGE_REPO_URL
  路径：~/spec-embedded-iot/knowledge/
  ├── platform/          (N 个平台，已同步)
  ├── protocols/
  └── vector_db/         (向量索引：已就绪 / 待重建)

项目级目录：
  .spec/
  ...（原有内容）
```

### 3.5 幂等性与安全保证
- 多次运行安全：已存在则 pull，不重复 clone。
- pull 失败不破坏本地改动（默认 stash 策略或询问）。
- 不删除 vector_db（本地构建产物）。

## §4 其他 Skill / 文档联动修改

### 4.1 需改路径字面量的文件清单

| 文件 | 改动内容 |
|------|----------|
| `skills/spec-knowledge-archiver/scripts/common.py` | `KNOWLEDGE_ROOT` 常量改新路径（§2.1） |
| `skills/spec-knowledge-archiver/SKILL.md` | 路径说明 `~/.agents/knowledge/` → `~/spec-embedded-iot/knowledge/` |
| `skills/spec-init/SKILL.md` | 新增 Step 0 知识库同步流程；更新中央知识库路径说明 |
| `skills/spec-code-summary/SKILL.md` | 输出路径改为新路径 |
| `skills/spec-project-overview/SKILL.md` | 输出路径改为新路径 |
| `skills/spec-using-agents/SKILL.md` | Path 行更新 |
| `AGENTS.md`（根） | Knowledge base path 行更新 |
| `CLAUDE.md`（根） | 知识库路径表更新 |

### 4.2 不改动的文件

- `skills/spec-project-overview-workspace/` 下含旧路径的快照文件：迭代历史快照，保持原貌。
- `.spec/` 项目级目录逻辑：项目内工作区，与中央知识库无关。

### 4.3 修改原则
- 所有 skill 对知识库路径的引用统一改为 `~/spec-embedded-iot/knowledge/`。
- 脚本内部不硬编码字面量，统一从 `common.py` 的 `KNOWLEDGE_ROOT` 取（已是现状，只需改一处定义）。

## §5 迁移执行步骤（分阶段）

迁移本身是手动一次性操作，spec-init 改造是为后续自动化。

### 阶段 A：新仓库初始化（数据迁移）

```
A1. mkdir ~/spec-embedded-iot && cd ~/spec-embedded-iot
A2. git init
A3. 拷贝当前 ~/.agents/knowledge/{platform,protocols,knowledge_config.json}
    → ~/spec-embedded-iot/knowledge/
    （vector_db/ 不拷贝）
A4. 创建 ~/spec-embedded-iot/.gitignore，内容：knowledge/vector_db/
A5. 创建 ~/spec-embedded-iot/README.md（仓库说明）
A6. 创建 ~/spec-embedded-iot/.repo_url（单行，填入实际 URL）
A7. git add -A && git commit -m "init: 知识库从 spec_v2 迁出独立"
A8.【用户执行】创建远程仓库 → git remote add origin $URL → git push -u origin main
```

### 阶段 B：spec_v2 仓库改造（代码 + 文档）

```
B1. 改 skills/spec-knowledge-archiver/scripts/common.py 的 KNOWLEDGE_ROOT
B2. 改 skills/spec-init/SKILL.md（新增 Step 0 知识库同步）
B3. 改 skills/spec-knowledge-archiver/SKILL.md 路径说明
B4. 改 skills/spec-code-summary/SKILL.md 路径
B5. 改 skills/spec-project-overview/SKILL.md 路径
B6. 改 skills/spec-using-agents/SKILL.md 路径
B7. 改根 AGENTS.md / CLAUDE.md 知识库路径表
```

### 验证阶段（阶段 B 改完后）

```
V0. 删除本地 ~/spec-embedded-iot（仅验证用）
V1. 跑改造后的 spec-init → 应自动 git clone 新仓库到 ~/spec-embedded-iot/
V2. 重建 vector_db：python embed_indexer.py（写入新路径）
V3. embed_search.py 搜索能返回结果
```

### 收尾（验证通过后）

```
C1. 删除 ~/.agents/knowledge/{platform,protocols,knowledge_config.json,vector_db}
C2. 创建 ~/.agents/knowledge/README.md（迁移说明，见 §1.3）
C3. git add -A && git commit -m "refactor: 知识库迁出至独立仓库 spec-embedded-iot"
C4. git push（spec_v2 仓库）
```

> **顺序要点**：阶段 B 的代码改动 push 前，必须先完成阶段 A + 验证 V0-V3。否则 spec_v2 的清理提交一旦 push，旧路径数据消失，若新仓库未就位会断档。

## §6 验证清单（验收标准）

| ID | 验证项 | 通过标准 |
|----|--------|----------|
| V1 | spec-init 首次 clone | `~/spec-embedded-iot/` 不存在时，spec-init 能 `git clone` 并拉到 platform/protocols |
| V2 | spec-init 幂等 pull | 已存在时再跑 spec-init，走 `git pull` 分支，无报错、不重复 clone |
| V3 | spec-init pull 冲突 | 本地有未提交改动时，spec-init 询问 stash/跳过/中止，不破坏数据 |
| V4 | spec-init URL 缺失 | 环境变量和 .repo_url 都没有时，报错并给出设置指引 |
| V5 | vector_db 缺失提示 | clone 后 vector_db 不存在，spec-init 询问是否重建 |
| V6 | 搜索可用 | `embed_search.py` 在新路径能搜出历史 bug 案例 |
| V7 | 归档可用 | `knowledge_archiver.py` 归档新文档到 `~/spec-embedded-iot/knowledge/...` |
| V8 | code-summary 输出 | `spec-code-summary` 产出写入新路径 |
| V9 | project-overview 输出 | `spec-project-overview` 产出写入新路径 |
| V10 | 旧仓库已清理 | `~/.agents/knowledge/` 仅剩 README.md，无 platform/protocols/vector_db |

## 风险与回滚

- **风险**：阶段 B 代码改动 push 后，旧机器未更新技能代码仍指向 `~/.agents/knowledge/`，会找不到知识库。
- **缓解**：spec-init 改造后包含路径迁移检测——发现旧路径有数据、新路径为空时，提示用户运行 spec-init 同步。
- **回滚**：阶段 C 的清理提交是单向的。若需回滚，新仓库 `~/spec-embedded-iot/` 可直接删除，从 spec_v2 历史恢复 `~/.agents/knowledge/` 内容（git revert 清理提交）。
