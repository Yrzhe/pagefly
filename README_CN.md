<div align="center">

<img src="docs/assets/readme/OG Image.png" alt="PageFly — Personal Knowledge OS" width="720" />

# PageFly

**你的知识，由 AI 结构化 — 捕获一切，让 Agent 编写 Wiki。**

[![MIT License](https://img.shields.io/badge/license-MIT-F59E0B?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=white)](https://react.dev)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)

[在线演示](https://pagefly.ink) · [快速开始](#快速开始) · [背后的故事](#背后的故事) · [English](README.md)

</div>

---

```bash
git clone https://github.com/Yrzhe/pagefly.git && cd pagefly
python -m src.cli setup          # 交互式：邮箱、密码、API 密钥
docker compose up -d             # → http://localhost
```

---

<div align="center">
  <img src="docs/assets/readme/idea.png" alt="PageFly 概念图" width="720" />
  <br />
  <sub>核心理念：一个从日常信息流中持续生长结构化知识的飞轮。</sub>
</div>

---

## 什么是 PageFly？

PageFly 是一个**自托管的私人知识平台** — 结构化、自动化、API-ready 的知识治理系统，把原始信息变成编译好的知识。

你把原始材料丢给它（PDF、Markdown、图片、语音备忘录、URL、Telegram 消息），它会：

1. **Capture 捕获** — 导入到结构化的原始层，附带元数据
2. **Distill 蒸馏** — AI 自动分类、打分、标注时效性、提取关键论点
3. **Compile 编译** — Agent 撰写并维护 Wiki 文章（概念页、摘要、关联图）
4. **Serve 服务** — REST API、Telegram Bot、Web 前端、兼容 Obsidian 的 Markdown 输出

你永远不需要手动写 Wiki — LLM 来维护它。

## 核心特性

| 特性 | 说明 |
|------|------|
| **多格式导入** | PDF、DOCX、图片（OCR）、语音（转写）、URL、纯文本 |
| **AI 蒸馏** | 自动分类、相关性打分、时效性标注、关键论点提取 |
| **Wiki 编译** | Agent 撰写概念页、摘要和关联图，采用更新优先的治理模型 |
| **Workspace 编辑器** | Tiptap 富文本编辑器，支持图片、表格、代码块 — 草稿 → 完成 → 导入知识库 |
| **Telegram Bot** | 通过 Telegram 发送任何内容 — 文字、图片、语音、文件，支持内联审批 |
| **每日漫步** | 随机知识重现，按新旧度加权，去重防重复 |
| **REST API** | ~60 个端点，多令牌认证（JWT + API Token + 主令牌） |
| **定时 Agent** | Cron 驱动的审查、编译、链接、趋势分析、每日漫步 |
| **知识图谱** | 交互式力导向图，展示文档和 Wiki 文章的关联 |
| **Obsidian 兼容** | Wiki 输出为带 YAML frontmatter 的 `.md` 文件 — 直接拖入 Obsidian |

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
   │  语音 · URL · 文本   │           │  Linker（发现关联）      │
   └──────────┬──────────┘           │  Trend（趋势洞察）       │
              │                      │  Review（审查 + 检查）    │
   ┌──────────▼──────────┐           │  Query（搜索 + 对话）    │
   │      治理层          │           └────────────┬───────────┘
   │                     │                        │
   │  分类器（AI）        │           ┌────────────▼───────────┐
   │  组织器              │           │      存储层             │
   │  完整性检查器        │           │                         │
   └─────────────────────┘           │  SQLite（元数据）        │
                                     │  文件系统（文档）        │
                                     │  Wiki（Markdown）       │
                                     └─────────────────────────┘
```

## 背后的故事

PageFly 的灵感来源于 [Andrej Karpathy 的 LLMWiki](https://x.com/karpathy/status/1039944530988847617) — 结构化知识编译可以被自动化的理念。

我看到那条推文后想：如果我们走得更远呢？不只是一个 Wiki，而是一个完整的 **捕获到服务的流水线**，包含导入、蒸馏、治理和 API 访问 — 加上一个让你与 AI Agent 并肩写作的工作区。

## 快速开始

### 方式一 — Docker（推荐）

**前置要求**: Docker + Docker Compose，一个 [Anthropic API 密钥](https://console.anthropic.com/)。

```bash
git clone https://github.com/Yrzhe/pagefly.git
cd pagefly
python -m src.cli setup      # 交互式：邮箱、密码、API 密钥、演示数据
docker compose up -d
```

`setup` 命令会生成带哈希密码的 `config.json`，可选加载演示知识库。

**已配置好？** 跳过 `setup`，直接 `docker compose up -d`。

### 方式二 — 纯环境变量启动

不需要 `config.json`。导出三个环境变量即可：

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export PAGEFLY_EMAIL=you@example.com
export PAGEFLY_PASSWORD=your-password
docker compose up -d
```

### 方式三 — 一键部署（Railway）

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https%3A%2F%2Fgithub.com%2FYrzhe%2Fpagefly)

在 Railway 面板设置 `ANTHROPIC_API_KEY`、`PAGEFLY_EMAIL`、`PAGEFLY_PASSWORD`，挂载 `/app/data` 卷。

### 访问

- **Web 前端**: `http://localhost`
- **API**: `http://localhost:8000/api`
- **Telegram**: 给你的 Bot 发消息即可

### 随时加载演示数据

```bash
python -m src.cli load-demo     # 添加 3 个示例文档 + 5 篇 Wiki 文章
python -m src.cli clear-demo    # 清除演示数据
```

## API 概览（~60 个端点）

| 类别 | 端点数 | 说明 |
|------|--------|------|
| 知识库 | 14 | 导入、列表、读取、更新、删除、下载文档 |
| Wiki | 2 | 列表和读取编译的 Wiki 文章 |
| Workspace | 8 | 富文本文档，状态流（草稿 → 完成 → 导入知识库） |
| 搜索 & 问答 | 3 | 全文搜索、Agent 问答、知识图谱 |
| 对话 | 3 | 共享对话（与 Telegram 同步） |
| 调度 | 6 | Cron 任务管理 + 运行历史 |
| 桌面活动 | 5 | 桌面捕获事件和音频上传 |
| 漫步 | 1 | 随机知识重现 |
| 分类 | 3 | 动态分类管理 |
| 系统 | 7 | 统计、趋势、令牌、健康检查 |

认证：Bearer token（登录 JWT、API Token 或主令牌）。

## 客户端

服务端独立运行 — 以下客户端是可选的内容捕获工具。

### 浏览器扩展（Chrome / Edge / Brave / Arc）

一键把当前网页剪藏到知识库。

路径：`browser-extension/`（Manifest V3，开发者模式加载）。

```
1. 打开 chrome://extensions → 启用「开发者模式」
2. 「加载已解压的扩展」→ 选择 browser-extension/ 文件夹
3. 点图标 → 设置服务器 URL + API Token
4. 任何页面：点图标 → "Clip this page"
```

### macOS 桌面捕获

菜单栏应用，每隔几秒捕获活动应用 + 窗口上下文，支持会议录音并服务端转写。

路径：`desktop-capture/`（Swift / SwiftUI，Xcode 15+）。

```bash
cd desktop-capture && ./scripts/package-local.sh
# → dist/PageflyCapture-<version>.dmg
```

打开 PageflyCapture → 菜单栏图标 → 偏好设置 → 填入服务器 URL + API Token → 授权辅助功能 + 麦克风。

## 技术栈

### 后端
| 层级 | 选型 |
|------|------|
| 运行时 | Python 3.11+ |
| API | FastAPI |
| 数据库 | SQLite（WAL 模式） |
| AI Agent | Claude Agent SDK (Anthropic) |
| 调度器 | APScheduler |
| Bot | python-telegram-bot |

### 前端
| 层级 | 选型 |
|------|------|
| 框架 | React 19 + Vite + TypeScript |
| 编辑器 | Tiptap (ProseMirror) |
| 样式 | Tailwind CSS v4 |
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
│   ├── agents/          # Compiler、Linker、Trend、Query、Review（Claude SDK）
│   ├── channels/        # Telegram Bot、REST API
│   ├── governance/      # 分类器、组织器、完整性检查器
│   ├── ingest/          # 流水线 + 转换器（PDF、DOCX、语音、图片、URL）
│   ├── scheduler/       # 定时任务、收件箱监听
│   ├── shared/          # 配置、漫步、索引器、类型
│   ├── storage/         # SQLite、删除逻辑
│   └── auth/            # JWT、TOTP 2FA、邮箱验证
├── config/
│   ├── SCHEMA.md        # Wiki 约定（注入到 Agent 提示词）
│   └── skills/          # Agent 技能定义
├── frontend/            # React + Vite + Tailwind + Tiptap
├── browser-extension/   # Chrome 扩展（Manifest V3）
├── desktop-capture/     # macOS 菜单栏应用（Swift）
├── data/                # 运行时数据（不追踪）
│   ├── raw/             # 导入的文档
│   ├── knowledge/       # 已分类 & 组织的
│   ├── wiki/            # 编译的文章
│   └── workspace/       # 编辑器图片
├── docker-compose.yml
└── Dockerfile           # 多阶段构建（Python + Node 前端）
```

## 链接

- **作者**: [@yrzhe_top](https://x.com/yrzhe_top)
- **在线**: [pagefly.ink](https://pagefly.ink)
- **灵感来源**: [Karpathy 的 LLMWiki](https://x.com/karpathy/status/1039944530988847617)

## 开源协议

[MIT](LICENSE) — 随便用。

---

<div align="center">
  <sub>由 <a href="https://x.com/yrzhe_top">yrzhe</a> 与 Claude 共同构建，一次对话接一次对话。</sub>
</div>
