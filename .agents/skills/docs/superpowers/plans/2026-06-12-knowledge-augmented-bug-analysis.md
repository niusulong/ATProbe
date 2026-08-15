# Knowledge-Augmented Bug Analysis 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 bug-solutions 知识库与 spec-bug-analyzer 技能集成，实现分析时自动检索历史案例、手动查询知识库、归档时自动提取摘要。

**Architecture:** 两级检索——归档时从报告模板的 Section 0 提取结构化摘要到索引，分析时先 Grep 搜索 index.md 摘要，高匹配才 Read 全文。平台优先检索，当前平台无高匹配时扩展到其他平台。

**Tech Stack:** Python 3 (extract_summary.py, knowledge_archiver.py), Markdown (SKILL.md, templates, index.md)

**Design Spec:** `docs/superpowers/specs/2026-06-12-knowledge-augmented-bug-analysis-design.md`

---

## File Structure

```
spec-knowledge-archiver/
├── SKILL.md                                    # MODIFY: 归档流程增加摘要提取步骤
├── scripts/
│   ├── knowledge_archiver.py                   # MODIFY: archive_entry + generate_index
│   └── extract_summary.py                      # CREATE: 从 BugAnalysis.md 提取结构化摘要
├── references/
│   └── index-template.md                       # CREATE: 5 列 index.md 模板说明
└── tests/
    └── test_extract_summary.py                 # CREATE: 摘要提取单元测试

spec-bug-analyzer/
├── SKILL.md                                    # MODIFY: +Step 2.5, Step 4 增强, Step 6 增强, 手动查询
└── references/
    └── bug-report-template.md                  # MODIFY: +Section 0 结构化摘要

knowledge/platform/EC626/bug-solutions/
├── index.md                                    # MODIFY: 3 列 → 5 列（由 archiver 自动重建）
├── .archive_meta.json                          # MODIFY: 条目新增 summary（由 archiver 自动重建）
└── *.md                                        # MODIFY: 20 篇补充 Section 0
```

---

### Task 1: 创建 extract_summary.py 单元测试

**Files:**
- Create: `spec-knowledge-archiver/tests/__init__.py`
- Create: `spec-knowledge-archiver/tests/test_extract_summary.py`

- [ ] **Step 1: 创建测试目录和文件**

创建 `spec-knowledge-archiver/tests/__init__.py`（空文件）。

创建 `spec-knowledge-archiver/tests/test_extract_summary.py`：

