import AppKit
import SwiftUI

/// Owns the NSStatusItem in the menu bar and the popover that hosts the
/// SwiftUI dropdown panel. For M1 the panel is a placeholder; later milestones
/// will swap in the full armed/paused/recording panels from the design canvas.
final class MenuBarController: NSObject {
    private let statusItem: NSStatusItem
    private let popover: NSPopover
    private var eventMonitor: Any?

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
    }

    deinit {
        if let monitor = eventMonitor {
            NSEvent.removeMonitor(monitor)
        }
    }

    // MARK: - Setup

    private func configureStatusItem() {
        if let button = statusItem.button {
            // SF Symbol placeholder — swap for a bespoke PageFly mark later.
            let image = NSImage(systemSymbolName: "circle.fill", accessibilityDescription: "PageFly Capture")
            image?.isTemplate = true
            button.image = image
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
            onQuit: { [weak self] in
                self?.closePopover()
                self?.onQuit()
            }
        )
        let hosting = NSHostingController(rootView: view)
        hosting.view.frame = NSRect(x: 0, y: 0, width: 360, height: 420)
        popover.contentViewController = hosting
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

    // Close popover on any click outside it — NSPopover's .transient should
    // already do this, but keep a manual monitor as insurance.
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
