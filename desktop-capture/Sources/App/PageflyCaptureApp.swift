import SwiftUI

@main
struct PageflyCaptureApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        // Menu bar app: no main window scene. The Settings scene is included
        // so SwiftUI has at least one Scene; it's not shown automatically.
        Settings {
            EmptyView()
        }
    }
}
