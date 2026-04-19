import AVFoundation
import Combine
import Foundation

/// Plays back a single audio recording at a time so the dashboard can wire
/// a play/stop button to each row. Holding a strong AVAudioPlayer is required
/// — letting it dealloc while playing cuts the sound off immediately.
@MainActor
final class AudioPreview: NSObject, ObservableObject, AVAudioPlayerDelegate {
    static let shared = AudioPreview()

    /// `local_uuid` of the row currently sounding, or nil when idle. The
    /// dashboard reads this to swap the play icon for stop on one row only.
    @Published private(set) var playingUUID: String?

    private var player: AVAudioPlayer?

    private override init() { super.init() }

    /// Toggle: if the same row is already playing, stop. Otherwise start
    /// the new file (cancelling any previous playback). Returns `nil` on
    /// success or a short user-facing error message on failure.
    @discardableResult
    func toggle(uuid: String, filePath: String) -> String? {
        if playingUUID == uuid {
            stop()
            return nil
        }
        return start(uuid: uuid, filePath: filePath)
    }

    func stop() {
        player?.stop()
        player = nil
        playingUUID = nil
    }

    private func start(uuid: String, filePath: String) -> String? {
        guard !filePath.isEmpty else { return "File missing on disk" }
        let url = URL(fileURLWithPath: filePath)
        guard FileManager.default.fileExists(atPath: filePath) else {
            return "File missing on disk"
        }
        do {
            let p = try AVAudioPlayer(contentsOf: url)
            p.delegate = self
            guard p.prepareToPlay(), p.play() else {
                return "Couldn't start playback"
            }
            player = p
            playingUUID = uuid
            return nil
        } catch {
            logCapture(.warn, "AudioPreview play failed for \(uuid): \(error)")
            return "Playback failed"
        }
    }

    // MARK: - AVAudioPlayerDelegate

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            // Only clear if the finished player is still the active one;
            // a fast double-tap could have already started a new one.
            if self.player === player {
                self.player = nil
                self.playingUUID = nil
            }
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in
            logCapture(.warn, "AudioPreview decode error: \(String(describing: error))")
            if self.player === player {
                self.player = nil
                self.playingUUID = nil
            }
        }
    }
}
