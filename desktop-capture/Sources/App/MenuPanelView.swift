import SwiftUI

/// M1 placeholder — shows the app name, a "not configured" state, and the
/// two menu affordances (Preferences, Quit). Later milestones replace this
/// with the full armed/paused/recording panels from the Wonder design canvas.
struct MenuPanelView: View {
    let onOpenPreferences: () -> Void
    let onQuit: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            body_content
            Divider()
            footer
        }
        .frame(width: 360)
        .padding(.vertical, 0)
    }

    private var header: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(Color.secondary)
                .frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 2) {
                Text("PageFly Capture")
                    .font(.system(size: 14, weight: .semibold))
                Text("Not configured")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
    }

    private var body_content: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("WELCOME")
                .font(.system(size: 10, weight: .semibold))
                .tracking(1.5)
                .foregroundStyle(Color(white: 0.55))
                .padding(.horizontal, 20)
                .padding(.top, 12)

            Text("Set your server URL and API token in Preferences to start capturing.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 20)
                .padding(.bottom, 16)
        }
    }

    private var footer: some View {
        HStack {
            Button(action: onOpenPreferences) {
                Text("Preferences…")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)

            Spacer()

            Button(action: onQuit) {
                Text("Quit")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }
}

#Preview {
    MenuPanelView(onOpenPreferences: {}, onQuit: {})
}
