import AppKit
import SwiftUI

/// Standalone dashboard window. Shows recent audio recordings up top
/// (clickable to play, deletable while still pending) and the captured
/// text-event log underneath (deletable while still pending). The popover
/// dashboard is intentionally a teaser; this window is where the user
/// actually inspects what the agent has stored locally.
final class DashboardWindowController: NSWindowController {
    convenience init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 600),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "PageFly Dashboard"
        window.center()
        window.minSize = NSSize(width: 620, height: 460)
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: DashboardView())
        self.init(window: window)
    }
}

// MARK: - SwiftUI

private struct DashboardView: View {
    @StateObject private var model = DashboardModel()
    @ObservedObject private var preview = AudioPreview.shared

    var body: some View {
        VStack(spacing: 0) {
            audioSection
                .frame(height: 240)
            Divider()
            eventsSection
        }
        .background(Color(NSColor.windowBackgroundColor))
        .onAppear { model.start() }
        .onDisappear { model.stop() }
    }

    // MARK: Audio section (top)

    private var audioSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("Voice recordings")
                    .font(.system(size: 13, weight: .semibold))
                Text("\(model.audio.count) total")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    model.refresh()
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .help("Refresh")
            }
            .padding(.horizontal, 16)
            .padding(.top, 14)

            if model.audio.isEmpty {
                emptyState(
                    "No recordings yet",
                    "Hit Record from the menu bar or HUD to capture a meeting."
                )
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(model.audio, id: \.local_uuid) { row in
                            AudioRow(
                                row: row,
                                isPlaying: preview.playingUUID == row.local_uuid,
                                onTogglePlay: { togglePlay(row) },
                                onDelete: { model.deleteAudio(row) }
                            )
                            Divider().opacity(0.3)
                        }
                    }
                }
            }
            if let err = model.lastError {
                Text(err)
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 6)
            }
        }
    }

    // MARK: Events section (bottom)

    private var eventsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("Captured events")
                    .font(.system(size: 13, weight: .semibold))
                Text("\(model.totalEvents) total · \(model.pendingEventCount) pending")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                Spacer()
                paginationControls
            }
            .padding(.horizontal, 16)
            .padding(.top, 14)

            if model.events.isEmpty {
                emptyState(
                    "No captured text yet",
                    "Once Accessibility permission is granted, focused window text will appear here."
                )
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(model.events, id: \.local_uuid) { row in
                            EventRow(
                                row: row,
                                onDelete: { model.deleteEvent(row) }
                            )
                            Divider().opacity(0.3)
                        }
                    }
                }
            }
        }
        .frame(maxHeight: .infinity)
    }

    @ViewBuilder
    private var paginationControls: some View {
        if model.pageCount > 1 {
            HStack(spacing: 6) {
                Button {
                    model.goToPage(model.page - 1)
                } label: {
                    Image(systemName: "chevron.left")
                }
                .buttonStyle(.borderless)
                .disabled(model.page <= 0)

                Text("Page \(model.page + 1) of \(model.pageCount)")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .frame(minWidth: 110)

                Button {
                    model.goToPage(model.page + 1)
                } label: {
                    Image(systemName: "chevron.right")
                }
                .buttonStyle(.borderless)
                .disabled(model.page >= model.pageCount - 1)
            }
        } else {
            Text("\(model.totalEvents) row\(model.totalEvents == 1 ? "" : "s")")
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
        }
    }

    private func emptyState(_ title: String, _ subtitle: String) -> some View {
        VStack(spacing: 6) {
            Text(title)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.secondary)
            Text(subtitle)
                .font(.system(size: 11))
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }

    private func togglePlay(_ row: LocalAudio) {
        if let err = preview.toggle(uuid: row.local_uuid, filePath: row.file_path) {
            model.lastError = err
        } else {
            model.lastError = nil
        }
    }
}

// MARK: - Rows

private struct AudioRow: View {
    let row: LocalAudio
    let isPlaying: Bool
    let onTogglePlay: () -> Void
    let onDelete: () -> Void

    @State private var confirmingDelete = false

