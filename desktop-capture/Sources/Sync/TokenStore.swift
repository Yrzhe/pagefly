import Foundation

/// File-backed API token store. Replaces Keychain for personal / ad-hoc
/// builds because every rebuild changes the binary's cdhash and Keychain
/// ACLs are bound to cdhash — so each rebuild prompted the user to "Always
/// Allow" before any uploader could read the token. The file lives at:
///   `~/Library/Application Support/PageFly/api_token`  (mode 0600)
///
/// This is a deliberate downgrade from Keychain — the token is protected
/// by POSIX permissions on the user's home, not by Keychain's per-binary
/// ACL. For the personal-use ad-hoc build that's the right tradeoff:
/// macOS already gates the home directory by login, and we get rid of
/// repeated unlock prompts. A future signed Developer ID release can swap
/// this back to Keychain (stable cdhash → no prompts).
enum TokenStore {
    private static let fileName = "api_token"

    private static var fileURL: URL {
        let support = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return support
            .appendingPathComponent("PageFly")
            .appendingPathComponent(fileName)
    }

    /// Returns nil when the file is missing or empty. Trims whitespace so a
    /// trailing newline pasted via `echo … >` doesn't poison the token.
    static func load() -> String? {
        guard let data = try? Data(contentsOf: fileURL),
              let raw = String(data: data, encoding: .utf8) else {
            return nil
        }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// Atomic write + chmod 600. Creates the parent directory if missing.
    static func save(_ value: String) throws {
        let url = fileURL
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(value.utf8).write(to: url, options: [.atomic])
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }

    /// No-op if the file is already absent.
    static func delete() {
        try? FileManager.default.removeItem(at: fileURL)
    }
}
