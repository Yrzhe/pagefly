import AppKit
import ApplicationServices

/// Reads the currently focused app + window + element via the macOS
/// Accessibility API. Returns nil when AX permission is denied or no app is
/// frontmost (rare).
///
/// Text strategy:
///   1. Grab the focused element's `AXValue` / `AXSelectedText` first — that's
///      the highest-signal source (what the user is actively typing/selecting).
///   2. Walk the focused *window* with a bounded budget to harvest visible
///      text + an `AXURL` from any `AXWebArea` descendant. The walk is
///      capped on depth, node count, and per-element messaging timeout so a
///      huge browser DOM never stalls the capture loop on the main thread.
///   3. The persisted `textExcerpt` prefers the focused-element text when
///      present; otherwise it falls back to the harvested window text.
enum AXReader {
    // Walk budgets — tuned for "responsive enough on a Comet/Chrome window
    // with a real page loaded". Bigger DOMs simply truncate.
    private static let maxTextChars = 1500
    private static let maxNodes = 400
    private static let maxDepth = 12
    /// Per-element AX messaging timeout. Default is ~6s, which is way too
    /// long for our 5-10s capture cadence.
    private static let messagingTimeoutSeconds: Float = 0.4

    static func currentSnapshot() -> ContextSnapshot? {
        guard let app = NSWorkspace.shared.frontmostApplication else {
            return nil
        }

        let appName = app.localizedName ?? "Unknown"
        let bundleID = app.bundleIdentifier ?? ""
        let pid = app.processIdentifier
        let axApp = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(axApp, messagingTimeoutSeconds)

        let window = copyElement(axApp, kAXFocusedWindowAttribute)
        let title = window.flatMap { copyString($0, kAXTitleAttribute) } ?? ""

        var role = ""
        var focusedText = ""
        if let focusedElement = copyElement(axApp, kAXFocusedUIElementAttribute) {
            role = copyString(focusedElement, kAXRoleAttribute) ?? ""
            focusedText = extractTextSafely(from: focusedElement, role: role) ?? ""
        }

        // Walk the window for richer context (page text + URL). Even when
        // focusedText is non-empty we still want the URL, so the walk runs
        // in both cases — it short-circuits on its own budget.
        var url = ""
        var harvested = ""
        if let w = window {
            AXUIElementSetMessagingTimeout(w, messagingTimeoutSeconds)
            var collector = TextCollector(limit: maxTextChars, nodeBudget: maxNodes)
            walk(w, depth: 0, collector: &collector, urlOut: &url)
            harvested = collector.text
        }

        // Prefer focused-element text — it's the active typing context — and
        // only fall back to harvested page text when the focus didn't yield
        // anything meaningful.
        let text = focusedText.isEmpty ? harvested : focusedText

        return ContextSnapshot(
            app: appName,
            bundleID: bundleID,
            windowTitle: title,
            url: url,
            textExcerpt: text,
            axRole: role,
            capturedAt: Date()
        )
    }

    /// Returns true if the app has been granted Accessibility access. Pass
    /// `prompt: true` once at startup to nudge the user into System Settings.
    static func isAccessibilityTrusted(prompt: Bool = false) -> Bool {
        let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [key: prompt] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    // MARK: - Tree walk

    /// Bounded text accumulator. Stops once `limit` chars or `nodeBudget`
    /// elements have been consumed so a 50k-node browser DOM can't stall us.
    private struct TextCollector {
        let limit: Int
        var nodeBudget: Int
        private var pieces: [String] = []
        private var charCount = 0

        init(limit: Int, nodeBudget: Int) {
            self.limit = limit
            self.nodeBudget = nodeBudget
        }

        var text: String { pieces.joined(separator: " ") }
        var done: Bool { charCount >= limit || nodeBudget <= 0 }

        mutating func consumeNode() { nodeBudget -= 1 }

        mutating func add(_ s: String?) {
            guard let raw = s else { return }
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            // Skip the noise: single-char labels, glyphs, empty strings.
            guard trimmed.count > 1 else { return }
            let remaining = limit - charCount
            if remaining <= 0 { return }
            let slice = trimmed.count <= remaining ? trimmed : String(trimmed.prefix(remaining))
            pieces.append(slice)
            charCount += slice.count
        }
    }

    private static func walk(
        _ element: AXUIElement,
        depth: Int,
        collector: inout TextCollector,
        urlOut: inout String
    ) {
        if collector.done || depth > maxDepth { return }
        collector.consumeNode()

        let role = copyString(element, kAXRoleAttribute) ?? ""
        // Don't descend into masked password fields, even structurally —
        // their value is already nil but the role itself signals intent.
        if PrivacyFilter.blockedAXRoles.contains(role) { return }

        // URL — most browsers expose AXWebArea with kAXURLAttribute. Only
        // keep the first one we find; nested iframes can spam.
        if urlOut.isEmpty, role == "AXWebArea" {
            if let s = copyURLString(element, kAXURLAttribute) {
                urlOut = s
            }
        }

        // Text — value is the most authoritative; fall back to title and
        // description for elements that label themselves textually.
        if let v = copyString(element, kAXValueAttribute) {
            collector.add(v)
        } else if let t = copyString(element, kAXTitleAttribute) {
            collector.add(t)
        }
        if let d = copyString(element, kAXDescriptionAttribute) {
            collector.add(d)
        }

        guard let kids = copyChildren(element) else { return }
        for child in kids {
            if collector.done { return }
            walk(child, depth: depth + 1, collector: &collector, urlOut: &urlOut)
        }
    }

    // MARK: - Attribute helpers

    private static func copyElement(_ parent: AXUIElement, _ attribute: String) -> AXUIElement? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(parent, attribute as CFString, &value)
        guard status == .success, let value else { return nil }
        guard CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return (value as! AXUIElement)
    }

    private static func copyString(_ element: AXUIElement, _ attribute: String) -> String? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        guard status == .success, let value else { return nil }
        return value as? String
    }

    /// Read `kAXURLAttribute` style values which come back as CFURL, not String.
    private static func copyURLString(_ element: AXUIElement, _ attribute: String) -> String? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        guard status == .success, let value else { return nil }
        if CFGetTypeID(value) == CFURLGetTypeID() {
            return (value as! NSURL).absoluteString
        }
        return value as? String
    }

    private static func copyChildren(_ element: AXUIElement) -> [AXUIElement]? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &value)
        guard status == .success, let value else { return nil }
        guard CFGetTypeID(value) == CFArrayGetTypeID() else { return nil }
        return (value as! [AXUIElement])
    }

    /// Pull text from a focused element. Skips secure fields outright.
    private static func extractTextSafely(from element: AXUIElement, role: String) -> String? {
        if PrivacyFilter.blockedAXRoles.contains(role) {
            return nil
        }
        if let v = copyString(element, kAXValueAttribute) {
            return v
        }
        if let v = copyString(element, kAXSelectedTextAttribute) {
            return v
        }
        return nil
    }
}