```python
"""extract_summary.py 单元测试"""
import json
import os
import tempfile
import sys

# 将 scripts 目录加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from extract_summary import extract_summary


def _write_temp_md(content):
    """写入临时 md 文件并返回路径"""
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_extract_full_summary():
    """测试完整摘要提取"""
    content = """\
# 测试问题 原因分析

## 0. 结构化摘要

> 以下信息供知识库检索使用，需完整准确填写。

| 字段 | 内容 |
|------|------|
| **平台** | EC626 |
| **模块** | LWIP/CoAP |
| **问题分类** | 资源耗尽 |
| **症状关键词** | memp_malloc fail, 系统死机, 长时间挂测 |
| **根因概述** | sock_event_queue 溢出导致 memp 未释放 |
| **调用链摘要** | CoAP GET → sock_event_queue → memp_malloc → 耗尽 |
| **检索关键词** | memp, LWIP, CoAP, 死机, 内存池 |

## 1. 问题描述

这里是问题描述。
"""
    path = _write_temp_md(content)
    try:
        result = extract_summary(path)
        assert result is not None
        assert result["platform"] == "EC626"
        assert result["module"] == "LWIP/CoAP"
        assert result["bug_type"] == "资源耗尽"
        assert result["symptoms"] == ["memp_malloc fail", "系统死机", "长时间挂测"]
        assert result["root_cause"] == "sock_event_queue 溢出导致 memp 未释放"
        assert result["call_chain_summary"] == "CoAP GET → sock_event_queue → memp_malloc → 耗尽"
        assert result["keywords"] == ["memp", "LWIP", "CoAP", "死机", "内存池"]
    finally:
        os.unlink(path)


def test_no_summary_section():
    """测试无摘要节时返回 None"""
    content = """\
# 测试问题 原因分析

## 1. 问题描述

没有摘要节。
"""
    path = _write_temp_md(content)
    try:
        result = extract_summary(path)
        assert result is None
    finally:
        os.unlink(path)


def test_partial_summary():
    """测试部分字段摘要"""
    content = """\
# 测试

## 0. 结构化摘要

| 字段 | 内容 |
|------|------|
| **平台** | EC626 |
| **模块** | MQTT |

## 1. 正文
"""
    path = _write_temp_md(content)
    try:
        result = extract_summary(path)
        assert result is not None
        assert result["platform"] == "EC626"
        assert result["module"] == "MQTT"
        assert "bug_type" not in result
    finally:
        os.unlink(path)


def test_single_keyword():
    """测试单个关键词（无逗号）"""
    content = """\
# 测试

## 0. 结构化摘要

| 字段 | 内容 |
|------|------|
| **症状关键词** | 死机 |

## 1. 正文
"""
    path = _write_temp_md(content)
    try:
        result = extract_summary(path)
        assert result["symptoms"] == ["死机"]
    finally:
        os.unlink(path)


def test_summary_at_end_of_file():
    """测试摘要在文件末尾（无后续章节）"""
    content = """\
# 测试

## 0. 结构化摘要

| 字段 | 内容 |
|------|------|
| **平台** | EC626 |
| **模块** | UART |
| **问题分类** | 缓冲区溢出 |
| **症状关键词** | FIFO 超时, 节点溢出 |
| **根因概述** | RX FIFO 超时未处理 |
| **调用链摘要** | UART RX → FIFO 超时 → pending 节点溢出 |
| **检索关键词** | UART, FIFO, 超时, 溢出 |
"""
    path = _write_temp_md(content)
    try:
        result = extract_summary(path)
        assert result is not None
        assert result["platform"] == "EC626"
        assert result["module"] == "UART"
        assert len(result["keywords"]) == 4
    finally:
        os.unlink(path)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/.agents/skills/spec-knowledge-archiver
python -m pytest tests/test_extract_summary.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'extract_summary'`

---

### Task 2: 实现 extract_summary.py

**Files:**
- Create: `spec-knowledge-archiver/scripts/extract_summary.py`

- [ ] **Step 1: 创建 extract_summary.py**

```python
#!/usr/bin/env python3
"""
从 Bug 分析报告中提取结构化摘要（Section 0）。

用法:
  python extract_summary.py <BugAnalysis.md路径>

输出: JSON 格式的 summary 对象到 stdout
"""

import json
import re
import sys

# 匹配 "## 0. 结构化摘要" 或 "## 0 结构化摘要"
SUMMARY_HEADER_RE = re.compile(r"^##\s*0[\.\s]+结构化摘要", re.MULTILINE)

# 匹配表格数据行: | **字段名** | 值 |
TABLE_ROW_RE = re.compile(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|$", re.MULTILINE)

# 中文字段名 → 英文字段名
FIELD_MAP = {
    "平台": "platform",
    "模块": "module",
    "问题分类": "bug_type",
    "症状关键词": "symptoms",
    "根因概述": "root_cause",
    "调用链摘要": "call_chain_summary",
    "检索关键词": "keywords",
}

# 逗号分隔的列表字段
LIST_FIELDS = {"symptoms", "keywords"}


def extract_summary(filepath):
    """从 Markdown 文件提取结构化摘要。

    Args:
        filepath: Markdown 文件路径

    Returns:
        dict: 摘要字段字典，无摘要时返回 None
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # 定位摘要节
    header_match = SUMMARY_HEADER_RE.search(content)
    if not header_match:
        return None

    # 截取到下一个 ## 节或文件末尾
    start = header_match.end()
    next_section = re.search(r"^## ", content[start:], re.MULTILINE)
    section_content = content[start:start + next_section.start()] if next_section else content[start:]

    # 解析表格行
    summary = {}
    for row in TABLE_ROW_RE.finditer(section_content):
        field_cn = row.group(1).strip()
        value = row.group(2).strip()

        field_en = FIELD_MAP.get(field_cn)
        if not field_en:
            continue

        if field_en in LIST_FIELDS:
            summary[field_en] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            summary[field_en] = value

    return summary if summary else None


def main():
    if len(sys.argv) < 2:
        print("用法: python extract_summary.py <BugAnalysis.md路径>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        print(f"错误: 文件不存在: {filepath}", file=sys.stderr)
        sys.exit(1)

    summary = extract_summary(filepath)

    if summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("错误: 未找到结构化摘要（## 0. 结构化摘要）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

注意：文件顶部需要 `import os`，补上：

```python
import json
import os
import re
import sys
```

- [ ] **Step 2: 运行测试确认通过**

```bash
cd ~/.agents/skills/spec-knowledge-archiver
python -m pytest tests/test_extract_summary.py -v
```

Expected: 5 tests PASS

- [ ] **Step 3: 提交**

```bash
cd ~/.agents/skills
git add spec-knowledge-archiver/scripts/extract_summary.py spec-knowledge-archiver/tests/
git commit -m "feat: add extract_summary.py with tests for Section 0 parsing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 修改 knowledge_archiver.py — archive_entry 增加摘要提取

