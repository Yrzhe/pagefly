# PageFly - Personal Knowledge Data Platform

> 初始想法记录 | 2026-04-05

## 灵感来源

### Karpathy 的 LMWiki 概念

Andrej Karpathy 提出的 LLM Knowledge Base 模式：
- **原始数据层**：将文章、论文、仓库等索引到 `raw/` 目录
- **Wiki 编译层**：LLM 增量"编译"出结构化的 `.md` 文件集合（摘要、反向链接、概念文章）
- **前端层**：用 Obsidian 查看 wiki、可视化数据
- **核心理念**：知识飞轮 -- 你从不手写 wiki，LLM 拥有它；查询结果回填到 wiki，知识越用越厚
- **操作**：Ingest（入库）、Query（查询）、Lint（健康检查）

来源：https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

### farzaa 的 Personal Knowledge Wiki Skill

一个 Claude Skill 实现，将个人数据编译成知识 wiki：
- 命令体系：`/wiki ingest`、`/wiki absorb`、`/wiki query`、`/wiki cleanup`、`/wiki breakdown`
- 目录结构自然涌现：`people/`、`projects/`、`places/`、`philosophies/` 等
- LLM 是"作者"而非"文件员"，写百科式文章
- 支持多数据源：Day One、Apple Notes、Obsidian、Notion、iMessage、CSV、邮件、Twitter

来源：https://gist.github.com/farzaa/c35ac0cfbeb957788650e36aabea836d

---

## 我的构想：数据中台

在上述灵感基础上，构建一个更完整的**个人知识数据中台**，部署在 VPS 的 Docker 中，使用 Claude Agent SDK 驱动。

### 核心原则

1. **只增不删** -- Agent 永远没有删除权限，只能：创建文件、移动文件、更新 metadata
2. **原文保留** -- 用户的原始内容（转为 Markdown 后）始终保留原文，不被 Agent 改写
3. **三层文件结构** -- raw/ -> knowledge/ -> wiki/，职责清晰分离
4. **数据库追踪** -- 每篇文章的当前位置、metadata、操作日志全部记录在数据库中

### 架构概览

```
外部输入（Telegram / API / 文件上传）
    |
    v
+------------------------------------------------------------------+
|                      Docker Container                             |
|                                                                   |
|  +--------------+   +------------------+   +------------------+  |
|  |  Ingest      |   |  Governance      |   |  Output          |  |
|  |  Pipeline    |   |  Agent           |   |  Agent           |  |
|  |              |   |  (定时触发)       |   |  (查询+回顾)      |  |
|  +------+-------+   +--------+---------+   +--------+---------+  |
|         |                    |                       |            |
|         v                    v                       v            |
|  +--------------------------------------------------------------+|
|  |                   文件系统 (Docker Volume)                     ||
|  |                                                               ||
|  |  data/                                                        ||
|  |  +-- raw/           <-- Ingest 写入（暂存区）                  ||
|  |  +-- knowledge/     <-- Governance 从 raw/ 移入（分类库）      ||
|  |  +-- wiki/          <-- Governance 编译生成（知识库）           ||
|  |                                                               ||
|  +--------------------------------------------------------------+|
|         |                                                         |
|         v                                                         |
|  +------------------------+                                       |
|  |  PostgreSQL / SQLite   |  <-- 文章位置、metadata、操作日志     |
|  +------------------------+                                       |
|                                                                   |
+----------+--------------------------------------+-----------------+
           |                                      |
     +-----v------+                       +-------v--------+
     |  Telegram   |                       |  REST API      |
     |  Bot        |                       |  接口           |
     |  (输入+输出) |                       |  (输入+输出)    |
     +------------+                       +----------------+
```

### 三层文件结构详解

```
data/
+-- raw/                    # 暂存区：Ingest Pipeline 写入
|   +-- 2026-04-05_abc123.md
|   +-- ...
|
+-- knowledge/              # 分类库：Governance Agent 从 raw/ 移入
|   +-- people/             #   原文保留，metadata 增强
|   +-- projects/
|   +-- research/
|   +-- finance/
|   +-- tech/
|   +-- ...                 #   目录按需自然涌现
|
+-- wiki/                   # 知识库：Governance Agent 基于 knowledge/ 编译生成
    +-- index.md            #   总索引
    +-- summaries/          #   摘要文章
    +-- concepts/           #   概念文章
    +-- connections/        #   关联分析
    +-- reviews/            #   每日/每周/每月回顾
    +-- ...
```

