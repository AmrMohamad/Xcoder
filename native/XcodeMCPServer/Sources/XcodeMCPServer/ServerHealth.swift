import Foundation
import Darwin

enum ServerHealth {
    static let processStartedAt = Date()
    static let publishIntervalNanoseconds: UInt64 = 1_000_000_000
    private static let staleStateSeconds: TimeInterval = 10

    static func healthJSON(
        registry: ActiveProcessRegistry = .shared,
        startedAt: Date = processStartedAt,
        source: String = "in_process"
    ) async -> String {
        JSONEnvelope.compactJSONString(await healthPayload(registry: registry, startedAt: startedAt, source: source))
    }

    static func publishedOrProbeHealthJSON(stateURL: URL = defaultStateURL()) async -> String {
        if var payload = publishedHealthPayload(stateURL: stateURL) {
            let observedAt = Date()
            if let startedAtEpoch = payload["started_at_epoch"] as? TimeInterval {
                payload["uptime_seconds"] = max(0, observedAt.timeIntervalSince1970 - startedAtEpoch)
            }
            if let updatedAtEpoch = payload["state_updated_at_epoch"] as? TimeInterval {
                payload["state_age_seconds"] = max(0, observedAt.timeIntervalSince1970 - updatedAtEpoch)
            }
            payload["health_source"] = "published_running_server"
            payload["observed_running_server"] = true
            return JSONEnvelope.compactJSONString(payload)
        }

        var payload = await healthPayload(registry: .shared, startedAt: processStartedAt, source: "self_probe")
        payload["observed_running_server"] = false
        return JSONEnvelope.compactJSONString(payload)
    }

    static func startRuntimePublisher(
        registry: ActiveProcessRegistry,
        startedAt: Date = processStartedAt,
        stateURL: URL = defaultStateURL()
    ) -> Task<Void, Never> {
        Task.detached(priority: .utility) {
            while !Task.isCancelled {
                await publishRuntimeHealth(registry: registry, startedAt: startedAt, stateURL: stateURL)
                try? await Task.sleep(nanoseconds: publishIntervalNanoseconds)
            }
        }
    }

    static func publishRuntimeHealth(
        registry: ActiveProcessRegistry,
        startedAt: Date = processStartedAt,
        stateURL: URL = defaultStateURL()
    ) async {
        let payload = await healthPayload(registry: registry, startedAt: startedAt, source: "runtime_state")
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else {
            return
        }
        try? data.write(to: stateURL, options: .atomic)
    }

    static func clearPublishedHealth(stateURL: URL = defaultStateURL()) {
        guard let payload = publishedHealthPayload(stateURL: stateURL),
              payload["pid"] as? Int == Int(ProcessInfo.processInfo.processIdentifier) else {
            return
        }
        try? FileManager.default.removeItem(at: stateURL)
    }

    private static func healthPayload(
        registry: ActiveProcessRegistry,
        startedAt: Date,
        source: String
    ) async -> [String: Any] {
        let snapshot = await registry.snapshot()
        let now = Date()
        let uptime = now.timeIntervalSince(startedAt)
        var payload: [String: Any] = [
            "schema_version": "xcode-mcp-server.health.v0.1",
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "pid": Int(ProcessInfo.processInfo.processIdentifier),
            "started_at": ISO8601DateFormatter().string(from: startedAt),
            "started_at_epoch": startedAt.timeIntervalSince1970,
            "state_updated_at": ISO8601DateFormatter().string(from: now),
            "state_updated_at_epoch": now.timeIntervalSince1970,
            "health_source": source,
            "uptime_seconds": max(0, uptime),
            "rss_bytes": currentResidentSizeBytes().map { $0 as Any } ?? NSNull(),
            "active_child_pid": snapshot.activeProcess.map { Int($0.pid) as Any } ?? NSNull(),
            "queued_tool_count": snapshot.queuedToolCount,
            "tool_running": snapshot.isToolRunning
        ]
        if let activeProcess = snapshot.activeProcess {
            payload["active_child_started_at"] = ISO8601DateFormatter().string(from: activeProcess.startedAt)
            payload["active_child_argv_summary"] = activeProcess.argvSummary
        }
        return payload
    }

    private static func publishedHealthPayload(stateURL: URL) -> [String: Any]? {
        guard let data = try? Data(contentsOf: stateURL),
              var payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pid = payload["pid"] as? Int,
              processIsAlive(pid_t(pid)),
              let updatedAtEpoch = payload["state_updated_at_epoch"] as? TimeInterval else {
            return nil
        }
        let stateAge = Date().timeIntervalSince1970 - updatedAtEpoch
        guard stateAge >= 0, stateAge <= staleStateSeconds else {
            return nil
        }
        payload["state_file"] = stateURL.path
        return payload
    }

    private static func defaultStateURL() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("xcode-mcp-server-\(geteuid()).health.json")
    }

    private static func currentResidentSizeBytes() -> UInt64? {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info_data_t>.size / MemoryLayout<natural_t>.size)
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { rebound in
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), rebound, &count)
            }
        }
        guard result == KERN_SUCCESS else {
            return nil
        }
        return UInt64(info.resident_size)
    }
}