**Files:**
- Modify: `spec-knowledge-archiver/scripts/knowledge_archiver.py`

本任务修改 `archive_entry()` 函数，归档时提取摘要并写入 `.archive_meta.json`。

- [ ] **Step 1: 添加 import**

在 `knowledge_archiver.py` 文件顶部的 import 区域添加：

```python
from extract_summary import extract_summary as extract_summary_from_md
```

插入位置：在 `from pathlib import Path` 之后。

- [ ] **Step 2: 修改 archive_entry 函数**

找到 `archive_entry()` 函数末尾（`is_new = existing is None` 和 `return` 之间），在写入文件后、更新元数据前，插入摘要提取逻辑。

将 `archive_entry()` 函数中更新元数据的代码块替换为：

```python
    # 提取结构化摘要（如果存在 Section 0）
    summary = None
    try:
        summary = extract_summary_from_md(output_path)
    except Exception:
        pass  # 无摘要时不阻断归档

    # 更新元数据
    entry_meta = {
        "title": title,
        "file": output_file,
        "hash": content_hash,
        "archived_at": datetime.now().isoformat(),
        "source_files": entry["md_files"],
    }
    if summary:
        entry_meta["summary"] = summary

    meta["entries"][entry["name"]] = entry_meta

    is_new = existing is None
    return (title, output_file, is_new)
```

即：原来的 `meta["entries"][entry["name"]] = { ... }` 整块替换为上述代码。

- [ ] **Step 3: 验证修改无语法错误**

```bash
cd ~/.agents/skills/spec-knowledge-archiver/scripts
python -c "import knowledge_archiver; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 提交**

```bash
cd ~/.agents/skills
git add spec-knowledge-archiver/scripts/knowledge_archiver.py
git commit -m "feat: extract summary during archive_entry

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 修改 knowledge_archiver.py — generate_index 改为 5 列

**Files:**
- Modify: `spec-knowledge-archiver/scripts/knowledge_archiver.py`

本任务修改 `generate_index()` 函数，将 index.md 从 3 列（#/标题/归档时间）改为 5 列（#/模块/症状关键词/根因方向/文件）。

- [ ] **Step 1: 替换 generate_index 函数**

将 `generate_index()` 函数整体替换为：

```python
def generate_index(dest_dir, platform, doc_type):
    """生成索引文件（5 列格式，含摘要信息）"""
    meta = load_meta(dest_dir)
    if not meta["entries"]:
        print(f"  无已归档条目，跳过索引生成")
        return

    type_labels = {"bug": "Bug 解决方案", "requirement": "需求解决方案"}
    label = type_labels.get(doc_type, doc_type)

    lines = [
        f"# {label}索引 - {platform}",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}，共 {len(meta['entries'])} 条",
        "",
        "| # | 模块 | 症状关键词 | 根因方向 | 文件 |",
        "|---|------|-----------|---------|------|",
    ]

    for idx, (entry_name, info) in enumerate(sorted(meta["entries"].items(),
                                                     key=lambda x: x[1].get("title", "")), 1):
        title = info["title"]
        file = info["file"]
        summary = info.get("summary", {})

        module = summary.get("module", "-")
        symptoms = ", ".join(summary.get("symptoms", [])) or "-"
        root_cause = summary.get("root_cause", "-")
        # 截断过长的根因描述（index.md 保持可读性）
        if len(root_cause) > 60:
            root_cause = root_cause[:57] + "..."

        lines.append(f"| {idx} | {module} | {symptoms} | {root_cause} | [{title}]({file}) |")

    lines.append("")
    index_path = os.path.join(dest_dir, "index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  索引已生成: {index_path}")
```

