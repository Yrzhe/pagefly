import Foundation
import os

/// Shared os.Logger — visible in Console.app, filterable by subsystem.
let logger = Logger(subsystem: "top.yrzhe.PageflyCapture", category: "app")

// MARK: - File logger

enum LogLevel: String {
    case debug = "DEBUG"
    case info = "INFO"
    case warn = "WARN"
    case error = "ERROR"
}

/// Append-only file logger at `~/Library/Logs/PageFly/capture.log`. Failure
/// to write is swallowed — losing log lines must never break capture.
final class FileLogger {
    static let shared = FileLogger()

    private let url: URL
    private let queue = DispatchQueue(label: "top.yrzhe.PageflyCapture.filelog", qos: .utility)
    private let formatter: ISO8601DateFormatter

    private init() {
        let logs = FileManager.default
            .urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs/PageFly", isDirectory: true)
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        self.url = logs.appendingPathComponent("capture.log")
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        self.formatter = f
    }

    func write(_ level: LogLevel, _ message: String) {
        let timestamp = formatter.string(from: Date())
        let line = "\(timestamp) [\(level.rawValue)] \(message)\n"
        queue.async { [url] in
            guard let data = line.data(using: .utf8) else { return }
            if let handle = try? FileHandle(forWritingTo: url) {
                defer { try? handle.close() }
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            } else {
                // First write — file doesn't exist yet.
                try? data.write(to: url, options: .atomic)
            }
        }
    }
}

/// Single helper used by the capture pipeline: routes to both os.Logger
/// (Console.app) and FileLogger (~/Library/Logs/PageFly/capture.log).
func logCapture(_ level: LogLevel, _ message: String) {
    switch level {
    case .debug: logger.debug("\(message, privacy: .public)")
    case .info: logger.info("\(message, privacy: .public)")
    case .warn: logger.warning("\(message, privacy: .public)")
    case .error: logger.error("\(message, privacy: .public)")
    }
    FileLogger.shared.write(level, message)
}
