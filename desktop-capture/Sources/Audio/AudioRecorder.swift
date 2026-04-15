import Foundation
import AVFoundation
import AppKit

/// Manual audio recorder for the menu bar app. M5 captures the user's
/// microphone only — AAC m4a at 16 kHz mono, 64 kbps. System audio via
/// ScreenCaptureKit is a planned follow-up; the file layout and
/// LocalAudio.source field are ready for a "mixed" value when that lands.
///
/// Important: AVAudioRecorder.stop() returns immediately but finalizes the
/// m4a container asynchronously. We wait for
/// `audioRecorderDidFinishRecording(_:successfully:)` before reading size and
/// inserting the LocalAudio row so the uploader never sees a truncated file.
/// If the process dies mid-finalization, `reconcileOrphans()` (called from
/// AppDelegate on launch) picks up any `.m4a` with no matching DB row.
@MainActor
final class AudioRecorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    static let shared = AudioRecorder()

    // MARK: Published state

    @Published private(set) var isRecording: Bool = false
    @Published private(set) var startedAt: Date?
    @Published private(set) var currentUUID: String?
    /// Rolling window of 6 normalized (0…1) power levels for the HUD waveform.
    @Published private(set) var levels: [Float] = Array(repeating: 0.05, count: 6)
    @Published private(set) var lastError: String?

    // MARK: Private

    private var recorder: AVAudioRecorder?
    private var meterTimer: Timer?
    private var triggerApp: String = ""
    /// Waiters that want to block (e.g. app termination) until the delegate
    /// confirms the file is finalized.
    private var finalizationWaiters: [CheckedContinuation<Void, Never>] = []

    private override init() { super.init() }

    // MARK: - Lifecycle

    /// Begin recording. Prompts for microphone access on first run.
    /// Returns true if the recorder started; false otherwise (lastError set).
    @discardableResult
    func start() -> Bool {
        guard !isRecording else { return true }
        let uuid = ContextDedup.makeLocalUUID()
        let dir = AudioRecorder.recordingsDirectory
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        } catch {
            lastError = "Can't create recordings folder: \(error.localizedDescription)"
            logCapture(.error, "Recording dir create failed: \(error)")
            return false
        }
        let url = dir.appendingPathComponent("\(uuid).m4a")

        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1,
            AVEncoderBitRateKey: 64_000,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
        ]

        do {
            let rec = try AVAudioRecorder(url: url, settings: settings)
            rec.delegate = self
            rec.isMeteringEnabled = true
            guard rec.prepareToRecord() else {
                lastError = "prepareToRecord returned false"
                logCapture(.error, "AVAudioRecorder prepareToRecord failed")
                return false
            }
            guard rec.record() else {
                lastError = "record() returned false — check microphone permission"
                logCapture(.error, "AVAudioRecorder record() failed")
                return false
            }
            self.recorder = rec
            self.startedAt = Date()
            self.currentUUID = uuid
            self.triggerApp = NSWorkspace.shared.frontmostApplication?.localizedName ?? ""
            self.isRecording = true
            self.lastError = nil
            self.levels = Array(repeating: 0.05, count: 6)
            startMetering()
            logCapture(.info, "Recording started uuid=\(uuid)")
            return true
        } catch {
            lastError = "AVAudioRecorder init: \(error.localizedDescription)"
            logCapture(.error, "AVAudioRecorder init failed: \(error)")
            return false
        }
    }

    /// Stop recording. Non-blocking — finalization + DB insert happen in the
    /// delegate callback. Use `stopAndWait()` when you need the file to be
    /// ready on return (e.g. during app termination).
    func stop() {
        guard isRecording, let rec = recorder else { return }
        isRecording = false
        stopMetering()
        rec.stop() // triggers audioRecorderDidFinishRecording on main
    }

    /// Blocking variant for `applicationWillTerminate`. Resumes once the
    /// delegate callback has inserted the DB row, or after a 3s safety
    /// timeout. On timeout the orphan file will be reconciled next launch.
    func stopAndWait() async {
        guard isRecording, let rec = recorder else { return }
        isRecording = false
        stopMetering()
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            finalizationWaiters.append(cont)
            rec.stop()
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                Task { @MainActor in
                    self?.resumeFinalizationWaiters(source: "timeout")
                }
            }
        }
    }

    /// Current elapsed seconds since the recording started; 0 if idle.
    var elapsedSeconds: Int {
        guard let started = startedAt else { return 0 }
        return max(0, Int(Date().timeIntervalSince(started).rounded()))
    }

    // MARK: - AVAudioRecorderDelegate

    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        // Delegate is called on the main queue per AVFoundation docs.
        Task { @MainActor in self.finalize(successfully: flag) }
    }

    nonisolated func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        Task { @MainActor in
            self.lastError = "Audio encode error: \(error?.localizedDescription ?? "unknown")"
            logCapture(.error, "AVAudioRecorder encode error: \(String(describing: error))")
        }
    }

    // MARK: - Finalize

    private func finalize(successfully flag: Bool) {
        guard let rec = recorder, let uuid = currentUUID, let start = startedAt else {
            resumeFinalizationWaiters(source: "no-recorder")
            return
        }
        let url = rec.url
        let endedAt = Date()
        let duration = max(0, Int(endedAt.timeIntervalSince(start).rounded()))
        let size = (try? FileManager.default
            .attributesOfItem(atPath: url.path)[.size] as? Int64) ?? 0

        if flag, size > 0 {
            insertLocalAudio(
                uuid: uuid,
                startedAt: start,
                endedAt: endedAt,
                duration: duration,
                path: url.path,
                size: size,
                triggerApp: triggerApp
            )
        } else {
            lastError = "Recording ended unsuccessfully (size=\(size)B)"
            logCapture(.warn, "Finalize: unsuccessful uuid=\(uuid) size=\(size)")
        }

        // Reset state
        self.recorder = nil
        self.currentUUID = nil
        self.startedAt = nil
        self.triggerApp = ""
        resumeFinalizationWaiters(source: "delegate")
    }

    /// Insert the LocalAudio row. On failure (disk full, locked db), we keep
    /// the file on disk — `reconcileOrphans()` on next launch will pick it up.
    private func insertLocalAudio(
        uuid: String,
        startedAt: Date,
        endedAt: Date,
        duration: Int,
        path: String,
        size: Int64,
        triggerApp: String
    ) {
        let iso = AudioRecorder.iso
        let audio = LocalAudio(
            local_uuid: uuid,
            started_at: iso.string(from: startedAt),
            ended_at: iso.string(from: endedAt),
            duration_s: duration,
            file_path: path,
            file_size_bytes: size,
            format: "m4a",
            source: "mic",
            trigger_app: triggerApp,
            status: LocalAudioStatus.pending_upload.rawValue,
            remote_id: nil,
            transcript: nil,
            created_at: iso.string(from: Date())
        )
        do {
            try LocalDB.shared.insertAudio(audio)
            logCapture(.info, "Recording finalized uuid=\(uuid) duration=\(duration)s size=\(size)B")
        } catch {
            lastError = "Couldn't save recording metadata (\(error.localizedDescription)) — will reconcile on next launch"
            logCapture(.error, "LocalAudio insert failed for \(uuid): \(error)")
        }
    }

    private func resumeFinalizationWaiters(source: String) {
        guard !finalizationWaiters.isEmpty else { return }
        let waiters = finalizationWaiters
        finalizationWaiters.removeAll()
        for w in waiters { w.resume() }
        if source == "timeout" {
            logCapture(.warn, "stopAndWait timed out waiting for finalize delegate")
        }
    }

    // MARK: - Metering

    private func startMetering() {
        meterTimer?.invalidate()
        let t = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        t.tolerance = 0.05
        meterTimer = t
    }

    private func stopMetering() {
        meterTimer?.invalidate()
        meterTimer = nil
    }

    private func tick() {
        guard let rec = recorder else { return }
        rec.updateMeters()
        let dB = rec.averagePower(forChannel: 0)
        let normalized: Float = max(0.05, min(1.0, (dB + 50) / 50))
        levels.removeFirst()
        levels.append(normalized)
    }

    // MARK: - Orphan reconciliation

    /// Scan the recordings folder and insert a LocalAudio row for any `.m4a`
    /// file that has no matching DB entry. Runs on launch as a safety net
    /// against: app killed mid-recording, DB write failure, or any future
    /// bug that drops files without metadata.
    static func reconcileOrphans() {
        let dir = recordingsDirectory
        guard let entries = try? FileManager.default.contentsOfDirectory(
            at: dir, includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey]
        ) else { return }

        let iso = AudioRecorder.iso
        var recovered = 0
        for url in entries where url.pathExtension.lowercased() == "m4a" {
            let uuid = url.deletingPathExtension().lastPathComponent
            // Skip if we already have a row.
            if (try? LocalDB.shared.audioExists(uuid: uuid)) == true { continue }

            let size = (try? FileManager.default
                .attributesOfItem(atPath: url.path)[.size] as? Int64) ?? 0
            guard size > 0 else { continue } // empty file — ignore

            let mtime = (try? url.resourceValues(forKeys: [.contentModificationDateKey])
                .contentModificationDate) ?? Date()

            let audio = LocalAudio(
                local_uuid: uuid,
                started_at: iso.string(from: mtime),
                ended_at: iso.string(from: mtime),
                duration_s: 0, // unknown; server can recompute if needed
                file_path: url.path,
                file_size_bytes: size,
                format: "m4a",
                source: "mic",
                trigger_app: "",
                status: LocalAudioStatus.pending_upload.rawValue,
                remote_id: nil,
                transcript: nil,
                created_at: iso.string(from: Date())
            )
            do {
                try LocalDB.shared.insertAudio(audio)
                recovered += 1
            } catch {
                logCapture(.warn, "reconcileOrphans: insert failed for \(uuid): \(error)")
            }
        }
        if recovered > 0 {
            logCapture(.info, "reconcileOrphans: recovered \(recovered) orphan recordings")
        }
    }

    // MARK: - Paths / formatters

    static var recordingsDirectory: URL {
        let support = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return support.appendingPathComponent("PageFly/recordings", isDirectory: true)
    }

    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}
