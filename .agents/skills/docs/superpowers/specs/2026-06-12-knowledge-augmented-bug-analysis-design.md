# Knowledge-Augmented Bug Analysis 设计文档

**日期**: 2026-06-12
**状态**: 已批准
**涉及技能**: spec-bug-analyzer, spec-knowledge-archiver

---

## 1. 背景与目标

### 1.1 现状

- `spec-bug-analyzer` 有 6 步分析工作流，使用静态 `analysis-patterns.md`（仅 7 个通用模式）
- `spec-knowledge-archiver` 已归档 20 篇 EC626 bug 解决方案到 `knowledge/platform/EC626/bug-solutions/`
- 两套系统完全独立，分析师无法利用历史案例

### 1.2 目标

- bug 分析时自动检索历史相似案例，辅助根因定位
- 支持手动查询知识库
- 知识库将多平台扩展（EC626 → ASR → 更多），检索需支持平台优先级
- 两级检索：先查摘要（低 token），高匹配才加载全文

---

## 2. 方案选型

| 方案 | 描述 | 优势 | 劣势 | 选择 |
|------|------|------|------|------|
| A: 摘要索引 + Grep | index.md 扩展摘要列，Grep 检索 | 零依赖，简单有效 | 关键词匹配有局限 | ✅ 选定 |
| B: JSON 索引 + 脚本 | 独立 JSON + Python 检索脚本 | 精细评分 | 额外脚本维护 | ❌ |
| C: A + 模式表 | 方案 A + 平台专属模式提取 | 最完整 | 模式表维护成本高 | ❌ |

---

## 3. 摘要结构定义

### 3.1 bug-report-template.md 新增 Section 0

在报告模板开头新增结构化摘要块，由 `spec-bug-analyzer` 在 Step 6 生成报告时填写：

```markdown
## 0. 结构化摘要

> 以下信息供知识库检索使用，需完整准确填写。

| 字段 | 内容 |
|------|------|
| **平台** | EC626 |
| **模块** | LWIP/CoAP |
| **问题分类** | 资源耗尽 |
| **症状关键词** | memp_malloc fail, 系统死机, 长时间挂测 |
| **根因概述** | sock_event_queue 溢出导致 memp 未释放，累积耗尽触发 HardFault |
| **调用链摘要** | CoAP GET → sock_event_queue → memp_malloc → 耗尽 → HardFault |
| **检索关键词** | memp, LWIP, CoAP, 死机, 内存池, sock_event, 挂测 |
```

### 3.2 index.md 扩展为 5 列表格

```markdown
| # | 模块 | 症状关键词 | 根因方向 | 文件 |
|---|------|-----------|---------|------|
| 1 | LWIP/CoAP | memp_malloc fail, 死机, 挂测 | 内存池耗尽，sock_event 未释放 | [标题](file.md) |
```

### 3.3 .archive_meta.json 新增 summary 对象

```json
{
  "entries": {
    "key": {
      "title": "...",
      "file": "...",
      "summary": {
        "module": "LWIP/CoAP",
        "bug_type": "资源耗尽",
        "symptoms": ["memp_malloc fail", "系统死机", "长时间挂测"],
        "root_cause": "sock_event_queue 溢出导致 memp 未释放，累积耗尽触发 HardFault",
        "keywords": ["memp", "LWIP", "CoAP", "死机", "内存池", "sock_event"],
        "call_chain_summary": "CoAP GET → sock_event_queue → memp_malloc → 耗尽 → HardFault",
        "platform": "EC626"
      },
      "hash": "...",
      "archived_at": "..."
    }
  }
}
```

---

## 4. spec-knowledge-archiver 改造

### 4.1 核心原则

摘要由报告生成时填写（模板约束），归档时由脚本机械提取（确定性强）。

### 4.2 新增提取脚本

**文件**: `spec-knowledge-archiver/scripts/extract_summary.py`

**功能**:
- 输入：BugAnalysis.md 文件路径
- 处理：解析 "## 0. 结构化摘要" Markdown 表格，提取各字段
- 输出：JSON 格式的 summary 对象到 stdout

**实现**：纯文本解析（正则匹配 Markdown 表格行），不依赖 LLM。

### 4.3 归档流程变更

```
原有流程：
  源文档 → 复制到 knowledge/platform/{platform}/bug-solutions/ → 更新 index.md → 更新 .archive_meta.json

改造后流程：
  源文档 → 复制到 knowledge/platform/{platform}/bug-solutions/
         → 运行 extract_summary.py 提取摘要
         → 更新 index.md（5 列表格）
         → 更新 .archive_meta.json（新增 summary 对象）
```

### 4.4 现有数据迁移

