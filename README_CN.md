<div align="center">

<img src="docs/assets/readme/OG Image.png" alt="PageFly — Personal Knowledge OS" width="720" />

# PageFly

[![MIT License](https://img.shields.io/badge/license-MIT-F59E0B?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=white)](https://react.dev)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)

[在线演示](https://pagefly.ink) · [背后的故事](#背后的故事) · [快速开始](#快速开始) · [English](README.md)

</div>

---

<div align="center">
  <img src="docs/assets/readme/idea.png" alt="PageFly 概念图" width="720" />
  <br />
  <sub>核心理念：一个从日常信息流中持续生长结构化知识的飞轮。</sub>
</div>

---

## 什么是 PageFly？

PageFly 是一个**自托管的私人知识数据平台** —— 结构化、自动化、API-ready 的知识治理系统。

你把原始材料丢给它（PDF、Markdown、图片、语音备忘录、URL、Telegram 消息），它会：

1. **Capture 捕获** —— 导入到结构化的原始层，附带元数据
2. **Distill 蒸馏** —— AI 自动分类、打分（相关性 1-10）、标注时效性、提取关键论点
3. **Compile 编译** —— Agent 撰写并维护 Wiki 文章（概念页、摘要、关联图）
4. **Serve 服务** —— REST API、Telegram Bot、兼容 Obsidian 的 Markdown 输出

你永远不需要手动写 Wiki —— LLM 来维护它。

## 背后的故事

PageFly 的灵感来源于 [Andrej Karpathy 的 LLMWiki](https://x.com/karpathy/status/1039944530988847617) —— 结构化知识编译可以被自动化的理念。

我看到那条推文后想：如果我们走得更远呢？不只是一个 Wiki，而是一个完整的 **捕获到服务的流水线**，包含导入、蒸馏、治理和 API 访问。

<div align="center">

**[看看我给 Karpathy 的回复 →](https://x.com/yrzhe_top/status/2039944530988847617)**

</div>

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                         渠道层                                │
│  Telegram Bot  ·  REST API  ·  Web 前端  ·  定时调度器        │
└─────────────┬───────────────────────────────────┬───────────┘
              │                                   │
   ┌──────────▼──────────┐           ┌────────────▼───────────┐
   │     导入流水线        │           │     Agent 系统          │
   │                     │           │                         │
   │  PDF · DOCX · 图片   │           │  Compiler（写 Wiki）     │
   │  语音 · URL · 文本   │           │  Query（搜索 + 对话）    │
   │                     │           │  Review（审查 + 检查）    │
   └──────────┬──────────┘           └────────────┬───────────┘
              │                                   │
   ┌──────────▼──────────┐           ┌────────────▼───────────┐
   │      治理层          │           │      存储层             │
   │                     │           │                         │
   │  分类器（AI）        │           │  SQLite（元数据）        │
   │  组织器              │           │  文件系统（文档）        │
   │  完整性检查器        │           │  Wiki（Markdown）       │
   └─────────────────────┘           └─────────────────────────┘
```

## 核心特性

| 特性 | 说明 |
|------|------|
| **多格式导入** | PDF、DOCX、图片（OCR）、语音（转写）、URL、纯文本 |
| **AI 蒸馏** | 自动分类、相关性打分（1-10）、时效性标注、关键论点提取 |
| **Wiki 编译** | Agent 撰写概念页、摘要和关联图，采用更新优先的治理模型 |
| **Telegram Bot** | 通过 Telegram 发送任何内容 —— 文字、图片、语音、文件，支持内联审批 |
| **REST API** | 完整 API，支持多令牌认证（主令牌 + 作用域客户端令牌） |
| **Obsidian 兼容** | Wiki 输出为带 YAML frontmatter 的 `.md` 文件 —— 直接拖入 Obsidian |

## 快速开始

### 前置要求

- Docker & Docker Compose
- API 密钥：Claude (Anthropic)、OpenAI（可选，语音转写）、Mistral（可选，OCR）
- Telegram Bot Token（可选）

### 1. 克隆 & 配置

```bash
git clone https://github.com/Yrzhe/pagefly.git
cd pagefly
cp config.json.example config.json
# 编辑 config.json，填入你的 API 密钥
```

### 2. Docker 启动

```bash
docker compose up -d
```

### 3. 访问

- **API**: `http://localhost:8000/docs`（Swagger UI）
- **Telegram**: 给你的 Bot 发消息即可开始
- **前端**: `http://localhost:5173`（开发）或部署到 Cloudflare Pages

## 技术栈

### 后端
| 层级 | 选型 |
|------|------|
| 运行时 | Python 3.11+ |
| API | FastAPI |
| 数据库 | SQLite |
| AI Agent | Claude Agent SDK (Anthropic) |
| 调度器 | APScheduler |
| Bot | python-telegram-bot |

### 前端
| 层级 | 选型 |
|------|------|
| 框架 | React + Vite + TypeScript |
| 样式 | Tailwind CSS v4 + shadcn/ui |
| 路由 | react-router-dom v6 |
| 图标 | Lucide React |

### AI 模型
| 任务 | 模型 |
|------|------|
| 分类 & Agent | Claude (Anthropic) |
| 语音转写 | gpt-4o-transcribe (OpenAI) |
| 图片 OCR | mistral-ocr-latest + mistral-small-latest |

## 项目结构

```
pagefly/
├── src/
│   ├── agents/          # Compiler、Query、Review Agent（Claude SDK）
│   ├── channels/        # Telegram Bot、REST API
│   ├── governance/      # 分类器、组织器、完整性检查器
│   ├── ingest/          # 流水线 + 转换器（PDF、DOCX、语音、图片、URL）
│   ├── scheduler/       # 定时任务、收件箱监听
│   ├── shared/          # 配置、索引器、活动日志、类型
│   └── storage/         # SQLite、删除逻辑
├── config/
│   ├── SCHEMA.md        # Wiki 约定（注入到 Agent 提示词）
│   └── skills/          # Agent 技能定义
├── frontend/            # React + Vite + Tailwind
├── data/                # 运行时数据（不追踪）
│   ├── raw/             # 导入的文档
│   ├── knowledge/       # 已分类 & 组织的
│   └── wiki/            # 编译的文章
├── docker-compose.yml
└── Dockerfile
```

## 链接

- **作者**: [@yrzhe_top](https://x.com/yrzhe_top)
- **那条推文**: [我给 Karpathy 的回复](https://x.com/yrzhe_top/status/2039944530988847617)
- **灵感来源**: [Karpathy 的 LLMWiki](https://x.com/karpathy/status/1039944530988847617)
- **在线**: [pagefly.ink](https://pagefly.ink)

## 开源协议

[MIT](LICENSE) —— 随便用。

---

<div align="center">
  <sub>由 <a href="https://x.com/yrzhe_top">yrzhe</a> 与 Claude 共同构建，一次对话接一次对话。</sub>
</div>