**文件流转方向：**
- `raw/` -> `knowledge/`：**移动**（文件从 raw/ 消失，出现在 knowledge/ 对应子目录）
- `knowledge/` -> `wiki/`：**编译生成**（knowledge/ 原文不动，wiki/ 新增 Agent 写的文章）

### 1. 输入层 (Ingest Pipeline)

**接收端口：**
- Telegram Bot（发文件、发语音、发文字）
- REST API（程序化接入）
- 文件上传接口

**支持格式：**
- 文本文件（.txt, .md）
- PDF 文档
- Word 文档（.docx）
- 图片（OCR 提取文字）
- 语音（STT 转文字）
- 网页内容（URL -> Markdown）

**处理流程：**
1. 接收原始文件
2. 格式转换 -> 统一转为 Markdown
3. 在 Markdown 头部插入 YAML metadata：
   ```yaml
   ---
   id: uuid
   title: 文档标题
   source_type: pdf | voice | image | text | url
   original_filename: xxx.pdf
   ingested_at: 2026-04-05T20:30:00Z
   tags: []
   status: raw
   location: raw/
   ---
   ```
4. 存入 `raw/` 文件夹
5. 记录到数据库（documents 表 + ingest_log 表）

### 2. 治理层 (Governance Agent)

**定时触发，职责：**

**Step 1 -- 整理（raw/ -> knowledge/）：**
- 扫描 `raw/` 中的新文件
- 分析内容，确定分类
- 移动文件到 `knowledge/` 对应子目录
- 更新文件 metadata 中的 `status: classified`、`location`
- 更新数据库中的文件路径

**Step 2 -- 编译（knowledge/ -> wiki/）：**
- 分析 knowledge/ 中的内容
- 生成/更新摘要文章、概念文章
- 建立反向链接和关联索引
- 新生成的文章写入 `wiki/`
- 维护 `wiki/index.md` 总索引

**Step 3 -- 日志：**
- 每次操作写入数据库 operations_log 表
- 记录：操作类型、源路径、目标路径、时间戳

### 3. 输出层 (Output Agent)

**定期回顾：**
- 每日回顾（Daily Review）：当天新增内容摘要 + 发现
- 每周回顾（Weekly Review）：本周趋势 + 知识图谱变化
- 每月回顾（Monthly Review）：月度洞察 + 知识体系演进
- 回顾文章存入 `wiki/reviews/`

**交互查询：**
- 通过 Telegram Bot 直接问问题
- 通过 REST API 程序化查询
- Agent 在 knowledge/ 和 wiki/ 中搜索，综合回答
- 返回格式：Markdown 文本、结构化 JSON

**主动推送：**
- 发现有价值的关联和趋势时主动通知
- 定时推送回顾报告到 Telegram

### 数据库设计（初步）

