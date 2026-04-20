import AppKit
import Combine
import SwiftUI

/// Owns the NSStatusItem in the menu bar and the popover that hosts the
/// SwiftUI dropdown panel. M8 reshapes the icon into a small state machine
/// so the menu bar tells the user at a glance what the app is doing:
///
/// noConfig     – no token yet, nothing is happening
/// noPermission – token saved but Accessibility is not granted
/// offline      – token was rejected or server is unreachable
/// checking     – actively testing connection
/// armed        – connected + permissions granted, capturing idle events
/// recording    – a meeting recording is in progress
@MainActor
final class MenuBarController: NSObject, NSPopoverDelegate {
    enum State: Equatable {
        case noConfig
        case noPermission
        case offline
        case checking
        case armed
        case paused
        case recording
    }

    private let statusItem: NSStatusItem
    private let popover: NSPopover
    private var eventMonitor: Any?
    private var cancellables = Set<AnyCancellable>()

    private var currentState: State = .noConfig

    private let onOpenPreferences: () -> Void
    private let onOpenDashboard: () -> Void
    private let onQuit: () -> Void

    init(
        onOpenPreferences: @escaping () -> Void,
        onOpenDashboard: @escaping () -> Void,
        onQuit: @escaping () -> Void
    ) {
        self.onOpenPreferences = onOpenPreferences
        self.onOpenDashboard = onOpenDashboard
        self.onQuit = onQuit

        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        self.popover = NSPopover()
        self.popover.behavior = .transient
        self.popover.animates = true

        super.init()

        self.popover.delegate = self
        configureStatusItem()
        configurePopover()
        observeInputs()
        AXTrustMonitor.shared.start()
        refreshState()
    }

    deinit {
        if let monitor = eventMonitor {
            NSEvent.removeMonitor(monitor)
        }
    }

    // MARK: - Setup

    private func configureStatusItem() {
        // Force an explicit length so the item reserves menu bar real estate
        // even on a busy notched display where macOS is eager to push new
        // arrivals into the overflow "…" menu.
        statusItem.length = 22
        if let button = statusItem.button {
            button.imagePosition = .imageOnly
            button.target = self
            button.action = #selector(togglePopover(_:))
        }
    }

    private func configurePopover() {
        let view = MenuPanelView(
            onOpenPreferences: { [weak self] in
                self?.closePopover()
                self?.onOpenPreferences()
            },
            onOpenDashboard: { [weak self] in
                self?.closePopover()
                self?.onOpenDashboard()
            },
            onQuit: { [weak self] in
                self?.closePopover()
                self?.onQuit()
            },
            onTest: {
                Task { await SettingsStore.shared.ping() }
            }
        )
        let hosting = NSHostingController(rootView: view)
        hosting.view.frame = NSRect(x: 0, y: 0, width: 360, height: 220)
        popover.contentViewController = hosting
    }

    private func observeInputs() {
        SettingsStore.shared.$connectionState
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.refreshState() }
            .store(in: &cancellables)

        SettingsStore.shared.$hasToken
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.refreshState() }
            .store(in: &cancellables)

        AudioRecorder.shared.$isRecording
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.refreshState() }
            .store(in: &cancellables)

        // The panel and the icon read AX trust from the same publisher so
        // they never disagree while the popover is open.
        AXTrustMonitor.shared.$isTrusted
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.refreshState() }
            .store(in: &cancellables)

        // Reflect user-invoked pause in the menu bar tint immediately
        // instead of waiting for the next connection-state event.
        CapturePipeline.shared.$isPausedByUser
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.refreshState() }
            .store(in: &cancellables)
    }

    // MARK: - State → UI

    private func refreshState() {
        let state = computeState()
        guard state != currentState else { return }
        currentState = state
        applyState(state)
    }

    private func computeState() -> State {
        if AudioRecorder.shared.isRecording { return .recording }
        if !SettingsStore.shared.hasToken { return .noConfig }
        if !AXTrustMonitor.shared.isTrusted { return .noPermission }
        // User pause takes precedence over connection state so the icon
        // stops looking "armed green" while captures are off.
        if CapturePipeline.shared.isPausedByUser { return .paused }
        switch SettingsStore.shared.connectionState {
        case .connected: return .armed
        case .checking: return .checking
        case .unauthorized, .unreachable: return .offline
        case .unknown: return .checking
        }
    }

    private func applyState(_ state: State) {
        guard let button = statusItem.button else { return }
        let (tint, description) = paintFor(state)
        if let base = NSImage(named: "MenuBarIcon") {
            button.image = Self.tinted(base, color: tint, size: NSSize(width: 18, height: 18))
        } else {
            let fb = NSImage(systemSymbolName: "doc.fill", accessibilityDescription: description)
            fb?.isTemplate = true
            button.image = fb
            logCapture(.warn, "menu bar: MenuBarIcon asset missing, using fallback")
        }
        button.contentTintColor = nil
        button.toolTip = description
    }

    /// Bake the tint into a non-template NSImage. Guaranteed to render as
    /// `color` regardless of menu bar appearance quirks that have made
    /// template + contentTintColor unreliable in practice.
    private static func tinted(_ source: NSImage, color: NSColor, size: NSSize) -> NSImage {
        let out = NSImage(size: size)
        out.lockFocus()
        let rect = NSRect(origin: .zero, size: size)
        source.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1.0)
        color.set()
        rect.fill(using: .sourceAtop)
        out.unlockFocus()
        out.isTemplate = false
        return out
    }

    /// Tint policy: neutral states use the dynamic `labelColor`, which
    /// resolves to near-black on light menu bars and near-white on dark
    /// ones. Colored states use system semantic colors that also adapt.
    /// We pre-tint the image with this color (see `tinted(…)`) rather than
    /// going through `contentTintColor`, because that path turned out to
    /// leave the icon flat-black on some dark menu bar configurations.
    private func paintFor(_ state: State) -> (tint: NSColor, description: String) {
        switch state {
        case .noConfig:
            return (.labelColor, "PageFly Capture — not configured")
        case .noPermission:
            return (.systemOrange, "PageFly Capture — Accessibility permission needed")
        case .offline:
            return (.systemRed, "PageFly Capture — server offline or token rejected")
        case .checking:
            return (.labelColor, "PageFly Capture — checking connection")
        case .armed:
            return (.systemGreen, "PageFly Capture — armed")
        case .paused:
            return (.systemYellow, "PageFly Capture — paused (click to resume)")
        case .recording:
            return (.systemRed, "PageFly Capture — recording")
        }
    }

    // MARK: - Popover handling

    @objc private func togglePopover(_ sender: Any?) {
        if popover.isShown {
            closePopover()
        } else {
            openPopover()
        }
    }

    private func openPopover() {
        guard let button = statusItem.button else { return }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        startMonitoringOutsideClicks()
    }

    private func closePopover() {
        popover.performClose(nil)
        stopMonitoringOutsideClicks()
    }

    private func startMonitoringOutsideClicks() {
        stopMonitoringOutsideClicks()
        eventMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor in self?.closePopover() }
        }
    }

    private func stopMonitoringOutsideClicks() {
        if let monitor = eventMonitor {
            NSEvent.removeMonitor(monitor)
            eventMonitor = nil
        }
    }

    // MARK: - NSPopoverDelegate

    nonisolated func popoverDidClose(_ notification: Notification) {
        Task { @MainActor in stopMonitoringOutsideClicks() }
    }
}