- [ ] **Step 2: 验证无语法错误**

```bash
cd ~/.agents/skills/spec-knowledge-archiver/scripts
python -c "import knowledge_archiver; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
cd ~/.agents/skills
git add spec-knowledge-archiver/scripts/knowledge_archiver.py
git commit -m "feat: generate_index with 5-column format including summary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 创建 index-template.md 参考文档

**Files:**
- Create: `spec-knowledge-archiver/references/index-template.md`

- [ ] **Step 1: 创建文件**

```markdown
# 知识库索引模板

知识库索引文件 (`index.md`) 由 `knowledge_archiver.py` 自动生成，格式如下：

## Bug 解决方案索引格式

```markdown
| # | 模块 | 症状关键词 | 根因方向 | 文件 |
|---|------|-----------|---------|------|
| 1 | LWIP/CoAP | memp_malloc fail, 死机, 挂测 | 内存池耗尽，sock_event 未释放 | [标题](file.md) |
| 2 | MQTT | SSL 握手失败, 连接错误 | 证书链不完整 | [标题](file.md) |
```

## 列说明

| 列 | 来源 | 用途 |
|----|------|------|
| **#** | 自动编号 | 排序参考 |
| **模块** | Section 0 → 模块 | Grep 匹配模块名 |
| **症状关键词** | Section 0 → 症状关键词 | Grep 匹配症状 |
| **根因方向** | Section 0 → 根因概述 | 匹配度评估，过长截断 60 字 |
| **文件** | 文件名 + Markdown 链接 | 加载全文 |

## 匹配度评估规则

- **高匹配**：模块 + 症状关键词均匹配
- **中匹配**：仅模块或仅症状匹配
- **无匹配**：均不匹配，跳过

## 检索优先级

```
当前平台 & 高匹配 > 当前平台 & 中匹配 > 其他平台 & 高匹配 > 其他平台 & 中匹配
```
```

- [ ] **Step 2: 提交**

```bash
cd ~/.agents/skills
git add spec-knowledge-archiver/references/index-template.md
git commit -m "docs: add index-template.md reference for 5-column index format

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 更新 spec-knowledge-archiver SKILL.md

**Files:**
- Modify: `spec-knowledge-archiver/SKILL.md`

- [ ] **Step 1: 更新索引描述**

在 SKILL.md 的「归档行为」部分，将：

```markdown
- **索引**：每次归档后自动生成 `index.md`，列出所有条目摘要
```

替换为：

```markdown
- **索引**：每次归档后自动生成 `index.md`（5 列：#/模块/症状关键词/根因方向/文件），列出所有条目摘要，供 bug 分析时 Grep 检索
```

- [ ] **Step 2: 添加摘要提取说明**

在「归档行为」列表末尾追加一项：

```markdown
- **摘要提取**：归档时自动从文档 Section 0（结构化摘要）提取模块、症状、根因等信息到 `.archive_meta.json` 的 `summary` 字段。脚本 `scripts/extract_summary.py` 负责解析，无需 LLM 参与
```

- [ ] **Step 3: 更新元数据描述**

将：

```markdown
- **元数据**：`.archive_meta.json` 记录每条归档的哈希、时间戳、源文件列表
```

替换为：

```markdown
- **元数据**：`.archive_meta.json` 记录每条归档的哈希、时间戳、源文件列表、结构化摘要（`summary` 对象，含 module/symptoms/root_cause/keywords 等字段）
```

- [ ] **Step 4: 提交**

```bash
cd ~/.agents/skills
git add spec-knowledge-archiver/SKILL.md
git commit -m "docs: update archiver SKILL.md with summary extraction docs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: 更新 bug-report-template.md — 添加 Section 0

**Files:**
- Modify: `spec-bug-analyzer/references/bug-report-template.md`

- [ ] **Step 1: 在文件最开头插入 Section 0**

在 `# [问题标题] 原因分析` 之前插入：

