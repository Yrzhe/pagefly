import Foundation
import ServiceManagement

/// Wraps `SMAppService.mainApp` so the rest of the app can toggle
/// launch-at-login without caring about the underlying plist mechanics.
///
/// macOS 13+ replaces the legacy `SMLoginItemSetEnabled` / LaunchAgent
/// pattern with `SMAppService`, which registers the running .app itself
/// as the login item. No helper target required, no plist file to
/// install by hand — the system owns the lifecycle.
enum LoginItemService {
    enum LoginItemError: LocalizedError {
        case registrationFailed(underlying: Error)
        case unregistrationFailed(underlying: Error)
        case notAuthorized

        var errorDescription: String? {
            switch self {
            case .registrationFailed(let err):
                return "Couldn't enable launch at login: \(err.localizedDescription)"
            case .unregistrationFailed(let err):
                return "Couldn't disable launch at login: \(err.localizedDescription)"
            case .notAuthorized:
                return "Launch at login is blocked by System Settings → Login Items."
            }
        }
    }

    /// Current registration state. `.requiresApproval` maps to `isEnabled=true`
    /// because from our perspective the user asked for it; they just need to
    /// approve in System Settings for it to actually take effect.
    static var isEnabled: Bool {
        switch SMAppService.mainApp.status {
        case .enabled, .requiresApproval:
            return true
        case .notRegistered, .notFound:
            return false
        @unknown default:
            return false
        }
    }

    /// `true` when the user needs to flip a switch in System Settings → Login
    /// Items before launch-at-login actually fires. The UI should surface a
    /// hint when this is the case.
    static var requiresUserApproval: Bool {
        SMAppService.mainApp.status == .requiresApproval
    }

    static func setEnabled(_ enabled: Bool) throws {
        let service = SMAppService.mainApp
        do {
            if enabled {
                if service.status != .enabled {
                    try service.register()
                }
            } else {
                if service.status != .notRegistered && service.status != .notFound {
                    try service.unregister()
                }
            }
        } catch {
            if enabled {
                throw LoginItemError.registrationFailed(underlying: error)
            } else {
                throw LoginItemError.unregistrationFailed(underlying: error)
            }
        }
    }
}
