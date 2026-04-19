import AppKit
import Foundation

/// Drains recorded audio to the PageFly server and polls for transcription.
/// Paired with Uploader (events): server design calls for audio-first so any
/// event referencing an audio_uuid resolves to a real remote id. M6 doesn't
/// auto-link events to audio yet, so the uploaders run independently.
///
/// Each flush does three things, in order:
///   1. Upload pending recordings FIFO (one at a time; m4a files are big).
///   2. Poll awaiting-transcription rows for STT completion.
///   3. Vacuum m4a files on disk whose transcript is > 7 days old.
@MainActor
final class AudioUploader {
    static let shared = AudioUploader()

    // MARK: Config

    static let baseInterval: TimeInterval = 5 * 60
    static let backoffLadder: [TimeInterval] = [30, 60, 120, 300]
    /// Give up on transcription if it hasn't finished in this long — covers
    /// server crashes or Whisper outages so single rows never re-poll forever.
    static let transcriptionTimeoutSeconds: TimeInterval = 24 * 3600
    /// Delete m4a after this long since the transcript arrived. Transcript
    /// itself stays in the DB row forever.
    static let fileRetentionDays: Int = 7

    // MARK: State

    private var timer: Timer?
    private var wakeObserver: NSObjectProtocol?
    private var isUploading = false
    private var backoffIndex = 0
    private var nextAttemptAt: Date?
    private var isStopped = true

    private init() {}

    // MARK: Lifecycle

    func start() {
        guard timer == nil else { return }
        isStopped = false
        scheduleTimer(after: 20) // settle after launch before first attempt
        installWakeObserver()
        logCapture(.info, "AudioUploader started")
    }

