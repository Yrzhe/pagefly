import Foundation
import os

/// Shared logger for the capture client. Goes through the unified logging
/// system so messages land in `~/Library/Logs/PageFly/capture.log` once we
/// wire that file destination up in M3 — until then they show in Console.app.
let logger = Logger(subsystem: "top.yrzhe.PageflyCapture", category: "app")
