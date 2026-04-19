import Foundation
import Combine

/// User-facing connection state. Drives both the menu bar icon tint and
/// the status row inside the dropdown panel.
enum ConnectionState: Equatable {
    case unknown          // never tested or token cleared
    case checking         // request in flight
    case connected        // last ping succeeded
    case unauthorized     // server reachable, token rejected (HTTP 401/403)
    case unreachable(String) // network error or non-2xx; payload = short reason

    var isConnected: Bool {
        if case .connected = self { return true }
        return false
    }
}

/// Single source of truth for user-tunable settings. Server URL is stored in
/// `UserDefaults`; the API token is held in the macOS Keychain. Don't ever
/// log the token's value, only its presence.
@MainActor
final class SettingsStore: ObservableObject {
    static let shared = SettingsStore()

    // MARK: Persisted

    @Published var serverURL: String {
        didSet { defaults.set(serverURL, forKey: Keys.serverURL) }
    }

    /// Max number of uploaded `.m4a` files to keep on disk after a successful
    /// transcription. 0 = delete the file immediately on upload success.
    /// Range 0…50, default 5. The transcript itself stays in the DB row
    /// regardless — this only governs the raw audio bytes.
    @Published var audioRetentionCount: Int {
        didSet {
            let clamped = min(50, max(0, audioRetentionCount))
            if clamped != audioRetentionCount {
                audioRetentionCount = clamped
                return
            }
            defaults.set(clamped, forKey: Keys.audioRetentionCount)
        }
    }

    /// Reading and writing the token always round-trips through Keychain.
    /// Treat as a write-only field from outside; never bind it to a SwiftUI
    /// `@State` for any duration longer than the keystroke session.
    ///
    /// WARNING: getter can block the calling thread briefly on first read
    /// under ad-hoc signing while macOS evaluates keychain access control.
    /// Never call from the main thread during app launch — use `probeToken()`
    /// instead. Upload/ping call sites are already on background Tasks.
    var apiToken: String? {
        get { Keychain.load(service: Keys.keychainService, account: Keys.keychainAccount) }
    }

    /// Throws if the Keychain write fails so callers can surface the error
    /// and avoid pinging with stale credentials. Passing nil or empty string
    /// deletes the saved token (and never throws).
    func setApiToken(_ token: String?) throws {
        if let value = token, !value.isEmpty {
            try Keychain.save(value, service: Keys.keychainService, account: Keys.keychainAccount)
            hasToken = true
        } else {
            Keychain.delete(service: Keys.keychainService, account: Keys.keychainAccount)
            hasToken = false
            connectionState = .unknown
        }
    }

    /// Read the stored token off the main thread and publish `hasToken` when
    /// done. Call this once at launch. Under ad-hoc signing, a rebuilt
    /// binary asking Security for a previously saved item can block while
    /// macOS resolves access control; doing it here keeps that off the main
    /// thread so the menu bar can appear immediately.
    func probeToken() {
        Task.detached(priority: .utility) {
            let present = (Keychain.load(service: Keys.keychainService, account: Keys.keychainAccount) != nil)
            logCapture(.info, "Keychain probe complete: hasToken=\(present)")
            await MainActor.run {
                if self.hasToken != present {
                    self.hasToken = present
                }
            }
        }
    }

    // MARK: Derived state (in-memory only)

    @Published private(set) var hasToken: Bool
    @Published var connectionState: ConnectionState = .unknown
    @Published var lastSyncedAt: Date?

    /// Stable per-install identifier. Not a secret; the server uses it so
    /// different Macs owned by the same user don't clobber each other.
    let deviceID: String

    // MARK: Init

    private let defaults: UserDefaults

    private init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        // The bare apex (`pagefly.ink`) serves the public landing page +
        // dashboard SPA from a static host that rejects POST with 405. The
        // FastAPI backend lives at `api.pagefly.ink`. Defaulting to the API
        // host means a fresh install uploads on first ping; users on the
        // pre-rename default get migrated by `migrateLegacyServerURL()`
        // below so they don't have to re-enter anything.
        let storedServerURL = defaults.string(forKey: Keys.serverURL) ?? "https://api.pagefly.ink"
        self.serverURL = SettingsStore.migrateLegacyServerURL(storedServerURL, defaults: defaults)
        // 5 is "remember the last meeting + a few before it" — small enough
        // that disk doesn't bloat, large enough that the user can scroll the
        // recent-recordings list without seeing already-vanished entries.
        self.audioRetentionCount = (defaults.object(forKey: Keys.audioRetentionCount) as? Int) ?? 5
        // Don't touch Keychain here — it can block for seconds on a rebuilt
        // ad-hoc binary while macOS resolves access. `probeToken()` fills
        // `hasToken` in via a background Task once the menu bar is up.
        self.hasToken = false
        if let existing = defaults.string(forKey: Keys.deviceID) {
            self.deviceID = existing
        } else {
            let generated = "dev_" + UUID().uuidString
                .replacingOccurrences(of: "-", with: "")
                .lowercased()
                .prefix(18)
            self.deviceID = String(generated)
            defaults.set(self.deviceID, forKey: Keys.deviceID)
        }
    }

    /// One-shot migration: rewrite the legacy SPA URL to the API host.
    /// Existing installs were defaulted to `pagefly.ink`, which is now the
    /// static landing page and rejects POST. Anyone whose stored value
    /// matches the old default gets silently flipped — they don't see a
    /// "your settings changed" dialog because they never set this themselves.
    private static func migrateLegacyServerURL(_ stored: String, defaults: UserDefaults) -> String {
        let legacy = ["https://pagefly.ink", "https://pagefly.ink/", "http://pagefly.ink"]
        if legacy.contains(stored) {
            let migrated = "https://api.pagefly.ink"
            defaults.set(migrated, forKey: Keys.serverURL)
            logCapture(.info, "Migrated server URL: \(stored) → \(migrated)")
            return migrated
        }
        return stored
    }

    // MARK: Ping

    /// Test reachability + token. Updates `connectionState` in place. Safe to
    /// call many times — concurrent calls are coalesced via the `checking`
    /// state guard.
    func ping() async {
        if connectionState == .checking { return }
        guard let client = APIClient.from(self) else {
            connectionState = .unknown
            return
        }
        connectionState = .checking
        let result = await client.ping()
        connectionState = result
        logger.info("Ping result: \(String(describing: result))")
    }

    // MARK: Keys

    private enum Keys {
        static let serverURL = "pagefly.serverURL"
        static let deviceID = "pagefly.deviceID"
        static let audioRetentionCount = "pagefly.audioRetentionCount"
        static let keychainService = "top.yrzhe.PageflyCapture"
        static let keychainAccount = "api-token"
    }
}
