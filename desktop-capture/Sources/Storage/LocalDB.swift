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
}
