# PageFly Workspace — Proof SDK Adapter Spec

> Adapter spec for porting the Proof SDK contracts (Every Inc., MIT, github.com/EveryInc/proof-sdk @ `main`, last push ~5 weeks ago, commit `fb25787`) into PageFly's stack:
> **FastAPI backend + Postgres + Tiptap React editor + async-only single-pending-suggestion agent loop.**
>
> This document is the source of truth for the six Workspace implementation tasks. It does **not** contain implementation code — only the data model, schemas, endpoints, and the open decisions that block coding.

---

> **Status: FROZEN 2026-04-30.** All 11 design decisions resolved by yrzhe in chat — see §7 for the locked answers and §11 for the link-sharing module added during freeze. Implementation of the Workspace sub-tasks (1 → 6) can begin without further design discussion. Any change to a §7 decision after this date requires a new spec revision.
>
> **Quick deltas from initial spec to lock-in** (full detail in §7):
> - Notification: long-poll → **SSE** (sub-1s message-level real-time)
> - Quote disambiguation: A/B/C all rejected → **G** (combined: unique → prefix+suffix → candidates retry)
> - Suggestion immediate-accept: B → **C** (`human:` callers only — forward-compat for shared-link humans, see §11)
> - Agent worker isolation: B with v2 trigger to hard Postgres role-based grants (§9a)
> - **New module §11**: link sharing (3-tier permissions, no-login visitors with localStorage identity, revocable + expirable, IP/UA audit log)
> - **New §9**: v2 upgrade path commitments (hard isolation, CRDT, full provenance, link passwords) with explicit triggers

## 0. Context & decisions snapshot

PageFly Workspace is the in-app "Docs" surface where humans and AI agents co-author shopify-store-page briefs, plan documents, and post-mortems. The first vertical slice is "AI as a polite second author": humans drag the cursor, type, and triage; agents triggered by `@-mention` or the right-side **Ask** button add comments, post one pending suggestion at a time, and only commit edits after the human accepts.

We have already evaluated the Proof SDK as the closest open-source prior art for the contract layer (op model, anchor model, provenance, agent-friendly HTTP). Proof's editor is Milkdown + Yjs + SQLite + Express; ours will be Tiptap + Postgres + FastAPI. We adopt Proof's wire contracts for ops, comments, suggestions, events, and authorship, and discard:

- Yjs / Hocuspocus realtime fragment sync (we are async-only — no live cursors, no CRDT)
- SQLite-specific store
- Milkdown / ProseMirror plugin code (replaced by Tiptap extensions)
- The hosted `/api/agent/*` and `/share/markdown` legacy aliases (we mount only the canonical routes)
- The "rewrite while connected clients exist" gating (no live clients in our model — it would always pass)

**Already-decided constraints (from yrzhe, locked):**

1. **Editor: Tiptap (React)** — not Milkdown, not raw ProseMirror. Tiptap's CommentMark / SuggestionMark extensions will be hand-rolled but their data shape mirrors Proof's marks.
2. **No realtime collab** — no Yjs, no Hocuspocus, no WebSocket fragment sync. All writes go through plain HTTP. Other clients see updates by re-fetching state or via long-poll events.
3. **One pending suggestion at a time** per document. The server enforces this at op-application time. (Proof allows N concurrent — see §3.)
4. **Agent triggered explicitly** by `@AgentName` mention OR the **Ask** button. No background polling, no auto-triggers on save.
5. **Backend: FastAPI + SQLAlchemy + Postgres**. Async stack throughout (`async def` + `asyncpg`).
6. **Comments are aggregated** when multiple commenters target the same range — Proof does not do this; we do (see §2 and §3).

**Stack summary:**

| Layer | Choice | Notes |
|---|---|---|
| Editor | Tiptap (React) + custom CommentMark/SuggestionMark | Marks are pure presentation; truth lives server-side |
| Doc transport | Markdown (canonical) + ProseMirror JSON (snapshot) | Markdown is the storage format like Proof |
| Backend | FastAPI + asyncpg + SQLAlchemy 2 (async) | Pydantic v2 schemas |
| DB | Postgres 16 | Append-only ops table + materialized comment/suggestion tables |
| Auth | JWT bearer (PageFly session) for humans; per-document share tokens for agents | Mirrors Proof's `accessToken` model |
| Realtime | Long-poll only (`/events/pending?after=<id>`) | No WS, no Yjs |
| Agent runtime | Same FastAPI app, agent worker is a background task triggered by @-mention or Ask button | Worker writes ops via the same HTTP API as humans |

---

## 0a. Quick-reference: answers to the 6 question groups

(Detailed answers are sprinkled throughout §1–§6. This is the cheat-sheet view.)

### Q1. Op model
- Op types: `comment.add`, `comment.reply`, `comment.resolve`, `suggestion.add`, `suggestion.accept`, `suggestion.reject`, `suggestion.cancel` (PageFly-only), `rewrite.apply` (humans only).
- Each op has envelope `{ type, by, ...specific, base_revision? }`.
- Op interdependencies: `suggestion.accept`/`.reject`/`.cancel` reference `suggestion_id` (from `add`'s response). `comment.reply`/`.resolve` reference `thread_id`.
- Persistence: **both** append-only `ops` log AND materialized `comments` / `comment_threads` / `suggestions` tables. `documents.markdown` is the canonical text projection. Replay-from-ops is for audit, not for normal reads.

### Q2. Anchor model
- Selector shape: `{ quote, prefix?, suffix?, occurrence?, fuzzy? }`. Resolved to a `(block_ref, range_start, range_end)` triple at write time.
- Quote-text resolution algorithm: §3a.
- When original text is later edited: hash check on read; if mismatched, mark is `drifted` (still rendered, with a warning). **Not auto-orphaned.** Human resolves by re-anchoring or resolving the thread.
- Ambiguity handling: prefix+suffix narrows; `occurrence` (1-based) is the final tiebreaker; if still ambiguous → `ANCHOR_NOT_FOUND` with `candidates: [...]`.
- Multi-comment aggregation: same resolved range → same `comment_thread` row (enforced by `(document_id, anchor_hash)` UNIQUE).

### Q3. Suggestion / pending-change flow
- **Max one** pending suggestion per doc (Postgres partial UNIQUE index — §4.5). Proof allows N; we don't.
- `kind` enum: `replace | insert | delete` (matches Proof exactly — `packages/agent-bridge/src/index.ts:28`).
- Conflict resolution: `suggestion.accept` requires `base_revision`; mismatch → `STALE_REVISION` with snapshot inline.
- Reject leaves a record: row stays with `status='rejected'`, `rejection_reason`, `resolved_by`, `resolved_at`. Hidden from the editor by default, visible in audit view.

### Q4. Provenance
- `by` field schema: `human:<uid>` or `ai:<agent_id>[:<version>]` (Proof PROVENANCE-SPEC-v2.md:277–284).
- Per-edit, per-document: spans live in `provenance_spans` keyed by `(document_id, revision)`. Each span describes one contiguous piece of authored text.
- History reconstruction: hybrid. `documents.markdown` is the live state; `document_revisions` stores per-revision snapshots; `ops` is the audit log. Don't replay ops to read; do replay them to debug or to compute "show me everything Alice wrote this week".
- Multi-author on same range: Proof doesn't support this directly (each span has one `origin`). We model "Alice wrote it, Bob approved it, Carol flagged it" via the **review stack** on a single span (§4.8). For "Alice typed half, Bob typed the other half of the same paragraph" — that's two adjacent spans.

### Q5. Auth & security
- Bearer scope: `viewer | commenter | editor | owner`. Agents capped at `commenter` or `editor` (configurable per agent registration). Agents can never be `owner`.
- Doc-access boundaries: explicit grants only via `document_access_tokens` rows. No "agent has all docs" superuser. The PageFly user session JWT does carry workspace-scoped access (humans can list/open any doc in their workspace).
- Rate limiting: §5.9. Per-document, per-Principal, Redis-backed.
- Idempotency: `Idempotency-Key` UUID, required for agents (Stage A in our launch). 24h TTL (Decision 9). Stored on `ops.idempotency_key` with UNIQUE per `(document_id, idempotency_key)`.

### Q6. Long-poll / events
- Cursor: opaque `BIGINT` = `ops.id`. Monotonically increasing. Pass via `?after=<id>`.
- Replay: agent missing events just resumes from their last `last_ack_id` in `event_cursors`. Ops table is never compacted in v1.
- WebSocket scope: **none for agents.** None for humans either in v1 (long-poll only). Decision 6 may add SSE for humans later; agents stay long-poll-only.
- Server holds long-poll up to 25s default (configurable via `?hold=` up to 60s). Returns 200 with `events: []` on timeout.

---

## 1. Adopted from Proof (verbatim or near-verbatim)

These are concepts and contracts we copy with little or no modification. For each we cite the Proof source so future re-reads are easy.

### 1.1 Authorship `by` field

**Source:** `AGENT_CONTRACT.md` lines 92–110, `docs/proof.SKILL.md:11–14`, `docs/PROVENANCE-SPEC-v2.md:277–284`

Every write op carries a `by` string. Format:

| Type  | Format                           | Examples                                 |
| ----- | -------------------------------- | ---------------------------------------- |
| AI    | `ai:model` or `ai:model:version` | `ai:claude`, `ai:claude:opus-4-5`        |
| Human | `human:name` or `human:email`    | `human:alice`, `human:alice@pagefly.io`  |

We adopt this verbatim. PageFly will normalize `human:<uuid>` (the user ID from our Supabase auth row) on the server so client-supplied `by` cannot be spoofed; the human-readable display name is denormalized into the comment/suggestion row at write time.

**Why we keep it:** It is the simplest discriminator that lets the UI render an avatar/badge without joining tables. Proof's `origin: human | ai` plus `typed_by` (PROVENANCE-SPEC-v2.md:26–35) is more nuanced; we collapse that into the single `by` string for v1 and revisit if "AI dictated by human" becomes a real use case (it isn't yet).

### 1.2 Op envelope and `Idempotency-Key`

**Source:** `AGENT_CONTRACT.md:122–134`, `docs/agent-docs.md:283–294`

The wire format for every mutating op is:

```http
POST /api/workspace/documents/<slug>/ops
Authorization: Bearer <token>
Idempotency-Key: <uuid>
Content-Type: application/json

{ "type": "comment.add", "by": "ai:agent_id", ...op-specific fields... }
```

We adopt:

- The `POST /<base>/<slug>/ops` endpoint shape.
- `Idempotency-Key` header (case-insensitive, also accept `X-Idempotency-Key` for compatibility with off-the-shelf agents).
- The op type taxonomy (see §1.3).
- The contract that `Idempotency-Key` reuse with a different payload hash returns `IDEMPOTENCY_KEY_REUSED` (Proof error code copied verbatim — `docs/agent-docs.md:292`).

### 1.3 Op type enumeration (verbatim)

**Source:** `AGENT_CONTRACT.md:122–132`, `docs/agent-docs.md:82–116`, `docs/proof.SKILL.md:83–96`

