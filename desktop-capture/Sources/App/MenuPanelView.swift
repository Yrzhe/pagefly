import SwiftUI

/// Menu bar dropdown panel. M3 adds the AX permission state and a live event
/// count from LocalDB so users can see the capture pipeline is doing work.
struct MenuPanelView: View {
    let onOpenPreferences: () -> Void
    let onOpenDashboard: () -> Void
    let onQuit: () -> Void
    let onTest: () -> Void

    @ObservedObject private var settings = SettingsStore.shared
    @ObservedObject private var recorder = AudioRecorder.shared
    @ObservedObject private var pipeline = CapturePipeline.shared
    @ObservedObject private var ocr = OCRRescue.shared
    @State private var pendingCount: Int = 0
    @State private var pendingAudioCount: Int = 0
    @State private var recentAudio: [LocalAudio] = []
    @State private var axTrusted: Bool = false

    // Panel polls its own AX + queue state. The menu bar icon reads the
    // same AX state from the shared AXTrustMonitor, but SwiftUI views
    // don't observe it directly — @ObservedObject on a MainActor singleton
    // during NSHostingController init has caused a startup hang in testing.
    private let pollTimer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 0) {
            header
            if settings.hasToken && !axTrusted {
                axBanner
            }
            Divider()
            statusBlock
            if settings.hasToken {
                Divider()
                dashboardBlock
            }
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
            blockBodyView
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            // Two-row button layout. Row 1: capture controls (what's
            // happening right now). Row 2: admin / navigation. Keeps
            // labels legible in a 360pt-wide popover — one-row packing
            // with 5-6 bordered buttons truncated to "Rec…", "P…",
            // "OCR…", "Test…", "Dash…", "Prefe…".
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    recordButton
                    if settings.hasToken && axTrusted {
                        pauseButton
                        ocrButton
                    }
                    Spacer()
                }
                if settings.hasToken {
                    HStack(spacing: 8) {
                        Button("Test connection", action: onTest)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .disabled(settings.connectionState == .checking)
                        Button("Dashboard…", action: onOpenDashboard)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        Button("Preferences…", action: onOpenPreferences)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        Spacer()
                    }
                } else {
                    HStack {
                        Button("Preferences…", action: onOpenPreferences)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        Spacer()
                    }
                }
            }
            if let status = ocr.lastStatus {
                Label(status, systemImage: "text.viewfinder")
                    .foregroundStyle(.secondary)
                    .font(.system(size: 11))
                    .padding(.top, 2)
            }
            if let err = ocr.lastError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                    .font(.system(size: 11))
                    .padding(.top, 2)
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

    @ViewBuilder
    private var ocrButton: some View {
        Button(action: triggerOCR) {
            if ocr.isRunning {
                Label("OCR…", systemImage: "text.viewfinder")
            } else {
                Label("OCR window", systemImage: "text.viewfinder")
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .disabled(ocr.isRunning)
        .help("Screenshot + OCR the focused window — rescue text from AX-blind apps like WeChat / Feishu. On-device, one-shot.")
    }

    private func triggerOCR() {
        // Fire-and-forget; OCRRescue surfaces status via @Published props
        // that this view already observes, so there's nothing to await here.
        // The popover will close from the outside-click monitor once the
        // user clicks into the target window, which is what we want — the
        // captured screenshot shouldn't include our own popover.
        OCRRescue.shared.rescueFocusedWindow()
    }

    @ViewBuilder
    private var pauseButton: some View {
        if pipeline.isPausedByUser {
            Button(action: { pipeline.setPausedByUser(false) }) {
                Label("Resume capture", systemImage: "play.fill")
                    .foregroundStyle(.green)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help("Resume capturing window activity")
        } else {
            Button(action: { pipeline.setPausedByUser(true) }) {
                Label("Pause", systemImage: "pause.fill")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help("Stop capturing until you resume. Does not affect audio recording.")
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
        if recorder.isRecording { return .red }
        if settings.hasToken && !axTrusted { return .orange }
        if pipeline.isPausedByUser { return .yellow }
        switch settings.connectionState {
        case .connected: return .green
        case .checking: return .secondary
        case .unauthorized, .unreachable: return .red
        case .unknown: return Color.secondary.opacity(0.6)
        }
    }

    private var headerSubtitle: String {
        if recorder.isRecording { return "Recording in progress" }
        if settings.hasToken && !axTrusted { return "Permission needed" }
        if pipeline.isPausedByUser { return "Paused" }
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

    @ViewBuilder
    private var blockBodyView: some View {
        if recorder.isRecording {
            // TimelineView ticks every second so the elapsed label stays
            // fresh without relying on the panel's 3s poll or plumbing a
            // @Published duration out of AudioRecorder.
            TimelineView(.periodic(from: .now, by: 1)) { _ in
                Text("Recording · \(formatElapsed(recorder.elapsedSeconds)). The floating HUD lets you stop from anywhere.")
            }
        } else {
            Text(blockBodyText)
        }
    }

    private var blockBodyText: String {
        if !settings.hasToken {
            return "Set your server URL and API token in Preferences to start capturing."
        }
        if !axTrusted {
            return "Grant Accessibility access in System Settings → Privacy & Security so PageFly can read which app and window you're focused on."
        }
        if pipeline.isPausedByUser {
            let queued = "\(pendingCount) event\(pendingCount == 1 ? "" : "s") still queued"
            return "Capture is paused. Nothing is being recorded. \(queued) — upload continues in the background. Hit Resume when you're ready."
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

    private func formatElapsed(_ seconds: Int) -> String {
        let m = seconds / 60
        let s = seconds % 60
        if m >= 60 {
            return String(format: "%d:%02d:%02d", m / 60, m % 60, s)
        }
        return String(format: "%d:%02d", m, s)
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
        pendingCount = (try? LocalDB.shared.pendingEventCount()) ?? 0
        pendingAudioCount = (try? LocalDB.shared.pendingAudioCount()) ?? 0
        recentAudio = (try? LocalDB.shared.fetchRecentAudio(limit: 5)) ?? []
        axTrusted = AXReader.isAccessibilityTrusted(prompt: false)
    }

    // MARK: - Dashboard

    private var dashboardBlock: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("DASHBOARD")
                .font(.system(size: 10, weight: .semibold))
                .tracking(1.5)
                .foregroundStyle(Color(white: 0.55))

            HStack(spacing: 14) {
                queueStat(
                    label: "Events queued",
                    count: pendingCount,
                    systemImage: "tray.full"
                )
                queueStat(
                    label: "Audio waiting",
                    count: pendingAudioCount,
                    systemImage: "waveform"
                )
            }

            if recentAudio.isEmpty {
                Text("No recordings yet.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent recordings")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.secondary)
                    ForEach(recentAudio, id: \.local_uuid) { row in
                        recentAudioRow(row)
                    }
                }
                .padding(.top, 2)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    private func queueStat(label: String, count: Int, systemImage: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage)
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
            Text("\(count)")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .monospacedDigit()
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
    }

    private func recentAudioRow(_ row: LocalAudio) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(audioStatusColor(row.status))
                .frame(width: 6, height: 6)
            Text(formatRecordingDuration(row.duration_s))
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .monospacedDigit()
                .frame(width: 44, alignment: .leading)
            Text(audioStatusLabel(row))
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Spacer()
            Text(audioAgeLabel(row))
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
                .monospacedDigit()
        }
    }

    private func audioStatusColor(_ raw: String) -> Color {
        switch LocalAudioStatus(rawValue: raw) {
        case .recording: return .red
        case .pending_upload, .uploading: return .orange
        case .uploaded: return .blue
        case .transcribed: return .green
        case .failed: return .red
        case .none: return .secondary
        }
    }

    private func audioStatusLabel(_ row: LocalAudio) -> String {
        switch LocalAudioStatus(rawValue: row.status) {
        case .recording: return "Recording"
        case .pending_upload: return "Waiting to upload"
        case .uploading: return "Uploading…"
        case .uploaded: return "Transcribing…"
        case .transcribed:
            // File-on-disk status matters here so the user understands why
            // a transcript exists but they can't replay the m4a anymore.
            return row.file_path.isEmpty ? "Transcribed (file pruned)" : "Transcribed"
        case .failed: return "Failed"
        case .none: return row.status
        }
    }

    private func formatRecordingDuration(_ seconds: Int) -> String {
        let m = seconds / 60
        let s = seconds % 60
        return String(format: "%d:%02d", m, s)
    }

    private func audioAgeLabel(_ row: LocalAudio) -> String {
        // Prefer uploaded_at over started_at because the dashboard list is
        // ordered by upload recency; mixing two clocks would scramble it.
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let stamp = row.uploaded_at ?? row.started_at
        guard let when = iso.date(from: stamp) else { return "" }
        let seconds = Int(Date().timeIntervalSince(when))
        if seconds < 60 { return "now" }
        if seconds < 3600 { return "\(seconds / 60)m" }
        if seconds < 86400 { return "\(seconds / 3600)h" }
        return "\(seconds / 86400)d"
    }

    private func openAXPane() {
        // Triggers the system prompt + focuses the right Settings pane.
        _ = AXReader.isAccessibilityTrusted(prompt: true)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
        // Nudge the shared trust monitor so the icon + panel flip as soon
        // as the user flicks the switch in System Settings, rather than
        // waiting for the next 5s poll.
        AXTrustMonitor.shared.refresh()
    }
}

#Preview {
    MenuPanelView(
        onOpenPreferences: {},
        onOpenDashboard: {},
        onQuit: {},
        onTest: {}
    )
}
