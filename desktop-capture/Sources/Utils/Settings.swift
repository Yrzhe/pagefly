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

    /// Reading and writing the token always round-trips through Keychain.
    /// Treat as a write-only field from outside; never bind it to a SwiftUI
    /// `@State` for any duration longer than the keystroke session.
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
        self.serverURL = defaults.string(forKey: Keys.serverURL) ?? "https://pagefly.ink"
        self.hasToken = (Keychain.load(service: Keys.keychainService, account: Keys.keychainAccount) != nil)
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
        static let keychainService = "top.yrzhe.PageflyCapture"
        static let keychainAccount = "api-token"
    }
}
