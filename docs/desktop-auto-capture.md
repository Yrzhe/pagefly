# Desktop Auto-Capture (YRZ-45)

> Status: design notes. Server side is being built first; Mac client comes after.

## Goal

Capture what the user does on their Mac (foreground app, window title, URL, visible text excerpt, meeting audio) → feed into PageFly's knowledge base so the daily compiler / chat can answer "what did I do last Tuesday" and surface patterns.

## Architecture

```
┌─────────────────────────── Mac ───────────────────────────┐
│ pagefly-capture (Swift + PyObjC, LaunchAgent + menubar)    │
│  ├── AXObserver      NSWorkspace + AXUIElementRef events  │
│  ├── Sampler         30s poll for long dwells             │
│  ├── AudioRecorder   system tap (ScreenCaptureKit) + mic  │
│  ├── Dedup           context-hash + dwell accumulator     │
│  ├── SQLite          local queue: screen events + audio   │
│  └── Uploader        batch → PageFly API                  │
└──────────────────────────┬───────────────────────────────┘
                           │ POST /api/activity/*
                           ▼
┌──────────────────────── PageFly server ──────────────────┐
│ activity_events table (one row per context block)         │
│ audio_recordings table (m4a file + transcript)            │
│ data/activity/YYYY-MM-DD.jsonl  (canonical append-only)   │
│ data/activity/audio/<id>.m4a + .transcript.txt            │
│ nightly compiler → "Work log YYYY-MM-DD" wiki article     │
└───────────────────────────────────────────────────────────┘
```

## Screen capture — decisions

| Topic | Decision | Why |
|---|---|---|
| Source | macOS Accessibility API (AX*) via PyObjC or Swift | Structured, cheap, no OCR, auto-skips password fields (`AXSecureTextField`) |
| Fields captured | `app`, `window_title`, `url` (browsers only), `text_excerpt` (first 1KB + last 200B of focused element), `ax_role` | Enough for daily summary, safe size |
| Trigger | **Hybrid**: event-driven (`NSWorkspace.didActivateApplication` + AX window-changed observer) + 30s poll for long dwells + idle suppression (`CGEventSource` > 60s idle) | Event-only misses long stays; timer-only misses quick switches; idle suppression avoids burning battery while user is afk |
| Dedup | Context hash = `sha1(app \| title \| url \| text[:500])`. Same hash → bump `duration_s += 30`; different → close row, open new. 30 min hard-cut. | One row per "context block" instead of spam |
| Multi-screen | Focused window only. Do not enumerate all visible windows. | Events explode; most bg windows are noise |
| Fallback OCR | Only for apps where AX returns no text (Figma, some Electron) | Expensive + privacy heavy, use sparingly |

## Audio recording — decisions

| Topic | Decision | Why |
|---|---|---|
| Source | ScreenCaptureKit system audio tap + AVAudioEngine mic, mixed or dual-track | Native, no BlackHole dependency on macOS 13+ |
| Trigger | Manual toggle in menubar + auto-start heuristic when Zoom / Google Meet / FaceTime / Teams / WeChat window is focused | Most use cases are meetings; don't record browsing by default |
| File format | m4a (AAC 64kbps mono, 16kHz) | ~0.5 MB/min, fine for speech |
| Location | `~/Library/Application Support/PageFly/recordings/<uuid>.m4a` | Out of iCloud sync |
| Transcription | Server-side (Whisper API), not on device | Better quality; client stays thin; $0.006/min is trivial |
| Retention | Raw m4a: delete after successful transcript + 7 day grace. Transcript: kept forever. | Audio is huge, transcript is tiny |

### Offline-safe upload protocol

Local SQLite rows:

```sql
CREATE TABLE local_audio (
  local_uuid   TEXT PRIMARY KEY,       -- generated on Mac
  started_at   TEXT,
  ended_at     TEXT,
  file_path    TEXT,
  status       TEXT,  -- recording → pending_upload → uploaded → transcribed → purged
  remote_id    INTEGER,                -- filled after server accepts upload
  transcript   TEXT                    -- filled after STT done
);

CREATE TABLE local_events (
  local_uuid   TEXT PRIMARY KEY,
  started_at   TEXT,
  ended_at     TEXT,
  app          TEXT, title TEXT, url TEXT, text_excerpt TEXT,
  audio_uuid   TEXT REFERENCES local_audio(local_uuid),  -- optional link
  status       TEXT,  -- pending → uploaded
  remote_id    INTEGER
);
```

