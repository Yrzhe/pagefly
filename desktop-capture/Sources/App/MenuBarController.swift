import AppKit
import Combine
import SwiftUI

/// Owns the NSStatusItem in the menu bar and the popover that hosts the
/// SwiftUI dropdown panel. Listens to SettingsStore so the icon tint reflects
/// the current connection state without polling.
@MainActor
final class MenuBarController: NSObject {
    private let statusItem: NSStatusItem
    private let popover: NSPopover
    private var eventMonitor: Any?
    private var cancellables = Set<AnyCancellable>()

    private let onOpenPreferences: () -> Void
    private let onQuit: () -> Void

    init(
        onOpenPreferences: @escaping () -> Void,
        onQuit: @escaping () -> Void
    ) {
        self.onOpenPreferences = onOpenPreferences
        self.onQuit = onQuit

        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        self.popover = NSPopover()
        self.popover.behavior = .transient
        self.popover.animates = true

        super.init()

        configureStatusItem()
        configurePopover()
        observeSettings()
    }

    deinit {
        if let monitor = eventMonitor {
            NSEvent.removeMonitor(monitor)
        }
    }

    // MARK: - Setup

    private func configureStatusItem() {
        if let button = statusItem.button {
            let image = NSImage(systemSymbolName: "circle.fill", accessibilityDescription: "PageFly Capture")
            image?.isTemplate = true
            button.image = image
            button.imagePosition = .imageOnly
            button.target = self
            button.action = #selector(togglePopover(_:))
            applyTint(for: SettingsStore.shared.connectionState)
        }
    }

    private func configurePopover() {
        let view = MenuPanelView(
            onOpenPreferences: { [weak self] in
                self?.closePopover()
                self?.onOpenPreferences()
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

    private func observeSettings() {
        SettingsStore.shared.$connectionState
            .receive(on: RunLoop.main)
            .sink { [weak self] state in
                self?.applyTint(for: state)
            }
            .store(in: &cancellables)
    }

    /// Tint the template status icon based on the current state. Template
    /// images recolour against any background, so this works in both light
    /// and dark menu bars.
    private func applyTint(for state: ConnectionState) {
        guard let button = statusItem.button else { return }
        switch state {
        case .connected:
            button.contentTintColor = .systemGreen
        case .checking:
            button.contentTintColor = .secondaryLabelColor
        case .unauthorized, .unreachable:
            button.contentTintColor = .systemRed
        case .unknown:
            button.contentTintColor = .tertiaryLabelColor
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
        eventMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            self?.closePopover()
        }
    }

    private func stopMonitoringOutsideClicks() {
        if let monitor = eventMonitor {
            NSEvent.removeMonitor(monitor)
            eventMonitor = nil
        }
    }
}
