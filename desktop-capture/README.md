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
| M1 | Xcode scaffold + menu bar shell | ✅ |
| M2 | Settings + Keychain + API ping | ✅ |
| M3 | AX capture + dedup + local SQLite | ✅ |
| M4 | Events uploader | ✅ |
| M5 | Audio recorder (manual) | ✅ |
| M6 | Audio uploader + STT linkage | ✅ |
| M7 | Launch-at-login + signing + auto-update | ✅ |
| M8 | Menu bar UX polish | — |

## Release / signing (M7)

Local unsigned builds run fine after clicking through the Gatekeeper warning.
Distribution requires a paid Apple Developer account.

One-time setup on the build machine:

```bash
# Register an app-specific password for notarytool
xcrun notarytool store-credentials pagefly-notary \
    --apple-id "you@example.com" \
    --team-id "ABCDE12345" \
    --password "<app-specific-password from appleid.apple.com>"
```

Cut a signed, notarized, stapled build:

```bash
cd desktop-capture
DEVELOPER_ID_APP="Developer ID Application: Your Name (ABCDE12345)" \
NOTARY_KEYCHAIN_PROFILE="pagefly-notary" \
./scripts/release.sh
```

Artifacts land in `dist/PageflyCapture.app` and `dist/PageflyCapture.zip`.
Upload the `.zip` as a GitHub Release asset; the in-app updater polls
`https://api.github.com/repos/Yrzhe/pagefly/releases/latest` and shows a
Download button in About → Updates when the tag is newer than the local
`CFBundleShortVersionString`.

### Launch at login

The General tab exposes a **Launch at login** toggle backed by
`SMAppService.mainApp`. On first enable, macOS may require the user to
approve the item in System Settings → General → Login Items; the UI
surfaces this via a yellow notice.
