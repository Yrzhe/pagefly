import Foundation
import GRDB

/// One row in `local_audio`. Lifecycle:
///   recording → pending_upload → uploading → uploaded → transcribed
/// (or → failed at any stage). Mirrors the server's `audio_recordings`
/// shape so the uploader in M6 is a thin transform.
struct LocalAudio: Codable, FetchableRecord, MutablePersistableRecord {
    var local_uuid: String
    var started_at: String          // ISO8601 UTC
    var ended_at: String?
    var duration_s: Int
    var file_path: String           // absolute path under ~/Library/Application Support/PageFly/recordings
    var file_size_bytes: Int64
    var format: String              // "m4a"
    var source: String              // "mic" | "system" | "mixed" — M5 ships "mic"
    var trigger_app: String         // host app name if user was in a meeting; "" otherwise
    var status: String              // see LocalAudioStatus
    var remote_id: Int64?           // assigned by server on upload (M6)
    var transcript: String?         // filled in M6 once STT finishes
    var created_at: String

    static let databaseTableName = "local_audio"
}

enum LocalAudioStatus: String {
    case recording          // actively being written to disk
    case pending_upload     // finished; waiting for the uploader
    case uploading          // upload in flight
    case uploaded           // server accepted; transcription may still be pending
    case transcribed        // server STT done; transcript field populated
    case failed             // permanent failure — stops retrying
}
