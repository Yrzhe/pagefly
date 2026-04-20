import AppKit
import Combine
import CryptoKit
import Foundation

/// User-triggered "OCR this window" action. Bridges `WindowOCR` (pure
/// capture + recognize) into the same `local_events` table that AX-based
/// capture writes to, so rescued content flows through the existing upload
/// pipeline without any server-side changes.
///
/// Rows emitted here carry `ax_role = "AXOCR"` and a dedicated context
/// hash so they never merge with the live AX-tracked row — a click at 09:32
/// creates a standalone timeline entry at 09:32, not a silent extension of
/// whatever was already open.
@MainActor
final class OCRRescue: ObservableObject {
    static let shared = OCRRescue()

    /// Transient UI state so the menu popover can show a spinner + result
    /// without having to plumb callbacks into SwiftUI.
    @Published private(set) var isRunning = false
    @Published private(set) var lastStatus: String?
    @Published private(set) var lastError: String?

    /// How long to wait before OCR-ing the same app again in auto mode.
    /// 5 minutes gives ~0.07% average CPU on a persistent chat app, well
    /// below the ~15% budget of continuous OCR (rem/screenpipe-style).
    private static let autoTTL: TimeInterval = 300
    /// When set, auto mode backs off further (e.g. after a permission
    /// failure). Avoids flooding the logs with the same "no Screen
    /// Recording TCC" error every 5 minutes.
    private static let autoBackoffAfterError: TimeInterval = 30 * 60

    /// Per-bundle timestamp of the last auto-OCR attempt. Manual mode
    /// ignores this map entirely so the user's button press is never
    /// throttled.
    private var autoLastAt: [String: Date] = [:]
    /// Permission-failure backoff per bundle — bumps `autoLastAt` out
    /// into the future so the next retry waits `autoBackoffAfterError`.
    private var autoErrorMuteUntil: Date?

    private let isoFormatter: ISO8601DateFormatter
    private var clearTask: Task<Void, Never>?

    private init() {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        self.isoFormatter = f
    }

    /// Run OCR on the currently focused window and insert the result as a
    /// new `local_events` row. Designed to be called from a menu action;
    /// popover-close timing is the caller's problem.
    func rescueFocusedWindow() {
        run(mode: .manual)
    }

    /// Auto mode — called by CapturePipeline when the AX snapshot came
    /// back empty (or near-empty on a Canvas-rendered page). Throttle
    /// key is `bundleID + URL` so a single browser process can OCR
    /// multiple Canvas pages independently (one Feishu page shouldn't
    /// lock out the next Feishu page for 5 min). Silent on success; on
    /// permission-like failures, bumps a global mute so logs don't get
    /// spammed. Manual mode is unaffected by throttle state.
    func autoRescueIfEligible(bundleID: String, url: String = "") {
        guard !isRunning else { return }
        guard !bundleID.isEmpty else { return }
        if let muteUntil = autoErrorMuteUntil, Date() < muteUntil { return }
        // Normalize URL to origin+path; query strings on SPA navigations
        // shouldn't produce a new throttle bucket per keystroke.
        let key = Self.throttleKey(bundleID: bundleID, url: url)
        if let last = autoLastAt[key], Date().timeIntervalSince(last) < Self.autoTTL {
            return
        }
        autoLastAt[key] = Date()
        run(mode: .auto)
    }

    /// Combine bundleID + URL (truncated to path) into a stable throttle
    /// key. Falls back to bundleID alone for non-web apps, and for
    /// `file://` URLs — those typically point to a locally-bundled
    /// WebView shell (e.g. Feishu's `file:///Applications/Lark.app/...`)
    /// that varies per internal route in ways we can't meaningfully
    /// distinguish, so per-URL throttling there just fires OCR
    /// continuously for one document.
    private static func throttleKey(bundleID: String, url: String) -> String {
        let bundle = bundleID.lowercased()
        guard !url.isEmpty, let u = URL(string: url) else { return bundle }
        if u.scheme == "file" { return bundle }
        let host = u.host ?? ""
        let path = u.path
        return "\(bundle)|\(host)\(path)"
    }