```sql
-- 文档表：追踪每篇文章的位置和状态
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  title TEXT,
  source_type TEXT,          -- pdf, voice, image, text, url
  original_filename TEXT,
  current_path TEXT,         -- 当前文件路径（raw/、knowledge/、wiki/）
  status TEXT,               -- raw, classified, compiled
  tags TEXT[],
  ingested_at TIMESTAMP,
  classified_at TIMESTAMP,
  metadata JSONB
);

-- 操作日志表：记录所有文件操作
CREATE TABLE operations_log (
  id SERIAL PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  operation TEXT,            -- ingest, move, classify, compile, update_metadata
  from_path TEXT,
  to_path TEXT,
  details JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

-- wiki 文章表：追踪 Agent 生成的文章
CREATE TABLE wiki_articles (
  id UUID PRIMARY KEY,
  title TEXT,
  article_type TEXT,         -- summary, concept, connection, review
  file_path TEXT,
  source_document_ids UUID[],  -- 基于哪些 knowledge 文章生成
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

---

## LLM 调用层级

不同模块需要不同层级的 LLM 能力：

| 模块 | 层级 | 实现方式 | 模型 | 说明 |
|------|------|----------|------|------|
| **分类器** (classifier) | Single LLM call | Claude API + 结构化输出 | Haiku 4.5 | 一次调用返回分类结果，便宜快速 |
| **Metadata 填充** | Single LLM call | Claude API + 结构化输出 | Haiku 4.5 | 提取标题、描述、标签 |
| **编译器** (compiler) | Agent | Claude Agent SDK | Opus 4.6 | 需要读多个文件、分析关联、生成文章 |
| **查询** (query) | Agent | Claude Agent SDK | Opus 4.6 | 需要搜索文件、综合回答 |
| **回顾生成** (review) | Agent | Claude Agent SDK | Opus 4.6 | 需要读取多天内容、生成洞察 |

### 分类器：简单 API 调用

```python
# classifier.py — 不需要 Agent，一次 API 调用即可
response = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=1024,
    system="你是 PageFly 文档分类器。根据提供的分类列表对文档分类。",
    messages=[{
        "role": "user",
        "content": f"分类列表：{categories_json}\n\n文档内容（前2000字）：\n{content[:2000]}"
    }],
    output_config={
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "subcategory": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "required": ["category", "title", "description", "tags", "confidence"],
                "additionalProperties": False
            }
        }
    }
)
```

### 编译器：Agent SDK

```python
# compiler.py — 需要 Agent，因为要读写多个文件、做复杂分析
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

async for message in query(
    prompt="扫描 knowledge/ 目录，编译新增内容到 wiki/",
    options=ClaudeAgentOptions(
        cwd="/data",
        allowed_tools=["Read", "Write", "Glob", "Grep"],
        system_prompt=open("skills/compiler_system.md").read(),
        agents={
            "summarizer": AgentDefinition(
                description="生成文章摘要",
                prompt="读取指定文档，生成结构化摘要",
                tools=["Read", "Write"]
            ),
            "linker": AgentDefinition(
                description="分析文章关联，生成反向链接",
                prompt="分析文档间的关联关系",
                tools=["Read", "Write", "Glob", "Grep"]
            )
        },
        # 自定义工具通过 MCP（如数据库操作）
        mcp_servers={
            "pagefly-db": {
                "command": "python",
                "args": ["src/mcp/db_server.py"]
            }
        }
    )
):
    ...
```

### Skill 管理

Agent 的行为通过标准 Skill 文件夹控制，每个 Skill 是一个独立文件夹，内含 `SKILL.md`：

```
config/
+-- categories.json              # 分类定义
+-- schedules.json               # 定时任务配置
+-- skills/                      # Skill 文件夹集合
    +-- compiler/                #   编译器 Skill
    |   +-- SKILL.md
    |   +-- references/          #   可选：参考资料
    +-- query/                   #   查询 Skill
    |   +-- SKILL.md
    +-- review/                  #   回顾生成 Skill
    |   +-- SKILL.md
    +-- summarizer/              #   摘要子 Agent Skill
    |   +-- SKILL.md
    +-- linker/                  #   关联分析子 Agent Skill
        +-- SKILL.md
```

**SKILL.md 格式规范：**

```yaml
---
name: compiler
description: "扫描 knowledge/ 目录，分析新增内容，生成摘要和概念文章到 wiki/。定时触发。"
---

# Compiler Agent

## 角色
你是 PageFly 的知识编译器...

