import AppKit
import Combine

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menuBar: MenuBarController?
    private var preferences: PreferencesWindowController?
    private var hud: HUDWindowController?
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Touch the DB early so any migration error surfaces before the user
        // does anything.
        _ = LocalDB.shared

        // Recover any .m4a files left behind by a crash / DB write failure so
        // the uploader can pick them up. Cheap enough to run every launch.
        AudioRecorder.reconcileOrphans()

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
                    AudioUploader.shared.start()
                } else {
                    CapturePipeline.shared.stop(reason: "token cleared")
                    Uploader.shared.stop(reason: "token cleared")
                    AudioUploader.shared.stop(reason: "token cleared")
                }
            }
            .store(in: &cancellables)

        // Show the floating HUD when a recording is active, hide otherwise.
        AudioRecorder.shared.$isRecording
            .receive(on: RunLoop.main)
            .sink { [weak self] recording in
                guard let self else { return }
                if recording {
                    if self.hud == nil { self.hud = HUDWindowController() }
                    self.hud?.showAtTopRight()
                } else {
                    self.hud?.hide()
                }
            }
            .store(in: &cancellables)
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Stop any in-flight recording and wait for the file to finalize so
        // the LocalAudio row exists before the process dies. If we time out,
        // reconcileOrphans() on next launch will still pick the file up.
        if AudioRecorder.shared.isRecording {
            let sem = DispatchSemaphore(value: 0)
            Task { @MainActor in
                await AudioRecorder.shared.stopAndWait()
                sem.signal()
            }
            // Drive the main run loop briefly so the Task + delegate can
            // progress while we wait. Bounded to 3.5s so the system's
            // terminate deadline is never exceeded.
            let deadline = Date().addingTimeInterval(3.5)
            while sem.wait(timeout: .now() + 0.05) == .timedOut, Date() < deadline {
                RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
            }
        }
        CapturePipeline.shared.stop(reason: "app terminating")
        Uploader.shared.stop(reason: "app terminating")
        AudioUploader.shared.stop(reason: "app terminating")
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