```markdown
## 0. 结构化摘要

> 以下信息供知识库检索使用，需完整准确填写。

| 字段 | 内容 |
|------|------|
| **平台** | [如 EC626 / ASR] |
| **模块** | [如 MQTT / LWIP / UART] |
| **问题分类** | [资源耗尽 / 状态机异常 / 参数错误 / 时序竞争 / 内存泄漏 / 协议异常 / 缓冲区溢出 / 超时] |
| **症状关键词** | [3-5 个关键词，逗号分隔，如: memp_malloc fail, 系统死机, 长时间挂测] |
| **根因概述** | [一句话描述根因，如: sock_event_queue 溢出导致 memp 未释放，累积耗尽触发 HardFault] |
| **调用链摘要** | [如: CoAP GET → sock_event_queue → memp_malloc → 耗尽 → HardFault] |
| **检索关键词** | [5-8 个检索词，中英文均可，逗号分隔] |

---

```

- [ ] **Step 2: 更新目录**

将目录部分从：

```markdown
## 目录
- [1. 问题描述](#1-问题描述)
- [2. 根本原因](#2-根本原因)
- [3. 相关文件](#3-相关文件)
```

改为：

```markdown
## 目录
- [0. 结构化摘要](#0-结构化摘要)
- [1. 问题描述](#1-问题描述)
- [2. 根本原因](#2-根本原因)
- [3. 相关文件](#3-相关文件)
```

- [ ] **Step 3: 提交**

```bash
cd ~/.agents/skills
git add spec-bug-analyzer/references/bug-report-template.md
git commit -m "feat: add Section 0 structured summary to bug report template

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: 更新 spec-bug-analyzer SKILL.md — 添加 Step 2.5 + 手动查询

**Files:**
- Modify: `spec-bug-analyzer/SKILL.md`

这是最大的改动。分 4 个子步骤。

- [ ] **Step 1: 在 Step 2 和 Step 3 之间插入 Step 2.5**

在 `### Step 3：对比分析（仅正常+异常两组日志时）` 之前插入：