## 约束
- 不可删除任何文件
- 不可修改 knowledge/ 中的原文内容
- 只能在 wiki/ 中创建和更新文章
...
```

每个 Skill 文件夹是独立的，可以随时添加、编辑、移除，不需要改代码。

---

## 技术选型（初步）

| 组件 | 选型 | 说明 |
|------|------|------|
| 运行环境 | Docker on VPS | 容器化部署 |
| Agent 框架 | Claude Agent SDK (Python) | 编译/查询/回顾 Agent |
| LLM API（简单调用）| Anthropic Claude API | 分类、metadata 填充 |
| 分类模型 | Claude Haiku 4.5 | 便宜快速，分类足够 |
| Agent 模型 | Claude Opus 4.6 | 编译/查询/回顾需要深度推理 |
| 数据库 | PostgreSQL / SQLite | 日志和元数据 |
| 文件存储 | 本地文件系统（Docker Volume） | Markdown 文件 |
| STT（语音转文字） | GPT-4o Transcribe (OpenAI API) | 语音输入 |
| OCR | Mistral OCR | 图片/PDF 文字提取 |
| PDF 处理 | Mistral OCR（自有脚本） | PDF 转 Markdown |
| Telegram | Telegram Bot API | 输入输出 + 控制台 |
| REST API | FastAPI (Python) | 对外接口 |
| MCP Server | 自建（Python） | Agent 的数据库工具 |

---

## 开发优先级

### Phase 1：基建层
- [ ] Docker 基础环境搭建
- [ ] 文件系统结构设计（data/raw, data/knowledge, data/wiki）
- [ ] 数据库 schema 设计与初始化
- [ ] REST API 基础框架
- [ ] Telegram Bot 基础接入

### Phase 2：输入管道
- [ ] 文本文件直接入库（.txt, .md）
- [ ] PDF -> Markdown 转换
- [ ] 图片 OCR -> Markdown
- [ ] 语音 STT -> Markdown
- [ ] Word -> Markdown
- [ ] URL -> Markdown（网页抓取）
- [ ] YAML metadata 自动注入 + 格式校验

### Phase 3：治理 Agent
- [ ] 定时扫描 raw/ 新文件
- [ ] 自动分类 + 移动到 knowledge/
- [ ] 索引维护（wiki/index.md）
- [ ] 摘要/概念文章编译到 wiki/
- [ ] 反向链接
- [ ] 操作日志记录

### Phase 4：输出能力
- [ ] 查询接口（API + Telegram）
- [ ] 每日/每周/每月回顾生成
- [ ] 趋势发现和主动推送

---

## 与 Karpathy LMWiki 的区别

| 维度 | LMWiki | PageFly |
|------|--------|--------------|
| 部署方式 | 本地 + Obsidian | VPS Docker 容器 |
| 交互方式 | CLI / Obsidian | Telegram + REST API |
| 输入源 | 主要是文档和网页 | 多模态（语音、图片、PDF、文件） |
| Agent | 手动触发 | 自动化定时 Agent |
| 数据库 | 纯文件系统 | 文件系统 + 关系型数据库 |
| 可访问性 | 仅本地 | 随时随地（手机/API） |
| 文件结构 | raw/ + wiki/ 两层 | raw/ + knowledge/ + wiki/ 三层 |
| 治理 | Lint 健康检查 | 完整的数据治理流程 |

---

## 命名

项目名：**PageFly**
含义：让知识页面真正"飞"起来 -- 自动化的知识编译、流转和输出。

---

## 模块化架构

整个系统由以下独立模块组成，每个模块职责单一、可独立开发和测试：

```
pagefly/
+-- src/
|   +-- channels/              # 通道层：外部接入
|   |   +-- telegram.ts        #   Telegram Bot（输入+输出）
|   |   +-- api.ts             #   REST API 路由（输入+输出）
|   |
|   +-- ingest/                # 输入管道：格式转换
|   |   +-- pipeline.ts        #   统一入口，调度到具体 converter
|   |   +-- converters/        #   每种格式一个独立模块
|   |   |   +-- text.ts        #     .txt / .md 直传
|   |   |   +-- pdf.ts         #     PDF -> Markdown
|   |   |   +-- docx.ts        #     Word -> Markdown
|   |   |   +-- image.ts       #     图片 OCR -> Markdown
|   |   |   +-- voice.ts       #     语音 STT -> Markdown
|   |   |   +-- url.ts         #     网页抓取 -> Markdown
|   |   |   +-- book.ts        #     电子书（epub等）-> Markdown
|   |   +-- metadata.ts        #   YAML metadata 注入 + 校验
|   |
|   +-- governance/            # 治理层：Agent 逻辑
|   |   +-- scheduler.ts       #   定时任务调度
|   |   +-- classifier.ts      #   内容分类（LLM 驱动）
|   |   +-- organizer.ts       #   文件整理（raw/ -> knowledge/）
|   |   +-- compiler.ts        #   知识编译（knowledge/ -> wiki/）
|   |   +-- indexer.ts         #   索引维护
|   |   +-- linker.ts          #   反向链接生成
|   |
|   +-- output/                # 输出层：查询和回顾
|   |   +-- query.ts           #   查询处理（搜索 + LLM 综合回答）
|   |   +-- review.ts          #   定期回顾生成（daily/weekly/monthly）
|   |   +-- notifier.ts        #   主动推送
|   |
|   +-- storage/               # 存储层：文件和数据库操作
|   |   +-- files.ts           #   文件系统操作（创建、移动、读取，禁止删除）
|   |   +-- db.ts              #   数据库连接和操作
|   |   +-- models.ts          #   数据模型定义
|   |
|   +-- shared/                # 共享工具
|       +-- types.ts           #   类型定义
|       +-- config.ts          #   配置管理（环境变量）
|       +-- logger.ts          #   日志
|
+-- data/                      # Docker Volume 挂载
|   +-- raw/
|   +-- knowledge/
|   +-- wiki/
|
+-- docker-compose.yml
+-- Dockerfile
+-- .env.example
```

### 各模块说明

#### 1. channels/ -- 通道层

负责与外部世界的连接，是所有输入输出的入口/出口。

| 模块 | 输入 | 输出 |
|------|------|------|
| telegram.ts | 接收文件/文字/语音消息 -> 调用 ingest pipeline | 回复查询结果、推送回顾 |
| api.ts | POST /ingest 上传文件 | GET /query 查询、GET /review 回顾 |

**设计原则：** 通道层只做协议转换（Telegram 消息 -> 统一格式、HTTP 请求 -> 统一格式），不含业务逻辑。新增通道（如 Discord、邮件）只需加一个文件。

#### 2. ingest/ -- 输入管道

每种格式一个 converter 模块，统一接口：

```typescript
interface Converter {
  // 判断是否能处理此文件
  canHandle(input: IngestInput): boolean
  // 转换为 Markdown
  convert(input: IngestInput): Promise<ConvertResult>
}