    var body: some View {
        HStack(spacing: 12) {
            playButton
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(DashboardFormat.duration(row.duration_s))
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                    Text(DashboardFormat.audioStatus(row))
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
                if !row.trigger_app.isEmpty {
                    Text(row.trigger_app)
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
                if let transcript = row.transcript, !transcript.isEmpty {
                    Text(transcript)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .padding(.top, 2)
                }
            }
            Spacer()
            Text(DashboardFormat.age(row.uploaded_at ?? row.started_at))
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
                .monospacedDigit()
            deleteSlot
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    @ViewBuilder
    private var playButton: some View {
        let canPlay = !row.file_path.isEmpty
        Button(action: onTogglePlay) {
            Image(systemName: isPlaying ? "stop.circle.fill" : "play.circle.fill")
                .font(.system(size: 22))
                .foregroundStyle(canPlay ? Color.accentColor : Color.secondary.opacity(0.5))
        }
        .buttonStyle(.plain)
        .disabled(!canPlay)
        .help(canPlay ? (isPlaying ? "Stop" : "Play") : "File no longer on disk")
    }

    @ViewBuilder
    private var deleteSlot: some View {
        if isDeletable {
            if confirmingDelete {
                HStack(spacing: 4) {
                    Button("Confirm") {
                        confirmingDelete = false
                        onDelete()
                    }
                    .controlSize(.small)
                    .keyboardShortcut(.return)
                    Button("Cancel") { confirmingDelete = false }
                        .controlSize(.small)
                        .keyboardShortcut(.escape)
                }
            } else {
                Button {
                    confirmingDelete = true
                } label: {
                    Image(systemName: "trash")
                        .foregroundStyle(.red)
                }
                .buttonStyle(.borderless)
                .help("Delete this recording (not yet uploaded)")
            }
        } else {
            // Reserve the same slot width so rows don't jiggle as items
            // transition from pending → uploaded mid-session.
            Color.clear.frame(width: 24, height: 16)
        }
    }

    private var isDeletable: Bool {
        let s = LocalAudioStatus(rawValue: row.status)
        return s == .pending_upload || s == .failed
    }
}

private struct EventRow: View {
    let row: LocalEvent
    let onDelete: () -> Void

    @State private var confirmingDelete = false

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            statusDot
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(row.app.isEmpty ? row.bundle_id : row.app)
                        .font(.system(size: 12, weight: .semibold))
                        .lineLimit(1)
                    if !row.window_title.isEmpty {
                        Text("·")
                            .foregroundStyle(.tertiary)
                        Text(row.window_title)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                if !row.url.isEmpty {
                    Text(row.url)
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
                if !row.text_excerpt.isEmpty {
                    Text(row.text_excerpt)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .padding(.top, 2)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(DashboardFormat.age(row.ended_at ?? row.started_at))
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                if row.duration_s > 0 {
                    Text("\(row.duration_s)s")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .monospacedDigit()
                }
            }
            deleteSlot
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private var statusDot: some View {
        Circle()
            .fill(DashboardFormat.eventColor(row.status))
            .frame(width: 6, height: 6)
            .padding(.top, 6)
    }

    @ViewBuilder
    private var deleteSlot: some View {
        if row.status == "pending" {
            if confirmingDelete {
                HStack(spacing: 4) {
                    Button("Confirm") {
                        confirmingDelete = false
                        onDelete()
                    }
                    .controlSize(.small)
                    .keyboardShortcut(.return)
                    Button("Cancel") { confirmingDelete = false }
                        .controlSize(.small)
                        .keyboardShortcut(.escape)
                }
            } else {
                Button {
                    confirmingDelete = true
                } label: {
                    Image(systemName: "trash")
                        .foregroundStyle(.red)
                }
                .buttonStyle(.borderless)
                .help("Delete this event (not yet uploaded)")
            }
        } else {
            Color.clear.frame(width: 24, height: 16)
        }
    }
}

// MARK: - Model

@MainActor
private final class DashboardModel: ObservableObject {
    static let pageSize = 100

    @Published var audio: [LocalAudio] = []
    @Published var events: [LocalEvent] = []
    @Published var totalEvents: Int = 0
    @Published var pendingEventCount: Int = 0
    @Published var page: Int = 0
    @Published var lastError: String?

    private var timer: Timer?

    var pageCount: Int {
        max(1, Int(ceil(Double(totalEvents) / Double(DashboardModel.pageSize))))
    }

    func start() {
        refresh()
        timer?.invalidate()
        let t = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        t.tolerance = 1
        timer = t
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func refresh() {
        do {
            audio = try LocalDB.shared.fetchRecentAudio(limit: 100)
            totalEvents = try LocalDB.shared.eventCount()
            // Clamp the page index in case rows were deleted off the end
            // (e.g. user emptied a page with the trash button) — otherwise
            // we'd render an empty page even though earlier rows remain.
            let lastValidPage = max(0, pageCount - 1)
            if page > lastValidPage { page = lastValidPage }
            events = try LocalDB.shared.fetchRecentEvents(
                limit: DashboardModel.pageSize,
                offset: page * DashboardModel.pageSize
            )
            pendingEventCount = try LocalDB.shared.pendingEventCount()
        } catch {
            lastError = "Couldn't read local DB: \(error.localizedDescription)"
        }
    }

    func goToPage(_ next: Int) {
        let clamped = max(0, min(next, max(0, pageCount - 1)))
        guard clamped != page else { return }
        page = clamped
        refresh()
    }

    func deleteAudio(_ row: LocalAudio) {
        // If a deleted recording is currently playing, stop it first so the
        // file vanishes cleanly instead of mid-frame.
        if AudioPreview.shared.playingUUID == row.local_uuid {
            AudioPreview.shared.stop()
        }
        do {
            // Re-read to make sure the row still qualifies (the uploader may
            // have flipped status to `uploading` between view render and click).
            let current = try LocalDB.shared.fetchAudio(localUUID: row.local_uuid) ?? row
            let removed = try LocalDB.shared.deleteLocalAudio(localUUID: current.local_uuid)
            if removed {
                removeFile(at: current.file_path)
                logCapture(.info, "Dashboard deleted audio \(current.local_uuid)")
            } else {
                lastError = "Recording is already uploading; can't delete."
            }
        } catch {
            lastError = "Delete failed: \(error.localizedDescription)"
        }
        refresh()
    }

    func deleteEvent(_ row: LocalEvent) {
        do {
            let removed = try LocalDB.shared.deletePendingEvent(localUUID: row.local_uuid)
            if removed {
                logCapture(.info, "Dashboard deleted event \(row.local_uuid)")
            } else {
                lastError = "Event was already uploaded; can't delete."
            }
        } catch {
            lastError = "Delete failed: \(error.localizedDescription)"
        }
        refresh()
    }

    private func removeFile(at path: String) {
        guard !path.isEmpty else { return }
        let fm = FileManager.default
        guard fm.fileExists(atPath: path) else { return }
        do {
            try fm.removeItem(atPath: path)
        } catch {
            logCapture(.warn, "Dashboard couldn't remove \(path): \(error)")
        }
    }
}

// MARK: - Formatting helpers

private enum DashboardFormat {
    static func duration(_ seconds: Int) -> String {
        let m = seconds / 60
        let s = seconds % 60
        return String(format: "%d:%02d", m, s)
    }

    static func age(_ iso: String) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = f.date(from: iso) else { return "" }
        let secs = Int(Date().timeIntervalSince(date))
        if secs < 60 { return "now" }
        if secs < 3600 { return "\(secs / 60)m ago" }
        if secs < 86400 { return "\(secs / 3600)h ago" }
        return "\(secs / 86400)d ago"
    }

    static func audioStatus(_ row: LocalAudio) -> String {
        switch LocalAudioStatus(rawValue: row.status) {
        case .recording: return "Recording"
        case .pending_upload: return "Waiting to upload"
        case .uploading: return "Uploading…"
        case .uploaded: return "Transcribing…"
        case .transcribed:
            return row.file_path.isEmpty ? "Transcribed (file pruned)" : "Transcribed"
        case .failed: return "Upload failed"
        case .none: return row.status
        }
    }

    static func eventColor(_ status: String) -> Color {
        switch status {
        case "pending": return .orange
        case "uploaded": return .green
        case "failed": return .red
        default: return .secondary
        }
    }
}
