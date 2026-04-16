import AppKit
import Combine
import Foundation

/// Minimal in-app updater. Polls the GitHub Releases API, compares the
/// published tag against `CFBundleShortVersionString`, and — if a newer
/// build exists — surfaces a "Download" action that opens the release's
/// HTML page in the user's default browser.
///
/// Why not Sparkle? Sparkle is overkill for a single-developer menu-bar
/// app that ships unsigned builds. Opening the release page is safer
/// (the user verifies the binary themselves) and avoids auto-installing
/// anything.
@MainActor
final class UpdateChecker: ObservableObject {
    static let shared = UpdateChecker()

    enum Status: Equatable {
        case unknown
        case checking
        case upToDate(current: String)
        case available(Release)
        case failed(String)
    }

    struct Release: Equatable {
        let version: String
        let htmlURL: URL
        let publishedAt: Date?
    }

    /// Default repo slug. Overridable via UserDefaults key `pagefly.updateRepo`
    /// for forks or private mirrors.
    private static let defaultRepo = "Yrzhe/pagefly"

    /// Auto-check cadence. Manual checks bypass this.
    static let minimumCheckInterval: TimeInterval = 6 * 3600

    @Published private(set) var status: Status = .unknown
    @Published private(set) var lastCheckedAt: Date?

    private var timer: Timer?
    private var inFlight: Task<Void, Never>?
    private var checkEpoch: UInt64 = 0

    private init() {}

    // MARK: - Lifecycle

    func start() {
        // Kick a silent check at launch and every 6h while running.
        Task { await self.checkNow(force: false, userInitiated: false) }
        timer?.invalidate()
        let t = Timer(timeInterval: Self.minimumCheckInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in
                await self?.checkNow(force: false, userInitiated: false)
            }
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        inFlight?.cancel()
        inFlight = nil
    }

    // MARK: - Check

    /// Run a check. When `userInitiated` is true the UI is expected to be
    /// watching `status`, so failures are surfaced. Otherwise failures stay
    /// in the logs.
    func checkNow(force: Bool, userInitiated: Bool) async {
        if let last = lastCheckedAt, !force,
           Date().timeIntervalSince(last) < Self.minimumCheckInterval {
            return
        }
        inFlight?.cancel()
        checkEpoch &+= 1
        let epoch = checkEpoch
        status = .checking
        let task = Task { [weak self] in
            guard let self else { return }
            do {
                let release = try await Self.fetchLatestRelease()
                await MainActor.run {
                    self.lastCheckedAt = Date()
                    if Self.isNewer(remote: release.version, than: Self.currentVersion) {
                        self.status = .available(release)
                        logCapture(.info, "updater: newer version available (\(release.version))")
                    } else {
                        self.status = .upToDate(current: Self.currentVersion)
                    }
                }
            } catch is CancellationError {
                // Silent — superseded by a newer check.
            } catch {
                let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                await MainActor.run {
                    self.lastCheckedAt = Date()
                    if userInitiated {
                        self.status = .failed(msg)
                    } else {
                        // Don't overwrite a prior "available" with a transient
                        // failure during a silent scheduled check.
                        if case .available = self.status { return }
                        self.status = .failed(msg)
                    }
                }
                logCapture(.warn, "updater: check failed — \(msg)")
            }
        }
        inFlight = task
        await task.value
        // Clear the reference so `stop()` and the next check don't cancel a
        // task that already finished. Only clear if we still own it — a
        // racing `checkNow` may have replaced `inFlight` with its own task,
        // detected via the epoch counter.
        if checkEpoch == epoch {
            inFlight = nil
        }
    }

    func openReleasePage() {
        guard case .available(let release) = status else { return }
        NSWorkspace.shared.open(release.htmlURL)
    }

    // MARK: - Networking

    private struct ReleasePayload: Decodable {
        let tag_name: String
        let html_url: String
        let published_at: String?
        let draft: Bool?
        let prerelease: Bool?
    }

