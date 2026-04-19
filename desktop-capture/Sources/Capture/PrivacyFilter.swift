import Foundation

/// Decides whether a given snapshot should be persisted at all. Three rules
/// today:
///   1. Drop if the bundle ID is on the blocklist.
///   2. Drop if the AX role is the secure text field (passwords).
///   3. Trim text excerpt to a bounded size so we never persist megabytes.
struct PrivacyFilter {
    /// Default hard blocklist — the kinds of apps that should never appear in
    /// a work log. Users can extend this in Preferences (M3+ polish).
    static let defaultBlocklist: Set<String> = [
        "com.apple.keychainaccess",
        "com.agilebits.onepassword",
        "com.agilebits.onepassword7",
        "com.1password.1password8",
        "com.bitwarden.desktop",
        "com.dashlane.dashlanephonefinal",
        "com.lastpass.LastPass",
        "com.apple.MobileSMS",         // Messages
        "org.whispersystems.signal-desktop",
        "com.tinyspeck.slackmacgap.privatebrowsing", // hypothetical, just an example
        // Skip self — opening the popover or Dashboard would otherwise
        // generate "open event (top.yrzhe.PageflyCapture)" rows that ride
        // up to the server and clutter the daily work log. The user does
        // not consider "I checked the dashboard" as work-log content.
        "top.yrzhe.pageflycapture",
    ]

    /// AX roles we always drop. AXSecureTextField means a password field is
    /// focused and its value is masked anyway; better to skip the whole event.
    static let blockedAXRoles: Set<String> = [
        "AXSecureTextField",
    ]

    /// Maximum bytes of text we keep per snapshot. Larger values get truncated
    /// to head + tail with a separator so the dedup hash stays stable for the
    /// same context but the row size stays bounded.
    static let maxTextBytes = 1024

    var blocklist: Set<String>

    init(blocklist: Set<String> = PrivacyFilter.defaultBlocklist) {
        self.blocklist = blocklist
    }

    /// Returns nil if the snapshot should be dropped. Otherwise returns a
    /// possibly-modified snapshot ready for the dedup stage.
    func sanitize(_ snapshot: ContextSnapshot) -> ContextSnapshot? {
        if blocklist.contains(snapshot.bundleID.lowercased()) {
            return nil
        }
        if PrivacyFilter.blockedAXRoles.contains(snapshot.axRole) {
            return nil
        }

        let trimmedText = PrivacyFilter.truncate(snapshot.textExcerpt, to: PrivacyFilter.maxTextBytes)

        return ContextSnapshot(
            app: snapshot.app,
            bundleID: snapshot.bundleID,
            windowTitle: snapshot.windowTitle,
            url: snapshot.url,
            textExcerpt: trimmedText,
            axRole: snapshot.axRole,
            capturedAt: snapshot.capturedAt
        )
    }

    static func truncate(_ s: String, to max: Int) -> String {
        guard s.utf8.count > max else { return s }
        // Keep head + tail with a marker so context is still readable.
        let head = String(s.prefix(max - 200))
        let tail = String(s.suffix(200))
        return head + " …[truncated] " + tail
    }
}
