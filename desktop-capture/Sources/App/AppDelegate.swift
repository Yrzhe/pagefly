import AppKit
import Combine

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menuBar: MenuBarController?
    private var preferences: PreferencesWindowController?
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Touch the DB early so any migration error surfaces before the user
        // does anything.
        _ = LocalDB.shared

        let menuBar = MenuBarController(
            onOpenPreferences: { [weak self] in self?.openPreferences() },
            onQuit: { NSApp.terminate(nil) }
        )
        self.menuBar = menuBar

        // Auto-ping if a token is already in Keychain so the menu bar dot is
        // accurate before the user clicks anywhere.
        if SettingsStore.shared.hasToken {
            Task { await SettingsStore.shared.ping() }
        }

        // Boot capture + uploader whenever a token exists. Stop them when
        // the token is forgotten. AX permission is checked inside start().
        SettingsStore.shared.$hasToken
            .receive(on: RunLoop.main)
            .sink { hasToken in
                if hasToken {
                    CapturePipeline.shared.start()
                    Uploader.shared.start()
                } else {
                    CapturePipeline.shared.stop(reason: "token cleared")
                    Uploader.shared.stop(reason: "token cleared")
                }
            }
            .store(in: &cancellables)
    }

    func applicationWillTerminate(_ notification: Notification) {
        CapturePipeline.shared.stop(reason: "app terminating")
        Uploader.shared.stop(reason: "app terminating")
        // Belt and suspenders: close any in-flight rows directly in the DB.
        let iso = ISO8601DateFormatter().string(from: Date())
        try? LocalDB.shared.closeOpenRows(at: iso)
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
