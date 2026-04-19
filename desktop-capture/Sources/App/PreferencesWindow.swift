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
    @State private var saveError: String?
    @State private var launchAtLogin: Bool = false
    @State private var launchAtLoginError: String?
    @State private var launchAtLoginNeedsApproval: Bool = false

    var body: some View {
        Form {
            Section {
                TextField("Server URL", text: $serverDraft, prompt: Text("https://api.pagefly.ink"))
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

                    if settings.hasToken {
                        Button("Forget token", role: .destructive, action: forgetToken)
                            .help("Remove the saved API token from Keychain")
                    }

                    Spacer()
                    statusBadge
                }
                if let saveError {
                    Label(saveError, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                        .font(.system(size: 11, weight: .medium))
                        .padding(.top, 4)
                }
            }

            Section {
                HStack(spacing: 12) {
                    Slider(
                        value: Binding(
                            get: { Double(settings.audioRetentionCount) },
                            set: { settings.audioRetentionCount = Int($0.rounded()) }
                        ),
                        in: 0...50,
                        step: 1
                    )
                    Text(retentionLabel)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 70, alignment: .trailing)
                        .monospacedDigit()
                }
            } header: {
                Text("Audio retention")
            } footer: {
                Text(retentionFooter)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Section {
                Toggle("Launch at login", isOn: Binding(
                    get: { launchAtLogin },
                    set: { toggleLaunchAtLogin($0) }
                ))
                if launchAtLoginNeedsApproval {
                    Label("Approve PageFly Capture in System Settings → Login Items.", systemImage: "hand.raised")
                        .foregroundStyle(.orange)
                        .font(.system(size: 11, weight: .medium))
                }
                if let launchAtLoginError {
                    Label(launchAtLoginError, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                        .font(.system(size: 11, weight: .medium))
                }
            } header: {
                Text("Startup")
            } footer: {
                Text("Starts PageFly Capture silently when you log in. Managed by macOS Login Items.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
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

    private var retentionLabel: String {
        let n = settings.audioRetentionCount
        if n == 0 { return "Off" }
        if n == 1 { return "1 file" }
        return "\(n) files"
    }

    private var retentionFooter: String {
        let n = settings.audioRetentionCount
        if n == 0 {
            return "Delete each recording from disk as soon as it's uploaded. Transcripts are still kept on the server."
        }
        return "Keep the most recent \(n) uploaded recording\(n == 1 ? "" : "s") on disk; older ones are deleted automatically. Transcripts are kept on the server regardless."
    }

    private func loadDrafts() {
        serverDraft = settings.serverURL
        // Don't pre-fill the token field for security; `hasToken` shows
        // whether one is already saved.
        tokenDraft = ""
        launchAtLogin = LoginItemService.isEnabled
        launchAtLoginNeedsApproval = LoginItemService.requiresUserApproval
    }

    private func toggleLaunchAtLogin(_ desired: Bool) {
        do {
            try LoginItemService.setEnabled(desired)
            launchAtLogin = LoginItemService.isEnabled
            launchAtLoginNeedsApproval = LoginItemService.requiresUserApproval
            launchAtLoginError = nil
        } catch {
            // Roll the toggle back so the UI reflects the real OS state.
            launchAtLogin = LoginItemService.isEnabled
            launchAtLoginError = error.localizedDescription
        }
    }

    private func commitServerURL() {
        settings.serverURL = serverDraft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func saveAndTest() {
        commitServerURL()
        let trimmedToken = tokenDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedToken.isEmpty {
            do {
                try settings.setApiToken(trimmedToken)
                tokenDraft = ""
                saveError = nil
            } catch {
                // Surface the failure and abort — pinging would validate the
                // OLD token still in Keychain and mislead the user.
                saveError = "Couldn't save to Keychain: \(error)"
                return
            }
        }
        Task { await settings.ping() }
    }

    private func forgetToken() {
        try? settings.setApiToken(nil)
        tokenDraft = ""
        saveError = nil
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
    @ObservedObject private var updater = UpdateChecker.shared

    var body: some View {
        VStack(alignment: .center, spacing: 12) {
            Image(systemName: "circle.fill")
                .font(.system(size: 44))
                .foregroundStyle(.secondary)
            Text("PageFly Capture")
                .font(.system(size: 16, weight: .semibold))
            Text("Version \(UpdateChecker.currentVersion)")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            Text("Menu bar client for the PageFly personal knowledge OS.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 300)

            Divider().padding(.vertical, 4)

            updateStatusRow
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(24)
    }

    @ViewBuilder
    private var updateStatusRow: some View {
        VStack(spacing: 8) {
            statusLine
            HStack(spacing: 8) {
                Button(action: manualCheck) {
                    if case .checking = updater.status {
                        HStack(spacing: 6) {
                            ProgressView().scaleEffect(0.6).frame(width: 12, height: 12)
                            Text("Checking…")
                        }
                    } else {
                        Text("Check for Updates")
                    }
                }
                .disabled(isChecking)

                if case .available = updater.status {
                    Button("Download") { updater.openReleasePage() }
                        .buttonStyle(.borderedProminent)
                }
            }
            if let last = updater.lastCheckedAt {
                Text("Last checked \(relative(last))")
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
            }
        }
    }

    private var isChecking: Bool {
        if case .checking = updater.status { return true }
        return false
    }

    @ViewBuilder
    private var statusLine: some View {
        switch updater.status {
        case .unknown:
            Text("Updates not checked yet.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        case .checking:
            Text("Checking for updates…")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        case .upToDate(let current):
            Label("Up to date · v\(current)", systemImage: "checkmark.seal.fill")
                .foregroundStyle(.green)
                .font(.system(size: 11, weight: .semibold))
        case .available(let release):
            Label("Update available · v\(release.version)", systemImage: "sparkles")
                .foregroundStyle(.orange)
                .font(.system(size: 11, weight: .semibold))
        case .failed(let why):
            Label(why, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
                .font(.system(size: 11, weight: .medium))
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func manualCheck() {
        Task { await updater.checkNow(force: true, userInitiated: true) }
    }

    private func relative(_ date: Date) -> String {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        return f.localizedString(for: date, relativeTo: Date())
    }
}