interface IngestInput {
  type: 'file' | 'url' | 'text'
  mimeType?: string
  filePath?: string       // 临时文件路径
  url?: string
  text?: string
  originalFilename?: string
}

interface ConvertResult {
  markdown: string         // 转换后的 Markdown 内容
  title: string            // 提取的标题
  suggestedTags?: string[] // 建议标签
}
```

**pipeline.ts** 的逻辑很简单：遍历所有 converter，找到能处理的，调用转换，注入 metadata，写入 raw/。

**新增格式只需：** 实现 Converter 接口，注册到 pipeline。

#### 3. governance/ -- 治理层

| 模块 | 触发方式 | 职责 |
|------|----------|------|
| scheduler.ts | cron 定时 | 调度治理任务 |
| classifier.ts | 被 organizer 调用 | LLM 分析内容，返回分类和标签 |
| organizer.ts | 定时触发 | 扫描 raw/，分类，移动到 knowledge/ |
| compiler.ts | 定时触发 | 读取 knowledge/，生成/更新 wiki/ 文章 |
| indexer.ts | 被 compiler 调用 | 维护 wiki/index.md |
| linker.ts | 被 compiler 调用 | 计算反向链接 |

#### 4. output/ -- 输出层

| 模块 | 触发方式 | 职责 |
|------|----------|------|
| query.ts | API/Telegram 请求 | 在 knowledge/ + wiki/ 搜索，LLM 综合回答 |
| review.ts | cron 定时 | 生成每日/每周/每月回顾，写入 wiki/reviews/ |
| notifier.ts | 被 review 或 governance 调用 | 通过 Telegram 推送通知 |

#### 5. storage/ -- 存储层

**files.ts 的权限控制：**
```typescript
// 允许的操作
createFile(path, content): Promise<void>
moveFile(from, to): Promise<void>
readFile(path): Promise<string>
updateFileMetadata(path, metadata): Promise<void>
listFiles(dir): Promise<string[]>

