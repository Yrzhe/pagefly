import AppKit
import Foundation

/// Drains pending rows from LocalDB to the server. Runs every 5 min by
/// default plus on wake, with exponential backoff on transient failures.
/// Also performs nightly-ish housekeeping: vacuums uploaded rows > 14 days
/// old and prunes the pending queue if it overflows.
///
/// Not an `actor` because it needs tight collaboration with `@MainActor`
/// state (SettingsStore, Timer, NSWorkspace notifications). Locking-wise
/// there's only one flush in flight at a time thanks to the `isUploading`
/// guard.
@MainActor
final class Uploader {
    static let shared = Uploader()

    // MARK: Config

    /// Nominal interval between opportunistic drains.
    static let baseInterval: TimeInterval = 5 * 60
    /// Rows uploaded per POST.
    static let batchSize = 500
    /// Drop oldest pending rows if queue exceeds this. A real offline spell
    /// should still be well under this limit; the cap protects against
    /// runaway disk growth.
    static let queueHardMax = 10_000
    /// Uploaded rows older than this get garbage-collected locally.
    static let retentionDays = 14

    /// Back-off schedule for transport / 5xx errors. Transitions reset on
    /// any successful batch.
    static let backoffLadder: [TimeInterval] = [30, 60, 120, 300]

    // MARK: State

    private(set) var isUploading = false
    private var timer: Timer?
    private var wakeObserver: NSObjectProtocol?
    private var backoffIndex: Int = 0
    private var nextAttemptAt: Date?
    /// Set when stop() is called so in-flight flushes / wake callbacks don't
    /// re-arm the timer after shutdown.
    private var isStopped = true

    private init() {}

    // MARK: Lifecycle

    func start() {
        guard timer == nil else { return }
        isStopped = false
        scheduleTimer(after: 15) // first drain 15s after start, not 5min
        installWakeObserver()
        logCapture(.info, "Uploader started")
    }

    func stop(reason: String = "stop") {
        isStopped = true
        timer?.invalidate()
        timer = nil
        if let o = wakeObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(o)
            wakeObserver = nil
        }
        logCapture(.info, "Uploader stopped (\(reason))")
    }

    private func installWakeObserver() {
        let ws = NSWorkspace.shared.notificationCenter
        wakeObserver = ws.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                logCapture(.info, "Wake — flushing uploader")
                await self?.flush()
            }
        }
    }

    private func scheduleTimer(after delay: TimeInterval) {
        timer?.invalidate()
        if isStopped { return }
        let t = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            Task { @MainActor in
                await self?.flush()
                // After each flush, reschedule for the next drain respecting
                // any active backoff — unless stop() was called mid-flush.
                self?.rescheduleAfterFlush()
            }
        }
        t.tolerance = 10
        timer = t
    }

    private func rescheduleAfterFlush() {
        if isStopped { return }
        let base: TimeInterval
        if let next = nextAttemptAt, next > Date() {
            base = next.timeIntervalSinceNow
        } else {
            base = Uploader.baseInterval
        }
        scheduleTimer(after: max(1, base))
    }

    // MARK: Flush

    /// Drain one batch. Safe to call repeatedly; overlapping calls are
    /// coalesced via `isUploading`.
    func flush() async {
        if isStopped { return }
        guard !isUploading else { return }
        isUploading = true
        defer { isUploading = false }

        // Housekeeping first so bugs in the drain path don't stop the DB
        // from self-limiting.
        runHousekeeping()

        // Hold back while a backoff window is active.
        if let next = nextAttemptAt, next > Date() { return }

        guard let client = APIClient.from(SettingsStore.shared) else {
            return
        }

        let pending: [LocalEvent]
        do {
            pending = try LocalDB.shared.fetchPending(limit: Uploader.batchSize)
        } catch {
            logCapture(.error, "fetchPending failed: \(error)")
            return
        }
        guard !pending.isEmpty else {
            return
        }

        do {
            let result = try await client.postEventsBatch(pending)
            try LocalDB.shared.markUploaded(result.inserted)
            // Any rows we sent that the server didn't confirm are poison
            // pills — malformed client-side. Mark failed so they stop
            // blocking the queue, but keep them in the DB for inspection.
            let sent = Set(pending.map { $0.local_uuid })
            let accepted = Set(result.inserted.keys)
            let rejected = Array(sent.subtracting(accepted))
            if !rejected.isEmpty {
                try LocalDB.shared.markFailed(rejected)
                logCapture(.warn, "Uploader: \(rejected.count) rows rejected, marked failed")
            }
            backoffIndex = 0
            nextAttemptAt = nil
            SettingsStore.shared.lastSyncedAt = Date()
            logCapture(.info, "Uploaded \(result.inserted.count)/\(pending.count) events (skipped=\(result.skipped))")
        } catch APIClient.BatchError.unauthorized {
            logCapture(.warn, "Uploader: token rejected — pausing until new token")
            SettingsStore.shared.connectionState = .unauthorized
            nextAttemptAt = Date().addingTimeInterval(Uploader.backoffLadder.last ?? 300)
            // Don't stop entirely — a new token will reset state.
        } catch APIClient.BatchError.server(let code, let body) {
            logCapture(.warn, "Uploader: server \(code) — backing off (body head: \(body))")
            applyBackoff()
        } catch APIClient.BatchError.transport(let why) {
            logCapture(.warn, "Uploader: transport fail (\(why)) — backing off")
            applyBackoff()
        } catch APIClient.BatchError.decode(let why) {
            logCapture(.error, "Uploader: response decode failed (\(why)) — backing off")
            applyBackoff()
        } catch {
            logCapture(.error, "Uploader: unknown error: \(error)")
            applyBackoff()
        }
    }

    private func applyBackoff() {
        let delay = Uploader.backoffLadder[min(backoffIndex, Uploader.backoffLadder.count - 1)]
        nextAttemptAt = Date().addingTimeInterval(delay)
        backoffIndex = min(backoffIndex + 1, Uploader.backoffLadder.count - 1)
    }

    // MARK: Housekeeping

    private func runHousekeeping() {
        do {
            let cutoff = Uploader.retentionCutoffISO()
            let removed = try LocalDB.shared.vacuumUploaded(olderThan: cutoff)
            if removed > 0 {
                logCapture(.info, "Vacuumed \(removed) uploaded rows older than \(Uploader.retentionDays)d")
            }
            let pruned = try LocalDB.shared.pruneIfOverflow(max: Uploader.queueHardMax)
            if pruned > 0 {
                logCapture(.warn, "Pruned \(pruned) oldest pending rows (queue > \(Uploader.queueHardMax))")
            }
        } catch {
            logCapture(.warn, "Housekeeping failed: \(error)")
        }
    }

    private static func retentionCutoffISO() -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = Date().addingTimeInterval(-Double(retentionDays) * 86400)
        return formatter.string(from: date)
    }
}
