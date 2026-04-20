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
        guard !isRunning else { return }
        isRunning = true
        lastError = nil
        lastStatus = "Capturing…"

        Task { [weak self] in
            guard let self else { return }
            defer { Task { @MainActor in self.isRunning = false } }
            do {
                // Give the popover ~250ms to finish closing. Without this
                // the screenshot still captures the popover's content area
                // and OCRs the menu text instead of the app.
                try? await Task.sleep(nanoseconds: 250_000_000)

                let result = try await WindowOCR.captureAndRecognize()
                try await self.persist(result)

                await MainActor.run {
                    if result.lineCount == 0 {
                        self.lastStatus = "OCR found no text. Window may be blank or all-image."
                    } else {
                        self.lastStatus = "OCR captured \(result.lineCount) line\(result.lineCount == 1 ? "" : "s") from \(result.app)."
                    }
                    Uploader.shared.kick()
                }
                self.scheduleStatusClear()
            } catch {
                logCapture(.error, "OCR rescue failed: \(error)")
                await MainActor.run {
                    self.lastError = (error as? LocalizedError)?.errorDescription
                        ?? error.localizedDescription
                    self.lastStatus = nil
                }
                self.scheduleStatusClear()
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
