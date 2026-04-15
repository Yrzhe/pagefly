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
    /// keep the hash stable even when long content scrolls or wraps.
    static func compute(_ s: ContextSnapshot) -> String {
        let titleSlice = String(s.windowTitle.prefix(120))
        let textSlice = String(s.textExcerpt.prefix(500))
        let raw = "\(s.bundleID)|\(s.app)|\(titleSlice)|\(s.url)|\(textSlice)"
        let digest = Insecure.SHA1.hash(data: Data(raw.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
