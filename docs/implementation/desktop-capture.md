# Desktop Capture Client — Implementation Plan

> Companion to the design doc in `docs/desktop-auto-capture.md`.
> Design decisions live there; this doc is just the execution sequence.

**Status:** Phase 1 (server side) complete · Phase 2 (Mac client) starting

## Goal

Ship a signed, notarized macOS menu-bar app that silently captures
foreground app context + meeting audio and pushes it to the PageFly
server via the `/api/activity/*` endpoints already landed in `main`.

## Stack

- **Swift 5.9+** + **AppKit `NSStatusItem`** + **SwiftUI** (preferences window)
- **GRDB.swift** for the local SQLite queue
- **ScreenCaptureKit** (macOS 13+) for system audio tap
- **AVAudioEngine** for microphone
- **AXUIElement** for accessibility-based screen capture
- **URLSession** (stdlib) for server upload
- **Keychain Services** for token storage

## Folder layout (monorepo)

```
real-pagefly/
└── desktop-capture/                ← new top-level, siblings: src/, frontend/, browser-extension/
    ├── PageflyCapture.xcodeproj/
    ├── Sources/
    │   ├── App/                    MenuBarController, PreferencesWindow, AppDelegate
    │   ├── Capture/                AXObserver, ScreenSampler, IdleMonitor,
    │   │                           PrivacyFilter, ContextDedup
    │   ├── Audio/                  AudioRecorder, MeetingDetector
    │   ├── Storage/                LocalDB (GRDB), Models (LocalEvent, LocalAudio)
    │   ├── Sync/                   Uploader, APIClient, Keychain
    │   └── Utils/                  Logger, Settings
    ├── Resources/
    │   ├── Info.plist              permission strings + LaunchAgent
    │   └── Assets.xcassets/
    ├── Tests/
    ├── .gitignore                  xcuserdata, DerivedData, *.p12, *.local.*
    └── README.md
```

## Milestones (ship in this order)

### M1 — Xcode scaffold + menu bar shell (≈ half a day)

Goal: double-click a built `.app`, see an icon in the menu bar, click
it, see a "Not configured" status.

Deliverables:
- Xcode project (SwiftUI `App` + `AppDelegate` bridge)
- `MenuBarController` with status icon, Start/Pause, Open Preferences, Quit
- Empty `PreferencesWindow` (SwiftUI) with tabs: General / Privacy / About
- Info.plist with placeholder usage descriptions for accessibility, mic, screen capture
- `.gitignore` + README with setup instructions

Exit: app builds, runs, menu bar item appears; no server calls yet.

### M2 — Settings + Keychain + API ping (≈ half a day)

Deliverables:
- Preferences fields: Server URL, API token
- Token stored via `SecItemAdd` (Keychain), never `UserDefaults`
- `APIClient` with `ping()` hitting an existing `/api/health` (or similar) endpoint
- Menu bar shows green dot when authed, red when not

Exit: user enters token → green dot → reopen app → still green (Keychain
persistence verified).

### M3 — AX capture + dedup + local SQLite queue (≈ 1 day)

Deliverables:
- `AXObserver` subscribing to `NSWorkspace.didActivateApplicationNotification`
  and per-app AX `kAXFocusedUIElementChangedNotification`
- `ScreenSampler` running every 30s on the main run loop
- `IdleMonitor` using `CGEventSourceSecondsSinceLastEventType` to suppress
  events after 60s idle
- `PrivacyFilter`: drop `AXSecureTextField`, honor app blocklist setting,
  detect Chrome/Safari private mode (via AX window subrole)
- `ContextDedup`: sha1 of (app|title|url|text[:500]); bump `duration_s`
  on same hash; open new row otherwise; 30-min hard cut
- `LocalDB` with `local_events` schema from the design doc
- Verbose log to `~/Library/Logs/PageFly/capture.log`

Exit: tail the log, switch between apps, confirm events are being written
with correct dedup and idle suppression.

### M4 — Uploader (events only) (≈ half a day)

Deliverables:
- `Uploader` actor running every 5 min and on `NSWorkspace.didWakeNotification`
- Drains `local_events WHERE status='pending'` in batches of ≤ 500
- `POST /api/activity/events/batch`; on 200, mark `status='uploaded'` +
  store `remote_id`
- Exponential backoff on 5xx / network errors; stop queuing beyond 10k rows
- Mac DB auto-vacuum rows older than 14 days with status='uploaded'

Exit: leave the app running for a few hours, hit the server
`/api/activity/events?from=...` endpoint, see events flow through.

### M5 — Audio recorder (≈ 1 day)

Deliverables:
- `AudioRecorder` mixing `ScreenCaptureKit` system audio tap +
  `AVAudioEngine` mic into a single AAC m4a (mono, 16 kHz, 64 kbps)
