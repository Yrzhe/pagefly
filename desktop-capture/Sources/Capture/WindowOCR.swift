import AppKit
import CoreGraphics
// @preconcurrency — VNImageRequestHandler / VNRecognizeTextRequest aren't
// yet marked Sendable by Apple (rdar://), which trips Swift 6 concurrency
// warnings when we dispatch the `.perform([request])` call onto a
// background queue inside `withCheckedThrowingContinuation`. The call is
// safe in practice — the handler is only used inside that queue.
@preconcurrency import Vision

/// Manually-triggered OCR rescue for AX-blind apps.
///
/// Some macOS apps expose nothing useful via the Accessibility API —
/// WeChat 4.x (Skia-rendered chat bubbles), Feishu, DingTalk, QQ, Figma
/// desktop, most games. For these the user can explicitly hit "OCR this
/// window" from the menu bar; we grab a single screenshot of the focused
/// window and run Apple Vision's on-device text recognizer.
///
/// Important tradeoffs vs. continuous OCR (rem/screenpipe style):
///   - CPU cost is paid *only* on manual click, not every 2s.
///   - Requires Screen Recording TCC permission (one prompt on first use).
///   - Won't capture the popover itself — caller must close it before
///     triggering so the screenshot reflects the app beneath.
enum WindowOCR {
    enum OCRError: Error, LocalizedError {
        case noFrontmostApp
        case noFocusedWindow
        case captureFailed(String)
        case recognitionFailed(String)

        var errorDescription: String? {
            switch self {
            case .noFrontmostApp:
                return "No frontmost application — click into the window you want to OCR first."
            case .noFocusedWindow:
                return "Couldn't find a normal window for the focused app."
            case .captureFailed(let why):
                return "Screenshot failed: \(why). Check Screen Recording permission in System Settings."
            case .recognitionFailed(let why):
                return "Text recognition failed: \(why)."
            }
        }
    }

    struct Result {
        let app: String
        let bundleID: String
        let windowTitle: String
        let text: String          // recognized text, one line per Vision observation
        let lineCount: Int
        let capturedAt: Date
    }

    /// Capture the focused window and return recognized text. Run on a
    /// background queue — Vision's text recognizer is CPU-heavy (~200ms on
    /// Apple Silicon for a typical window).
    static func captureAndRecognize() async throws -> Result {
        guard let app = NSWorkspace.shared.frontmostApplication else {
            throw OCRError.noFrontmostApp
        }
        // NSStatusItem popovers with .transient shouldn't put us in
        // frontmost, but if somehow they did, OCR-ing our own popover
        // would just return the word "Preferences" forever. Better to
        // fail loudly than silently.
        let selfID = Bundle.main.bundleIdentifier?.lowercased() ?? ""
        let targetID = (app.bundleIdentifier ?? "").lowercased()
        if !selfID.isEmpty, targetID == selfID {
            throw OCRError.captureFailed("Target was PageFly itself — click into the window you want to OCR first")
        }
        let pid = app.processIdentifier
        let appName = app.localizedName ?? "Unknown"
        let bundleID = app.bundleIdentifier ?? ""

        guard let (windowID, title) = focusedWindowInfo(pid: pid) else {
            throw OCRError.noFocusedWindow
        }

        guard let cgImage = captureWindow(windowID: windowID) else {
            throw OCRError.captureFailed("CGWindowListCreateImage returned nil")
        }

        let (text, count) = try await recognizeText(in: cgImage)

        return Result(
            app: appName,
            bundleID: bundleID,
            windowTitle: title,
            text: text,
            lineCount: count,
            capturedAt: Date()
        )
    }

    // MARK: - Window resolution

    /// Pick a normal (layer 0, on-screen) window for the given pid. When an
    /// app has multiple windows we take the first one returned by
    /// CGWindowListCopyWindowInfo, which is macOS's front-to-back z-order
    /// and therefore the same one the user is looking at.
    private static func focusedWindowInfo(pid: pid_t) -> (CGWindowID, String)? {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let list = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return nil
        }
        for w in list {
            guard let owner = w[kCGWindowOwnerPID as String] as? pid_t, owner == pid else { continue }
            guard let layer = w[kCGWindowLayer as String] as? Int, layer == 0 else { continue }
            guard let id = w[kCGWindowNumber as String] as? CGWindowID, id > 0 else { continue }
            let title = w[kCGWindowName as String] as? String ?? ""
            return (id, title)
        }
        return nil
    }

    // MARK: - Screenshot

    /// Apple deprecated `CGWindowListCreateImage` in Sonoma in favor of
    /// ScreenCaptureKit's `SCScreenshotManager`, but the new API is macOS
    /// 14+ only and our deployment target is 13. Keep the deprecated call
    /// for now — it still works in macOS 15 and the permission gate is the
    /// same Screen Recording TCC entry.
    @available(macOS, deprecated: 14.0)
    private static func captureWindow(windowID: CGWindowID) -> CGImage? {
        let options: CGWindowImageOption = [.boundsIgnoreFraming, .bestResolution]
        return CGWindowListCreateImage(.null, .optionIncludingWindow, windowID, options)
    }

    // MARK: - Vision

    /// Apple Vision on-device recognizer. `.accurate` is slower but handles
    /// mixed Chinese + English cleanly, which is the WeChat use case we
    /// actually care about. Returns (text, observation count). Runs the
    /// Vision work on a background QoS queue so the main thread isn't
    /// stalled by a ~200ms recognizer pass.
    private static func recognizeText(in image: CGImage) async throws -> (String, Int) {
        try await withCheckedThrowingContinuation { continuation in
            let request = VNRecognizeTextRequest { req, err in
                if let err {
                    continuation.resume(throwing: OCRError.recognitionFailed(err.localizedDescription))
                    return
                }
                let results = req.results as? [VNRecognizedTextObservation] ?? []
                let lines = results.compactMap { $0.topCandidates(1).first?.string }
                continuation.resume(returning: (lines.joined(separator: "\n"), lines.count))
            }
            request.recognitionLevel = .accurate
            // Chinese-first; Vision returns one or the other per region, so
            // listing both lets mixed-language WeChat chats OCR correctly.
            request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
            request.usesLanguageCorrection = true

            let handler = VNImageRequestHandler(cgImage: image, options: [:])
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    try handler.perform([request])
                } catch {
                    continuation.resume(throwing: OCRError.recognitionFailed(error.localizedDescription))
                }
            }
        }
    }
}
