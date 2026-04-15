import Foundation

/// Collapses a stream of identical-context snapshots into one row that grows
/// in `duration_s`, and emits a fresh row whenever the context hash changes
/// (or whenever a hard 30-minute cap is hit).
///
/// The dedup state is in-memory; `LocalDB` is the persistent counterpart.
/// Crash recovery isn't perfect (we may miss the trailing `ended_at` of an
/// open row) but the upload pipeline tolerates that since the server
/// computes everything from `started_at` + `duration_s`.
@MainActor
final class ContextDedup {
    static let hardCutSeconds: Int = 30 * 60   // 30-min hard cut
    static let bumpInterval: Int = 30          // matches ScreenSampler tick

    /// Currently open row, if any. When the user keeps focus on the same
    /// context, we extend this row instead of creating a new one.
    private var current: Open?

    private struct Open {
        let localUUID: String
        let snapshot: ContextSnapshot
        let hash: String
        var startedAt: Date
        var lastSeen: Date
        var duration: Int
    }

    private let db: LocalDB
    private let isoFormatter: ISO8601DateFormatter

    init(db: LocalDB = .shared) {
        self.db = db
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        self.isoFormatter = f
    }

    /// Process one snapshot. Either inserts a new row, extends the open row,
    /// or rotates (close current + open new) if the hash changed or the
    /// 30-minute cap was hit.
    func ingest(_ snapshot: ContextSnapshot) {
        let hash = ContextHash.compute(snapshot)
        let now = snapshot.capturedAt

        if let open = current,
           open.hash == hash,
           open.duration < ContextDedup.hardCutSeconds {
            extendCurrent(open: open, snapshot: snapshot, at: now)
            return
        }

        // Hash changed (or hard-cut). Close current and open a new row.
        if current != nil {
            closeCurrent(at: now)
        }
        startNew(snapshot: snapshot, hash: hash, at: now)
    }

    /// Force-close any open row (called when capture is paused, app quits,
    /// or the system goes idle).
    func flush(at date: Date = Date()) {
        if current != nil {
            closeCurrent(at: date)
        }
    }

    // MARK: - Private

    private func extendCurrent(open: Open, snapshot: ContextSnapshot, at now: Date) {
        let bump = max(1, Int(now.timeIntervalSince(open.lastSeen).rounded()))
        let cappedBump = min(bump, ContextDedup.bumpInterval * 2)
        let newDuration = open.duration + cappedBump

        var updated = open
        updated.duration = newDuration
        updated.lastSeen = now
        current = updated

        do {
            try db.extend(
                localUUID: open.localUUID,
                by: cappedBump,
                endedAt: isoFormatter.string(from: now),
                textExcerpt: snapshot.textExcerpt
            )
        } catch {
            logCapture(.error, "extend failed for \(open.localUUID): \(error)")
        }
    }

    private func closeCurrent(at date: Date) {
        guard let open = current else { return }
        do {
            try db.extend(
                localUUID: open.localUUID,
                by: 0,
                endedAt: isoFormatter.string(from: date),
                textExcerpt: open.snapshot.textExcerpt
            )
        } catch {
            logCapture(.error, "close failed for \(open.localUUID): \(error)")
        }
        current = nil
    }

    private func startNew(snapshot: ContextSnapshot, hash: String, at now: Date) {
        let uuid = ContextDedup.makeLocalUUID()
        let event = LocalEvent(
            local_uuid: uuid,
            started_at: isoFormatter.string(from: now),
            ended_at: nil,
            duration_s: 0,
            app: snapshot.app,
            bundle_id: snapshot.bundleID,
            window_title: snapshot.windowTitle,
            url: snapshot.url,
            text_excerpt: snapshot.textExcerpt,
            ax_role: snapshot.axRole,
            context_hash: hash,
            audio_uuid: nil,
            status: LocalEventStatus.pending.rawValue,
            remote_id: nil,
            created_at: isoFormatter.string(from: now)
        )
        do {
            try db.insert(event)
            current = Open(
                localUUID: uuid,
                snapshot: snapshot,
                hash: hash,
                startedAt: now,
                lastSeen: now,
                duration: 0
            )
            logCapture(.info, "open \(snapshot.app): \(snapshot.windowTitle.prefix(60))")
        } catch {
            logCapture(.error, "insert failed: \(error)")
        }
    }

    /// Server-friendly UUID — base32 alphabet, length 22 to satisfy the
    /// server's `^[A-Za-z0-9_-]{8,64}$` validation comfortably.
    static func makeLocalUUID() -> String {
        let raw = UUID().uuidString
            .replacingOccurrences(of: "-", with: "")
            .lowercased()
        // 32 hex chars; trim to 22 for slightly shorter rows.
        return String(raw.prefix(22))
    }
}
