# PageFly Workspace — Proof Adapter Spec

> YRZ-192: Proof SDK 通读 + PageFly Workspace spec
> Status: Draft — 待 yrzhe 拍板后解锁 YRZ-191 子任务

---

## 1. Proof SDK 调研结论

### 1.1 Op 模型

Proof 的 op 通过 `POST /documents/:slug/ops` 发送：

| Op Type | 用途 |
|---------|------|
| `comment.add` | 锚定评论到引用文本 |
| `comment.reply` | 回复评论 thread |
| `comment.resolve` | 关闭评论 thread |
| `suggestion.add` | 创建 inline 建议（insert/replace/delete） |
| `suggestion.accept` | 接受建议，应用修改 |
| `suggestion.reject` | 拒绝建议，保留原文 |
| `rewrite.apply` | 替换整个文档 markdown |

另有两个独立编辑端点（不是 op）：
- `POST /edit` — 结构化操作（append/replace/insert），max 50 ops/request，需要 `baseUpdatedAt` 乐观锁
- `POST /edit/v2` — block-level 编辑，stable block refs（`b1`, `b2`...），需要 `baseRevision` 乐观锁

**持久化模型**：DB 存 materialized state（markdown + revision），不是 op log。`document_events` 表做审计和事件投递（outbox 模式），但不是可重建的 op log。

### 1.2 Anchor 模型

- 评论/建议用 `quote` 字段锚定（精确文本匹配）
- Bridge executor 将 quote 解析为 ProseMirror `{from, to}` range
- Mark 同时存 `range` 和 `quote`，quote 是 fallback
- 编辑后 range 失效时，fallback 到 quote-text 重新匹配
- `orphaned: boolean` 标记内容已被删除的锚点
- `/edit` 端点支持 `target.occurrence` (`first|last|N`) 消歧重复文本
- 多评论同 range 通过 `thread` ID 聚合

### 1.3 Suggestion / Pending Change

- 种类：`insert` | `delete` | `replace`
- 生命周期：`pending → accepted` (应用) 或 `pending → rejected` (保留原文)
- 可立即应用：`suggestion.add` 时传 `"status": "accepted"`
- Proof **没有**限制同时 pending 的数量
- 冲突处理靠乐观锁（`baseRevision` / `baseUpdatedAt`）

### 1.4 Provenance

- `by` 格式：`ai:model` / `ai:model:version` / `human:name`
- Provenance 是 **per-span**（内容区域），不是 per-document
- 三级 review：`skimmed` (AI/人) → `flagged` (仅人) → `approved` (仅人)
- 版本重建基于 content-based selectors（语义），不是 byte offset
- 嵌入存储：`<!-- PROVENANCE {json} -->` HTML 注释
- `OrchestratedMarkMeta` 追踪多 agent 链：`runId`, `agentId`, `proposalId`

### 1.5 Auth

- 两种 token：`ownerSecret`（完全控制）+ `accessToken`（scoped：viewer/commenter/editor）
- Rate limit：未认证 20 req/min，认证 120 req/min
- Idempotency：`Idempotency-Key` header，双表去重

### 1.6 Events

- Long-poll：`GET /events/pending?after=<cursor>&limit=N`
- Ack：`POST /events/ack` 标记已处理
- WebSocket **只用于**实时协作（Yjs CRDT），不用于事件推送
- 事件类型：`comment.added`, `comment.replied`, `comment.resolved`

---

## 2. 直接采纳的部分

| Proof 设计 | PageFly 采纳 | 说明 |
|-----------|------------|------|
| `comment.add/reply/resolve` op 模型 | ✅ 采纳 | 评论 CRUD 协议 |
| `suggestion.add/accept/reject` op 模型 | ✅ 采纳 | 建议生命周期 |
| suggestion `kind`: insert/delete/replace | ✅ 采纳 | 三种建议类型 |
| `quote` 文本锚定 | ✅ 采纳 | 评论/建议的定位方式 |
| `by` 格式 `ai:model` / `human:name` | ✅ 采纳 | author 标识 |
| `orphaned` flag | ✅ 采纳 | 标记失效锚点 |
| Idempotency-Key header | ✅ 采纳 | mutation 幂等 |
| 三级 review (skimmed/flagged/approved) | ✅ 采纳 | provenance review |

## 3. 改造的部分

| Proof 设计 | PageFly 改造 | 原因 |
|-----------|------------|------|
| SQLite + Drizzle ORM | **SQLite + raw SQL** | PageFly 已有 SQLite 基础，无需引入 Drizzle |
| Express route system | **FastAPI endpoints** | PageFly 后端是 Python |
| Hocuspocus / Yjs 实时协作 | **不做实时协作 v1** | v1 异步协作，不需要多光标 |
| Materialized state + Yjs CRDT | **Markdown + revision counter** | 简化：每次保存全量 markdown + 递增 revision |
| document_events outbox | **operations_log 复用** | PageFly 已有 operations_log 表 |
| Block-level `/edit/v2` | **不需要 v1** | 直接保存全量，不做 block diff |
| `rewrite.apply` + live client detection | **不需要 v1** | 单用户 + agent，无并发编辑 |

## 4. 新增的部分（Proof 没有）

