import Foundation
import CryptoKit

/// One reading of "what is the user looking at right now" — produced by
/// `AXReader`, filtered by `PrivacyFilter`, deduplicated by `ContextDedup`,
/// and finally persisted into `local_events`.
///
/// Treat this as immutable; create new instances for new readings.
struct ContextSnapshot {
    let app: String          // e.g. "Visual Studio Code"
    let bundleID: String     // e.g. "com.microsoft.VSCode"
    let windowTitle: String
    let url: String          // empty unless the host app exposes AXURL
    let textExcerpt: String  // truncated; see PrivacyFilter
    let axRole: String       // e.g. "AXTextArea", "AXWebArea", "AXSecureTextField"
    let capturedAt: Date
}

enum ContextHash {
    /// sha1 over the dedup-significant fields. Title and text are truncated to
    /// keep the hash stable even when long content scrolls or wraps. Title is
    /// also normalized to strip unread-count badges (`"(3) Bloome"`,
    /// `"[12] Slack"`, `"(99+) Mail"`) before hashing — without this, every
    /// new incoming message bumped the badge → new title → new hash → a
    /// fresh row per message tick. The display copy of title is preserved on
    /// the snapshot itself; only the hash key uses the stripped form.
    static func compute(_ s: ContextSnapshot) -> String {
        let titleSlice = String(stripBadgeCounts(s.windowTitle).prefix(120))
        let textSlice = String(s.textExcerpt.prefix(500))
        let raw = "\(s.bundleID)|\(s.app)|\(titleSlice)|\(s.url)|\(textSlice)"
        let digest = Insecure.SHA1.hash(data: Data(raw.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    /// Strip leading `(N)` / `[N]` / `(N+)` badge counts from a window
    /// title. Recurses for nested badges (`"(3) (Beta) Slack"` keeps
    /// `"(Beta) Slack"`). Internal — only used for dedup hashing.
    static func stripBadgeCounts(_ title: String) -> String {
        var s = title.trimmingCharacters(in: .whitespaces)
        while let opener = s.first, opener == "(" || opener == "[" {
            let closer: Character = opener == "(" ? ")" : "]"
            guard let closeIdx = s.firstIndex(of: closer) else { break }
            let inside = s[s.index(after: s.startIndex)..<closeIdx]
            // Accept "12", "99+", "+12" — anything that's only digits and +.
            let allDigits = !inside.isEmpty && inside.allSatisfy { $0.isNumber || $0 == "+" }
            guard allDigits else { break }
            s = String(s[s.index(after: closeIdx)...]).trimmingCharacters(in: .whitespaces)
        }
        return s
    }
}
