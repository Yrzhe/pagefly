import Foundation
import CoreGraphics

/// Reports system-wide idle time using CGEventSource. We treat any sample
/// where idle > `threshold` as "user is afk" so the capture pipeline can
/// stop sampling and stop bumping duration on any open row.
struct IdleMonitor {
    var threshold: TimeInterval = 60

    var isIdle: Bool {
        secondsSinceLastInput >= threshold
    }

    var secondsSinceLastInput: TimeInterval {
        // .combinedSessionState is the documented "any input" event source.
        let any = CGEventType(rawValue: ~0)!
        return CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: any)
    }
}
