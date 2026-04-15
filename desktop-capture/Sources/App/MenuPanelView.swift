import SwiftUI

/// Menu bar dropdown panel. M2 wires the real connection state from
/// `SettingsStore` and offers a manual Test button. Capture/Recording
/// affordances land in M3+.
struct MenuPanelView: View {
    let onOpenPreferences: () -> Void
    let onQuit: () -> Void
    let onTest: () -> Void

    @ObservedObject private var settings = SettingsStore.shared

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            statusBlock
            Divider()
            footer
        }
        .frame(width: 360)
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
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
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
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
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
        switch settings.connectionState {
        case .connected: return .green
        case .checking: return .secondary
        case .unauthorized, .unreachable: return .red
        case .unknown: return Color.secondary.opacity(0.6)
        }
    }

    private var headerSubtitle: String {
        switch settings.connectionState {
        case .connected: return "Connected"
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
        switch settings.connectionState {
        case .connected:
            return "Talking to \(settings.serverURL). Capture pipeline lands in the next milestone."
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
}

#Preview {
    MenuPanelView(onOpenPreferences: {}, onQuit: {}, onTest: {})
}
