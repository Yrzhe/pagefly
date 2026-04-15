import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menuBar: MenuBarController?
    private var preferences: PreferencesWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menuBar = MenuBarController(
            onOpenPreferences: { [weak self] in self?.openPreferences() },
            onQuit: { NSApp.terminate(nil) }
        )
        self.menuBar = menuBar

        // If a token is already in Keychain from a previous launch, ping the
        // server so the icon ends up coloured before the user clicks anywhere.
        if SettingsStore.shared.hasToken {
            Task { await SettingsStore.shared.ping() }
        }
    }

    private func openPreferences() {
        if preferences == nil {
            preferences = PreferencesWindowController()
        }
        preferences?.showWindow(nil)
        preferences?.window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
