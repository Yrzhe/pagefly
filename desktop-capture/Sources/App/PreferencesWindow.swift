import AppKit
import SwiftUI

/// Preferences window — empty SwiftUI TabView shell for M1. Fields land in M2.
final class PreferencesWindowController: NSWindowController {
    convenience init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 480, height: 540),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Preferences"
        window.center()
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: PreferencesView())
        self.init(window: window)
    }
}

struct PreferencesView: View {
    var body: some View {
        TabView {
            GeneralPlaceholder()
                .tabItem { Label("General", systemImage: "gearshape") }
            PrivacyPlaceholder()
                .tabItem { Label("Privacy", systemImage: "shield") }
            AboutPlaceholder()
                .tabItem { Label("About", systemImage: "info.circle") }
        }
        .frame(minWidth: 480, minHeight: 520)
        .padding(0)
    }
}

private struct GeneralPlaceholder: View {
    var body: some View {
        placeholder("General settings will land in M2: Server URL, API Token, Launch at login, Capture frequency.")
    }
}

private struct PrivacyPlaceholder: View {
    var body: some View {
        placeholder("Privacy controls will land in M3: app blocklist, private browsing handling, password-field protection.")
    }
}

private struct AboutPlaceholder: View {
    var body: some View {
        VStack(alignment: .center, spacing: 12) {
            Image(systemName: "circle.fill")
                .font(.system(size: 44))
                .foregroundStyle(.secondary)
            Text("PageFly Capture")
                .font(.system(size: 16, weight: .semibold))
            if let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String {
                Text("Version \(version)")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
            Text("Menu bar client for the PageFly personal knowledge OS.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 300)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(24)
    }
}

@ViewBuilder
private func placeholder(_ text: String) -> some View {
    VStack(alignment: .leading, spacing: 12) {
        Text(text)
            .font(.system(size: 12))
            .foregroundStyle(.secondary)
        Spacer()
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .padding(24)
}