    func stop(reason: String = "stop") {
        isStopped = true
        timer?.invalidate()
        timer = nil
        if let o = wakeObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(o)
            wakeObserver = nil
        }
        logCapture(.info, "AudioUploader stopped (\(reason))")
    }

    private func installWakeObserver() {
        let ws = NSWorkspace.shared.notificationCenter
        wakeObserver = ws.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                logCapture(.info, "Wake — flushing AudioUploader")
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
            base = AudioUploader.baseInterval
        }
        scheduleTimer(after: max(1, base))
    }

    // MARK: Flush

    /// One upload + poll + vacuum pass. Coalesces overlapping calls.
    func flush() async {
        if isStopped { return }
        guard !isUploading else { return }
        isUploading = true
        defer { isUploading = false }

        // Vacuum runs even when offline — pure local bookkeeping.
        vacuumExpiredFiles()

        // Respect active backoff.
        if let next = nextAttemptAt, next > Date() { return }

        guard let client = APIClient.from(SettingsStore.shared) else { return }

        await drainPending(client: client)
        await pollAwaitingTranscription(client: client)
    }

    // MARK: Upload pending

    private func drainPending(client: APIClient) async {
        let pending: [LocalAudio]
        do {
            pending = try LocalDB.shared.fetchPendingAudioUpload(limit: 16)
        } catch {
            logCapture(.error, "fetchPendingAudioUpload failed: \(error)")
            return
        }
        guard !pending.isEmpty else { return }

        for audio in pending {
            if isStopped { return }
            // Mark in flight so a parallel flush (shouldn't happen but belt &
            // suspenders) doesn't pick this up again.
            try? LocalDB.shared.markAudioUploading(uuid: audio.local_uuid)
            do {
                let result = try await client.uploadAudio(audio)
                try LocalDB.shared.markAudioUploaded(
                    uuid: audio.local_uuid,
                    remoteID: result.remoteID,
                    uploadedAtISO: AudioUploader.iso.string(from: Date())
                )
                backoffIndex = 0
                nextAttemptAt = nil
                SettingsStore.shared.lastSyncedAt = Date()
                logCapture(.info, "Uploaded audio uuid=\(audio.local_uuid) remote=\(result.remoteID) dup=\(result.duplicate)")
            } catch APIClient.AudioUploadError.fileMissing(let what) {
                logCapture(.warn, "Audio file missing (\(what)) — marking failed")
                try? LocalDB.shared.markAudioFailed(uuid: audio.local_uuid)
            } catch APIClient.AudioUploadError.unauthorized {
                logCapture(.warn, "AudioUploader: token rejected — pausing")
                SettingsStore.shared.connectionState = .unauthorized
                nextAttemptAt = Date().addingTimeInterval(AudioUploader.backoffLadder.last ?? 300)
                // Revert so the next flush (post new token) picks it up again.
                try? LocalDB.shared.revertAudioToPending(uuid: audio.local_uuid)
                return
            } catch APIClient.AudioUploadError.server(let code, let body) {
                logCapture(.warn, "AudioUploader: server \(code) — backoff (body head: \(body))")
                try? LocalDB.shared.revertAudioToPending(uuid: audio.local_uuid)
                applyBackoff()
                return
            } catch APIClient.AudioUploadError.transport(let why) {
                logCapture(.warn, "AudioUploader: transport fail (\(why)) — backoff")
                try? LocalDB.shared.revertAudioToPending(uuid: audio.local_uuid)
                applyBackoff()
                return
            } catch APIClient.AudioUploadError.decode(let why) {
                logCapture(.error, "AudioUploader: decode fail (\(why)) — marking failed")
                try? LocalDB.shared.markAudioFailed(uuid: audio.local_uuid)
            } catch {
                logCapture(.error, "AudioUploader: unknown error: \(error)")
                try? LocalDB.shared.revertAudioToPending(uuid: audio.local_uuid)
                applyBackoff()
                return
            }
        }
    }

    // MARK: Poll transcription

    private func pollAwaitingTranscription(client: APIClient) async {
        let rows: [LocalAudio]
        do {
            rows = try LocalDB.shared.fetchAwaitingTranscription()
        } catch {
            logCapture(.error, "fetchAwaitingTranscription failed: \(error)")
            return
        }
        guard !rows.isEmpty else { return }

        let iso = AudioUploader.iso
        let now = Date()
        let timeoutCutoff = now.addingTimeInterval(-AudioUploader.transcriptionTimeoutSeconds)

        for audio in rows {
            if isStopped { return }
            guard let remoteID = audio.remote_id else { continue }

            // Abandon rows that have been awaiting transcription too long.
            // Anchor on uploaded_at (when the server first saw the file) so
            // long offline spells before upload don't incorrectly age rows out.
            // Fall back to created_at for any legacy rows without uploaded_at.
            let anchorISO = audio.uploaded_at ?? audio.created_at
            let anchorDate = iso.date(from: anchorISO) ?? now
            if anchorDate < timeoutCutoff {
                logCapture(.warn, "Audio uuid=\(audio.local_uuid) transcription timeout (24h since upload) — marking failed")
                try? LocalDB.shared.markAudioFailed(uuid: audio.local_uuid)
                continue
            }

            do {
                let status = try await client.getAudioStatus(remoteID: remoteID)
                switch status.status {
                case "transcribed":
                    let transcribedAt = status.transcribed_at.isEmpty
                        ? iso.string(from: now)
                        : status.transcribed_at
                    try LocalDB.shared.markAudioTranscribed(
                        remoteID: remoteID,
                        transcript: status.transcript,
                        transcribedAtISO: transcribedAt
                    )
                    logCapture(.info, "Transcribed audio remote=\(remoteID) (\(status.transcript.count) chars)")
                case "failed":
                    logCapture(.warn, "Server marked audio remote=\(remoteID) failed: \(status.error)")
                    try LocalDB.shared.markAudioFailed(uuid: audio.local_uuid)
                default:
                    // Still transcribing; leave the row alone and try next cycle.
                    break
                }
            } catch APIClient.AudioUploadError.unauthorized {
                SettingsStore.shared.connectionState = .unauthorized
                return
            } catch {
                // Transport / decode issues don't warrant marking the row
                // failed — server may just be down. Log + continue.
                logCapture(.warn, "getAudioStatus(\(remoteID)) failed: \(error)")
            }
        }
    }

    // MARK: Vacuum

    /// Two-pass vacuum:
    ///   (1) Time-based: delete .m4a for transcripts older than `fileRetentionDays`.
    ///   (2) Count-based: enforce the user's `audioRetentionCount` cap so the
    ///       N most-recent uploaded/transcribed files stay and everything
    ///       older gets removed even if it's still inside the time window
    ///       (e.g. user set "keep 0" → delete on upload).
    /// Transcripts (stored in the DB row) stay forever; only the raw m4a
    /// bytes are touched.
    private func vacuumExpiredFiles() {
        let cutoff = Date().addingTimeInterval(-Double(AudioUploader.fileRetentionDays) * 86400)
        let cutoffISO = AudioUploader.iso.string(from: cutoff)
        do {
            let rows = try LocalDB.shared.fetchTranscribedForFileCleanup(olderThan: cutoffISO)
            var removed = 0
            for row in rows {
                if removeAudioFile(at: row.file_path) { removed += 1 }
                try? LocalDB.shared.clearAudioFilePath(uuid: row.local_uuid)
            }
            if removed > 0 {
                logCapture(.info, "Vacuumed \(removed) m4a files older than \(AudioUploader.fileRetentionDays)d")
            }
        } catch {
            logCapture(.warn, "Audio time-vacuum failed: \(error)")
        }

        let keep = max(0, SettingsStore.shared.audioRetentionCount)
        do {
            let retained = try LocalDB.shared.fetchRetainedAudioFiles()
            // First `keep` are the most recent — protect them; drop the rest.
            let drop = retained.count > keep ? Array(retained.dropFirst(keep)) : []
            var removed = 0
            for row in drop {
                if removeAudioFile(at: row.file_path) { removed += 1 }
                try? LocalDB.shared.clearAudioFilePath(uuid: row.local_uuid)
            }
            if removed > 0 {
                logCapture(.info, "Pruned \(removed) m4a files beyond keep-N=\(keep)")
            }
        } catch {
            logCapture(.warn, "Audio keep-N vacuum failed: \(error)")
        }
    }

    /// Returns true iff a file existed at the path and was successfully
    /// removed. Missing files are silent (vacuum may run twice).
    private func removeAudioFile(at path: String) -> Bool {
        guard !path.isEmpty, FileManager.default.fileExists(atPath: path) else { return false }
        do {
            try FileManager.default.removeItem(atPath: path)
            return true
        } catch {
            logCapture(.warn, "Failed to remove \(path): \(error)")
            return false
        }
    }

    // MARK: Helpers

    private func applyBackoff() {
        let delay = AudioUploader.backoffLadder[min(backoffIndex, AudioUploader.backoffLadder.count - 1)]
        nextAttemptAt = Date().addingTimeInterval(delay)
        backoffIndex = min(backoffIndex + 1, AudioUploader.backoffLadder.count - 1)
    }

    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}
