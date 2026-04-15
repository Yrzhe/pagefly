import AppKit
import SwiftUI

/// Borderless, non-activating floating panel that hosts the recording HUD
/// pill. Show it when recording starts, hide when it stops. It never takes
/// focus so the user can keep typing or switching apps while recording.
@MainActor
final class HUDWindowController: NSWindowController {
    convenience init() {
        let panel = HUDPanel(
            contentRect: NSRect(x: 0, y: 0, width: 320, height: 60),
            styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]

        let hosting = NSHostingController(rootView: HUDView())
        panel.contentViewController = hosting

        self.init(window: panel)
    }

    func showAtTopRight() {
        guard let window, let screen = NSScreen.main else { return }
        let visible = screen.visibleFrame
        let origin = NSPoint(
            x: visible.maxX - window.frame.width - 20,
            y: visible.maxY - window.frame.height - 20
        )
        window.setFrameOrigin(origin)
        window.orderFrontRegardless()
    }

    func hide() {
        window?.orderOut(nil)
    }
}

/// Subclass needed to override `canBecomeKey` so the panel can receive mouse
/// events (for the stop button) without stealing focus from the active app.
final class HUDPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

// MARK: - SwiftUI view

struct HUDView: View {
    @ObservedObject private var recorder = AudioRecorder.shared

    /// 1Hz tick for the elapsed time display. Metering lives on the recorder.
    private let clock = Timer.publish(every: 1, on: .main, in: .common).autoconnect()
    @State private var tick: Int = 0

    var body: some View {
        HStack(spacing: 12) {
            recordIndicator
            info
            waveform
            stopButton
        }
        .padding(.horizontal, 12)
        .frame(width: 320, height: 60)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(.regularMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.6), lineWidth: 0.5)
                )
                .shadow(color: Color.black.opacity(0.12), radius: 15, x: 0, y: 6)
        )
        .onReceive(clock) { _ in tick &+= 1 }
    }

    private var recordIndicator: some View {
        ZStack {
            Circle()
                .fill(Color.red.opacity(0.15))
                .frame(width: 32, height: 32)
            Circle()
                .fill(Color.red.opacity(0.35))
                .frame(width: 20, height: 20)
            Circle()
                .fill(Color.red)
                .frame(width: 10, height: 10)
        }
    }

    private var info: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(formatElapsed(recorder.elapsedSeconds))
                .font(.system(size: 15, weight: .semibold, design: .monospaced))
                .foregroundStyle(.primary)
            HStack(spacing: 4) {
                Text("RECORDING")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.red)
                Text("·")
                    .foregroundStyle(.secondary)
                Text(String((recorder.currentUUID ?? "").prefix(6)))
                    .font(.system(size: 10, weight: .regular, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var waveform: some View {
        HStack(spacing: 3) {
            ForEach(recorder.levels.indices, id: \.self) { i in
                Capsule()
                    .fill(Color.red.opacity(0.8))
                    .frame(width: 3, height: max(4, CGFloat(recorder.levels[i]) * 20))
            }
        }
        .frame(height: 20)
    }

    private var stopButton: some View {
        Button(action: { recorder.stop() }) {
            RoundedRectangle(cornerRadius: 2)
                .fill(Color.white)
                .frame(width: 12, height: 12)
                .padding(9)
                .background(
                    Circle().fill(Color(white: 0.1))
                )
        }
        .buttonStyle(.plain)
        .help("Stop recording")
    }

    private func formatElapsed(_ seconds: Int) -> String {
        let h = seconds / 3600
        let m = (seconds % 3600) / 60
        let s = seconds % 60
        if h > 0 {
            return String(format: "%d:%02d:%02d", h, m, s)
        }
        return String(format: "%02d:%02d", m, s)
    }
}

#Preview {
    HUDView()
        .frame(width: 320, height: 60)
        .padding(40)
        .background(Color.gray.opacity(0.2))
}