    // MARK: - Runner

    private enum Mode { case manual, auto }

    private func run(mode: Mode) {
        guard !isRunning else { return }
        isRunning = true
        if mode == .manual {
            lastError = nil
            lastStatus = "Capturing…"
        }

        Task { [weak self] in
            guard let self else { return }
            defer { Task { @MainActor in self.isRunning = false } }
            do {
                if mode == .manual {
                    // Give the popover ~250ms to finish closing. Without
                    // this the screenshot captures the popover's content
                    // area and OCRs the menu text instead of the app.
                    try? await Task.sleep(nanoseconds: 250_000_000)
                }

                let result = try await WindowOCR.captureAndRecognize()
                try await self.persist(result)

                if mode == .manual {
                    await MainActor.run {
                        if result.lineCount == 0 {
                            self.lastStatus = "OCR found no text. Window may be blank or all-image."
                        } else {
                            self.lastStatus = "OCR captured \(result.lineCount) line\(result.lineCount == 1 ? "" : "s") from \(result.app)."
                        }
                        Uploader.shared.kick()
                    }
                    self.scheduleStatusClear()
                } else {
                    // Auto mode logs instead of nagging the popover.
                    logCapture(.info, "Auto OCR (\(result.bundleID)) → \(result.lineCount) line(s)")
                    await MainActor.run { Uploader.shared.kick() }
                }
            } catch {
                logCapture(mode == .manual ? .error : .warn,
                           "\(mode == .manual ? "Manual" : "Auto") OCR failed: \(error)")
                if mode == .manual {
                    await MainActor.run {
                        self.lastError = (error as? LocalizedError)?.errorDescription
                            ?? error.localizedDescription
                        self.lastStatus = nil
                    }
                    self.scheduleStatusClear()
                } else {
                    // Likely Screen Recording permission or similar system
                    // issue — back off so we don't retry every tick and
                    // fill the logs with the same error.
                    await MainActor.run {
                        self.autoErrorMuteUntil = Date().addingTimeInterval(Self.autoBackoffAfterError)
                    }
                }
            }
        }
    }

    // MARK: - Persistence

    private func persist(_ result: WindowOCR.Result) async throws {
        let nowIso = isoFormatter.string(from: result.capturedAt)
        let uuid = ContextDedup.makeLocalUUID()
        // Private context hash so the AX dedup path never tries to extend
        // this row. Each OCR click stands alone.
        let hashInput = "AXOCR|\(result.bundleID)|\(nowIso)|\(result.text.prefix(500))"
        let digest = Insecure.SHA1.hash(data: Data(hashInput.utf8))
        let hash = digest.map { String(format: "%02x", $0) }.joined().prefix(16)

        let event = LocalEvent(
            local_uuid: uuid,
            started_at: nowIso,
            ended_at: nowIso,
            duration_s: 0,
            app: result.app,
            bundle_id: result.bundleID,
            window_title: result.windowTitle,
            url: "",
            text_excerpt: result.text,
            ax_role: "AXOCR",
            context_hash: String(hash),
            audio_uuid: nil,
            status: LocalEventStatus.pending.rawValue,
            remote_id: nil,
            created_at: nowIso
        )
        try LocalDB.shared.insert(event)
        logCapture(.info, "OCR rescue (\(result.bundleID)) → \(result.lineCount) line(s)")
    }

    /// Clear success/error text after 6s so the popover doesn't look stuck
    /// on a stale message if the user opens it again later.
    private func scheduleStatusClear() {
        clearTask?.cancel()
        clearTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 6 * 1_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                self?.lastStatus = nil
                self?.lastError = nil
            }
        }
    }
}