Proof defines exactly these op types under `POST /ops`:

```
comment.add
comment.reply
comment.resolve
suggestion.add
suggestion.accept
suggestion.reject
rewrite.apply
```

We adopt all seven verbatim. Plus we ADD `suggestion.cancel` (see §3) for the rare case where the agent itself wants to retract a suggestion before the human accepts/rejects it — Proof does not have this but we need it because PageFly forces the "single pending suggestion" invariant.

### 1.4 Quote selector for anchoring

**Source:** `docs/PROVENANCE-SPEC-v2.md:118–133`, `agent-docs.md:97–102`

Proof anchors comments and suggestions by the **quoted text**, not by character offsets:

```yaml
selector:
  quote: "The deadline is March 15, 2025."
```

with optional `fuzzy: true` for whitespace/punctuation tolerance. Resolution is "find first occurrence; if not found, report `ANCHOR_NOT_FOUND` and require the agent to re-read state" (`agent-docs.md:374–378`).

We adopt the quote-text-as-anchor model. We extend it (see §2) with explicit disambiguation fields (`prefix`, `suffix`, `occurrence`) to handle the "the appears 50× in the doc" problem, which Proof punts on.

### 1.5 Snapshot + revision optimistic locking (Edit V2 contract)

**Source:** `docs/agent-docs.md:238–298`

Proof's `edit/v2` flow:

1. `GET /documents/<slug>/snapshot` returns `{ revision, blocks: [{ ref: "b1", markdown, type }, ...] }`.
2. `POST /edit/v2` requires `baseRevision`. If stale, 409 `STALE_REVISION` with the latest snapshot inlined for retry.
3. Block refs (`b1`, `b2`, ...) are stable across the revision. `replace_block`, `insert_after`, `insert_before`, `delete_block` are the v2 ops.

We adopt this almost verbatim for **structural** edits (the kind a human keystroke or `rewrite.apply` produces). The block refs map to Tiptap top-level nodes' positions at snapshot time. We explicitly **do not** expose `edit/v2` on the public agent API — agents use only `/ops` (comments + suggestions). `edit/v2` is internal, used by the human editor's autosave path only (see §5 on endpoint scope).

### 1.6 Append-only event stream + cursor polling

**Source:** `docs/agent-docs.md:301–311`, `AGENT_CONTRACT.md:136–139`, `packages/agent-bridge/src/index.ts:248–269`

Proof exposes:

```
GET  /documents/<slug>/events/pending?after=<cursor>&limit=100
POST /documents/<slug>/events/ack  body: { "upToId": <cursor>, "by": "..." }
```

Events are monotonically-numbered records of ops + state changes. Clients poll with `after=` and ack to compact (the Proof server may keep pending forever otherwise).

