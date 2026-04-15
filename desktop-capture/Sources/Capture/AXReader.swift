import AppKit
import ApplicationServices

/// Reads the currently focused app + window + element via the macOS
/// Accessibility API. Returns nil when AX permission is denied or no app is
/// frontmost (rare).
enum AXReader {
    static func currentSnapshot() -> ContextSnapshot? {
        guard let app = NSWorkspace.shared.frontmostApplication else {
            return nil
        }

        let appName = app.localizedName ?? "Unknown"
        let bundleID = app.bundleIdentifier ?? ""
        let pid = app.processIdentifier

        let axApp = AXUIElementCreateApplication(pid)

        let title = copyElement(axApp, kAXFocusedWindowAttribute)
            .flatMap { copyString($0, kAXTitleAttribute) } ?? ""

        var role = ""
        var text = ""
        if let focusedElement = copyElement(axApp, kAXFocusedUIElementAttribute) {
            role = copyString(focusedElement, kAXRoleAttribute) ?? ""
            text = extractTextSafely(from: focusedElement, role: role) ?? ""
        }

        return ContextSnapshot(
            app: appName,
            bundleID: bundleID,
            windowTitle: title,
            url: "",  // M3 keeps URL extraction out of scope; AXWebArea wiring later.
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

    // MARK: - Helpers

    private static func copyElement(_ parent: AXUIElement, _ attribute: String) -> AXUIElement? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(parent, attribute as CFString, &value)
        guard status == .success, let value else { return nil }
        // Attributes that return an element bridge to AXUIElement; the
        // CFGetTypeID guard below is belt-and-suspenders against a misnamed
        // attribute returning a string by accident.
        guard CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return (value as! AXUIElement)
    }

    private static func copyString(_ element: AXUIElement, _ attribute: String) -> String? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        guard status == .success else { return nil }
        return value as? String
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
