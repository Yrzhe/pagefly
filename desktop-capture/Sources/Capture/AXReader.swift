import AppKit
import ApplicationServices

/// Reads the currently focused app + window + element via the macOS
/// Accessibility API. Returns nil when AX permission is denied or no app is
/// frontmost (rare).
///
/// Text strategy:
///   1. Poke the app element with the Chromium/WebKit "screen reader is
///      active" flags so Electron/browser apps materialize their full AX
///      tree. Cached per-pid to avoid paying the tree rebuild every poll.
///   2. Grab the focused element's `AXValue` / `AXSelectedText` first — that's
///      the highest-signal source (what the user is actively typing/selecting).
///   3. Walk the focused *window* with a bounded budget (node count, depth,
///      *and* wall-clock) to harvest visible text + an `AXURL` from any
///      `AXWebArea` descendant. Decorative roles are skipped entirely.
///   4. The persisted `textExcerpt` prefers the focused-element text when
///      present; otherwise it falls back to the harvested window text.
enum AXReader {
    // Walk budgets — tuned for "responsive enough on a Comet/Chrome window
    // with a real page loaded, but rich enough that Electron apps (Slack,
    // Cursor, Notion, Discord) actually yield their content instead of
    // running out of node budget on chrome before reaching the pane".
    // Bigger DOMs simply truncate.
    private static let maxTextChars = 4000
    private static let maxNodes = 1500
    private static let maxDepth = 20
    /// Per-element AX messaging timeout. Default is ~6s, which is way too
    /// long for our 5-10s capture cadence.
    private static let messagingTimeoutSeconds: Float = 0.3
    /// Total wall-clock budget for the window walk. A pathological slow app
    /// could otherwise burn `maxNodes × messagingTimeoutSeconds` seconds on
    /// the main thread. Screenpipe's equivalent default is 250ms — we give
    /// ourselves a little more headroom.
    private static let walkBudgetSeconds: CFTimeInterval = 0.3

    /// Decorative AX roles whose subtrees never contain content the user
    /// would want logged. Skipping these frees node budget for the real
    /// content pane in Electron/Chromium apps that spam the AX tree with
    /// scrollbars, images, toolbars, and progress indicators. Derived from
    /// Screenpipe's `macos.rs` (crates/screenpipe-a11y).
    private static let decorativeRoles: Set<String> = [
        "AXScrollBar",
        "AXImage",
        "AXSplitter",
        "AXGrowArea",
        "AXMenuBar",
        "AXMenu",
        "AXToolbar",
        "AXRuler",
        "AXBusyIndicator",
        "AXProgressIndicator",
        "AXLayoutItem",
    ]

    /// Per-pid TTL for the "enhanced UI" flag poke. Chromium-based apps
    /// materialize their full AX tree when they see `AXEnhancedUserInterface`
    /// go true, but rebuilding that tree is expensive, so we only poke once
    /// every few minutes per pid. The flag stays on between pokes; the TTL
    /// is just "don't re-set it every sample".
    private static let enhanceTTL: TimeInterval = 180
    private static var enhancedAt: [pid_t: Date] = [:]

    static func currentSnapshot() -> ContextSnapshot? {
        guard let app = NSWorkspace.shared.frontmostApplication else {
            return nil
        }

        let appName = app.localizedName ?? "Unknown"
        let bundleID = app.bundleIdentifier ?? ""
        let pid = app.processIdentifier
        let axApp = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(axApp, messagingTimeoutSeconds)
        enhanceChromiumIfNeeded(axApp: axApp, pid: pid)

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
            // Try the Safari/Chrome/Edge fast path: the window itself exposes
            // `AXDocument` (a URL string) without having to descend into the
            // web tree at all. Saves hundreds of nodes on browser windows.
            if let docURL = copyString(w, "AXDocument") {
                url = docURL
            }
            var collector = TextCollector(limit: maxTextChars, nodeBudget: maxNodes)
            let deadline = CFAbsoluteTimeGetCurrent() + walkBudgetSeconds
            walk(w, depth: 0, collector: &collector, urlOut: &url, deadline: deadline)
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

    // MARK: - Chromium / WebKit tree materialization

    /// The single biggest lever for Electron and WebKit-backed apps. Without
    /// these flags Chromium returns a stripped AX tree with ~none of the
    /// content; with them the full tree materializes. Refs:
    ///   - Chromium codereview.chromium.org/6909013
    ///   - electron/electron#7206
    ///   - obsidianmd/obsidian-releases#3002 (needs AXManualAccessibility)
    /// Safe to call on non-Chromium apps — they ignore unknown attributes.
    private static func enhanceChromiumIfNeeded(axApp: AXUIElement, pid: pid_t) {
        let now = Date()
        if let last = enhancedAt[pid], now.timeIntervalSince(last) < enhanceTTL {
            return
        }
        enhancedAt[pid] = now
        setBool(axApp, "AXEnhancedUserInterface", true)
        setBool(axApp, "AXManualAccessibility", true)
    }

    private static func setBool(_ element: AXUIElement, _ attribute: String, _ value: Bool) {
        let cfValue = value as CFBoolean
        _ = AXUIElementSetAttributeValue(element, attribute as CFString, cfValue)
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
        urlOut: inout String,
        deadline: CFAbsoluteTime
    ) {
        if collector.done || depth > maxDepth { return }
        if CFAbsoluteTimeGetCurrent() > deadline { return }
        collector.consumeNode()

        let role = copyString(element, kAXRoleAttribute) ?? ""
        // Don't descend into masked password fields, even structurally —
        // their value is already nil but the role itself signals intent.
        if PrivacyFilter.blockedAXRoles.contains(role) { return }
        // Decorative subtrees: skip the whole branch, don't just skip this
        // node. Their descendants are also noise.
        if decorativeRoles.contains(role) { return }

        // URL — most browsers expose AXWebArea with kAXURLAttribute. Only
        // keep the first one we find; nested iframes can spam. Cheaper
        // `AXDocument` on the window is tried before the walk even starts.
        if urlOut.isEmpty, role == "AXWebArea" {
            if let s = copyURLString(element, kAXURLAttribute) {
                urlOut = s
            }
        }

        // Text — value is the most authoritative; fall back to title and
        // description for elements that label themselves textually. On text
        // elements that expose selected text (many Electron editors do)
        // that's often the only non-empty string they hand back.
        if let v = copyString(element, kAXValueAttribute) {
            collector.add(v)
        } else if let t = copyString(element, kAXTitleAttribute) {
            collector.add(t)
        } else if let sel = copyString(element, kAXSelectedTextAttribute) {
            collector.add(sel)
        }
        if let d = copyString(element, kAXDescriptionAttribute) {
            collector.add(d)
        }

        // Always use kAXChildrenAttribute. The prior kAXVisibleChildrenAttribute
        // pre-fetch cost an extra IPC round-trip per element and Electron apps
        // routinely return [] for visible children even when the content IS
        // visible, so it was net-negative. Screenpipe also walks children
        // directly.
        guard let kids = copyChildren(element) else { return }
        for child in kids {
            if collector.done { return }
            if CFAbsoluteTimeGetCurrent() > deadline { return }
            walk(child, depth: depth + 1, collector: &collector, urlOut: &urlOut, deadline: deadline)
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
        let arr = value as! [AXUIElement]
        return arr.isEmpty ? nil : arr
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