We adopt this verbatim, including the `upToId` ack semantics. PageFly long-poll: server holds the request open up to 25s if no events; returns 200 with empty array on timeout. (Proof's open-source code does not include the long-poll holding; it returns immediately. We add the holding because we have no WS.)

### 1.7 Provenance v2.0 review-stack model (selectively)

**Source:** `docs/PROVENANCE-SPEC-v2.md` (entire doc)

Proof v2.0 distinguishes:

- **origin**: `human | ai` (intellectual)
- **basis** (AI-only): `described | inferred | suggested`
- **review**: stack of `{ level: skimmed|flagged|approved, by, at, reviewed_hash, notes }`

We adopt the **review stack** verbatim (see §4 below). It maps cleanly to "AI added a paragraph, Alice approved it, Bob then flagged it" without losing any signal.

We adopt **origin** but collapse it into `by` (the prefix `ai:` vs `human:` is the origin).

We **defer** `basis` and `typed_by` to v2 (see §7 open decisions). For MVP, we record `meta.basis` as a free-text string when the agent provides it but do not enforce the enum.

We **discard** the embedded-YAML-in-markdown storage format (`PROVENANCE-SPEC-v2.md:309–328`). Postgres rows are fine; we don't need the markdown to be a portable provenance container in v1.

### 1.8 Discovery JSON & state response shape

**Source:** `AGENT_CONTRACT.md:54–78`, `docs/proof.SKILL.md:158`

Proof responds to `POST /documents` with a self-describing JSON that includes `_links` (HAL-lite hypermedia) so the agent can discover state/ops/events endpoints from the create response. We copy this pattern — every state response includes a `_links` block. Useful for external agents that haven't read this spec.

We **do not** mount `/.well-known/agent.json` in v1 (no need; PageFly agents are first-party).

### 1.9 Error codes (verbatim subset)

We copy these strings as-is so anyone reading Proof docs gets the same failure modes:

- `STALE_REVISION` (409) — `baseRevision` doesn't match
- `ANCHOR_NOT_FOUND` (409) — quote text could not be located
- `IDEMPOTENCY_KEY_REQUIRED` (400) — mutation submitted without key
- `IDEMPOTENCY_KEY_REUSED` (409) — same key + different payload hash
- `BASE_REVISION_REQUIRED` (400) — for `edit/v2`

We **add**:

- `PENDING_SUGGESTION_EXISTS` (409) — our single-pending-suggestion rule (Proof has no equivalent)
- `SUGGESTION_NOT_PENDING` (409) — accept/reject called on already-resolved suggestion
- `RANGE_DRIFTED` (409) — quote anchor still resolves but to materially different text (hash check from PROVENANCE-SPEC-v2.md:226–252)
- `REWRITE_FORBIDDEN_FOR_AGENT` (403) — agent attempted `rewrite.apply` (§2.7)
- `AGENT_NOT_FOUND` (404) — `@<agent_id>` mentioned in document text or invocation does not match a registered agent (depends on Decision 3)
- `THREAD_RESOLVED` (409) — `comment.reply` to an already-resolved thread

Full HTTP-status mapping reference table (used by FastAPI exception handler):

| Code | Status | Retryable? | retry_with hint |
|---|---|---|---|
| `STALE_REVISION` | 409 | yes | `state` (re-read snapshot, retry with new `base_revision`) |
| `RANGE_DRIFTED` | 409 | yes | `state` |
| `ANCHOR_NOT_FOUND` | 409 | yes | `state` (re-read, find new anchor) — body includes `candidates` if any |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | yes | n/a (add the header and resend) |
| `IDEMPOTENCY_KEY_REUSED` | 409 | no | n/a (use a fresh UUID) |
| `BASE_REVISION_REQUIRED` | 400 | yes | n/a |
| `PENDING_SUGGESTION_EXISTS` | 409 | no (must wait) | `pending_suggestion` (id of the blocker) |
| `SUGGESTION_NOT_PENDING` | 409 | no | n/a |
| `REWRITE_FORBIDDEN_FOR_AGENT` | 403 | no | n/a |
| `AGENT_NOT_FOUND` | 404 | no | n/a |
| `THREAD_RESOLVED` | 409 | no | n/a |
| `RATE_LIMITED` | 429 | yes | `Retry-After` header |
| `UNAUTHENTICATED` | 401 | no | n/a |
| `FORBIDDEN` | 403 | no | n/a |
| `NOT_FOUND` | 404 | no | n/a |
| `INVALID_PAYLOAD` | 422 | no | n/a (fix the schema and retry) |

---

## 2. Modified from Proof

### 2.1 Storage: SQLite → Postgres

**Proof:** `packages/doc-store-sqlite/src/index.ts` — wraps `server/db.js` with sqlite-specific `createDocument`, `listDocumentEvents`, etc.

**Ours:** Postgres. Functionally a drop-in concept (Proof's store interface in `doc-store-sqlite/src/index.ts:13–22` is just a bag of typed function references), but Postgres lets us:

- Use `JSONB` for op payloads with GIN indexing for filter queries
- Use `tsvector` over `documents.markdown` for the fast text search the right-side panel needs
- Use a single `BIGSERIAL` for the global event ID rather than per-document sequences (Proof uses per-doc — fine but more bookkeeping)
- Use SQL `NOTIFY` for server-internal long-poll wake-up so we don't busy-poll the ops table

**Why we diverge:** PageFly already runs on Postgres (Supabase). Adding SQLite would split the operational story. The Proof maintainers themselves split the store interface (`packages/doc-store-sqlite` is one of five packages — `docs/adr/2026-03-proof-sdk-public-core.md:13–18`) precisely so others can swap it.

### 2.2 No realtime: Hocuspocus / Yjs → polling only

**Proof:** Has Yjs collab via `server/collab.js` (`packages/doc-server/src/index.ts:3–4`). The `/edit/v2` response includes `collab.fragmentStatus` and `collab.markdownStatus` fields tracking whether the change has propagated to live Yjs peers (`docs/agent-docs.md:208–212, 273–277`). Rewrites are blocked when authenticated collab clients are connected (`LIVE_CLIENTS_PRESENT`, `agent-docs.md:295–297, 380–384`).

**Ours:** None of that exists. We never have "live authenticated collaborators" because there is no fragment-level sync. Other tabs see writes by polling `/events/pending` or refreshing `state`. The `collab.*` fields are dropped from our response shape; `LIVE_CLIENTS_PRESENT` is removed from the error enum.

**Why we diverge:** Async-only is locked (yrzhe decision, §0). Yjs + Hocuspocus is the single biggest cost in the Proof codebase (operationally + cognitively) and the agent loop doesn't need it. The cost of "another user doesn't see my edit for ≤5s" is acceptable for a docs/briefs use case.

### 2.3 Editor: Milkdown / ProseMirror plugins → Tiptap extensions

**Proof:** `packages/doc-editor/src/index.ts:4–6` re-exports `comments`, `marks`, `suggestions` plugins. These are ProseMirror plugins that hook into Milkdown's transactions to render decorations and dispatch ops.

**Ours:** Tiptap extensions for `CommentMark` and `SuggestionMark`. The data shape is the same (a mark with `id`, `by`, `createdAt`, `quote`, plus `kind` for suggestions). The plumbing is different: Tiptap's `addCommands` registers `tr.setMark(...)` commands; on a successful mutation response, we apply the mark optimistically; on a 409, we revert.

**Why we diverge:** PageFly is a React-first app with existing Tiptap usage in the design history (Wonder artboards). Switching to Milkdown would force a second editor framework into the codebase. Tiptap's mark API is rich enough — we don't lose anything by porting.

**Concrete implication:** the agent never sees ProseMirror JSON. Everything the agent reads/writes is markdown (matching Proof's `Accept: text/markdown` content-negotiation pattern, `agent-docs.md:46–56`). The Tiptap JSON form lives on the human-facing side only.

### 2.4 Multi-comment aggregation on the same range

**Proof:** Each `comment.add` is its own mark with its own ID (`packages/agent-bridge/src/index.ts:204–225` — replies and resolves go through `markId`). If five comments anchor to the same quote, the document has five overlapping marks. Proof's UI presumably stacks them in a sidebar; the data model does not group them.

**Ours:** Comments anchored to the **same resolved range** (same start/end after quote resolution) are grouped into a `comment_thread`. The mark in the editor renders a single bubble showing the count; opening the bubble reveals the thread. `comment.reply` already exists in Proof (a reply attaches to a `markId`); we reuse it but additionally let `comment.add` with the same anchor auto-create or auto-merge into a thread.

**Why we diverge:** PageFly will run multiple agents on the same doc (e.g., a copy agent + an SEO agent + a fact-check agent) — Proof typically runs one. Without aggregation, the editor margins fill up with overlapping highlights. Aggregation is the cheapest UX fix.

### 2.5 Single pending suggestion

**Proof:** No restriction. You can have N pending suggestions on the same doc, even overlapping. `suggestion.accept` (`AGENT_CONTRACT.md:130`) is the resolver.

**Ours:** Server enforces at most one suggestion with `status='pending'` per document. New `suggestion.add` while one is pending returns `409 PENDING_SUGGESTION_EXISTS` with the existing suggestion ID inlined so the caller can show "wait for the human to triage" UX.

**Why we diverge:** §0 decision. Reduces UX noise, makes the human's mental model "one popup at a time", and removes the conflict-detection complexity of overlapping pending edits.

### 2.6 Bridge routes folded into one path namespace

**Proof:** Mounts both the canonical routes (`/documents/:slug/ops`, `/documents/:slug/state`) AND a parallel "bridge" namespace (`/documents/:slug/bridge/state`, `/documents/:slug/bridge/comments`, etc.) — see `docs/agent-docs.md:14–22` and `packages/agent-bridge/src/index.ts:108–122`. The bridge is auth-scoped differently (see `bridgeRoutes` import).

**Ours:** Only one path: `/api/workspace/documents/:slug/...`. Auth scope is decided per-route by what role the bearer token carries (see §5.6). No parallel `/bridge/` namespace.

**Why we diverge:** The Proof "bridge" exists to give external agents a stable API surface independent of hosted-product changes. PageFly agents ARE first-party. One namespace reduces cognitive overhead.

### 2.7 `rewrite.apply` semantics

**Proof:** `rewrite.apply` replaces the entire document. Blocked when live collaborators present unless `force: true` (and `force` is ignored on hosted Proof). Disruptive — Proof tells agents to prefer `edit/v2` (`agent-docs.md:38, 380–384`).

**Ours:** `rewrite.apply` is **agent-forbidden by default** for v1. Only humans can issue it (via "Replace document" admin action). Agents requesting it get `403 REWRITE_FORBIDDEN_FOR_AGENT`. The op type is still in the enum so the same op log can carry both human and agent rewrites.

**Why we diverge:** Trust gradient. We have not yet earned the right to let an agent silently replace 100KB of human text. Revisit when the agent has demonstrated reliability.

### 2.8 Provenance storage: embedded YAML → relational

**Proof:** Recommends embedding provenance as YAML in an HTML comment at the bottom of the markdown file (`PROVENANCE-SPEC-v2.md:309–328`). This makes markdown files self-contained and portable.

**Ours:** Provenance lives in Postgres `document_revisions` + `provenance_spans` tables. Markdown stays clean. Export-to-markdown will optionally append the YAML block for portability (post-v1).

**Why we diverge:** We don't have a "share this markdown file" use case in v1. Postgres queries (e.g., "show every span Alice approved") are trivial relational; over embedded YAML they require a parse step.

---

## 3. New (not in Proof)

### 3.1 Multi-agent same-range comment thread aggregation

Already described in §2.4. Concretely: a `comment_threads` table keyed by `(document_id, anchor_hash)` where `anchor_hash = sha256(start_block_ref || start_offset || end_block_ref || end_offset)`. New `comment.add` ops with a matching hash append to the existing thread instead of creating a new one. The thread's `participants` list (denormalized JSON array of `by` strings) is updated atomically.

Why this is not in Proof: Proof was built around a single-agent (Claude) UX. Multi-agent collaboration on the same span is an emergent need we'll have from day one (copy agent + SEO agent + fact-check agent in the same Workspace).

### 3.2 `@-mention` parsing → agent invocation contract

PageFly's editor interprets `@AgentName` in any text node as an agent invocation. On document save (or on `Enter` after the mention), the server scans the diff for new `@<known_agent_id>` tokens and dispatches an agent invocation:

```
POST /api/workspace/documents/<slug>/agent/invoke
{
  "agent_id": "copy-coach",
  "trigger": "mention" | "ask_button",
  "context": { "block_ref": "b3", "selection_range": [10, 50] | null, "user_message": "tighten this" }
}
```

The agent worker reads the doc state, calls the LLM, and posts ops via the regular `/ops` endpoint. The invocation row is logged to `agent_invocations` for billing + observability.

Proof does not have this. Its `presence` endpoint and the `agent.id` field are orthogonal — they describe an agent that has already decided to act. We need the explicit "user pressed Ask, now act" trigger.

### 3.3 `suggestion.cancel`

Op type added on top of Proof's seven. Lets the agent retract a suggestion it created if it now has a better one and the human hasn't triaged yet. Required because of the single-pending-suggestion rule (§2.5) — without `cancel`, an agent that wants to revise its own suggestion has to wait for the human or hit `409 PENDING_SUGGESTION_EXISTS`.

Schema:

```json
{ "type": "suggestion.cancel", "by": "ai:copy-coach", "suggestion_id": "<uuid>" }
```

Behavior: only the original `by` author can cancel. Sets status to `cancelled`, leaves a record. Does not require human action.

### 3.4 Agent-invocation rate limiting per document

Per-document budget: max 50 agent ops/hour (configurable). Returns `429` with `Retry-After`. Proof has rate limiting in `429` mention only (`docs/proof.SKILL.md:144`) but no documented budget.

### 3.5 `RANGE_DRIFTED` error code

When the quote anchor still text-matches but the surrounding context has shifted enough that the resolved range hashes differently from `meta.context_hash` recorded at op-creation time. Lets the agent decide whether to retry vs ask the human. Built on top of Proof's hash-verification idea (`PROVENANCE-SPEC-v2.md:226–252`) but exposed as a distinct error vs `ANCHOR_NOT_FOUND` so the client can branch.

### 3.6 Disambiguation fields on quote selector

Proof's quote selector (`PROVENANCE-SPEC-v2.md:118–133`) is `{ quote: "text", fuzzy?: true }`. We add:

```json
{
  "quote": "the",
  "prefix": "in ",
  "suffix": " brief",
  "occurrence": 2
}
```

`prefix`+`suffix`: text just before/after the target span. Used to disambiguate when the same quote appears multiple times. Agents are encouraged to provide ~20 chars on each side.

`occurrence`: 1-based ordinal as a fallback if prefix/suffix collide too. Resolver order: (1) prefix+suffix exact, (2) prefix-only, (3) `occurrence`-th match. If still ambiguous → `ANCHOR_NOT_FOUND` with `candidates: [...]` listing all matches so the agent can re-pick.

### 3.7 Comment thread "participants" denormalization

Each comment thread row carries `participants: jsonb` (array of `by` strings) for quick "who's in this thread" rendering without joining `comments` rows. Updated transactionally on `comment.add`/`comment.reply`.

### 3.8 Per-document "pinned context" for agents

When invoking an agent, a doc may have stored "pinned context" (e.g., brand voice, prior-decision log) attached at `documents.pinned_context: jsonb`. The agent worker fetches this and prepends to the system prompt. Not part of Proof — this is PageFly's "every agent should know the brand voice" need.

---

## 3a. Anchor resolution algorithm (detailed)

This section is normative for the implementation of `resolve_anchor()` server-side. It is the single piece of logic the spec writer most expects to be implemented incorrectly.

### Inputs

- `selector`: `{ quote: str, prefix?: str, suffix?: str, occurrence?: int, fuzzy?: bool }`
- `markdown`: the document's current markdown
- `block_index`: a precomputed list of `(block_ref, block_start_offset, block_end_offset, block_markdown)` tuples derived from the snapshot

### Algorithm

```
def resolve_anchor(selector, markdown, block_index) -> Resolution:
    quote = selector["quote"]
    prefix = selector.get("prefix") or ""
    suffix = selector.get("suffix") or ""
    occurrence = selector.get("occurrence")  # 1-based, optional
    fuzzy = selector.get("fuzzy", False)

    # Step 1: find ALL exact occurrences of `quote`.
    matches = find_all(markdown, quote)
    if not matches and fuzzy:
        matches = find_all_fuzzy(markdown, quote)  # NFKC + collapse-ws + diacritic-strip
    if not matches:
        raise AnchorNotFound(reason="quote_not_found", candidates=[])

    # Step 2: filter by prefix+suffix if provided.
    if prefix or suffix:
        filtered = [
            m for m in matches
            if (not prefix or markdown[max(0, m.start - len(prefix)):m.start].endswith(prefix))
            and (not suffix or markdown[m.end:m.end + len(suffix)].startswith(suffix))
        ]
        if filtered:
            matches = filtered

    # Step 3: if still ambiguous and `occurrence` given, pick that one.
    if len(matches) > 1 and occurrence is not None:
        if 1 <= occurrence <= len(matches):
            matches = [matches[occurrence - 1]]

    # Step 4: if exactly one, resolve to a block_ref + offset-within-block.
    if len(matches) == 1:
        m = matches[0]
        block = _block_containing(block_index, m.start)
        return Resolution(
            block_ref=block.ref,
            range_start=m.start - block.start_offset,
            range_end=m.end - block.start_offset,
            absolute_start=m.start,
            absolute_end=m.end,
            content_hash=sha256(quote),
        )

    # Step 5: still ambiguous → return candidates.
    raise AnchorNotFound(
        reason="ambiguous",
        candidates=[
            {"block_ref": _block_containing(block_index, m.start).ref,
             "absolute_start": m.start, "absolute_end": m.end}
            for m in matches[:10]   # cap to avoid huge response
        ],
    )
```

### Notes

- **Step 1's `find_all`** must search in the *clean* markdown — not in any HTML-annotated derivative. Proof learned this the hard way (`agent-docs.md:374–378`); the `<span data-proof="authored">` tags broke their search until they added a strip-then-search fallback. Since we don't have those tags (provenance lives in Postgres), we always search clean text.
- **Fuzzy** is opt-in. We default `fuzzy=False` because false positives in fuzzy matching are worse than `ANCHOR_NOT_FOUND`.
- **`occurrence` after prefix/suffix filtering**: occurrence is the index *after* prefix/suffix narrowing, not before. This way an agent that says "the second occurrence in the Intro section" doesn't break when an unrelated occurrence is added before the Intro.
- **`content_hash` returned**: stored in the materialized `comments`/`suggestions` row. On future renders, we recompute the hash of the current text at the resolved range; mismatch → mark as drifted (UI shows "this comment may no longer apply"). This is Proof's hash-cache pattern (`PROVENANCE-SPEC-v2.md:226–252`).
- **`_block_containing`** is a binary search over `block_index` since blocks are non-overlapping.

### Drift detection (read path)

When `/state` returns the materialized comments/suggestions, the server runs:

```
for row in comments_or_suggestions:
    current_text = markdown[abs_start:abs_end]
    if sha256(current_text) != row.content_hash:
        row.status_hint = "drifted"
```

The frontend renders drifted marks with a small warning glyph but does not move them. Resolving drift is a human action: re-anchor or resolve the thread.

---

## 3b. Op application: server-side processing pipeline

For every `POST /ops`, FastAPI runs the following pipeline. This is the contract every op handler conforms to.

```
1. Auth: resolve Principal from Bearer token.
   - Reject 401 if no token, 403 if token's role insufficient for op.type.

2. Idempotency check:
   - If Idempotency-Key present:
     - Look up (document_id, idempotency_key) in `ops`.
     - If exists with same payload_hash → return cached response.
     - If exists with different payload_hash → 409 IDEMPOTENCY_KEY_REUSED.
   - If absent and caller is agent → 400 IDEMPOTENCY_KEY_REQUIRED.

3. Payload validation (Pydantic discriminated union by `type`).
   - Reject 422 INVALID_PAYLOAD on schema failure.

4. Optimistic-lock check (only ops that mutate text):
   - For suggestion.accept, rewrite.apply: require `base_revision`.
   - SELECT revision FROM documents WHERE id=:id FOR UPDATE.
   - If row.revision != base_revision → 409 STALE_REVISION (with snapshot inline).

5. Op-specific handler runs in a single transaction:
   - Inserts into `ops` (always).
   - Inserts/updates the materialized table (`comments`, `comment_threads`, `suggestions`).
   - For text-mutating ops: UPDATE documents SET markdown=..., revision=revision+1.
   - Inserts into `document_revisions`.

6. Provenance side-effects (best-effort, non-blocking):
   - For text-additive ops: insert a `provenance_spans` row with origin from `by`.
   - For human-approved suggestions: insert a `provenance_reviews` row at level=approved.

7. Response envelope (5.10) returned. Event row is naturally the inserted op row (no separate event log).

8. NOTIFY `events:<document_id>` triggers any waiting long-poll connections to wake up.
```

### Op-specific handlers (concise pseudocode)

```python
def handle_comment_add(op):
    selector = op.payload["selector"]
    res = resolve_anchor(selector, doc.markdown, doc.block_index)
    anchor_hash = sha256(f"{res.block_ref}|{res.range_start}|{res.range_end}")
    thread = comment_threads.upsert_by_anchor(doc.id, anchor_hash, res, by=op.by)
    comments.insert(thread_id=thread.id, op_id=op.id, body=op.payload["text"], by=op.by)
    thread.participants = sorted(set(thread.participants + [op.by]))
    return {"thread_id": thread.id, "comment_id": ..., "drifted": False}

def handle_comment_reply(op):
    thread = comment_threads.get(op.payload["thread_id"])
    if thread.status == "resolved":
        raise THREAD_RESOLVED
    comments.insert(thread_id=thread.id, op_id=op.id, body=op.payload["text"], by=op.by)
    thread.participants = sorted(set(thread.participants + [op.by]))

def handle_comment_resolve(op):
    thread = comment_threads.get(op.payload["thread_id"])
    thread.status = "resolved"; thread.resolved_by = op.by; thread.resolved_at = now()

def handle_suggestion_add(op):
    # Single-pending check is enforced by the partial unique index;
    # we let Postgres throw IntegrityError and translate to PENDING_SUGGESTION_EXISTS.
    res = resolve_anchor(op.payload["selector"], doc.markdown, doc.block_index)
    try:
        suggestions.insert(
            document_id=doc.id, op_id=op.id, kind=op.payload["kind"], by=op.by,
            quote=res.quote, block_ref=res.block_ref,
            range_start=res.range_start, range_end=res.range_end,
            new_content=op.payload.get("content"), status="pending",
        )
    except IntegrityError:
        existing = suggestions.find(document_id=doc.id, status="pending")
        raise PENDING_SUGGESTION_EXISTS(pending_suggestion=existing.id)

def handle_suggestion_accept(op):
    s = suggestions.get(op.payload["suggestion_id"])
    if s.status != "pending": raise SUGGESTION_NOT_PENDING
    if op.base_revision != doc.revision: raise STALE_REVISION
    # Apply the textual change.
    new_md = apply_change(doc.markdown, s)  # uses s.range_start/end + s.new_content
    doc.markdown = new_md; doc.revision += 1
    s.status = "accepted"; s.resolved_by = op.by; s.resolved_at = now()
    document_revisions.insert(doc.id, doc.revision, new_md, sha256(new_md), op.id)
    # Provenance: insert span with origin=ai, plus a level=approved review by the human.
    span = provenance_spans.insert(...)
    provenance_reviews.insert(span.id, level="approved", by=op.by, ...)

def handle_suggestion_reject(op):
    s = suggestions.get(op.payload["suggestion_id"])
    if s.status != "pending": raise SUGGESTION_NOT_PENDING
    s.status = "rejected"; s.resolved_by = op.by; s.resolved_at = now()
    s.rejection_reason = op.payload.get("reason")

def handle_suggestion_cancel(op):
    s = suggestions.get(op.payload["suggestion_id"])
    if s.status != "pending": raise SUGGESTION_NOT_PENDING
    if s.by != op.by: raise FORBIDDEN  # only original author can cancel
    s.status = "cancelled"

def handle_rewrite_apply(op):
    if op.by.startswith("ai:"): raise REWRITE_FORBIDDEN_FOR_AGENT
    if op.base_revision != doc.revision: raise STALE_REVISION
    # Rejecting all pending suggestions is a side-effect of rewrite.
    suggestions.update_all_pending(doc.id, status="superseded")
    doc.markdown = op.payload["content"]; doc.revision += 1
    document_revisions.insert(...)
```

---

## 4. DB schema

SQLAlchemy 2.x async style. All times are `TIMESTAMPTZ`. All ID columns are `UUID` (gen_random_uuid()) unless noted. Postgres 16.

### 4.1 `documents`

```python
class Document(Base):
    __tablename__ = "documents"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    slug          = Column(Text, nullable=False, unique=True, index=True)  # 8-char base62, like Proof
    workspace_id  = Column(UUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    title         = Column(Text, nullable=False, default="Untitled")
    markdown      = Column(Text, nullable=False, default="")              # canonical text
    revision      = Column(BigInteger, nullable=False, default=0)         # bumps on every successful mutation
    pinned_context= Column(JSONB, nullable=True)                          # see §3.8
    owner_id      = Column(UUID, ForeignKey("users.id"), nullable=False)
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    deleted_at    = Column(TIMESTAMPTZ, nullable=True)                    # soft delete

    # Full-text search
    __table_args__ = (
        Index("documents_markdown_tsv", text("to_tsvector('english', markdown)"), postgresql_using="gin"),
    )
```

**Why `revision` is a column on the doc, not derived:** matches Proof's `baseRevision` contract (`agent-docs.md:259–272`). Lets us do `UPDATE documents SET revision=revision+1 WHERE id=:id AND revision=:base_revision RETURNING revision` for atomic optimistic-lock check.

### 4.2 `ops` (append-only log)

```python
class Op(Base):
    __tablename__ = "ops"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)  # global monotonic, also serves as event cursor
    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    type          = Column(Text, nullable=False)            # "comment.add" | "suggestion.accept" | ...
    by            = Column(Text, nullable=False)            # "ai:claude" | "human:<uid>"
    payload       = Column(JSONB, nullable=False)           # op-specific fields
    idempotency_key = Column(UUID, nullable=True)
    payload_hash  = Column(Text, nullable=False)            # sha256 of canonicalized payload, for IDEMPOTENCY_KEY_REUSED check
    base_revision = Column(BigInteger, nullable=True)       # filled when caller passed it
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("document_id", "idempotency_key", name="ops_idempotency_uniq"),
        Index("ops_document_id_id_idx", "document_id", "id"),  # cursor scan: WHERE document_id=? AND id>? ORDER BY id
        Index("ops_payload_gin", "payload", postgresql_using="gin"),
    )
```

**Append-only.** No UPDATE, no DELETE. Compaction is a future concern (Proof has no compaction either).

`id` doubles as the global event cursor (matches Proof's "after=<id>" semantics, `AGENT_CONTRACT.md:138`). Per-document cursor scans use the composite index.

### 4.3 `comment_threads`

```python
class CommentThread(Base):
    __tablename__ = "comment_threads"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    anchor_hash   = Column(Text, nullable=False)            # sha256(block_ref + offsets) — see §3.1
    quote         = Column(Text, nullable=False)            # exact text at creation
    block_ref     = Column(Text, nullable=False)            # "b3"
    range_start   = Column(Integer, nullable=False)         # offset within block at creation
    range_end     = Column(Integer, nullable=False)
    status        = Column(Text, nullable=False, default="open")  # open | resolved
    participants  = Column(JSONB, nullable=False, default=list)   # ["ai:copy-coach", "human:abc..."]
    created_by    = Column(Text, nullable=False)            # the `by` of the first comment
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    resolved_at   = Column(TIMESTAMPTZ, nullable=True)
    resolved_by   = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("document_id", "anchor_hash", name="comment_threads_anchor_uniq"),
        Index("comment_threads_status_idx", "document_id", "status"),
    )
```

**Anchor uniqueness** is what enforces aggregation: a second `comment.add` with the same `anchor_hash` is appended to this thread, not into a new thread.

### 4.4 `comments` (materialized)

```python
class Comment(Base):
    __tablename__ = "comments"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    thread_id     = Column(UUID, ForeignKey("comment_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    op_id         = Column(BigInteger, ForeignKey("ops.id"), nullable=False)
    body          = Column(Text, nullable=False)
    by            = Column(Text, nullable=False)
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("comments_thread_created_idx", "thread_id", "created_at"),
    )
```

Replies are just rows on the same thread. No separate `comment_replies` table (Proof's `comment.reply` op also doesn't materialize separately — it's the same mark with a `parentMarkId`).

### 4.5 `suggestions` (materialized)

```python
class Suggestion(Base):
    __tablename__ = "suggestions"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    op_id         = Column(BigInteger, ForeignKey("ops.id"), nullable=False)
    kind          = Column(Text, nullable=False)            # replace | insert | delete
    quote         = Column(Text, nullable=False)
    prefix        = Column(Text, nullable=True)
    suffix        = Column(Text, nullable=True)
    block_ref     = Column(Text, nullable=False)
    range_start   = Column(Integer, nullable=False)
    range_end     = Column(Integer, nullable=False)
    new_content   = Column(Text, nullable=True)             # null for kind=delete
    status        = Column(Text, nullable=False, default="pending")  # pending | accepted | rejected | cancelled | superseded
    by            = Column(Text, nullable=False)            # author
    resolved_by   = Column(Text, nullable=True)             # who accepted/rejected
    resolved_at   = Column(TIMESTAMPTZ, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        # Single-pending-suggestion rule (§2.5):
        Index(
            "suggestions_one_pending_per_doc",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("suggestions_status_idx", "document_id", "status"),
    )
```

**The partial unique index is how we enforce the single-pending rule at the DB level.** Postgres lets us index `WHERE status='pending'`; trying to insert a second pending suggestion violates the constraint and we return `409 PENDING_SUGGESTION_EXISTS`. This is more reliable than an application-level check.

### 4.6 `document_revisions` (snapshot history)

```python
class DocumentRevision(Base):
    __tablename__ = "document_revisions"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    revision      = Column(BigInteger, nullable=False)
    markdown      = Column(Text, nullable=False)
    content_hash  = Column(Text, nullable=False)            # sha256, used by provenance staleness check
    op_id         = Column(BigInteger, ForeignKey("ops.id"), nullable=True)  # null only for revision 0
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("document_id", "revision", name="document_revisions_uniq"),
    )
```

**Snapshots policy:** every successful mutation writes a row. Older rows are GC'd by a nightly job (keep last 100 + every 24h marker). Reconstruction (Proof's "ops + snapshots" model) is hybrid — we can replay ops since the latest snapshot, OR jump straight to the latest `markdown` via the `documents.markdown` column. The revision table is for provenance/audit, not for replay.

### 4.7 `provenance_spans`

```python
class ProvenanceSpan(Base):
    __tablename__ = "provenance_spans"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    revision      = Column(BigInteger, nullable=False)      # the revision at which this span was created
    selector      = Column(JSONB, nullable=False)           # { quote, prefix, suffix, occurrence } or { anchor: "..." }
    origin        = Column(Text, nullable=False)            # human | ai (denormalized from `by` prefix)
    by            = Column(Text, nullable=False)
    basis         = Column(Text, nullable=True)             # described | inferred | suggested | null (free-text in v1)
    basis_detail  = Column(Text, nullable=True)
    content_hash  = Column(Text, nullable=False)            # hash of the resolved range at creation
    sources       = Column(JSONB, nullable=True)            # { type, uri/path/content_hash }[]
    meta          = Column(JSONB, nullable=True)            # model, inserted_at, etc.
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("provenance_document_revision_idx", "document_id", "revision"),
    )
```

### 4.8 `provenance_reviews`

```python
class ProvenanceReview(Base):
    __tablename__ = "provenance_reviews"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    span_id       = Column(UUID, ForeignKey("provenance_spans.id", ondelete="CASCADE"), nullable=False, index=True)
    level         = Column(Text, nullable=False)            # skimmed | flagged | approved
    by            = Column(Text, nullable=False)
    reviewed_hash = Column(Text, nullable=False)            # snapshot hash at review time
    notes         = Column(Text, nullable=True)
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("provenance_reviews_span_idx", "span_id", "created_at"),
    )
```

The review stack (Proof PROVENANCE-SPEC-v2.md:174–198) is just rows ordered by `created_at`. `getEffectiveReviewLevel(span)` is a SELECT that filters out rows where `reviewed_hash != current_content_hash` and picks the highest level.

**Review level rules (enforced server-side, copied from Proof PROVENANCE-SPEC-v2.md:193–197):**
- `skimmed`: AI or human may add
- `flagged`: human only
- `approved`: human only, AND `by` of the review must differ from the `by` of the span (no self-approval; copied from Proof's "AI cannot approve its own content")

### 4.9 `agent_invocations`

```python
class AgentInvocation(Base):
    __tablename__ = "agent_invocations"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id      = Column(Text, nullable=False)
    trigger       = Column(Text, nullable=False)            # mention | ask_button | api
    context       = Column(JSONB, nullable=False)
    invoked_by    = Column(Text, nullable=False)            # user who triggered (or "system")
    status        = Column(Text, nullable=False, default="queued")  # queued | running | succeeded | failed | cancelled
    started_at    = Column(TIMESTAMPTZ, nullable=True)
    finished_at   = Column(TIMESTAMPTZ, nullable=True)
    error         = Column(Text, nullable=True)
    cost_tokens   = Column(Integer, nullable=True)
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("agent_invocations_doc_status_idx", "document_id", "status"),
        Index("agent_invocations_created_idx", "created_at"),
    )
```

### 4.10 `document_access_tokens`

```python
class DocumentAccessToken(Base):
    __tablename__ = "document_access_tokens"

    id            = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash    = Column(Text, nullable=False, unique=True)  # sha256 of the bearer token
    role          = Column(Text, nullable=False)               # viewer | commenter | editor | owner
    issued_to     = Column(Text, nullable=True)                # "ai:agent_id" or "human:<uid>" — informational
    expires_at    = Column(TIMESTAMPTZ, nullable=True)
    revoked_at    = Column(TIMESTAMPTZ, nullable=True)
    created_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    last_used_at  = Column(TIMESTAMPTZ, nullable=True)
```

Mirrors Proof's `accessToken` model (`AGENT_CONTRACT.md:80–89`). `ownerSecret` is a token with role=`owner`; `accessToken` is `viewer/commenter/editor`.

### 4.11 `event_cursors` (per-subscriber ack tracking)

```python
class EventCursor(Base):
    __tablename__ = "event_cursors"

    document_id   = Column(UUID, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    subscriber_id = Column(Text, primary_key=True)          # "ai:agent_id" or "human:<uid>"
    last_ack_id   = Column(BigInteger, nullable=False, default=0)
    updated_at    = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
```

Lets us answer "what's the oldest unacked event" cheaply for compaction/health metrics. Proof's `events/ack` endpoint (`AGENT_CONTRACT.md:139`) uses the same `upToId` semantics.

### 4.12 Foreign-key/index summary

| Table | FK in | FK out |
|---|---|---|
| documents | (none) | workspaces, users |
| ops | comments, suggestions, document_revisions | documents |
| comment_threads | comments | documents |
| comments | (none) | comment_threads, ops |
| suggestions | (none) | documents, ops |
| document_revisions | (none) | documents, ops |
| provenance_spans | provenance_reviews | documents |
| provenance_reviews | (none) | provenance_spans |
| agent_invocations | (none) | documents |
| document_access_tokens | (none) | documents |
| event_cursors | (none) | documents |

All `ON DELETE CASCADE` is set so deleting a document cleans up everything below it. Documents themselves are soft-deleted (`deleted_at`).

---

## 5. API endpoints

All endpoints are prefixed with `/api/workspace`. JSON request/response bodies. Error format:

```json
{ "error": { "code": "PENDING_SUGGESTION_EXISTS", "message": "...", "retry_with": { ... } } }
```

Auth: `Authorization: Bearer <jwt-or-share-token>`. JWT is a PageFly user session; share token is row-keyed via `document_access_tokens.token_hash`. Both flow through one FastAPI dependency that returns a `Principal { kind: 'user' | 'agent', id, role_on_doc }`.

Idempotency: every mutating route accepts `Idempotency-Key`. Required for agents (per §6 stage). Optional but recommended for humans. Header alias `X-Idempotency-Key` accepted.

### 5.1 Document CRUD

| Method | Path | Purpose | Caller |
|---|---|---|---|
| POST | `/documents` | Create a new document. Body: `{ title?, markdown?, workspace_id }`. Response includes `slug`, `revision=0`, `_links`. | human |
| GET | `/documents/:slug` | Discovery-friendly read. With `Accept: application/json` returns `{ title, markdown, revision, _links }`; with `Accept: text/markdown` returns raw markdown. Mirrors Proof content-negotiation (`agent-docs.md:46–56`). | human, agent |
| GET | `/documents/:slug/state` | Full state read: title, markdown, revision, current pending suggestion (if any), open thread count, capability hints, `agent` block (`titleApi`, `stateApi`, `auth`). | human, agent |
| GET | `/documents/:slug/snapshot` | Block-keyed snapshot: `{ revision, blocks: [{ ref: "b1", markdown, type }] }`. | human, agent |
| PUT | `/documents/:slug/title` | Update title. Body `{ title }`. | human, agent (commenter+) |
| DELETE | `/documents/:slug` | Soft-delete. | human (owner) |

### 5.2 Ops endpoint (the agent's entry point)

| Method | Path | Purpose | Caller |
|---|---|---|---|
| POST | `/documents/:slug/ops` | Apply a single op. Body is the op envelope: `{ type, by, ...op_specific, base_revision? }`. Headers: `Idempotency-Key`, `X-Agent-Id`. Response: `{ revision, op_id, applied: true, materialized: { thread_id?, comment_id?, suggestion_id?, ... } }`. | human, agent |

**Op-type-specific request schemas** (request body shape passed inside the `/ops` envelope):

```jsonc
// comment.add
{ "type": "comment.add", "by": "ai:claude",
  "selector": { "quote": "old text", "prefix": "in ", "suffix": " brief", "occurrence": 1 },
  "text": "Consider tightening this.",
  "in_reply_to_thread_id": null }                     // optional; if set, skips anchor matching

// comment.reply
{ "type": "comment.reply", "by": "human:abc",
  "thread_id": "<uuid>", "text": "agreed" }

// comment.resolve
{ "type": "comment.resolve", "by": "human:abc", "thread_id": "<uuid>" }

// suggestion.add
{ "type": "suggestion.add", "by": "ai:claude",
  "kind": "replace",                                  // replace | insert | delete
  "selector": { "quote": "old text", "prefix": "...", "suffix": "..." },
  "content": "new text",                              // null for kind=delete
  "rationale": "shorter and stronger" }

// suggestion.accept
{ "type": "suggestion.accept", "by": "human:abc",
  "suggestion_id": "<uuid>",
  "base_revision": 42 }                               // required to detect drift

// suggestion.reject
{ "type": "suggestion.reject", "by": "human:abc",
  "suggestion_id": "<uuid>", "reason": "off-brand" }

// suggestion.cancel (PageFly-only)
{ "type": "suggestion.cancel", "by": "ai:claude", "suggestion_id": "<uuid>" }

// rewrite.apply (humans only in v1)
{ "type": "rewrite.apply", "by": "human:abc",
  "content": "# New markdown...", "base_revision": 42 }
```

**Op interdependency:** `suggestion.accept` / `.reject` / `.cancel` reference the `suggestion.add` they target via `suggestion_id` (the UUID returned from the `add`). `comment.reply` / `.resolve` reference `thread_id`. The server dereferences these to row IDs in `suggestions` / `comment_threads`; if the row doesn't exist or status is wrong, returns `404` or `409 SUGGESTION_NOT_PENDING`.

### 5.3 Edit endpoints (humans only, internal autosave)

These are the ProseMirror/Tiptap autosave path. **Not exposed to agents** — agents must use `/ops`. Mirrors Proof `edit/v2` shape (`agent-docs.md:238–281`).

| Method | Path | Purpose | Caller |
|---|---|---|---|
| POST | `/documents/:slug/edit/v2` | Block-level structural edits with `baseRevision`. Body `{ by, base_revision, operations: [{ op, ref, blocks?/block? }] }`. 409 `STALE_REVISION` includes latest snapshot inline. | human only |
| POST | `/documents/:slug/edit` | Simpler text-find/replace. Body `{ by, base_updated_at, operations: [{ op: "append"|"replace"|"insert", section?/search?/after?, content }] }`. | human only |

### 5.4 Events (long-poll)

| Method | Path | Purpose | Caller |
|---|---|---|---|
| GET | `/documents/:slug/events/pending?after=<id>&limit=100&hold=25` | Returns events with `id > after`. If none, holds the request open up to `hold` seconds (default 25, max 60). Response: `{ events: [{ id, type, by, payload, created_at }], cursor: <max_id> }`. | human, agent |
| POST | `/documents/:slug/events/ack` | Persist that subscriber has consumed up to `up_to_id`. Body `{ up_to_id, by }`. Used for compaction telemetry only — does not delete events. | human, agent |

**Replay behavior:** if an agent misses events (long downtime), it just resumes with its last known cursor. The ops table is append-only and never compacted. Agent worker keeps its `last_ack_id` in `event_cursors`.

### 5.5 Agent invocation

| Method | Path | Purpose | Caller |
|---|---|---|---|
| POST | `/documents/:slug/agent/invoke` | Trigger an agent. Body `{ agent_id, trigger, context }`. Response: `{ invocation_id, status: "queued" }`. The actual op writes happen later through `/ops` from the worker. | human |
| GET | `/documents/:slug/agent/invocations?status=&limit=` | List recent invocations. | human |
| POST | `/documents/:slug/agent/invocations/:id/cancel` | Cancel a queued or running invocation. Sets status=cancelled; the worker checks this between LLM turns. | human |

### 5.6 Auth / share / tokens

| Method | Path | Purpose | Caller |
|---|---|---|---|
| POST | `/documents/:slug/access-tokens` | Mint a share token. Body `{ role: "viewer"|"commenter"|"editor", expires_at?, issued_to? }`. Response includes the cleartext token ONCE. | human (owner) |
| DELETE | `/documents/:slug/access-tokens/:id` | Revoke. | human (owner) |
| GET | `/documents/:slug/access-tokens` | List (without cleartext). | human (owner) |

### 5.7 Provenance read

| Method | Path | Purpose | Caller |
|---|---|---|---|
| GET | `/documents/:slug/provenance?revision=` | Returns spans + reviews for a revision (default current). | human, agent |
| POST | `/documents/:slug/provenance/:span_id/reviews` | Add a review (`{ level, notes? }`). 403 if level=approved and `by` matches span's `by`. | human, agent (skimmed only) |

### 5.8 Per-route caller matrix (auth scope)

| Caller role | docs CRUD | /ops | /edit, /edit/v2 | /events | /agent/invoke | /access-tokens |
|---|---|---|---|---|---|---|
| anonymous | — | — | — | — | — | — |
| viewer | GET only | — | — | GET | — | — |
| commenter | GET only | comment.* only | — | GET | invoke (if member) | — |
| editor | GET, PUT title | all except rewrite.apply | yes | GET | invoke | — |
| owner | full | all | yes | full | full | full |
| agent (kind=agent, role≤editor) | GET only | comment.*, suggestion.{add,cancel} | — | GET | — | — |

**Agents are intentionally never editor/owner.** They cannot `rewrite.apply`, cannot `suggestion.accept` (that's the human's call), cannot mint share tokens, cannot delete docs. This is enforced both by the JWT scope and by `/ops` payload validation.

### 5.9 Rate limiting

Per-document, per-`Principal`:
- humans: 600 ops/hour soft, 1200/hour hard (429 with `Retry-After`)
- agents: 50 ops/hour per agent_id, 200/hour per document across all agents

Implemented as Redis counters with TTL; falls back to in-memory bucket if Redis unavailable.

### 5.10 Response envelope

Every successful mutation:

```json
{
  "ok": true,
  "revision": 43,
  "op_id": 12087,
  "materialized": {
    "comment_id": "...",
    "thread_id": "...",
    "suggestion_id": "..."
  },
  "_links": {
    "state": "/api/workspace/documents/<slug>/state",
    "events": "/api/workspace/documents/<slug>/events/pending?after=12087"
  }
}
```

The `revision` field is what the client uses as its next `base_revision`.

---

## 6. Frontend integration notes

### 6.1 Tiptap mark extensions

Two custom marks:

- **`CommentMark`** — `name: "commentMark"`, attrs: `{ thread_id, count, status }`. Renders an inline highlight + badge with the count. Click opens the thread sidebar.
- **`SuggestionMark`** — `name: "suggestionMark"`, attrs: `{ suggestion_id, kind, by, status }`. Renders strikethrough (delete), underline (insert), or both (replace). The popover shows `before`/`after` and Accept/Reject buttons.

Marks are **read-only from the editor's perspective.** They are applied to the doc only after a successful `/ops` round-trip materializes them. The editor never creates a mark optimistically.

This means: when the agent posts a comment, the user's editor learns about it via either (a) the long-poll event arriving, or (b) the user re-reading state. There is no peer-to-peer mark sync. This is fine because async-only is the design.

Equivalent Proof code path: `packages/doc-editor/src/index.ts:4–6` re-exports `comments.ts` and `suggestions.ts` plugins, which run against the live Yjs doc. We do the same logical thing but driven by polled state.

### 6.2 The right-side Copilot panel

Sticky panel on the right. Three modes:

1. **Idle** — shows a list of agents available in the workspace; user clicks one + types a prompt → `POST /agent/invoke`.
2. **Working** — shows the agent's status (from `agent_invocations.status` polled every 2s + the long-poll event stream). Includes a "Cancel" button.
3. **Triage** — when there's a pending suggestion, the panel shows the diff with Accept/Reject. Pressing Accept dispatches `suggestion.accept`; Reject dispatches `suggestion.reject`.

Data flow: panel subscribes to `/events/pending` for the active doc. Every event of type `suggestion.*` updates the panel. Every event of type `comment.*` updates the comment sidebar (separate component).

### 6.3 The comment sidebar

Vertical list of `comment_threads` for the active doc, sorted by document position (resolved from `block_ref` + `range_start`). Each thread item shows:

- The quote text
- The participants list (avatars from `participants` JSONB)
- The latest reply
- A status badge (open / resolved)

Clicking scrolls the editor to the thread's range and opens the inline popover.

### 6.4 Optimistic vs server-authoritative state

| Action | Optimistic? | Why |
|---|---|---|
| Type a character | Yes (Tiptap default) | Local edit; autosave debounces and posts `/edit/v2`. On 409, revert and re-fetch. |
| Add a comment from UI | No | The CommentMark only appears after the server returns the `thread_id`. Latency hit ~150ms — acceptable. |
| Accept a suggestion | Yes | The mark disappears immediately; the underlying text swaps when the response arrives. On failure, restore. |
| Resolve a thread | Yes | Status flips locally; on failure, flip back. |

### 6.5 Markdown ↔ Tiptap JSON conversion

Stored canonical: markdown (`documents.markdown`).

On open: server returns markdown; client parses with a Tiptap-compatible markdown parser (e.g., `tiptap-markdown` extension). Marks (CommentMark/SuggestionMark) are NOT in the markdown — they are layered on top from the `/state` response's `comment_threads` and `pending_suggestion` arrays.

On save: client serializes Tiptap JSON back to markdown via the same extension; sends to `/edit/v2`. The server treats the markdown as authoritative and does not store Tiptap JSON.

This matches Proof's "markdown is the projection" model (`agent-docs.md:208–212`).

---

## 6a. Agent worker design

The agent worker is the process that turns "user pressed Ask" or "user typed @AgentName" into actual `/ops` writes. Recommended stack: **arq** (async Redis-queue) workers, separate process, same Python codebase.

### Lifecycle of one invocation

```
1. POST /agent/invoke creates row in agent_invocations (status=queued).
   - Enqueues a job in Redis: { invocation_id, document_id, agent_id }.
2. arq worker picks up the job.
   - SELECT FOR UPDATE the invocation row, set status=running, started_at=now().
   - Re-fetch the doc state (markdown + open threads + pending suggestion).
3. Worker constructs the system prompt:
   - Brand-voice + workspace pinned_context + agent's own profile prompt.
4. Worker calls Anthropic Messages API with the doc state + user_message.
   - Tool-use mode enabled with these tools:
     - propose_comment(selector, text)
     - propose_suggestion(kind, selector, content, rationale)
     - cancel_pending_suggestion(suggestion_id)
   - Each tool call maps directly to a /ops POST.
5. For each tool call the LLM returns:
   - Worker POSTs to /api/workspace/documents/<slug>/ops with by="ai:<agent_id>",
     Idempotency-Key=<deterministic from invocation_id + tool_call_index>.
   - On 409 PENDING_SUGGESTION_EXISTS: worker decides whether to cancel its
     own pending suggestion first or abort. Default: abort with note.
   - On 409 ANCHOR_NOT_FOUND with candidates: worker re-prompts the LLM
     showing the candidate list, asks it to re-pick. Max 2 retries per anchor.
   - On 429: respect Retry-After.
6. Worker sets agent_invocations.status=succeeded (or failed with error).
   - Logs cost_tokens.
7. Cancellation: worker checks agent_invocations.status between LLM turns;
   if it's been flipped to cancelled, exits gracefully without further /ops.
```

### Why this isolation matters

- The web FastAPI process never blocks on Anthropic. Web stays responsive even when the LLM is slow.
- One stuck LLM call can't hold a Postgres transaction (worker opens a fresh conn per `/ops`).
- Horizontal scaling: more worker processes = more concurrent agents.

### What the worker does NOT do

- Long-poll `/events/pending` waiting for the human's response. The agent loop is **one-shot** per invocation. Human triage of the suggestion is decoupled — when accepted, the worker is not notified (the doc just changes and the human can re-invoke the agent if needed).
- Edit text directly via `/edit/v2`. Agents only see `/ops`.
- Mutate any other tables. Worker has the same `agent` Principal as a remote agent calling our HTTP API.

### Tool-call schemas (LLM side)

```json
// propose_comment
{
  "name": "propose_comment",
  "description": "Add a comment anchored to a quote in the document.",
  "input_schema": {
    "type": "object",
    "required": ["quote", "text"],
    "properties": {
      "quote": { "type": "string", "description": "Exact text from doc." },
      "prefix": { "type": "string", "description": "~20 chars before quote, for disambiguation." },
      "suffix": { "type": "string", "description": "~20 chars after quote." },
      "text": { "type": "string", "description": "The comment body." }
    }
  }
}

// propose_suggestion
{
  "name": "propose_suggestion",
  "input_schema": {
    "type": "object",
    "required": ["kind", "quote", "rationale"],
    "properties": {
      "kind": { "type": "string", "enum": ["replace", "insert", "delete"] },
      "quote": { "type": "string" },
      "prefix": { "type": "string" },
      "suffix": { "type": "string" },
      "content": { "type": "string", "description": "New text (omit for kind=delete)." },
      "rationale": { "type": "string", "description": "Why this change." }
    }
  }
}

// cancel_pending_suggestion
{
  "name": "cancel_pending_suggestion",
  "input_schema": {
    "type": "object",
    "required": ["suggestion_id"],
    "properties": { "suggestion_id": { "type": "string", "format": "uuid" } }
  }
}
```

The worker is responsible for validating these tool calls match Pydantic schemas before forwarding to `/ops`.

---

## 6b. Event flow end-to-end

How a single agent comment shows up in the human's editor:

```
1. Human types "@copy-coach can you tighten the intro?" in the editor.
2. Tiptap autosave debounces 500ms, posts /edit/v2.
3. Server applies the edit, advances revision, writes op id 12087.
4. Server scans the new text for @<agent_id>; finds copy-coach.
5. Server enqueues an arq job (also creates row in agent_invocations).
6. arq worker:
   a. Sets running.
   b. Calls Anthropic. LLM emits propose_comment(...).
   c. Worker POSTs /ops { type: "comment.add", by: "ai:copy-coach", ... }.
   d. Server inserts op id 12089, materializes thread + comment.
   e. NOTIFY events:<document_id>.
7. Meanwhile the human's frontend has been holding GET /events/pending?after=12087.
8. NOTIFY wakes the request handler; it queries ops where id>12087,
   returns events 12088, 12089. Cursor=12089.
9. Frontend receives the comment.add event.
   a. Refreshes /state to get the new comment_threads + revision.
   b. Renders a CommentMark in the editor at the resolved range.
   c. Updates the comment sidebar.
10. Frontend POSTs /events/ack {up_to_id: 12089, by: "human:abc"}.
11. event_cursors row is updated. Used only for telemetry.
```

Total latency budget (target): step 1 → step 9 in <15s, dominated by the LLM call (steps 6a-6c).

---

## 7. Resolved decisions (locked 2026-04-30)

All 10 original open decisions resolved by yrzhe in chat. Spec is now in **freeze state** — no further design discussion required to start implementation.

| # | Decision | Locked answer | Notes |
|---|---|---|---|
| 1 | Markdown flavor | **A — GFM** | Tables required for product briefs |
| 2 | Block-ref stability | **A — positional + STALE_REVISION** | Same as Proof |
| 3 | Agent identity | **B — `agents` table per workspace** | Token tied to agent_id; admin-registered |
| 4 | `suggestion.add` immediate-accept | **C — `human:` callers only** | Forward-compat for v2 multi-human collab; v1 effectively = B since only agents call this API |
| 5 | Orphaned comment threads | **A — `status=orphaned`, hidden by default** | UX toggle to reveal |
| 6 | Notification mechanism | **B — SSE (revised from original recommendation)** | Browser AND agent both use SSE for sub-1s latency. CDN config: ensure no SSE buffering on Cloudflare/proxies. Long-poll fallback if SSE proxy fails. |
| 7 | Provenance v1 scope | **B — Review stack + `by` field** | Full PROVENANCE-SPEC-v2 deferred to v2 |
| 8 | Quote disambiguation | **G (new — combined approach)** | (1) unique → anchor; (2) multi-match → use prefix+suffix; (3) still multi-match → return `candidates` with surrounding 50-char preview, agent retries with longer/more-specific quote; (4) only error if retry exhausted |
| 9 | Idempotency-Key TTL | **A — 24 hours** | Nightly job nulls keys older than 24h |
| 10 | Agent worker placement | **B — independent arq + Redis worker** | v1: soft data-isolation (code separation, no `import`); v2 trigger: hard isolation via Postgres role-based grants. See §9. |

### Key revisions from initial spec to lock-in

- **§6 (long-poll → SSE)**: Original recommended long-poll. yrzhe pushed back: "what about real-time multi-user collab and agent live-updates?" After clarifying that there are two layers of "real-time" (message-level vs character-level CRDT), and that switching from long-poll to SSE is a small change while CRDT is a separate product, decision moved to SSE for sub-1s message-level latency. CRDT/Yjs/Hocuspocus explicitly out-of-scope for v1.

- **§4 (suggestion immediate-accept)**: yrzhe's instinct chose C over B for forward-compat with future multi-human collab via shared links (see §11). In v1 only agents call `suggestion.add` (humans edit directly via Tiptap), so C's behavior is identical to B; but C's permission-by-identity framing means v2 won't need a protocol change when grants for shared-link humans get added.

- **§8 (quote disambiguation)**: Original A vs B vs C all rejected. New "G" (combined): unique → prefix/suffix → candidates retry → error. Keeps determinism (no LLM in the path), avoids silent wrong-anchor, gives agents a graceful retry loop.

---

## 8a. v1 implementation freeze — what the resolutions enable

With §7 locked, all six Workspace implementation sub-tasks are unblocked:

| Sub-task | Was waiting on | Now unblocked? |
|---|---|---|
| 1. Workspace doc page + Tiptap editor | §7.1 (markdown flavor), §7.2 (block-refs) | ✅ |
| 2. Comments table + sidebar + multi-agent grouping | §7.5 (orphaned), §7.8 (anchor disambiguation) | ✅ |
| 3. Pending change + diff + Approve/Reject | §7.4 (immediate-accept) | ✅ |
| 4. Agent integration + @-mention + Ask | §7.3 (agent identity), §7.10 (worker placement) | ✅ |
| 5. Provenance | §7.7 (provenance scope) | ✅ |
| 6. Output Pipeline (X) | (no blockers) | ✅ |

Recommended start order: 1 → 2 → 4 → 3 → 5 → 6.

---

## 8. Reading log

Files read in full (downloaded from `raw.githubusercontent.com/EveryInc/proof-sdk/main/...`):

| Path | Size | Notes |
|---|---|---|
| `AGENT_CONTRACT.md` | 3.6KB / 154 lines | Core HTTP contract. Op types live in lines 122–132. Token semantics 80–89. |
| `docs/agent-docs.md` | 15KB / 396 lines | The bulk of the wire-protocol detail. `edit/v2` revision-locking 238–298. Error code enum 286–298. |
| `docs/PROVENANCE-SPEC-v2.md` | 41KB / 480 lines | Provenance v2.0. Selectors 82–166. Review stack 174–198. Resolution algorithm 226–252. NOTE: the file ends with an embedded JSON dump of legacy v1 offset-spans (lines 478–479) showing what we're moving away from. |
| `docs/proof.SKILL.md` | 5.2KB / 162 lines | Agent skill summary. Confirms `Idempotency-Key`, error table 138–144. |
| `docs/adr/2026-03-proof-sdk-public-core.md` | 956 bytes / 36 lines | Justifies the package split — useful evidence the storage layer is meant to be swappable. |
| `apps/proof-example/examples/agent-http-bridge.ts` | 3.2KB / 114 lines | Concrete agent call sequence: create doc → set presence → get state → add comment. |
| `packages/agent-bridge/src/index.ts` | 7.9KB / 279 lines | Typed client. Confirms request shapes (suggestion `kind` is exactly `'insert' \| 'delete' \| 'replace'`, line 28). |
| `packages/doc-server/src/index.ts` | 1.2KB / 45 lines | Tiny — just re-exports server routers. The actual handlers live in `server/agent-routes.js` (not in this repo's public packages). |
| `packages/doc-core/src/index.ts` | 222 bytes / 4 lines | Re-exports four files: `marks.js`, `provenance-sidecar.js`, `remark-proof-marks.js`, `agent-identity.js` — none of which are in the public repo. |
| `packages/doc-editor/src/index.ts` | 397 bytes / 6 lines | Re-exports `comments`, `marks`, `suggestions` plugins — not in the public repo. |
| `packages/doc-store-sqlite/src/index.ts` | 1.2KB / 49 lines | Wraps `server/db.js` — defines the store interface (`SqliteDocumentStore`, lines 13–22) but the real impl is hidden. |
| `README.md` | 2.1KB / 98 lines | Workspace layout 17–24, canonical routes 56–70. |

**Surprises / contradictions with prior assumptions:**

1. **The "public" Proof SDK is mostly re-exports of code that isn't in the public repo.** `doc-core/src/index.ts:1-4` imports from `'../../../src/formats/marks.js'` etc. — paths that traverse up out of `packages/` into a `src/` directory that **isn't published**. Same story for `doc-editor`, `doc-server`, `doc-store-sqlite`. The "MIT, last push 5 weeks ago" framing is technically true but materially misleading: only the **contract docs** (AGENT_CONTRACT, agent-docs, PROVENANCE-SPEC, the bridge client TS) are first-class public artifacts. The actual handler implementations are private. **Implication for us:** we're cloning the contract, not the code. We will rewrite every handler from scratch, which is what we wanted anyway. This is fine — but we should not budget any time for "look up Proof's exact algorithm for X" because that algorithm is not visible.

2. **Proof has a `force: true` for rewrites that's silently ignored on hosted.** `agent-docs.md:381–384`. Confirms that even Proof acknowledges full-doc rewrite from agents is dangerous. Reinforces our §2.7 decision to forbid `rewrite.apply` for agents entirely in v1.

3. **Proof's quote selector does NOT have prefix/suffix disambiguation.** I expected it would (the v2.0 spec is otherwise thorough). It only offers `quote` + optional `fuzzy`. Multi-occurrence ambiguity is not addressed in the spec — agents are just told to pass a longer quote. This means our §3.6 prefix/suffix/occurrence extension is a genuine improvement, not a port.

4. **Proof's "presence" is HTTP-based, not WS-based.** `POST /documents/:slug/presence` (`AGENT_CONTRACT.md:14, agent-docs.md:303–311`) is a write that records presence into events. So even Proof — which has Yjs for fragments — does NOT use WS for presence; it uses ops. **Implication:** our async-only model loses very little vs Proof on the presence front. We can use the same presence-as-an-op pattern.

5. **The `X-Agent-Id` header is the correct way to attach agent identity** for hosted Proof. It's separate from the `by` field (`agent-docs.md:88–89`). I had assumed `by` did everything; in reality `by` is authorship and `X-Agent-Id` is presence. We should adopt this split: `by` writes to ops, `X-Agent-Id` writes to presence. Both are optional headers, defaults derived from the bearer token.

6. **The PROVENANCE-SPEC-v2.md document still has v1 offset-based JSON embedded in it.** Lines 478–479 contain `<!-- PROVENANCE { ... offset spans ... } -->`. The body of the doc says v2 abandons offsets in favor of selectors, but the doc itself isn't fully migrated. **Implication:** Proof's own production data is probably mixed v1/v2. We avoid this debt by starting greenfield with selectors only.

7. **There is no `comment.update` op in Proof.** You can `add`, `reply`, `resolve` — but you can't edit a comment after posting. Same for suggestions: no `update`, only `add`/`accept`/`reject`. **Implication:** if we want users to be able to edit their own comment text post-hoc, that's net-new behavior to design (probably `comment.update` op + a 5-minute edit window). Recommend deferring; not in scope for v1.

8. **The `revision` integer is global per-document, monotonically increasing on every successful mutation** (including comments — adding a comment bumps the revision because it's a state change agents need to be aware of). I had assumed `revision` only counted text-content changes. Worth being explicit in §4.1: every op-applied increments `documents.revision`.

9. **No WebSocket for agents.** `packages/doc-server/src/index.ts:4` imports `getCollabRuntime` (Yjs WS for fragments) but the agent-bridge package never references it. Agents in Proof talk only HTTP. **Implication for our §0:** the "no WS" decision is fully aligned with Proof's agent contract. The WS in Proof is exclusively for human-to-human Yjs collab, which we are dropping anyway. So our async-only stance is in fact identical to Proof's agent-side.

10. **Idempotency keys are not always required — there's a "stage" field.** `agent-docs.md:286–290` describes `contract.mutationStage` (Stage A / B / C rollout) and `contract.idempotencyRequired`. So Proof itself has been gradually rolling out idempotency requirements. **Implication:** we should require idempotency from agents on day one (we have no legacy clients) but make it optional for human callers initially. Reflected in §5.

---

## 9. v2 upgrade paths (deferred, but pre-committed triggers)

These are **not in v1** but committed to as future work with explicit trigger conditions. Captured here so they don't get lost.

### 9a. Hard data-isolation between agent classes

**Current (v1)**: Soft constraint. `cron-agent` (compiler/review/lint) and `workspace-agent` (workspace) share the same Postgres user and connection pool. Isolation via:
- Code separation: `src/agents/legacy/` vs `src/agents/workspace/`. No cross-import.
- No workspace table imports in legacy agent files. Code review checks for it.
- Audit log: every write to workspace tables records `originating_agent_id`.

**v2 upgrade**: Postgres role-based access control.
- `cron_agent_user`: `GRANT SELECT, INSERT, UPDATE` on legacy tables; **explicit `REVOKE` on `workspace_*` tables**.
- `workspace_agent_user`: mirror image.
- Each worker service connects with its own DB user.

**Trigger conditions (any one suffices to upgrade)**:
1. A non-yrzhe-authored agent is integrated (third-party / community / user-supplied agent).
2. Any production incident where an agent writes to a table it shouldn't have.
3. Multi-tenant launch (real users beyond yrzhe).

**Why deferred**: v1 has 4-5 agents, all yrzhe-written, behavior predictable. Maintaining role/grant configuration adds operational overhead; physical isolation (separate worker process + separate task router) already prevents runtime interference, which is the more pressing concern.

### 9b. Real-time character-level CRDT collaboration

**Current (v1)**: SSE message-level real-time (sub-1s). Two users editing same paragraph → optimistic locking, last-save-wins, "content changed, please refresh" notice.

**v2 upgrade**: Yjs + Hocuspocus + Tiptap collaboration extension. Multi-cursor, sub-100ms character sync.

**Trigger conditions**:
1. ≥3 active concurrent editors on the same document, regularly (not edge case).
2. User feedback explicitly mentions "I lost my edits because two of us were typing".
3. Real-time meeting / brainstorm use case becomes core (not the case in v1).

**Why deferred**: half-year-class engineering effort; storage migration from markdown-string to Y.Doc binary; comment anchor resolver needs to migrate to Yjs RelativePosition. v1's SSE foundation does not need to be rewritten — Yjs runs on top. Effort is in editor + storage layer, not the network layer.

### 9c. Full provenance spec (PROVENANCE-SPEC-v2.md)

**Current (v1)**: `by` field + review stack only.

**v2 upgrade**: Selectors, basis enum, sources, conventions per Proof's full v2.0 spec. "This sentence was written by agent_research at 14:22, based on [PDF page 12], reviewed by Alice at 14:30."

**Trigger conditions**:
1. ≥50 documents in production (enough corpus for "show me what was AI-generated" tooling to matter).
2. External fact-check / audit requirement appears.
3. Output Pipeline publishes content where source attribution is legally needed (e.g., paid newsletters with citations).

**Why deferred**: ~3 weeks of work. v1's `by`-field-only model captures the data needed to retrofit later — every op already records authorship at write time, so v2 spec can be layered on as additional `op.metadata` fields without DB rewrites.

### 9d. Password-protected share links

**Current (v1)**: revocation + expiration only.

**v2 upgrade**: optional per-link password gate. Visitor sees password prompt before document loads.

**Trigger condition**: yrzhe wants to share a sensitive doc that can't expire on a fixed schedule.

**Why deferred**: 24h-expiry short links + DM single-recipient delivery covers ~95% of "I need this gated" cases. Notion has password protection — usage data shows <2% of links use it.

---

## 10. (reserved — was numbered §11 in chat, but slot here)

(intentionally empty to preserve chat-numbering ↔ spec-numbering mapping)

---

## 11. Link-sharing module (resolved 2026-04-30)

PageFly Workspace supports collaboration via **shared links**. Visitors do not need to register or log in. Each link grants a specific permission scope and can be revoked or expired.

### 11.1 Permission tiers (3-tier — yrzhe locked: 11a)

| Tier | Read doc | Comment | @-mention agent | Edit content | Trigger Approve/Reject |
|---|---|---|---|---|---|
| `read` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `comment` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `edit` | ✅ | ✅ | ✅ | ✅ | ✅ |

- `read`: 给老板看提案 / 公开预览
- `comment`: 给同事审稿
- `edit`: 跟合作者一起写

Permission tier is enforced server-side on every op. Frontend disables UI affordances by tier.

### 11.2 Visitor identity (B+C combined — yrzhe locked: 11b)

**No login required.** Visitor identity assignment:

1. **First visit on a new browser**: a modal asks "请输入你的名字" (or default "游客"). Stored in `localStorage` keyed by `share_token`. Also POSTed to backend → recorded against the visitor session.
2. **Subsequent visits** (same browser, same link): name auto-populated from localStorage. Visitor can change it via a button.
3. **Pre-set name in link** (optional, when generating the link): yrzhe checks "Send to a specific person" → enters "Alice" → URL becomes `/share/<token>?name=Alice`. Alice opens link → name field pre-populated, modal still shown for confirmation.

Visitor identity is recorded in the `by` field as `guest:<visitor_uuid>` where `visitor_uuid` is generated on first visit and persisted in localStorage. Display name is a separate field, mutable.

**Spoofing prevention**: backend stores visitor_uuid → display_name binding per share_token. Same uuid + new browser = treated as new visitor (browsers don't share localStorage). yrzhe sees both events in audit log.

### 11.3 Revocation & expiration (yrzhe locked: 11c)

**Revocation**: yrzhe clicks "Revoke" on the share link UI → `share_links.revoked_at = now()`.
- Visitors with the link open: their next op / event-fetch returns `403 LINK_REVOKED`. Frontend shows banner and read-only fallback.
- New visitors clicking the link: HTTP 410 Gone with explanation page.

**Expiration**: when generating a link, yrzhe selects:
- "24 hours" (default for one-off shares)
- "7 days"
- "30 days"
- "Never" (permanent — for trusted long-term collaborators)

Server enforces `expires_at` on every request. Same 410 response on expiry.

**Password protection**: NOT in v1. See §9d for v2 trigger.

### 11.4 Visitor activity logging (B — yrzhe locked: 11d)

Every visitor action records:
- `share_token`
- `visitor_uuid` (from localStorage)
- `display_name` at time of action
- `ip_address`
- `user_agent`
- `timestamp`
- `action_type` (`view` / `comment` / `edit` / `approve_suggestion` / etc.)

yrzhe sees an audit log per share link: "Alice (Chrome, 北京 IP) opened this link 14:22, posted 2 comments, edited paragraph 3 at 14:31".

GDPR-style retention: keep 90 days, then anonymize IP (hash with rotating salt).

### 11.5 DB additions

```sql
CREATE TABLE share_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    share_token     VARCHAR(32) NOT NULL UNIQUE,         -- random URL-safe slug
    permission      VARCHAR(16) NOT NULL CHECK (permission IN ('read','comment','edit')),
    preset_name     VARCHAR(64),                          -- optional pre-filled visitor name
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,                          -- NULL = no expiry
    revoked_at      TIMESTAMPTZ                           -- NULL = active
);

CREATE INDEX idx_share_links_token ON share_links(share_token) WHERE revoked_at IS NULL;
CREATE INDEX idx_share_links_doc ON share_links(document_id);

CREATE TABLE share_visitors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_link_id   UUID NOT NULL REFERENCES share_links(id) ON DELETE CASCADE,
    visitor_uuid    UUID NOT NULL,                        -- from client localStorage
    display_name    VARCHAR(64) NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (share_link_id, visitor_uuid)
);

CREATE TABLE share_visitor_events (
    id              BIGSERIAL PRIMARY KEY,
    share_link_id   UUID NOT NULL REFERENCES share_links(id) ON DELETE CASCADE,
    visitor_uuid    UUID NOT NULL,
    action_type     VARCHAR(32) NOT NULL,
    target_op_id    UUID,                                 -- references ops(id) if action created an op
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_share_visitor_events_link ON share_visitor_events(share_link_id, created_at DESC);
```

### 11.6 API endpoints

```
POST   /api/workspace/documents/:doc_id/share-links
  body: { permission, expires_at?, preset_name? }
  resp: { share_token, full_url, ... }

GET    /api/workspace/documents/:doc_id/share-links
  resp: list of all active+expired+revoked links for this doc

DELETE /api/workspace/share-links/:link_id
  effect: sets revoked_at = now()

GET    /api/workspace/share-links/:link_id/audit
  resp: { visitors: [...], events: [...] }

POST   /api/share/:token/identify
  body: { display_name, visitor_uuid? }
  resp: { visitor_uuid, document_id, permission, document_state }
  notes: visitor_uuid is generated server-side if not provided; client persists
         it in localStorage. This is the entry point — replaces /documents/:slug/state
         for share-token-based access.

POST   /api/share/:token/ops
  headers: X-Visitor-UUID, X-Visitor-Name
  body: same op model as /api/workspace/documents/:slug/ops
  permission_check: server validates op type against share_link.permission tier

GET    /api/share/:token/events/stream
  same as /api/workspace/documents/:slug/events/stream but token-gated
```

### 11.7 Frontend integration

- New route: `/share/:token` (no auth required).
- On mount: call `/api/share/:token/identify` with localStorage visitor_uuid (if any). Modal pops if no display_name yet.
- Renders the same `WorkspacePage` component with permission-derived feature flags:
  - `read`: editor in read-only mode, no comment / agent panel
  - `comment`: editor in read-only mode, comment sidebar visible, agent panel visible
  - `edit`: full editor + comments + agent + suggestions

### 11.8 Forward-compat note

Decision §7.4 (`suggestion.add` immediate-accept = C, `human:` only) was specifically chosen to support this module. Future state when a sharing visitor with `edit` tier wants to fast-path their own suggestion: the protocol already handles it via the same `human:<visitor_uuid>` identity.

---

*End of spec. Frozen for implementation 2026-04-30.*