    private static func fetchLatestRelease() async throws -> Release {
        let repo = UserDefaults.standard.string(forKey: "pagefly.updateRepo") ?? defaultRepo
        // UserDefaults is writable by anyone with local access (`defaults
        // write …`), so we never trust the raw string — reject anything that
        // isn't a standard owner/repo slug before it lands in the URL.
        guard Self.isValidRepoSlug(repo) else {
            throw UpdateCheckerError.badURL
        }
        guard let url = URL(string: "https://api.github.com/repos/\(repo)/releases/latest") else {
            throw UpdateCheckerError.badURL
        }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")
        req.setValue("PageflyCapture/\(currentVersion) (macOS)", forHTTPHeaderField: "User-Agent")

        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw UpdateCheckerError.transport("no http response")
        }
        switch http.statusCode {
        case 200: break
        case 404: throw UpdateCheckerError.noReleases
        case 403: throw UpdateCheckerError.rateLimited
        default: throw UpdateCheckerError.serverStatus(http.statusCode)
        }
        let payload = try JSONDecoder().decode(ReleasePayload.self, from: data)
        if payload.draft == true || payload.prerelease == true {
            throw UpdateCheckerError.noReleases
        }
        guard let html = URL(string: payload.html_url),
              html.scheme == "https",
              let host = html.host?.lowercased(),
              (host == "github.com" || host.hasSuffix(".github.com")) else {
            // Even a well-formed response can't redirect the user to a
            // non-github host — that would sidestep the slug validation
            // above and let an attacker serve a trojanized build.
            throw UpdateCheckerError.badResponse
        }
        let version = Self.normalizeVersion(payload.tag_name)
        let published: Date? = payload.published_at.flatMap {
            let f = ISO8601DateFormatter()
            f.formatOptions = [.withInternetDateTime]
            return f.date(from: $0)
        }
        return Release(version: version, htmlURL: html, publishedAt: published)
    }

    // MARK: - Version math

    static var currentVersion: String {
        (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0.0.0"
    }

    static func normalizeVersion(_ raw: String) -> String {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("v") || s.hasPrefix("V") { s.removeFirst() }
        return s
    }

    /// Compare semver-ish strings. Extra numeric components default to 0 so
    /// "1.0" < "1.0.1". Non-numeric suffixes (e.g. "-beta") are ignored for
    /// the comparison, which is fine for a consumer updater.
    static func isNewer(remote: String, than local: String) -> Bool {
        let r = components(from: remote)
        let l = components(from: local)
        let count = max(r.count, l.count)
        for i in 0..<count {
            let a = i < r.count ? r[i] : 0
            let b = i < l.count ? l[i] : 0
            if a != b { return a > b }
        }
        return false
    }

    private static func components(from version: String) -> [Int] {
        let core = version.split(separator: "-", maxSplits: 1).first.map(String.init) ?? version
        return core.split(separator: ".").map { Int($0) ?? 0 }
    }

    /// GitHub restricts owner + repo names to letters, digits, `-`, `_`, `.`
    /// with a single slash separator. Reject anything else so a tampered
    /// UserDefaults value can't become `evil.com/?x=` or include path escapes.
    static func isValidRepoSlug(_ slug: String) -> Bool {
        let parts = slug.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2, !parts[0].isEmpty, !parts[1].isEmpty else { return false }
        let allowed = CharacterSet(charactersIn:
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.")
        for part in parts {
            if part.rangeOfCharacter(from: allowed.inverted) != nil { return false }
            if part == "." || part == ".." { return false }
        }
        return true
    }
}

enum UpdateCheckerError: LocalizedError {
    case badURL
    case noReleases
    case rateLimited
    case serverStatus(Int)
    case transport(String)
    case badResponse

    var errorDescription: String? {
        switch self {
        case .badURL: return "Update feed URL is invalid."
        case .noReleases: return "No published release found yet."
        case .rateLimited: return "GitHub rate limit hit. Try again later."
        case .serverStatus(let code): return "Update server returned status \(code)."
        case .transport(let why): return "Couldn't reach update server: \(why)."
        case .badResponse: return "Malformed update response."
        }
    }
}
