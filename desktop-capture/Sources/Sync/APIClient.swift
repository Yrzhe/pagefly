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

    // MARK: - Audio upload (M6)

    enum AudioUploadError: Error {
        case fileMissing(String)           // local m4a not on disk
        case unauthorized
        case server(Int, String)
        case transport(String)
        case decode(String)
    }

    struct AudioUploadResult {
        let remoteID: Int64
        let status: String                 // typically "uploaded"
        let duplicate: Bool
    }

    struct AudioStatus: Decodable {
        let id: Int64
        let status: String                 // uploaded | transcribing | transcribed | failed
        let duration_s: Int
        let transcript: String
        let transcribed_at: String
        let error: String
    }

    /// Multipart POST /api/activity/audio. Returns the server row id the
    /// client should store in LocalAudio.remote_id. Idempotent on local_uuid
    /// — a second upload for the same uuid returns `duplicate: true` without
    /// re-transcribing, so crash-retry is safe.
    func uploadAudio(_ audio: LocalAudio) async throws -> AudioUploadResult {
        guard !audio.file_path.isEmpty else {
            throw AudioUploadError.fileMissing(audio.local_uuid)
        }
        let fileURL = URL(fileURLWithPath: audio.file_path)
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            throw AudioUploadError.fileMissing(audio.file_path)
        }

        // Heavy work (file read + multipart assembly) happens on a detached
        // task so the caller's actor (MainActor for AudioUploader) stays
        // responsive even on multi-hour recordings. URLSession.data's own
        // I/O is already off-main.
        let request: URLRequest
        do {
            request = try await Task.detached(priority: .userInitiated) { [serverURL, token, deviceID] in
                try APIClient.buildAudioUploadRequest(
                    audio: audio,
                    fileURL: fileURL,
                    serverURL: serverURL,
                    token: token,
                    deviceID: deviceID
                )
            }.value
        } catch let err as AudioUploadError {
            throw err
        } catch {
            throw AudioUploadError.transport("prepare upload: \(error.localizedDescription)")
        }

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let err as URLError {
            throw AudioUploadError.transport(err.shortDescription)
        } catch {
            throw AudioUploadError.transport(String(describing: error))
        }

        guard let http = response as? HTTPURLResponse else {
            throw AudioUploadError.transport("no response")
        }
        switch http.statusCode {
        case 200..<300:
            do {
                let decoded = try JSONDecoder().decode(AudioUploadResponse.self, from: data)
                return AudioUploadResult(
                    remoteID: decoded.id,
                    status: decoded.status,
                    duplicate: decoded.duplicate ?? false
                )
            } catch {
                throw AudioUploadError.decode("response decode: \(error)")
            }
        case 401, 403:
            throw AudioUploadError.unauthorized
        default:
            let body = String(data: data, encoding: .utf8) ?? ""
            throw AudioUploadError.server(http.statusCode, String(body.prefix(200)))
        }
    }

    /// GET /api/activity/audio/{id}/status. Used to poll transcription state.
    func getAudioStatus(remoteID: Int64) async throws -> AudioStatus {
        let url = serverURL
            .appendingPathComponent("/api/activity/audio/\(remoteID)/status")
        let request = makeRequest(url: url, method: "GET", timeout: 15)

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let err as URLError {
            throw AudioUploadError.transport(err.shortDescription)
        } catch {
            throw AudioUploadError.transport(String(describing: error))
        }

        guard let http = response as? HTTPURLResponse else {
            throw AudioUploadError.transport("no response")
        }
        switch http.statusCode {
        case 200..<300:
            do {
                return try JSONDecoder().decode(AudioStatus.self, from: data)
            } catch {
                throw AudioUploadError.decode("status decode: \(error)")
            }
        case 401, 403:
            throw AudioUploadError.unauthorized
        default:
            let body = String(data: data, encoding: .utf8) ?? ""
            throw AudioUploadError.server(http.statusCode, String(body.prefix(200)))
        }
    }

    // MARK: - Multipart helpers

    /// Build the full multipart POST request. Intentionally static + `throws`
    /// so it's callable from `Task.detached` without capturing `self` and
    /// without running on the caller's actor.
    fileprivate static func buildAudioUploadRequest(
        audio: LocalAudio,
        fileURL: URL,
        serverURL: URL,
        token: String,
        deviceID: String
    ) throws -> URLRequest {
        let fileData: Data
        do {
            fileData = try Data(contentsOf: fileURL)
        } catch {
            throw AudioUploadError.transport("read file: \(error.localizedDescription)")
        }

        var components = URLComponents(
            url: serverURL.appendingPathComponent("/api/activity/audio"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [
            URLQueryItem(name: "local_uuid", value: audio.local_uuid),
            URLQueryItem(name: "started_at", value: audio.started_at),
            URLQueryItem(name: "ended_at", value: audio.ended_at ?? ""),
            URLQueryItem(name: "duration_s", value: String(audio.duration_s)),
            URLQueryItem(name: "source", value: audio.source),
            URLQueryItem(name: "trigger_app", value: audio.trigger_app),
            URLQueryItem(name: "device_id", value: deviceID),
        ]
        guard let url = components?.url else {
            throw AudioUploadError.decode("bad URL composition")
        }

        let boundary = "pagefly.\(UUID().uuidString)"
        var request = URLRequest(url: url, timeoutInterval: 180)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("PageflyCapture/0.0.1", forHTTPHeaderField: "User-Agent")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = APIClient.multipartBody(
            fileData: fileData,
            fileName: fileURL.lastPathComponent,
            mimeType: "audio/mp4",
            boundary: boundary
        )
        return request
    }

    private static func multipartBody(
        fileData: Data,
        fileName: String,
        mimeType: String,
        boundary: String
    ) -> Data {
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        return body
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

private struct AudioUploadResponse: Decodable {
    let id: Int64
    let status: String
    let size_bytes: Int64?
    let duplicate: Bool?
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