- 对现有 20 篇 EC626 案例补充 Section 0 结构化摘要
- 补充后重新运行 archiver 更新 index.md 和 .archive_meta.json

---

## 5. spec-bug-analyzer 改造

### 5.1 工作流变更（6 步 → 7 步）

```
Step 1:   获取参考文档（日志文件）
Step 2:   日志分析
Step 2.5: 🆕 知识库检索（自动模式）
Step 3:   对比分析（可选）
Step 4:   根因识别（参考历史案例）
Step 5:   代码交叉验证
Step 6:   生成报告（含结构化摘要）
```

### 5.2 Step 2.5 知识库检索流程

```
1. 从 Step 2 分析结果中提取检索线索：
   - 涉及模块（如 MQTT, LWIP, UART）
   - 错误关键字（如 memp_malloc fail, ASSERT, timeout）
   - 异常现象（如死机, 连接失败, 内存泄漏）

2. Grep 搜索知识库索引：
   - 优先搜索当前平台：~/.agents/knowledge/platform/{当前平台}/bug-solutions/index.md
   - 当前平台无高匹配时，扩展到其他平台
   - 平台从日志特征或用户说明中自动判断

3. 评估匹配度：
   - 模块 + 症状双重匹配 → 高相关
   - 仅模块或仅症状匹配 → 中相关
   - 无匹配 → 跳过

4. 结果处理：
   - 高相关案例 → Read 加载全文，注入 Step 4 分析上下文
   - 中相关案例 → 展示摘要供分析师参考
   - 无匹配 → 正常继续分析
```

### 5.3 Step 4 根因识别增强

```
1. 先参考 analysis-patterns.md 的通用模式（保留）
2. 如果 Step 2.5 匹配到历史案例：
   - 将历史案例的根因分析、调用链、修复方案作为参考
   - 明确标注"参考历史案例：[案例标题]"
3. 如果历史案例的根因与当前分析一致，直接引用并验证
4. 如果不一致，对比差异，可能发现新的故障模式
```

### 5.4 Step 6 报告生成增强

生成报告时必须填写 Section 0 结构化摘要，为后续归档检索提供数据。

### 5.5 手动查询模式

独立触发分支，不依赖完整 7 步工作流：

```
触发方式：
  用户说"查询类似的 LWIP 问题" / "有没有 CoAP 死机的案例" / "知识库搜索 xxx"

处理流程：
  1. 解析用户查询中的关键词和模块
  2. 优先搜索当前项目对应平台的 index.md
  3. 当前平台无结果时，扩展到其他平台
  4. 展示匹配结果列表（标题 + 摘要）
  5. 用户选择某个案例 → Read 加载全文
```

---

## 6. 检索平台优先级

```
检索排序：
  当前平台 & 高匹配 > 当前平台 & 中匹配 > 其他平台 & 高匹配 > 其他平台 & 中匹配

平台判断来源：
  - 日志特征自动判断（如 EC626 日志中的特定格式）
  - 用户明确说明的平台
  - 默认使用当前项目主平台
```

---

## 7. 文件改动范围

### 修改的文件

| 文件 | 改动内容 |
|------|---------|
| `spec-bug-analyzer/SKILL.md` | +Step 2.5 知识库检索, Step 4 增强, Step 6 增加摘要, 手动查询分支 |
| `spec-bug-analyzer/references/bug-report-template.md` | +Section 0 结构化摘要 |
| `spec-knowledge-archiver/SKILL.md` | 归档流程增加 extract_summary.py 调用 |
| `knowledge/platform/EC626/bug-solutions/index.md` | 3 列 → 5 列，补摘要 |
| `knowledge/platform/EC626/bug-solutions/.archive_meta.json` | 条目新增 summary 对象 |
| `knowledge/platform/EC626/bug-solutions/*.md` | 20 篇现有文档补充 Section 0 |

### 新增的文件

| 文件 | 用途 |
|------|------|
| `spec-knowledge-archiver/scripts/extract_summary.py` | 从 BugAnalysis.md 提取结构化摘要 |
| `spec-knowledge-archiver/references/index-template.md` | 5 列 index.md 模板 |

### 不变的文件

- `spec-bug-analyzer/references/analysis-patterns.md`
- `spec-bug-analyzer/references/contrast-analysis-guide.md`
- `spec-bug-analyzer/references/log-analyzer-guide.md`
- `spec-bug-analyzer/scripts/log_analyzer.py`

---

## 8. 不涉及的方面

- 不引入向量数据库或 embedding 索引
- 不修改 `log_analyzer.py`
- 不修改其他技能（spec-dump-analyzer、spec-ec-dump-analyzer 等）
- 不涉及跨技能的知识共享协议