- Menu bar toggle "Start recording" / "Stop recording"
- `MeetingDetector` heuristic: focused window bundle id in
  {us.zoom.xos, com.google.Chrome+meet.google.com, com.apple.FaceTime,
   com.microsoft.teams2, com.tencent.xinWeChat} → prompt to auto-record
  with 30 s grace period
- Files land in `~/Library/Application Support/PageFly/recordings/<uuid>.m4a`
- Emits a `LocalAudio` row with `status='pending_upload'`

Exit: start a 2-min recording, stop, confirm m4a file + DB row exist.

### M6 — Audio uploader + STT linkage (≈ half a day)

Deliverables:
- Uploader protocol from design doc: **audio first**, then events
- `POST /api/activity/audio` with `X-Local-UUID` header (local_uuid in query param)
- On 200: update `LocalAudio.remote_id`, status → `uploaded`
- Poll `GET /api/activity/audio/{id}/status` every 20 s until
  `status='transcribed'` or `failed`
- On transcribed: cache transcript locally (for UI) and delete raw m4a
  after 7 days grace
- Events referencing a not-yet-uploaded audio hold in queue until the
  audio row has a remote_id

Exit: record a meeting, close lid, reopen later, confirm audio uploads,
transcribes, and linked events appear on server with `audio_id` set.

### M7 — LaunchAgent + auto-update + code signing (≈ 1 day)

Deliverables:
- LaunchAgent plist installed to `~/Library/LaunchAgents/top.yrzhe.PageflyCapture.plist`
  on first run
- "Launch at login" toggle in Preferences (ServiceManagement framework)
- Signing + notarization via `codesign` + `notarytool`; CI script in
  `desktop-capture/scripts/release.sh`
- Sparkle or a minimal in-app updater hitting a GitHub Releases feed

Exit: install the notarized .dmg on a second Mac, grant permissions,
see events stream to server automatically after reboot.

### M8 — Menu bar UX polish + privacy indicator (≈ half a day)

Deliverables:
- Icon reflects state: armed (filled) / paused (hollow) / recording (red dot)
  / offline (gray) / no permissions (warning triangle)
- Dropdown shows: last upload time, queue size, today's minutes captured
- "Open server dashboard" opens the Schedules page in browser
- Accessibility permission onboarding: detect missing permission, show
  guided modal that opens System Settings at the right pane

Exit: give it to another person, watch them install and get to first-upload
with no hand-holding.

## Dependencies between milestones

```
M1 → M2 → M3 → M4
           ↓
           M5 → M6
                ↓
                M7 → M8
```

M7 (signing) is technically independent after M2 but should land before
anyone non-developer uses the app.

## Testing strategy

- **Unit**: `ContextDedup`, `PrivacyFilter`, `APIClient` retry logic,
  `Uploader` state machine — XCTest, no UI
- **Integration**: stub server via `URLProtocol` subclass; verify audio-
  before-events ordering, FK fallback behavior, offline buffering
- **Manual smoke checklist** in README before every release: lock screen,
  sleep/wake, offline → online, permission revoke, blocklist app focus,
  private browsing, multi-screen

## Acceptance criteria for Phase 2

- [ ] Notarized `.dmg` downloadable from GitHub Releases
- [ ] Fresh Mac can install, grant 3 permissions, see "green dot" in < 2 min
- [ ] 24 hours of uninterrupted running produces coherent "Work log
      YYYY-MM-DD" wiki article next morning via the existing
      `activity_log` scheduled task
- [ ] Meeting recorded in Zoom appears as transcribed text linked to
      events in the same time window
- [ ] No sensitive apps (1Password, Banking, Messages) appear in events
- [ ] Readme covers install, uninstall, permission troubleshooting, blocklist config

## Risks / unknowns

1. **Chrome/Safari URL extraction via AX is flaky** → fallback: AppleScript
   via `NSAppleScript` with user opt-in; accept missing URL as non-fatal.
2. **ScreenCaptureKit requires screen recording permission** even for
   audio-only system tap → must explain clearly in onboarding.
3. **macOS 13 minimum** cuts off users on macOS 12 Monterey (~8% at time
   of writing) → acceptable; would need `CoreAudio` tap fallback otherwise.
4. **Signing certificates** — user needs a paid Developer Program account
   ($99/yr) for notarization. Unsigned build works locally with "allow
   anyway" but not for distribution.
5. **Whisper cost at scale** — 1h meeting = $0.36. If user's meeting
   volume is high, consider local Whisper.cpp on server side later.

## Out of scope for this issue

- Windows / Linux clients (separate future issues)
- On-device transcription (server Whisper is fine for now)
- OCR fallback for apps without AX text (Figma, some Electron)
- Cross-device sync beyond the server (multi-Mac)
- iOS companion app

## Milestone tracking

Milestones are tracked on the internal roadmap; close them as they ship.
Phase 2 is considered done only when the acceptance criteria above are all met.
