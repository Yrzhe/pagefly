import SwiftUI

/// Menu bar dropdown panel. M3 adds the AX permission state and a live event
/// count from LocalDB so users can see the capture pipeline is doing work.
struct MenuPanelView: View {
    let onOpenPreferences: () -> Void
    let onQuit: () -> Void
    let onTest: () -> Void

    @ObservedObject private var settings = SettingsStore.shared
    @ObservedObject private var recorder = AudioRecorder.shared
    @State private var pendingCount: Int = 0
    @State private var axTrusted: Bool = AXReader.isAccessibilityTrusted(prompt: false)

    // Refresh pending count + AX state every 3s while the popover is open.
    private let pollTimer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 0) {
            header
            if settings.hasToken && !axTrusted {
                axBanner
            }
            Divider()
            statusBlock
            Divider()
            footer
        }
        .frame(width: 360)
        .onReceive(pollTimer) { _ in refresh() }
        .onAppear { refresh() }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 2) {
                Text("PageFly Capture")
                    .font(.system(size: 14, weight: .semibold))
                Text(headerSubtitle)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if settings.hasToken && axTrusted && pendingCount > 0 {
                VStack(alignment: .trailing, spacing: 0) {
                    Text("\(pendingCount)")
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .foregroundStyle(.primary)
                    Text("queued")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
    }

    private var axBanner: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("Accessibility access required")
                    .font(.system(size: 12, weight: .semibold))
                Text("PageFly can't read window titles or focused text without it.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Grant…", action: openAXPane)
                .buttonStyle(.bordered)
                .controlSize(.small)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(Color.orange.opacity(0.08))
    }

    private var statusBlock: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(blockTitle)
                .font(.system(size: 10, weight: .semibold))
                .tracking(1.5)
                .foregroundStyle(Color(white: 0.55))
            Text(blockBody)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                recordButton
                if settings.hasToken {
                    Button("Test connection", action: onTest)
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .disabled(settings.connectionState == .checking)
                }
                Button("Open Preferences", action: onOpenPreferences)
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                Spacer()
            }
            if let err = recorder.lastError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                    .font(.system(size: 11))
                    .padding(.top, 2)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    @ViewBuilder
    private var recordButton: some View {
        if recorder.isRecording {
            Button(action: { recorder.stop() }) {
                Label("Stop recording", systemImage: "stop.circle.fill")
                    .foregroundStyle(.red)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        } else {
            Button(action: { _ = recorder.start() }) {
                Label("Record", systemImage: "mic.fill")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
    }

    private var footer: some View {
        HStack {
            Button(action: onOpenPreferences) {
                Text("Preferences…").font(.system(size: 11)).foregroundStyle(.secondary)
            }.buttonStyle(.plain)
            Spacer()
            Button(action: onQuit) {
                Text("Quit").font(.system(size: 11)).foregroundStyle(.secondary)
            }.buttonStyle(.plain)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    // MARK: - Derived

    private var statusColor: Color {
        if settings.hasToken && !axTrusted { return .orange }
        switch settings.connectionState {
        case .connected: return .green
        case .checking: return .secondary
        case .unauthorized, .unreachable: return .red
        case .unknown: return Color.secondary.opacity(0.6)
        }
    }

    private var headerSubtitle: String {
        if settings.hasToken && !axTrusted { return "Permission needed" }
        switch settings.connectionState {
        case .connected: return "Capturing"
        case .checking: return "Testing connection…"
        case .unauthorized: return "Token rejected"
        case .unreachable(let why): return "Unreachable · \(why)"
        case .unknown: return settings.hasToken ? "Not tested yet" : "Not configured"
        }
    }

    private var blockTitle: String {
        settings.hasToken ? "STATUS" : "WELCOME"
    }

    private var blockBody: String {
        if !settings.hasToken {
            return "Set your server URL and API token in Preferences to start capturing."
        }
        if !axTrusted {
            return "Grant Accessibility access in System Settings → Privacy & Security so PageFly can read which app and window you're focused on."
        }
        switch settings.connectionState {
        case .connected:
            let queued = "\(pendingCount) event\(pendingCount == 1 ? "" : "s") queued"
            return "Capture is live. \(queued). \(lastSyncedLabel())"
        case .checking:
            return "Pinging \(settings.serverURL)…"
        case .unauthorized:
            return "The token in Keychain wasn't accepted. Re-paste it in Preferences."
        case .unreachable(let why):
            return "Can't reach \(settings.serverURL): \(why). Check the URL or your network."
        case .unknown:
            return "Click Test connection to verify your token + server URL."
        }
    }

    private func lastSyncedLabel() -> String {
        guard let when = settings.lastSyncedAt else { return "Not synced yet." }
        let seconds = Int(Date().timeIntervalSince(when))
        if seconds < 60 { return "Synced just now." }
        if seconds < 3600 { return "Synced \(seconds / 60)m ago." }
        if seconds < 86400 { return "Synced \(seconds / 3600)h ago." }
        return "Synced \(seconds / 86400)d ago."
    }

    private func refresh() {
        axTrusted = AXReader.isAccessibilityTrusted(prompt: false)
        pendingCount = (try? LocalDB.shared.pendingEventCount()) ?? 0
    }

    private func openAXPane() {
        // Triggers the system prompt + focuses the right Settings pane.
        _ = AXReader.isAccessibilityTrusted(prompt: true)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }
}

#Preview {
    MenuPanelView(onOpenPreferences: {}, onQuit: {}, onTest: {})
}
