# PageFly Capture (macOS menu bar client)

The desktop companion to [real-pagefly](../). A native Swift + AppKit + SwiftUI
menu bar app that captures your focused-app context and meeting audio and
uploads them to your self-hosted PageFly server via the `/api/activity/*`
endpoints.

Phase 1 (server side) is already shipped; this directory tracks the Mac
client across milestones M1 – M8.

## Layout

```
desktop-capture/
├── project.yml              XcodeGen spec (canonical)
├── Sources/
│   ├── App/                 AppDelegate, MenuBarController, PreferencesWindow, MenuPanelView
│   ├── Capture/             (M3)   AXObserver, ScreenSampler, IdleMonitor, PrivacyFilter, ContextDedup
│   ├── Audio/               (M5)   AudioRecorder
│   ├── Storage/             (M3)   LocalDB (GRDB), Models
│   ├── Sync/                (M2+M4+M6) Uploader, APIClient, Keychain
│   └── Utils/               Logger, Settings
├── Resources/
│   ├── Info.plist           Bundle metadata + permission usage strings
│   └── PageflyCapture.entitlements
└── Tests/                   XCTest targets
```

## Prerequisites

- macOS 13 (Ventura) or newer
- **Full Xcode** 15+ installed (not just Command Line Tools)
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) — `brew install xcodegen`

## Generate the Xcode project

The `.xcodeproj` is gitignored; `project.yml` is the source of truth. Run:

```bash
cd desktop-capture
xcodegen
open PageflyCapture.xcodeproj
```

Re-run `xcodegen` any time `project.yml` or the folder structure changes.

## Build & run

Inside Xcode: select the `PageflyCapture` scheme → ⌘R. On first launch macOS
will prompt for permissions as features are enabled across milestones. For M1
(menu bar shell) no permissions are needed yet.

## Design references

- Liquid-glass light theme panels on the design canvas
- Server API contract: `src/channels/api.py:497+` (look for `/api/activity/*`)
- Overall architecture: `../docs/desktop-auto-capture.md`
- Execution plan: `../docs/implementation/desktop-capture.md`

## Milestones

| # | Scope | Status |
|---|---|---|
| M1 | Xcode scaffold + menu bar shell | ✅ in progress |
| M2 | Settings + Keychain + API ping | — |
| M3 | AX capture + dedup + local SQLite | — |
| M4 | Events uploader | — |
| M5 | Audio recorder (manual) | — |
| M6 | Audio uploader + STT linkage | — |
| M7 | LaunchAgent + signing + auto-update | — |
| M8 | Menu bar UX polish | — |
