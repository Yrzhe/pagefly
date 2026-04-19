import Combine
import Foundation

/// Shared source of truth for "is the user currently granting us
/// Accessibility access?". AXIsProcessTrusted has no notification API, so
/// we poll at a coarse cadence and publish via Combine. Both the menu bar
/// icon and the popover panel subscribe, so they never disagree about the
/// state.
@MainActor
final class AXTrustMonitor: ObservableObject {
    static let shared = AXTrustMonitor()

    @Published private(set) var isTrusted: Bool

    private var timer: Timer?

    private init() {
        self.isTrusted = AXReader.isAccessibilityTrusted(prompt: false)
    }

    /// Begin polling. Safe to call multiple times — each call resets the
    /// timer so a spurious second start doesn't stack handlers.
    func start(pollInterval: TimeInterval = 5) {
        timer?.invalidate()
        let t = Timer(timeInterval: pollInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    /// Force an immediate read, e.g. right after asking the user to grant
    /// permission so the UI flips as soon as they accept the prompt.
    func refresh() {
        let trusted = AXReader.isAccessibilityTrusted(prompt: false)
        if trusted != isTrusted {
            isTrusted = trusted
        }
    }
}
