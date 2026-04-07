# PageFly 实施计划

## Phase 1：项目骨架 + 基建

### Stage 1.1：项目初始化
**Goal**: 建立项目目录结构和基本配置
**Status**: Not Started

- [ ] 初始化 Python 项目（pyproject.toml / requirements.txt）
- [ ] 创建目录结构：

```
pagefly/
+-- src/
|   +-- channels/          # Telegram, API
|   +-- ingest/            # pipeline + converters
|   |   +-- converters/
|   +-- governance/         # classifier, organizer, compiler
|   +-- output/            # query, review, notifier
|   +-- storage/           # files, db
|   +-- shared/            # types, config, logger
|   +-- mcp/               # 自建 MCP server（给 Agent 用的工具）
+-- config/
|   +-- categories.json
|   +-- schedules.json
|   +-- skills/
|       +-- compiler/
|       |   +-- SKILL.md
|       +-- query/
|       |   +-- SKILL.md
|       +-- review/
|       |   +-- SKILL.md
|       +-- summarizer/
|       |   +-- SKILL.md
|       +-- linker/
|           +-- SKILL.md
+-- data/                  # Docker Volume 挂载点
|   +-- raw/
|   +-- knowledge/
|   +-- wiki/
+-- docs/
|   +-- idea.md
+-- tests/
+-- Dockerfile
+-- docker-compose.yml
+-- .env.example
+-- .gitignore
```

- [ ] 创建 .env.example（API keys 占位）
- [ ] 创建 .gitignore
- [ ] Git 初始化

### Stage 1.2：存储层基建
**Goal**: 文件操作 + 数据库连接
**Status**: Not Started

- [ ] `src/storage/files.py` — 文件操作（创建、移动、读取、更新 metadata，禁止删除）
- [ ] `src/storage/db.py` — 数据库连接（SQLite 先跑起来，后面可换 PostgreSQL）
- [ ] `src/storage/models.py` — 数据模型（documents, operations_log, wiki_articles 表）
- [ ] 数据库 schema 初始化脚本
- [ ] `src/shared/config.py` — 环境变量和配置读取
- [ ] `src/shared/logger.py` — 日志模块
- [ ] `src/shared/types.py` — 类型定义

### Stage 1.3：Metadata 模块
**Goal**: YAML frontmatter 注入和校验
**Status**: Not Started

- [ ] `src/ingest/metadata.py` — YAML frontmatter 注入
  - UUID 生成
  - ISO 8601 时间格式生成 + 校验
  - frontmatter 插入到 Markdown 头部
  - frontmatter 解析和更新
  - frontmatter 格式校验

### Stage 1.4：分类配置
**Goal**: categories.json + 校验逻辑
**Status**: Not Started

- [ ] `config/categories.json` — 初始分类定义
- [ ] `src/governance/classifier.py` — 分类器（Claude API 单次调用 + 结构化输出）
  - 加载 categories.json
  - 调用 LLM 分类
  - 校验返回的 category 是否在 JSON 中
  - 不在则重试（最多 3 次）
  - 返回结构化分类结果

### Stage 1.5：Ingest Pipeline 基础
**Goal**: 最简单的文本入库流程跑通
**Status**: Not Started

- [ ] `src/ingest/pipeline.py` — 统一入口
- [ ] `src/ingest/converters/text.py` — 文本/Markdown 直传（最简 converter）
- [ ] 端到端流程：接收 .md 文件 -> 注入 metadata -> 写入 raw/ -> 记录到数据库

### Stage 1.6：Governance 基础（organizer）
**Goal**: raw/ -> knowledge/ 的移动流程
**Status**: Not Started

- [ ] `src/governance/organizer.py` — 文件整理
  - 扫描 raw/ 新文件
  - 调用 classifier 分类
  - 移动到 knowledge/{category}/
  - 更新文件 metadata（status, location, classified_at）
  - 更新数据库记录
  - 写入操作日志
- [ ] `src/governance/scheduler.py` — 基础定时调度（先用简单的 cron/asyncio）

### Stage 1.7：Docker 化
**Goal**: 整个基建能在 Docker 中跑起来
**Status**: Not Started

- [ ] Dockerfile（Python 基础镜像）
- [ ] docker-compose.yml（app + 可选 postgres）
- [ ] data/ 目录作为 Docker Volume
- [ ] .env 注入 API keys
- [ ] 验证：Docker 内能完成 文本入库 -> 分类 -> 移动 的完整流程

---

## Phase 2：更多 Converter + Telegram（后续细化）

- PDF -> Markdown（Mistral OCR 脚本）
- 图片 OCR -> Markdown（LLM Vision）
- 语音 STT -> Markdown（GPT-4o Transcribe）
- Word -> Markdown
- URL -> Markdown
- Telegram Bot 接入（输入 + 输出 + 控制台）
- REST API 基础路由

## Phase 3：Agent 编译 + 输出（后续细化）

- Compiler Agent（knowledge/ -> wiki/）
- Skill 文件编写
- MCP Server（数据库工具）
- Query Agent
- Review Agent（daily/weekly/monthly）

## Phase 4：高级功能（后续细化）

- Telegram 审核流程（低 confidence 通知）
- Web 前端
- 趋势发现和主动推送
