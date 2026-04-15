import Foundation

/// Thin URLSession wrapper for talking to a PageFly server. M2 only needs a
/// `ping()` that confirms the server is reachable and the token is accepted.
/// Later milestones extend with /api/activity/events/batch and audio upload.
struct APIClient {
    let serverURL: URL
    let token: String

    /// Build from current SettingsStore values; returns nil if either is missing
    /// or the URL is malformed.
    @MainActor
    static func from(_ settings: SettingsStore) -> APIClient? {
        guard let token = settings.apiToken, !token.isEmpty else { return nil }
        let trimmed = settings.serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let url = URL(string: trimmed) else { return nil }
        return APIClient(serverURL: url, token: token)
    }

    /// Probes an authenticated endpoint to verify both reachability and token
    /// validity in one round-trip.
    func ping() async -> ConnectionState {
        let endpoint = serverURL.appendingPathComponent("/api/schedules")
        var request = URLRequest(url: endpoint, timeoutInterval: 8)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("PageflyCapture/0.0.1", forHTTPHeaderField: "User-Agent")

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .unreachable("no response")
            }
            switch http.statusCode {
            case 200..<300:
                return .connected
            case 401, 403:
                return .unauthorized
            default:
                return .unreachable("HTTP \(http.statusCode)")
            }
        } catch let error as URLError {
            return .unreachable(error.shortDescription)
        } catch {
            return .unreachable(String(describing: error))
        }
    }
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
