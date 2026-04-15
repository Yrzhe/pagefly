import Foundation
import GRDB

/// One row in `local_events`. Mirrors the server-side activity_events shape so
/// uploading is a thin transformation. `local_uuid` is the idempotency key the
/// server uses on POST /api/activity/events/batch.
struct LocalEvent: Codable, FetchableRecord, MutablePersistableRecord {
    var local_uuid: String
    var started_at: String          // ISO8601 UTC
    var ended_at: String?
    var duration_s: Int
    var app: String                 // human-readable app name (e.g. "Visual Studio Code")
    var bundle_id: String           // CFBundleIdentifier (e.g. "com.microsoft.VSCode")
    var window_title: String
    var url: String
    var text_excerpt: String
    var ax_role: String
    var context_hash: String        // sha1(app|bundle|title|url|text[:500]) for dedup
    var audio_uuid: String?         // optional link to local_audio (M5)
    var status: String              // "pending" | "uploaded"
    var remote_id: Int64?           // assigned by server on upload (M4)
    var created_at: String          // when the row was first inserted

    static let databaseTableName = "local_events"
}

/// Lifecycle states, kept as raw strings in the DB to avoid schema migrations
/// every time we add one.
enum LocalEventStatus: String {
    case pending
    case uploaded
}