// 禁止的操作 -- 不暴露 delete 方法
// deleteFile() -- 不存在
```

### 模块间依赖关系

```
channels (telegram, api)
    |
    +---> ingest/pipeline ---> ingest/converters/* ---> storage/files
    |                      +-> ingest/metadata        +-> storage/db
    |
    +---> output/query ------> storage/files + storage/db
    |
    +---> output/review (也可由 scheduler 触发)

governance/scheduler
    |
    +---> governance/organizer ---> governance/classifier (LLM)
    |                           +-> storage/files + storage/db
    |
    +---> governance/compiler ---> governance/indexer
    |                          +-> governance/linker
    |                          +-> storage/files + storage/db
    |
    +---> output/review
    +---> output/notifier
```

---

## Converter 方案

| 格式 | 方案 | API/工具 |
|------|------|----------|
| 语音 | GPT-4o Transcribe | OpenAI API |
| PDF | Mistral OCR | 自有脚本 |
| 图片 | LLM Vision 直接识别 | Claude/GPT-4o Vision |
| Word | 库转换 | mammoth 等 |
| 文本 | 直传 | .txt/.md 无需转换 |
| URL | 网页抓取 | firecrawl / readability |
| 电子书 | epub 解析 | 待定 |

---

## Metadata 设计

### YAML Frontmatter 规范

每个 Markdown 文件顶部必须包含 YAML frontmatter，由脚本自动注入，不经过 LLM。

**阶段 1 -- Ingest 时（脚本自动填写）：**

```yaml
---
id: 550e8400-e29b-41d4-a716-446655440000
title: ""                                     # 暂空，Governance Agent 后续填写
description: ""                               # 暂空，Governance Agent 后续填写
source_type: pdf                              # pdf | voice | image | text | url | docx
original_filename: report.pdf
ingested_at: 2026-04-05T20:30:00+08:00        # ISO 8601 带时区，脚本生成
status: raw                                   # raw -> classified -> reviewed
location: raw/                                # 当前文件位置
tags: []                                      # 暂空，Governance Agent 后续填写
---
```

**阶段 2 -- Governance Agent 整理后：**

```yaml
---
id: 550e8400-e29b-41d4-a716-446655440000
title: "2026年Q1半导体行业分析报告"
description: "覆盖功率半导体、SiC、GaN等细分领域的市场趋势和竞争格局分析"
source_type: pdf
original_filename: report.pdf
ingested_at: 2026-04-05T20:30:00+08:00
classified_at: 2026-04-05T21:00:00+08:00      # 新增：分类时间
status: classified
location: knowledge/research/半导体/
tags: [半导体, 功率半导体, 行业分析]
category: research
subcategory: 半导体
related: []                                    # 关联文档（后续 linker 填写）
---
```

### 时间格式校验

强制 ISO 8601 格式，脚本层面校验：

```python
from datetime import datetime, timezone

def validate_datetime(dt_str: str) -> bool:
    try:
        datetime.fromisoformat(dt_str)
        return True
    except ValueError:
        return False

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()
```

### Metadata 注入脚本

```python
import uuid, yaml

def inject_metadata(markdown_content: str, source_type: str,
                    original_filename: str) -> str:
    metadata = {
        'id': str(uuid.uuid4()),
        'title': '',
        'description': '',
        'source_type': source_type,
        'original_filename': original_filename,
        'ingested_at': now_iso(),
        'status': 'raw',
        'location': 'raw/',
        'tags': [],
    }
    frontmatter = '---\n' + yaml.dump(
        metadata, allow_unicode=True, default_flow_style=False
    ) + '---\n\n'
    return frontmatter + markdown_content
```

### 文件不可变原则

- 文件内容入库后**不可修改**（metadata 更新除外）
- 地址变化：一般只变一次（raw/ -> knowledge/xxx/）
- 所有地址变化必须同步更新：文件 frontmatter 的 location 字段 + 数据库记录
- 用户可通过前端手动移动文件，同样触发数据库更新

---

## Governance 分类策略

### 分类体系：预设骨架 + 受控涌现

分类定义存储在外部 JSON 文件 `config/categories.json` 中，不硬编码。
LLM 返回的 category/subcategory 必须在此 JSON 文件中存在，否则强制重新生成。

**config/categories.json：**

```json
{
  "categories": [
    {
      "id": "research",
      "name": "研究",
      "subcategories": ["半导体", "AI", "量化", "宏观经济"]
    },
    {
      "id": "tech",
      "name": "技术",
      "subcategories": ["前端", "后端", "AI工程", "DevOps", "工具"]
    },
    {
      "id": "finance",
      "name": "财经",
      "subcategories": ["A股", "美股", "加密货币", "投资策略"]
    },
    {
      "id": "people",
      "name": "人物",
      "subcategories": []
    },
    {
      "id": "projects",
      "name": "项目",
      "subcategories": []
    },
    {
      "id": "ideas",
      "name": "想法",
      "subcategories": []
    },
    {
      "id": "notes",
      "name": "笔记",
      "subcategories": []
    },
    {
      "id": "misc",
      "name": "未分类",
      "subcategories": []
    }
  ]
}
```

**维护方式：**
- 你随时可以手动编辑此 JSON 文件，添加/修改分类
- Agent 不会自动修改此文件
- Agent 想建议新分类时 -> 通过 Telegram 通知你，你决定是否加入 JSON

### 分类决策流程

```
Governance Agent 定时扫描 raw/ 新文件
    |
    v
读取文件 metadata + 内容摘要（前 2000 字）
    |
    v
加载 config/categories.json
    |
    v
调用 LLM，prompt 中包含完整 category 列表：
"请从以下分类中选择最匹配的：[categories JSON]"
    |
    v
LLM 返回结构化 JSON：
{
  "category": "research",
  "subcategory": "半导体",
  "title": "2026年Q1半导体行业分析",
  "description": "覆盖功率半导体...",
  "tags": ["半导体", "功率半导体"],
  "confidence": 0.92,
  "reasoning": "文档主要讨论了..."
}
    |
    v
校验：category 和 subcategory 是否在 JSON 文件中？
    |
    +-- 不在 --> 重新调用 LLM（最多 3 次），仍失败则归入 misc
    |
    +-- 在 --> confidence >= 0.8？
               |
               +-- YES --> 自动移动到 knowledge/{category}/{subcategory}/
               |           更新 metadata（title, description, tags, status, location）
               |           更新数据库
               |           写入操作日志
               |
               +-- NO  --> 移动到 knowledge/misc/
                           标记 status: needs_review
                           Telegram 通知用户审核
```

### Telegram 审核流程

当文件 confidence 不足，用户收到 Telegram 消息：

```
📄 新文件待审核

文件：2026-04-05_abc123.md
标题（LLM建议）：xxx技术分析
建议分类：research/AI
置信度：0.65
摘要：本文讨论了...

请选择操作：
[✅ 确认分类] [📂 选择其他分类] [📌 留在misc]
```

- **确认分类** -> Agent 将文件从 misc/ 移到建议的分类目录，更新 metadata + DB
- **选择其他分类** -> 展示 category 列表（从 JSON 读取），用户选择后移动
- **留在 misc** -> 文件保留在 misc/，status 改为 reviewed（已审阅，有意留在此处）

### 定时策略

| 任务 | 频率 | 可配置 |
|------|------|--------|
| 扫描 raw/ 新文件 + 分类 | 每 30 分钟 | 是（config） |
| 编译 wiki/ | 每天 1 次（凌晨） | 是 |
| 每日回顾 | 每天 22:00 | 是 |
| 每周回顾 | 每周日 22:00 | 是 |
| 每月回顾 | 每月 1 日 22:00 | 是 |

所有定时频率存储在 config/ 中，可调整。

---

## 数据库追踪

### 文件生命周期追踪

每个文件的完整生命周期都通过数据库记录：

```
1. Ingest  -> documents 表新增记录，status=raw，location=raw/
2. 分类    -> documents 表更新 status=classified，location=knowledge/xxx/
                operations_log 新增记录（operation=classify, from=raw/, to=knowledge/xxx/）
3. 用户手动移动 -> documents 表更新 location
                     operations_log 新增记录（operation=manual_move）
```

文件内容入库后不可变，只有 metadata 字段可更新。

---

## 未来功能（待细化）

- **Web 前端**：浏览 knowledge/ 和 wiki/ 内容，搜索，下载，手动编辑 metadata，手动移动文件，新增笔记
- **用户在前端写笔记**：直接在 Web UI 写 Markdown，自动带 metadata 入库
- **新分类建议**：Agent 可通过 Telegram 建议新分类，用户确认后自动更新 categories.json
