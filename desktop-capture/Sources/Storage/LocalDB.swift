import Foundation
import GRDB

/// Owns the local SQLite queue. Lives at
/// `~/Library/Application Support/PageFly/capture.db`.
///
/// All mutations go through `dbQueue.write { ... }`; reads can use
/// `dbQueue.read { ... }`. GRDB handles serialization across threads.
final class LocalDB {
    static let shared = LocalDB()

    let dbQueue: DatabaseQueue

    private init() {
        let url = LocalDB.databaseURL()
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            var config = Configuration()
            config.foreignKeysEnabled = true
            self.dbQueue = try DatabaseQueue(path: url.path, configuration: config)
            try LocalDB.migrator.migrate(self.dbQueue)
        } catch {
            // If the DB can't even be opened, the app can't run. Crash with a
            // clear message rather than entering an inconsistent state.
            fatalError("LocalDB init failed at \(url.path): \(error)")
        }
    }

    static func databaseURL() -> URL {
        let support = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return support.appendingPathComponent("PageFly/capture.db")
    }

    // MARK: - Migrations

    private static var migrator: DatabaseMigrator {
        var m = DatabaseMigrator()

        m.registerMigration("v1_create_local_events") { db in
            try db.create(table: LocalEvent.databaseTableName) { t in
                t.column("local_uuid", .text).notNull().primaryKey()
                t.column("started_at", .text).notNull()
                t.column("ended_at", .text)
                t.column("duration_s", .integer).notNull().defaults(to: 0)
                t.column("app", .text).notNull().defaults(to: "")
                t.column("bundle_id", .text).notNull().defaults(to: "")
                t.column("window_title", .text).notNull().defaults(to: "")
                t.column("url", .text).notNull().defaults(to: "")
                t.column("text_excerpt", .text).notNull().defaults(to: "")
                t.column("ax_role", .text).notNull().defaults(to: "")
                t.column("context_hash", .text).notNull().defaults(to: "")
                t.column("audio_uuid", .text)
                t.column("status", .text).notNull().defaults(to: "pending")
                t.column("remote_id", .integer)
                t.column("created_at", .text).notNull()
            }
            try db.create(index: "idx_local_events_status",
                          on: LocalEvent.databaseTableName,
                          columns: ["status"])
            try db.create(index: "idx_local_events_started",
                          on: LocalEvent.databaseTableName,
                          columns: ["started_at"])
            try db.create(index: "idx_local_events_hash",
                          on: LocalEvent.databaseTableName,
                          columns: ["context_hash"])
        }

        m.registerMigration("v2_create_local_audio") { db in
            try db.create(table: LocalAudio.databaseTableName) { t in
                t.column("local_uuid", .text).notNull().primaryKey()
                t.column("started_at", .text).notNull()
                t.column("ended_at", .text)
                t.column("duration_s", .integer).notNull().defaults(to: 0)
                t.column("file_path", .text).notNull().defaults(to: "")
                t.column("file_size_bytes", .integer).notNull().defaults(to: 0)
                t.column("format", .text).notNull().defaults(to: "m4a")
                t.column("source", .text).notNull().defaults(to: "mic")
                t.column("trigger_app", .text).notNull().defaults(to: "")
                t.column("status", .text).notNull().defaults(to: "pending_upload")
                t.column("remote_id", .integer)
                t.column("transcript", .text)
                t.column("created_at", .text).notNull()
            }
            try db.create(index: "idx_local_audio_status",
                          on: LocalAudio.databaseTableName,
                          columns: ["status"])
            try db.create(index: "idx_local_audio_started",
                          on: LocalAudio.databaseTableName,
                          columns: ["started_at"])
        }

        m.registerMigration("v3_audio_transcribed_at") { db in
            try db.alter(table: LocalAudio.databaseTableName) { t in
                t.add(column: "transcribed_at", .text)
            }
        }

        m.registerMigration("v4_audio_uploaded_at") { db in
            try db.alter(table: LocalAudio.databaseTableName) { t in
                t.add(column: "uploaded_at", .text)
            }
        }

        return m
    }

    // MARK: - Helpers used by the capture pipeline

    func insert(_ event: LocalEvent) throws {
        try dbQueue.write { db in
            var copy = event
            try copy.insert(db)
        }
    }

    /// Bump duration and update text_excerpt + ended_at on an existing row.
    /// Used by the dedup path when the same context block stays focused.
    func extend(localUUID: String, by seconds: Int, endedAt: String, textExcerpt: String) throws {
        try dbQueue.write { db in
            try db.execute(sql: """
                UPDATE local_events
                SET duration_s = duration_s + ?,
                    ended_at = ?,
                    text_excerpt = ?
                WHERE local_uuid = ?
                """, arguments: [seconds, endedAt, textExcerpt, localUUID])
        }
    }

    /// Close any in-flight rows on app pause / quit so duration stays bounded.
    func closeOpenRows(at iso: String) throws {
        try dbQueue.write { db in
            try db.execute(sql: """
                UPDATE local_events
                SET ended_at = COALESCE(ended_at, ?)
                WHERE ended_at IS NULL
                """, arguments: [iso])
        }
    }

    func pendingEventCount() throws -> Int {
        try dbQueue.read { db in
            try Int.fetchOne(db, sql:
                "SELECT COUNT(*) FROM local_events WHERE status = 'pending'"
            ) ?? 0
        }
    }

    // MARK: - Uploader helpers

    /// Fetch the oldest pending rows, limited to `limit`. Only rows with a
    /// non-null `ended_at` are returned so the currently-open live row stays
    /// local until it rotates.
    func fetchPending(limit: Int) throws -> [LocalEvent] {
        try dbQueue.read { db in
            try LocalEvent.fetchAll(db, sql: """
                SELECT * FROM local_events
                WHERE status = 'pending' AND ended_at IS NOT NULL
                ORDER BY started_at ASC
                LIMIT ?
                """, arguments: [limit])
        }
    }

    /// Bulk-transition rows to `uploaded` and store their server ids. `idMap`
    /// is the `{local_uuid: server_id}` payload returned by the batch POST.
    func markUploaded(_ idMap: [String: Int64]) throws {
        guard !idMap.isEmpty else { return }
        try dbQueue.write { db in
            for (uuid, remoteId) in idMap {
                try db.execute(sql: """
                    UPDATE local_events
                    SET status = 'uploaded', remote_id = ?
                    WHERE local_uuid = ?
                    """, arguments: [remoteId, uuid])
            }
        }
    }

    /// Bulk-transition rows to `failed`. Used when the server explicitly
    /// rejected them (malformed, unsafe uuid) so they stop blocking the
    /// queue. Failed rows are kept for inspection and are not retried.
    func markFailed(_ uuids: [String]) throws {
        guard !uuids.isEmpty else { return }
        try dbQueue.write { db in
            for uuid in uuids {
                try db.execute(sql: """
                    UPDATE local_events
                    SET status = 'failed'
                    WHERE local_uuid = ?
                    """, arguments: [uuid])
            }
        }
    }

    /// Delete uploaded rows older than the given threshold. Keeps the local
    /// db from growing without bound (server has full history already).
    @discardableResult
    func vacuumUploaded(olderThan iso: String) throws -> Int {
        try dbQueue.write { db in
            try db.execute(sql: """
                DELETE FROM local_events
                WHERE status = 'uploaded' AND COALESCE(ended_at, started_at) < ?
                """, arguments: [iso])
            return db.changesCount
        }
    }

    /// If the pending backlog exceeds `max`, drop the oldest excess rows so
    /// the queue doesn't balloon when the server has been offline for days.
    /// Dropping isn't ideal but unbounded growth is worse.
    @discardableResult
    func pruneIfOverflow(max: Int) throws -> Int {
        try dbQueue.write { db in
            let current = try Int.fetchOne(db, sql:
                "SELECT COUNT(*) FROM local_events WHERE status = 'pending'"
            ) ?? 0
            guard current > max else { return 0 }
            let overflow = current - max
            try db.execute(sql: """
                DELETE FROM local_events
                WHERE local_uuid IN (
                    SELECT local_uuid FROM local_events
                    WHERE status = 'pending'
                    ORDER BY started_at ASC
                    LIMIT ?
                )
                """, arguments: [overflow])
            return overflow
        }
    }

    // MARK: - Audio helpers (M5+)

    func insertAudio(_ audio: LocalAudio) throws {
        try dbQueue.write { db in
            var copy = audio
            try copy.insert(db)
        }
    }

    func pendingAudioCount() throws -> Int {
        try dbQueue.read { db in
            try Int.fetchOne(db, sql:
                "SELECT COUNT(*) FROM local_audio WHERE status = 'pending_upload'"
            ) ?? 0
        }
    }

    func audioExists(uuid: String) throws -> Bool {
        try dbQueue.read { db in
            try Int.fetchOne(db, sql:
                "SELECT 1 FROM local_audio WHERE local_uuid = ? LIMIT 1",
                arguments: [uuid]
            ) != nil
        }
    }

    // MARK: - Audio uploader helpers (M6)

    /// Oldest `pending_upload` rows first. M6 uploads FIFO.
    func fetchPendingAudioUpload(limit: Int) throws -> [LocalAudio] {
        try dbQueue.read { db in
            try LocalAudio.fetchAll(db, sql: """
                SELECT * FROM local_audio
                WHERE status = 'pending_upload'
                ORDER BY started_at ASC
                LIMIT ?
                """, arguments: [limit])
        }
    }

    /// Rows that have a remote_id but haven't been marked transcribed yet.
    /// The uploader polls their status endpoint.
    func fetchAwaitingTranscription() throws -> [LocalAudio] {
        try dbQueue.read { db in
            try LocalAudio.fetchAll(db, sql: """
                SELECT * FROM local_audio
                WHERE status IN ('uploading', 'uploaded')
                  AND remote_id IS NOT NULL
                ORDER BY started_at ASC
                """)
        }
    }

    func markAudioUploading(uuid: String) throws {
        try dbQueue.write { db in
            try db.execute(
                sql: "UPDATE local_audio SET status = 'uploading' WHERE local_uuid = ?",
                arguments: [uuid]
            )
        }
    }

    /// Revert a row to pending_upload — used when a transient failure
    /// (401, transport) interrupts an in-flight upload so the next flush
    /// picks it up again via fetchPendingAudioUpload.
    func revertAudioToPending(uuid: String) throws {
        try dbQueue.write { db in
            try db.execute(
                sql: "UPDATE local_audio SET status = 'pending_upload' WHERE local_uuid = ? AND status = 'uploading'",
                arguments: [uuid]
            )
        }
    }

    func markAudioUploaded(uuid: String, remoteID: Int64, uploadedAtISO: String) throws {
        try dbQueue.write { db in
            try db.execute(sql: """
                UPDATE local_audio
                SET status = 'uploaded',
                    remote_id = ?,
                    uploaded_at = ?
                WHERE local_uuid = ?
                """, arguments: [remoteID, uploadedAtISO, uuid])
        }
    }

    /// Match by remote_id because the status-poll response keys off the server row id.
    func markAudioTranscribed(remoteID: Int64, transcript: String, transcribedAtISO: String) throws {
        try dbQueue.write { db in
            try db.execute(sql: """
                UPDATE local_audio
                SET status = 'transcribed',
                    transcript = ?,
                    transcribed_at = ?
                WHERE remote_id = ?
                """, arguments: [transcript, transcribedAtISO, remoteID])
        }
    }

    /// Terminal failure — stops retrying. Keep the file on disk for a manual
    /// retry; reconcileOrphans skips rows with a matching uuid so we won't
    /// re-insert duplicates.
    func markAudioFailed(uuid: String) throws {
        try dbQueue.write { db in
            try db.execute(
                sql: "UPDATE local_audio SET status = 'failed' WHERE local_uuid = ?",
                arguments: [uuid]
            )
        }
    }

    /// Rows eligible to have their local .m4a deleted: transcribed and older
    /// than the cutoff. Transcript stays in the row forever; only the raw
    /// audio file gets removed to save disk.
    func fetchTranscribedForFileCleanup(olderThan iso: String) throws -> [LocalAudio] {
        try dbQueue.read { db in
            try LocalAudio.fetchAll(db, sql: """
                SELECT * FROM local_audio
                WHERE status = 'transcribed'
                  AND transcribed_at IS NOT NULL
                  AND transcribed_at < ?
                  AND file_path <> ''
                """, arguments: [iso])
        }
    }

    /// After we delete the m4a on disk, blank out file_path so we don't
    /// keep trying. The row itself stays for the transcript.
    func clearAudioFilePath(uuid: String) throws {
        try dbQueue.write { db in
            try db.execute(
                sql: "UPDATE local_audio SET file_path = '' WHERE local_uuid = ?",
                arguments: [uuid]
            )
        }
    }

    // MARK: - Dashboard / retention helpers

    /// Rows where the m4a is still on disk, ordered most-recent first. Skips
    /// `pending_upload` so a slow upload queue can never be silently culled
    /// by the keep-N cap before it ships. Used by both the dashboard list
    /// and the keep-N retention enforcer.
    func fetchRetainedAudioFiles() throws -> [LocalAudio] {
        try dbQueue.read { db in
            try LocalAudio.fetchAll(db, sql: """
                SELECT * FROM local_audio
                WHERE file_path <> ''
                  AND status IN ('uploaded', 'transcribed')
                ORDER BY COALESCE(uploaded_at, created_at) DESC
                """)
        }
    }

    /// Most-recent audio rows for the dashboard list, regardless of file
    /// presence — we still want to show the user a transcribed/failed row
    /// even after its m4a is gone.
    func fetchRecentAudio(limit: Int) throws -> [LocalAudio] {
        try dbQueue.read { db in
            try LocalAudio.fetchAll(db, sql: """
                SELECT * FROM local_audio
                ORDER BY COALESCE(uploaded_at, created_at) DESC
                LIMIT ?
                """, arguments: [limit])
        }
    }

    /// Most-recent events for the dashboard list. Mixes pending + uploaded
    /// so the user sees the full picture; the row's own status drives
    /// whether the delete control appears. Paged because the table can
    /// grow into the thousands once uploads back up against an offline
    /// server, and rendering a 5k-row LazyVStack still costs real memory.
    func fetchRecentEvents(limit: Int, offset: Int = 0) throws -> [LocalEvent] {
        try dbQueue.read { db in
            try LocalEvent.fetchAll(db, sql: """
                SELECT * FROM local_events
                ORDER BY COALESCE(ended_at, started_at) DESC
                LIMIT ? OFFSET ?
                """, arguments: [limit, offset])
        }
    }

    /// Total row count — drives the dashboard's page-of-N indicator.
    func eventCount() throws -> Int {
        try dbQueue.read { db in
            try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM local_events") ?? 0
        }
    }

    /// Hard-delete a single event row. The dashboard only exposes this for
    /// `pending` rows so we never destroy something the server already has.
    /// Refuses to delete uploaded rows even if called by mistake.
    @discardableResult
    func deletePendingEvent(localUUID: String) throws -> Bool {
        try dbQueue.write { db in
            try db.execute(sql: """
                DELETE FROM local_events
                WHERE local_uuid = ? AND status = 'pending'
                """, arguments: [localUUID])
            return db.changesCount > 0
        }
    }

    /// Hard-delete a local audio row. The dashboard only exposes this for
    /// rows the server hasn't accepted yet (`pending_upload` or `failed`).
    /// Caller is responsible for removing the m4a on disk.
    @discardableResult
    func deleteLocalAudio(localUUID: String) throws -> Bool {
        try dbQueue.write { db in
            try db.execute(sql: """
                DELETE FROM local_audio
                WHERE local_uuid = ? AND status IN ('pending_upload', 'failed')
                """, arguments: [localUUID])
            return db.changesCount > 0
        }
    }

    /// Look up a single audio row — used by the dashboard so the delete
    /// path can read `file_path` without holding stale view state.
    func fetchAudio(localUUID: String) throws -> LocalAudio? {
        try dbQueue.read { db in
            try LocalAudio.fetchOne(
                db,
                sql: "SELECT * FROM local_audio WHERE local_uuid = ?",
                arguments: [localUUID]
            )
        }
    }
}