**Upload order (strict):**

1. Foreach `local_audio WHERE status='pending_upload'`:
   - `POST /api/activity/audio` (multipart, `X-Local-UUID: <uuid>`) → server responds `{audio_id}`
   - Update row: `status='uploaded', remote_id=audio_id`
2. Foreach `local_events WHERE status='pending' AND (audio_uuid IS NULL OR audio.remote_id IS NOT NULL)`:
   - Resolve `audio_remote_id` via join
   - `POST /api/activity/events/batch` body `{events: [{..., audio_id: audio_remote_id}]}`
   - Update row: `status='uploaded', remote_id=...`
3. Server transcribes async; when done, writes transcript back on `audio_recordings` row. Mac polls `GET /api/activity/audio/<id>/status` or uses long-poll / server-push.

**Why not sync?** Transcription takes 5–60s for typical meetings. Blocking the upload pipeline stalls everything else.

**Offline handling:** Uploader loop runs every 5 min + on network-reachable event. Queue grows locally. When back online it drains audio first, then events. No placeholders leak to the server — server never sees an event that references a not-yet-uploaded audio.

## Retention & size math

Quick back-of-envelope:

- Screen event row: ~500 B serialized
- Typical day: ~2000 events (30s poll × 8h + app switches), post-dedup ~200 rows → **~100 KB/day**
- 30 days raw: ~3 MB
- 1 year raw: ~36 MB

So **7 days was too conservative**. Revised: keep raw jsonl **30 days on server**, roll older days into daily summaries only. Local Mac SQLite auto-vacuums rows older than 14 days (since they've been uploaded).

Audio is different: 1h meeting = ~30 MB m4a. Auto-purge raw audio 7 days after successful transcription (transcript stays).

## Privacy & edge cases

| Case | Handling |
|---|---|
| Private browsing | Detect `AXDocument` hint + known private-mode windows → drop URL/title, keep `app` only |
| Sensitive apps (1Password, Banking, Messages, Signal) | Default blocklist; user can extend |
| Lock screen / lid closed | `CGSessionCopyCurrentDictionary` + wake events → pause |
| Accessibility permission revoked | Menubar icon red, retry every 5 min, push local notification |
| Mic/screen recording permission revoked | Separate indicator; audio pauses but screen continues |
| Huge editor content | Truncate to 1 KB head + 200 B tail |
| On a call + idle timer fires | Don't suppress during active audio recording |
| Clock skew / timezone | Always store as `started_at` UTC ISO8601, display in client tz |
| Duplicate upload after crash | Use `local_uuid` idempotency key server-side |
| User pauses capture | Menubar toggle → capture off + optional "auto-resume in N min" |
| Meeting auto-detect false positive | User can untick the recording within 30s to drop it (grace period) |

## Server side (build first)

New code in `src/channels/api.py`, `src/storage/db.py`:

- Tables: `activity_events`, `audio_recordings`
- Endpoints:
  - `POST /api/activity/events/batch` — idempotent on `local_uuid`
  - `POST /api/activity/audio` — multipart m4a upload
  - `GET  /api/activity/audio/{id}/status` — poll transcription
  - `GET  /api/activity/events?from=...&to=...` — retrieval for daily summary + chat
- Storage:
  - Events: `data/activity/YYYY-MM-DD.jsonl` (append on upload)
  - Audio: `data/activity/audio/<id>.m4a`
  - Transcript: `data/activity/audio/<id>.transcript.json`
- Nightly: compiler reads previous day events + transcripts → generates "Work log" wiki article

## Open questions (deferred until Mac client)

- Menubar UX: pause/resume/blocklist/privacy indicator
- LaunchAgent plist location + auto-update mechanism
- Signed & notarized binary (required for accessibility permission UX to not suck)
- Swift vs Python for the client — Swift likely wins for AX performance & ScreenCaptureKit; Python fine for prototype
- Chrome/Safari URL extraction via AX is flaky; may need `osascript` fallback
