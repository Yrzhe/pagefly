import Foundation

/// Thin URLSession wrapper for talking to a PageFly server.
struct APIClient {
    let serverURL: URL
    let token: String
    let deviceID: String

    /// Build from current SettingsStore values; returns nil if either is missing
    /// or the URL is malformed.
    @MainActor
    static func from(_ settings: SettingsStore) -> APIClient? {
        guard let token = settings.apiToken, !token.isEmpty else { return nil }
        let trimmed = settings.serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let url = URL(string: trimmed) else { return nil }
        return APIClient(serverURL: url, token: token, deviceID: settings.deviceID)
    }

    // MARK: - Ping

    /// Probes an authenticated endpoint to verify both reachability and token
    /// validity in one round-trip.
    func ping() async -> ConnectionState {
        let endpoint = serverURL.appendingPathComponent("/api/schedules")
        let request = makeRequest(url: endpoint, method: "GET", timeout: 8)

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .unreachable("no response")
            }
            switch http.statusCode {
            case 200..<300: return .connected
            case 401, 403: return .unauthorized
            default: return .unreachable("HTTP \(http.statusCode)")
            }
        } catch let error as URLError {
            return .unreachable(error.shortDescription)
        } catch {
            return .unreachable(String(describing: error))
        }
    }

    // MARK: - Events batch

    enum BatchError: Error {
        case unauthorized
        case server(Int, String)           // non-2xx HTTP
        case transport(String)             // URLError / transport
        case decode(String)                // response didn't match schema
    }

    struct BatchResult {
        let inserted: [String: Int64]      // local_uuid → server row id
        let skipped: Int
    }

    /// POST /api/activity/events/batch. Throws a typed error on failure so the
    /// uploader can drive back-off / state transitions without string parsing.
    func postEventsBatch(_ events: [LocalEvent]) async throws -> BatchResult {
        let endpoint = serverURL.appendingPathComponent("/api/activity/events/batch")
        var request = makeRequest(url: endpoint, method: "POST", timeout: 30)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let payload = BatchPayload(events: events.map { EventPayload(from: $0, deviceID: deviceID) })
        do {
            request.httpBody = try JSONEncoder.batch.encode(payload)
        } catch {
            throw BatchError.decode("encode failed: \(error)")
        }

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let err as URLError {
            throw BatchError.transport(err.shortDescription)
        } catch {
            throw BatchError.transport(String(describing: error))
        }

        guard let http = response as? HTTPURLResponse else {
            throw BatchError.transport("no response")
        }
        switch http.statusCode {
        case 200..<300:
            do {
                let decoded = try JSONDecoder().decode(BatchResponse.self, from: data)
                return BatchResult(inserted: decoded.inserted, skipped: decoded.skipped)
            } catch {
                throw BatchError.decode("response decode failed: \(error)")
            }
        case 401, 403:
            throw BatchError.unauthorized
        default:
            let body = String(data: data, encoding: .utf8) ?? ""
            throw BatchError.server(http.statusCode, body.prefix(200).description)
        }
    }

    // MARK: - Helpers

    private func makeRequest(url: URL, method: String, timeout: TimeInterval) -> URLRequest {
        var r = URLRequest(url: url, timeoutInterval: timeout)
        r.httpMethod = method
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        r.setValue("PageflyCapture/0.0.1", forHTTPHeaderField: "User-Agent")
        return r
    }
}

// MARK: - Wire types

private struct BatchPayload: Encodable {
    let events: [EventPayload]
}

private struct EventPayload: Encodable {
    let local_uuid: String
    let device_id: String
    let started_at: String
    let ended_at: String
    let duration_s: Int
    let app: String
    let window_title: String
    let url: String
    let text_excerpt: String
    let ax_role: String
    let audio_id: Int64?
    let metadata_json: String

    init(from event: LocalEvent, deviceID: String) {
        self.local_uuid = event.local_uuid
        self.device_id = deviceID
        self.started_at = event.started_at
        self.ended_at = event.ended_at ?? ""
        self.duration_s = event.duration_s
        self.app = event.app
        self.window_title = event.window_title
        self.url = event.url
        self.text_excerpt = event.text_excerpt
        self.ax_role = event.ax_role
        // audio_uuid is a LOCAL reference; the server expects the resolved
        // int id of audio_recordings. M4 has no audio uploads yet, so null.
        self.audio_id = nil
        // Server schema doesn't have a bundle_id column; tuck it into the
        // metadata blob so analytics can still filter on it later.
        self.metadata_json = EventPayload.metadata(bundleID: event.bundle_id)
    }

    static func metadata(bundleID: String) -> String {
        guard !bundleID.isEmpty else { return "{}" }
        // Inline JSON; avoids pulling a second encoder through.
        let escaped = bundleID.replacingOccurrences(of: "\"", with: "\\\"")
        return "{\"bundle_id\":\"\(escaped)\"}"
    }
}

private struct BatchResponse: Decodable {
    let inserted: [String: Int64]
    let skipped: Int
}

private extension URLError {
    var shortDescription: String {
        switch code {
        case .notConnectedToInternet: return "no internet"
        case .timedOut: return "timed out"
        case .cannotFindHost: return "host not found"
        case .cannotConnectToHost: return "can't connect"
        case .secureConnectionFailed: return "TLS failed"
        case .badServerResponse: return "bad response"
        default: return "network error"
        }
    }
}

private extension JSONEncoder {
    static let batch: JSONEncoder = {
        let e = JSONEncoder()
        return e
    }()
}