```markdown
### Step 2.5：知识库检索

从 Step 2 分析结果中提取检索线索，搜索知识库历史案例。

**提取检索线索**：
- 涉及模块（如 MQTT, LWIP, UART, CoAP）
- 错误关键字（如 memp_malloc fail, ASSERT, timeout, ERROR）
- 异常现象（如死机, 连接失败, 内存泄漏, 断连）

**检索流程**：

1. **确定当前平台**：从日志特征或用户说明判断平台（如 EC626、ASR）
2. **优先搜索当前平台**索引：
   ```
   ~/.agents/knowledge/platform/{当前平台}/bug-solutions/index.md
   ```
   使用 Grep 搜索模块名和症状关键词。
3. **当前平台无高匹配时**，扩展搜索其他平台：
   ```
   ~/.agents/knowledge/platform/*/bug-solutions/index.md
   ```
4. **评估匹配度**：
   - 模块 + 症状双重匹配 → 高相关
   - 仅模块或仅症状匹配 → 中相关
   - 无匹配 → 跳过
5. **结果处理**：
   - 高相关案例 → Read 加载全文，注入 Step 4 分析上下文
   - 中相关案例 → 展示摘要（模块/症状/根因方向）供参考
   - 无匹配 → 正常继续分析

**检索排序**：当前平台 & 高匹配 > 当前平台 & 中匹配 > 其他平台 & 高匹配 > 其他平台 & 中匹配

**无知识库时**：如果知识库路径不存在或 index.md 为空，跳过此步骤，不影响后续分析。
```

- [ ] **Step 2: 修改 Step 4 根因定位**

将 Step 4 从：

```markdown
### Step 4：根因定位

沿调用链向上追溯：从错误表现位置开始，逐层追问"谁调用了这个？传入了什么？"，直到找到原始触发点。常见问题模式参见 `references/analysis-patterns.md` §5。
```

替换为：

```markdown
### Step 4：根因定位

沿调用链向上追溯：从错误表现位置开始，逐层追问"谁调用了这个？传入了什么？"，直到找到原始触发点。

**参考来源（按优先级）**：
1. `references/analysis-patterns.md` §5 的通用问题模式
2. Step 2.5 匹配到的历史案例（如有）：
   - 将历史案例的根因分析、调用链、修复方案作为参考
   - 明确标注「参考历史案例：[案例标题]」
   - 如果历史案例根因与当前一致，直接引用并验证
   - 如果不一致，对比差异，可能发现新的故障模式
```

- [ ] **Step 3: 修改 Step 6 报告生成部分**

在 Step 6 的「使用模板：`references/bug-report-template.md`」之后追加：

```markdown

**结构化摘要**：报告必须包含 Section 0（结构化摘要），填写平台、模块、问题分类、症状关键词、根因概述、调用链摘要、检索关键词。此摘要是知识库检索的数据来源，归档时由脚本自动提取。
```

- [ ] **Step 4: 在文件末尾「参考文档」列表之前插入手动查询模式**

在 `## 参考文档` 之前插入：

```markdown
## 手动查询模式

不进入完整分析流程，直接查询知识库历史案例。

**触发方式**：用户说「查询类似的 LWIP 问题」/「有没有 CoAP 死机的案例」/「知识库搜索 xxx」/「查历史 bug」。

**处理流程**：

1. 解析用户查询中的关键词和模块名
2. 优先搜索当前项目对应平台的 index.md：
   ```
   ~/.agents/knowledge/platform/{当前平台}/bug-solutions/index.md
   ```
3. 当前平台无结果时，扩展到其他平台
4. 展示匹配结果列表（标题 + 模块 + 症状 + 根因方向）
5. 用户选择某个案例 → Read 加载全文展示

**无匹配时**：告知用户知识库中无相关案例，建议用完整分析流程（spec 分析bug）进行诊断。
```

- [ ] **Step 5: 提交**

```bash
cd ~/.agents/skills
git add spec-bug-analyzer/SKILL.md
git commit -m "feat: add Step 2.5 knowledge retrieval, enhance Step 4/6, add manual query mode

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: 为现有 20 篇 EC626 案例补充 Section 0 摘要

**Files:**
- Modify: `knowledge/platform/EC626/bug-solutions/*.md`（20 个文件）

这是数据迁移任务。每个文件需要在第一个 `##` 标题之前插入 Section 0 结构化摘要。摘要内容需要根据每个文件的实际内容提取。

- [ ] **Step 1: 确认文件列表**

```bash
ls ~/.agents/knowledge/platform/EC626/bug-solutions/*.md | grep -v index.md | sort
```

Expected: 20 个 .md 文件

- [ ] **Step 2: 逐个文件读取并生成摘要**

对每个文件执行：
1. Read 文件内容
2. 从内容中提取：平台（均为 EC626）、模块、问题分类、症状关键词、根因概述、调用链摘要、检索关键词
3. 构造 Section 0 Markdown 表格
4. 用 Edit 在文件第一个 `## ` 标题之前插入 Section 0

**Section 0 插入模板**（每个文件需要根据内容填充）：

```markdown
## 0. 结构化摘要

> 以下信息供知识库检索使用，需完整准确填写。

| 字段 | 内容 |
|------|------|
| **平台** | EC626 |
| **模块** | [从内容提取] |
| **问题分类** | [从内容提取] |
| **症状关键词** | [从内容提取，3-5个] |
| **根因概述** | [从内容提取，一句话] |
| **调用链摘要** | [从内容提取] |
| **检索关键词** | [从内容提取，5-8个] |

---

```

**处理顺序**（按文件名排序）：
1. `COAP协议持续GET操作时模组死机.md`
2. `长期挂测挂测900多次出现死机.md`
3. `TCP连接后xiic0去激活概率性死机.md`
4. `UDP链路未关闭.md`
5. `AT_CTM2MREG定时器未停止.md`
6. `CeuTask_ASSERT_PsifSuspendInd.md`
7. `CoAPOPTION返回ERROR.md`
8. `DNSSERVER无效地址校验缺失.md`
9. `DNSSERVER设置dns2实际写入dns1.md`
10. `LWM2MCREATE_AT命令ERROR.md`
11. `LWM2M加密连接REGISTER TIMEOUT.md`
12. `MQTT_SSL双向认证内存分配崩溃.md`
13. `MQTT_SSL双向认证连接失败.md`
14. `MQTT_SSL连接成功但MQTTConnect失败.md`
15. `NWBLEPSTR返回ERROR.md`
16. `TCP_RECVMODE0_收不到数据断连.md`
17. `TCP连接XIIC0去激活死机.md`
18. `UART_RX_FIFO超时pending节点溢出.md`
19. `UDP连接PSM模式.md`
20. `ipv6_udp_ppp_crash.md`

> **注意**：此步骤建议使用 subagent 并行处理多个文件。每个 subagent 读取一个文件、提取摘要、插入 Section 0。

- [ ] **Step 3: 提交**

```bash
cd ~/.agents/skills
git add knowledge/platform/EC626/bug-solutions/
git commit -m "data: add Section 0 structured summaries to 20 existing EC626 cases

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: 重新归档更新索引和元数据

**Files:**
- Modify: `knowledge/platform/EC626/bug-solutions/index.md`（由脚本重建）
- Modify: `knowledge/platform/EC626/bug-solutions/.archive_meta.json`（由脚本重建）

- [ ] **Step 1: 验证 extract_summary.py 可以从已有文件提取摘要**

随机测试一个文件：

```bash
cd ~/.agents/skills/spec-knowledge-archiver/scripts
python extract_summary.py ~/.agents/knowledge/platform/EC626/bug-solutions/UDP链路未关闭.md
```

Expected: JSON 输出含 platform, module, symptoms 等字段

- [ ] **Step 2: 运行增量归档重建索引**

由于所有文件内容已变更（新增 Section 0），增量归档会检测到哈希变化：

```bash
cd ~/.agents/skills/spec-knowledge-archiver/scripts
python knowledge_archiver.py archive --project D:/EC626 --type bug --incremental
```

> 注意：`--project` 路径需指向实际的 EC626 项目路径。如果项目路径不在本地，可手动触发索引生成：
> ```bash
> python knowledge_archiver.py index --platform EC626 --type bug
> ```

- [ ] **Step 3: 验证 index.md 为 5 列格式**

```bash
head -10 ~/.agents/knowledge/platform/EC626/bug-solutions/index.md
```

Expected: 表头为 `| # | 模块 | 症状关键词 | 根因方向 | 文件 |`

- [ ] **Step 4: 验证 .archive_meta.json 包含 summary**

```bash
python -c "import json; m=json.load(open('$HOME/.agents/knowledge/platform/EC626/bug-solutions/.archive_meta.json')); e=list(m['entries'].values())[0]; print('summary' in e, e.get('summary',{}).get('module',''))"
```

Expected: `True <模块名>`

- [ ] **Step 5: 提交**

```bash
cd ~/.agents/skills
git add knowledge/platform/EC626/bug-solutions/index.md knowledge/platform/EC626/bug-solutions/.archive_meta.json
git commit -m "data: rebuild EC626 index and metadata with 5-column format and summaries

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ Section 3.1 (摘要结构定义) → Task 7 (template) + Task 9 (data migration)
- ✅ Section 3.2 (index.md 5列) → Task 4 (generate_index)
- ✅ Section 3.3 (archive_meta summary) → Task 3 (archive_entry)
- ✅ Section 4 (archiver改造) → Task 1-6
- ✅ Section 5.1 (7步工作流) → Task 8
- ✅ Section 5.2 (Step 2.5检索) → Task 8 Step 1
- ✅ Section 5.3 (Step 4增强) → Task 8 Step 2
- ✅ Section 5.4 (Step 6增强) → Task 8 Step 3
- ✅ Section 5.5 (手动查询) → Task 8 Step 4
- ✅ Section 6 (平台优先级) → Task 8 Step 1
- ✅ Section 4.4 (现有数据迁移) → Task 9-10

**2. Placeholder scan:** 无 TBD/TODO/待定。Task 9 的摘要内容需要根据文件内容动态生成，已在步骤中明确说明提取规则和模板。

**3. Type consistency:**
- extract_summary.py 返回的 dict key 名称（platform/module/bug_type/symptoms/root_cause/call_chain_summary/keywords）与 archive_meta.json summary 对象字段名一致
- generate_index() 读取的 summary 字段名与 extract_summary 输出一致
- bug-report-template.md 的字段中文名与 FIELD_MAP 映射一致