| 功能 | 说明 |
|------|------|
| **同文档只允许一条 pending suggestion** | YRZ-191 决策：避免冲突，Proof 不限制 |
| **@-mention 解析** | 评论中 `@agent_xxx` 触发 agent 响应 |
| **同 range 多评论 UI 聚合** | 按 anchor 折叠到一张卡片，按时间堆叠 |
| **Agent Copilot panel** | 右侧常驻面板，Proof 没有 UI 层 |
| **Output Pipeline** | 文档 → X/公众号/博客发布，Proof 没有 |
| **知识库素材引用** | 编辑时从 knowledge/ 和 wiki/ 拉素材，Proof 没有 |

## 5. DB Schema（SQLAlchemy 风格）

```sql
-- Workspace 文档（独立于 knowledge documents）
CREATE TABLE workspace_documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',          -- full markdown
    revision INTEGER NOT NULL DEFAULT 1,       -- optimistic lock counter
    status TEXT NOT NULL DEFAULT 'draft',       -- draft | review | published
    created_by TEXT NOT NULL DEFAULT 'human',   -- human:uid | ai:agent_id
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 评论（锚定到文档文本）
CREATE TABLE workspace_comments (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES workspace_documents(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES workspace_comments(id),  -- thread reply
    author_type TEXT NOT NULL,                 -- human | ai:agent_id
    author_name TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,                     -- 评论正文
    quote TEXT NOT NULL DEFAULT '',            -- 锚定文本
    anchor_from INTEGER,                       -- ProseMirror range start
    anchor_to INTEGER,                         -- ProseMirror range end
    orphaned INTEGER NOT NULL DEFAULT 0,       -- 锚点失效
    status TEXT NOT NULL DEFAULT 'open',        -- open | resolved
    created_at TEXT NOT NULL
);
CREATE INDEX idx_ws_comments_doc ON workspace_comments(doc_id);

-- Suggestions（agent 自己判断是否创建，不限数量）
CREATE TABLE workspace_suggestions (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES workspace_documents(id) ON DELETE CASCADE,
    comment_id TEXT REFERENCES workspace_comments(id),  -- 触发的评论
    author_type TEXT NOT NULL,                 -- ai:agent_id
    kind TEXT NOT NULL,                        -- insert | delete | replace
    quote TEXT NOT NULL,                       -- 锚定原文
    content TEXT NOT NULL DEFAULT '',          -- 替换内容
    status TEXT NOT NULL DEFAULT 'pending',     -- pending | accepted | rejected
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

-- 文档版本历史（每次保存记录）
CREATE TABLE workspace_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES workspace_documents(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    content TEXT NOT NULL,                     -- snapshot
    author_type TEXT NOT NULL,
    author_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_ws_revisions_doc ON workspace_revisions(doc_id, revision DESC);
```

## 6. API Endpoint 列表

### 文档 CRUD

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/workspace/documents` | 列出所有 workspace 文档 |
| POST | `/api/workspace/documents` | 创建新文档 |
| GET | `/api/workspace/documents/:id` | 获取文档内容 + metadata |
| PATCH | `/api/workspace/documents/:id` | 更新文档内容（需 revision 乐观锁） |
| DELETE | `/api/workspace/documents/:id` | 删除文档 |

### 评论

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/workspace/documents/:id/comments` | 列出文档所有评论（含 threads） |
| POST | `/api/workspace/documents/:id/comments` | 创建评论（锚定 quote） |
| POST | `/api/workspace/comments/:id/reply` | 回复评论 |
| POST | `/api/workspace/comments/:id/resolve` | 标记评论已解决 |

### 建议（Pending Change）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/workspace/documents/:id/suggestions` | 创建建议（需无 pending） |
| POST | `/api/workspace/suggestions/:id/accept` | 接受建议（apply diff） |
| POST | `/api/workspace/suggestions/:id/reject` | 拒绝建议 |

### Agent 触发

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/workspace/documents/:id/ask` | 选中文本 → 触发 agent 响应 |

### Output Pipeline（v2）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/workspace/documents/:id/publish` | 发布到外部平台 |

## 7. 决策点（已拍板 2026-05-14）

| # | 问题 | 决定 |
|---|------|------|
| D1 | Editor | **Tiptap**（评论锚定需要 ProseMirror range） |
| D2 | Pending suggestion 限制 | **不限制数量**，Agent 自己判断是否创建 suggestion |
| D3 | Agent 响应方式 | **Agent 自己判断**是评论还是 suggestion |
| D4 | workspace_documents | **独立表**，和 knowledge documents 分离 |
| D5 | 版本历史粒度 | **每次保存一条** revision |
| D6 | Output Pipeline 优先级 | **1) 博客导出**（MD + 图片压缩包） → 2) X → 3) 微信公众号 |
| D7 | 实时协作 | **不需要** v1，异步模式 |

---

## 8. 推荐开工顺序

```
D1-D7 决策拍板
    ↓
子任务 1: workspace_documents 表 + CRUD API + Tiptap 编辑器页面
    ↓
子任务 2: workspace_comments 表 + 评论侧栏 + range 高亮
    ↓
子任务 4: Agent 集成 + @-mention / Ask 触发
    ↓
子任务 3: workspace_suggestions 表 + diff + Approve/Reject
    ↓
子任务 5: workspace_revisions 表 + provenance
    ↓
子任务 6: Output Pipeline（第一个平台）
```
