import AppKit
import SwiftUI

/// Preferences window. M2 wires the General tab to SettingsStore + APIClient.
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
            GeneralTab()
                .tabItem { Label("General", systemImage: "gearshape") }
            PrivacyPlaceholder()
                .tabItem { Label("Privacy", systemImage: "shield") }
            AboutTab()
                .tabItem { Label("About", systemImage: "info.circle") }
        }
        .frame(minWidth: 480, minHeight: 520)
    }
}

// MARK: - General tab

private struct GeneralTab: View {
    @ObservedObject private var settings = SettingsStore.shared

    @State private var serverDraft: String = ""
    @State private var tokenDraft: String = ""
    @State private var revealToken: Bool = false

    var body: some View {
        Form {
            Section {
                TextField("Server URL", text: $serverDraft, prompt: Text("https://pagefly.ink"))
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(commitServerURL)
            } header: {
                Text("Server")
            } footer: {
                Text("Where this Mac will send captured events and audio.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Section {
                HStack(spacing: 8) {
                    Group {
                        if revealToken {
                            TextField("API Token", text: $tokenDraft, prompt: Text("paste from server settings"))
                        } else {
                            SecureField("API Token", text: $tokenDraft, prompt: Text("paste from server settings"))
                        }
                    }
                    .textFieldStyle(.roundedBorder)

                    Button(action: { revealToken.toggle() }) {
                        Image(systemName: revealToken ? "eye.slash" : "eye")
                    }
                    .buttonStyle(.borderless)
                    .help(revealToken ? "Hide token" : "Show token")
                }
            } header: {
                Text("API Token")
            } footer: {
                Text("Stored in your macOS Keychain. Never sent anywhere except your server.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Section {
                HStack(spacing: 12) {
                    Button("Save & Test", action: saveAndTest)
                        .keyboardShortcut(.return, modifiers: [.command])
                        .disabled(serverDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    if !settings.hasToken {
                        Spacer()
                    } else {
                        Button("Forget token", role: .destructive, action: forgetToken)
                            .help("Remove the saved API token from Keychain")
                    }

                    Spacer()
                    statusBadge
                }
            }
        }
        .formStyle(.grouped)
        .padding(.vertical, 4)
        .onAppear(perform: loadDrafts)
    }

    @ViewBuilder
    private var statusBadge: some View {
        switch settings.connectionState {
        case .unknown:
            Label("Not tested", systemImage: "circle")
                .foregroundStyle(.secondary)
                .font(.system(size: 11))
        case .checking:
            HStack(spacing: 6) {
                ProgressView().scaleEffect(0.6).frame(width: 12, height: 12)
                Text("Testing…").font(.system(size: 11)).foregroundStyle(.secondary)
            }
        case .connected:
            Label("Connected", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.system(size: 11, weight: .semibold))
        case .unauthorized:
            Label("Token rejected", systemImage: "xmark.octagon.fill")
                .foregroundStyle(.red)
                .font(.system(size: 11, weight: .semibold))
        case .unreachable(let why):
            Label("Unreachable · \(why)", systemImage: "wifi.exclamationmark")
                .foregroundStyle(.orange)
                .font(.system(size: 11, weight: .semibold))
        }
    }

    private func loadDrafts() {
        serverDraft = settings.serverURL
        // Don't pre-fill the token field for security; `hasToken` shows
        // whether one is already saved.
        tokenDraft = ""
    }

    private func commitServerURL() {
        settings.serverURL = serverDraft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func saveAndTest() {
        commitServerURL()
        let trimmedToken = tokenDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedToken.isEmpty {
            settings.setApiToken(trimmedToken)
            tokenDraft = ""
        }
        Task { await settings.ping() }
    }

    private func forgetToken() {
        settings.setApiToken(nil)
        tokenDraft = ""
    }
}

// MARK: - Privacy placeholder

private struct PrivacyPlaceholder: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Privacy controls land in M3: app blocklist, private browsing handling, password-field protection.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(24)
    }
}

// MARK: - About tab

private struct AboutTab: View {
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
