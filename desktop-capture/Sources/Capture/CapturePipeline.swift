import AppKit
import Combine

/// Top-level orchestrator for screen-context capture. Wires together:
///   - NSWorkspace app-activation notifications (event-driven sampling)
///   - A 30s timer (catch long dwell on the same window)
///   - IdleMonitor (suppress when user is afk > 60s)
///   - PrivacyFilter → ContextDedup → LocalDB
///
/// Started/stopped externally via `start()` / `stop()`. AppDelegate boots it
/// when SettingsStore has a token.
@MainActor
final class CapturePipeline: ObservableObject {
    static let shared = CapturePipeline()

    private(set) var isRunning = false

    /// User-initiated pause. Distinct from `pausedForIdle` (which comes
    /// from the idle monitor and auto-resumes on any input). This one
    /// only flips via explicit menu action and is intentionally
    /// non-persistent across relaunches so a user can't accidentally
    /// leave captures off for days.
    @Published private(set) var isPausedByUser: Bool = false

    private let dedup: ContextDedup
    private let privacy: PrivacyFilter
    private var idle: IdleMonitor

    private var sampleTimer: Timer?
    private var workspaceObserver: NSObjectProtocol?
    private var sleepObserver: NSObjectProtocol?
    private var wakeObserver: NSObjectProtocol?

    private var pausedForIdle = false

    private init() {
        // Defaults built inline so the @MainActor isolation of ContextDedup
        // is honored without needing default-argument evaluation in the
        // caller's context.
        self.dedup = ContextDedup()
        self.privacy = PrivacyFilter()
        self.idle = IdleMonitor()
    }

    // MARK: - Lifecycle

    func start() {
        guard !isRunning else { return }
        guard AXReader.isAccessibilityTrusted(prompt: false) else {
            logCapture(.warn, "AX permission not granted; pipeline parked until user grants it.")
            return
        }
        isRunning = true
        installObservers()
        scheduleSampler()
        sampleNow(reason: "start")
        logCapture(.info, "Capture pipeline started.")
    }

    func stop(reason: String = "stop") {
        guard isRunning else { return }
        isRunning = false
        sampleTimer?.invalidate()
        sampleTimer = nil
        removeObservers()
        dedup.flush(at: Date())
        logCapture(.info, "Capture pipeline stopped (\(reason)).")
    }

    /// User-invoked pause/resume from the menu. The pipeline itself stays
    /// "running" so we keep workspace observers registered and the timer
    /// scheduled — sampleNow just short-circuits while paused. This keeps
    /// resume instant (no observer re-install) and means we still close
    /// the open row cleanly on pause.
    func setPausedByUser(_ paused: Bool) {
        guard paused != isPausedByUser else { return }
        isPausedByUser = paused
        if paused {
            dedup.flush(at: Date())
            logCapture(.info, "Capture paused by user.")
        } else {
            logCapture(.info, "Capture resumed by user.")
            sampleNow(reason: "resume")
        }
    }

    // MARK: - Observers

    private func installObservers() {
        let ws = NSWorkspace.shared.notificationCenter
        workspaceObserver = ws.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.sampleNow(reason: "app-activate") }
        }
        sleepObserver = ws.addObserver(
            forName: NSWorkspace.willSleepNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.flushOnSleep() }
        }
        wakeObserver = ws.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.sampleNow(reason: "wake") }
        }
    }

    private func removeObservers() {
        let ws = NSWorkspace.shared.notificationCenter
        if let o = workspaceObserver { ws.removeObserver(o) }
        if let o = sleepObserver { ws.removeObserver(o) }
        if let o = wakeObserver { ws.removeObserver(o) }
        workspaceObserver = nil
        sleepObserver = nil
        wakeObserver = nil
    }

    // MARK: - Sampling

    private func scheduleSampler() {
        sampleTimer?.invalidate()
        let timer = Timer.scheduledTimer(withTimeInterval: TimeInterval(ContextDedup.bumpInterval), repeats: true) { [weak self] _ in
            Task { @MainActor in self?.sampleNow(reason: "tick") }
        }
        timer.tolerance = 5
        sampleTimer = timer
    }

    private func sampleNow(reason: String) {
        guard isRunning else { return }
        if isPausedByUser { return }

        if idle.isIdle {
            if !pausedForIdle {
                pausedForIdle = true
                dedup.flush(at: Date())
                logCapture(.info, "Idle > \(Int(idle.threshold))s — pausing capture.")
            }
            return
        }
        if pausedForIdle {
            pausedForIdle = false
            logCapture(.info, "User active again — resuming capture.")
        }

        guard let raw = AXReader.currentSnapshot() else {
            logCapture(.debug, "No snapshot available (\(reason)).")
            return
        }
        guard let clean = privacy.sanitize(raw) else {
            logCapture(.debug, "Filtered \(raw.bundleID) (\(reason)).")
            return
        }
        dedup.ingest(clean)

        // Auto-OCR rescue — fires when AX yielded essentially nothing
        // actionable, covering two distinct failure modes:
        //
        //   1. AX-blind apps (Skia / custom renderers): empty text + empty
        //      URL. WeChat 4.x, Feishu desktop client, DingTalk, Figma
        //      desktop, most games.
        //   2. Canvas-rendered web pages: we have a URL (the browser
        //      exposed one) but the page body is drawn on a <canvas> so
        //      AX text is < ~40 chars of sidebar chrome. Feishu docs,
        //      Google Docs' "canvas rendering" beta, Figma web, Linear's
        //      editor. For these the URL alone is a poor work-log entry.
        //
        // OCRRescue.autoRescueIfEligible is a no-op if the per-bundle TTL
        // (5min) hasn't elapsed, so the cost in the common case is one
        // dictionary lookup.
        let textIsThin = clean.textExcerpt.count < 40
        let axBlind = textIsThin && clean.url.isEmpty
        let canvasLikelyWeb = textIsThin && !clean.url.isEmpty
        if (axBlind || canvasLikelyWeb) && !clean.bundleID.isEmpty {
            OCRRescue.shared.autoRescueIfEligible(bundleID: clean.bundleID, url: clean.url)
        }
    }

    private func flushOnSleep() {
        dedup.flush(at: Date())
        logCapture(.info, "System sleeping — flushed open row.")
    }
}
