import Foundation
import Darwin

enum ServerHealth {
    static let processStartedAt = Date()
    static let instanceID = UUID().uuidString
    static let publishIntervalNanoseconds: UInt64 = 1_000_000_000
    private static let staleStateSeconds: TimeInterval = 10

    static func healthJSON(
        registry: ActiveProcessRegistry = .shared,
        startedAt: Date = processStartedAt,
        source: String = "in_process"
    ) async -> String {
        JSONEnvelope.compactJSONString(await healthPayload(registry: registry, startedAt: startedAt, source: source))
    }

    static func publishedOrProbeHealthJSON(stateURL: URL? = nil) async -> String {
        if let stateURL {
            if let payload = observedPayload(stateURL: stateURL) {
                return JSONEnvelope.compactJSONString(payload)
            }
            var payload = await healthPayload(registry: .shared, startedAt: processStartedAt, source: "self_probe")
            payload["observed_running_server"] = false
            return JSONEnvelope.compactJSONString(payload)
        }

        return aggregateHealthJSON(directoryURL: defaultStateDirectory())
    }

    static func aggregateHealthJSON(directoryURL: URL) -> String {
        let servers = publishedHealthPayloads(directoryURL: directoryURL)
        return JSONEnvelope.compactJSONString([
            "schema_version": XcodeMCPConstants.healthAggregateSchemaVersion,
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "server_count": servers.count,
            "servers": servers,
            "observed_running_server": !servers.isEmpty
        ])
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
        try? secureAtomicWrite(data, to: stateURL)
    }

    static func clearPublishedHealth(stateURL: URL = defaultStateURL()) {
        guard let payload = publishedHealthPayload(stateURL: stateURL),
              payload["pid"] as? Int == Int(ProcessInfo.processInfo.processIdentifier),
              payload["instance_id"] as? String == instanceID else {
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
            "schema_version": XcodeMCPConstants.healthSchemaVersion,
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "pid": Int(ProcessInfo.processInfo.processIdentifier),
            "instance_id": instanceID,
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
            payload["active_operation_id"] = activeProcess.operationID.uuidString
            if let command = activeProcess.command {
                var commandPayload: [String: Any] = [
                    "group": command.commandGroup,
                    "option_names": command.optionNames,
                    "argument_count": command.argumentCount
                ]
                commandPayload["subcommand"] = command.subcommand ?? NSNull()
                payload["active_command"] = commandPayload
            }
        }
        return payload
    }

    private static func publishedHealthPayload(stateURL: URL) -> [String: Any]? {
        guard isSecureStateFile(stateURL),
              let data = try? Data(contentsOf: stateURL),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              payload["schema_version"] as? String == XcodeMCPConstants.healthSchemaVersion,
              let pid = payload["pid"] as? Int,
              processIsAlive(pid_t(pid)),
              let instance = payload["instance_id"] as? String,
              !instance.isEmpty,
              let updatedAtEpoch = payload["state_updated_at_epoch"] as? TimeInterval else {
            return nil
        }
        let stateAge = Date().timeIntervalSince1970 - updatedAtEpoch
        guard stateAge >= 0, stateAge <= staleStateSeconds else {
            return nil
        }
        return payload
    }

    static func defaultStateDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("xcoder", isDirectory: true)
            .appendingPathComponent("mcp-health", isDirectory: true)
            .appendingPathComponent(String(geteuid()), isDirectory: true)
    }

    static func defaultStateURL() -> URL {
        defaultStateDirectory().appendingPathComponent(
            "\(ProcessInfo.processInfo.processIdentifier)-\(instanceID).json"
        )
    }

    private static func observedPayload(stateURL: URL) -> [String: Any]? {
        guard var payload = publishedHealthPayload(stateURL: stateURL) else {
            return nil
        }
        let observedAt = Date()
        if let startedAtEpoch = payload["started_at_epoch"] as? TimeInterval {
            payload["uptime_seconds"] = max(0, observedAt.timeIntervalSince1970 - startedAtEpoch)
        }
        if let updatedAtEpoch = payload["state_updated_at_epoch"] as? TimeInterval {
            payload["state_age_seconds"] = max(0, observedAt.timeIntervalSince1970 - updatedAtEpoch)
        }
        payload["health_source"] = "published_running_server"
        payload["observed_running_server"] = true
        return payload
    }

    private static func publishedHealthPayloads(directoryURL: URL) -> [[String: Any]] {
        guard isSecureDirectory(directoryURL),
              let stateURLs = try? FileManager.default.contentsOfDirectory(
                at: directoryURL,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
              ) else {
            return []
        }
        return stateURLs
            .filter { $0.pathExtension == "json" }
            .compactMap(observedPayload(stateURL:))
            .sorted { ($0["pid"] as? Int ?? 0) < ($1["pid"] as? Int ?? 0) }
    }

    private static func secureAtomicWrite(_ data: Data, to stateURL: URL) throws {
        let directoryURL = stateURL.deletingLastPathComponent()
        try ensureSecureDirectory(directoryURL)
        let temporaryURL = directoryURL.appendingPathComponent(".\(UUID().uuidString).tmp")
        let descriptor = Darwin.open(
            temporaryURL.path,
            O_WRONLY | O_CREAT | O_EXCL,
            mode_t(S_IRUSR | S_IWUSR)
        )
        guard descriptor >= 0 else {
            throw CocoaError(.fileWriteUnknown)
        }
        var shouldRemoveTemporaryFile = true
        defer {
            if shouldRemoveTemporaryFile {
                Darwin.unlink(temporaryURL.path)
            }
        }

        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        try handle.write(contentsOf: data)
        try handle.synchronize()
        try handle.close()
        guard Darwin.rename(temporaryURL.path, stateURL.path) == 0 else {
            throw CocoaError(.fileWriteUnknown)
        }
        shouldRemoveTemporaryFile = false
    }

    private static func ensureSecureDirectory(_ directoryURL: URL) throws {
        var partialURL = URL(fileURLWithPath: "/", isDirectory: true)
        for component in directoryURL.pathComponents.dropFirst() {
            partialURL.appendPathComponent(component, isDirectory: true)
            if Darwin.mkdir(partialURL.path, mode_t(S_IRWXU)) != 0, errno != EEXIST {
                throw CocoaError(.fileWriteNoPermission)
            }
        }
        guard isOwnedDirectory(directoryURL),
              Darwin.chmod(directoryURL.path, mode_t(S_IRWXU)) == 0,
              isSecureDirectory(directoryURL) else {
            throw CocoaError(.fileWriteNoPermission)
        }
    }

    private static func isOwnedDirectory(_ directoryURL: URL) -> Bool {
        var metadata = stat()
        guard lstat(directoryURL.path, &metadata) == 0 else {
            return false
        }
        return (metadata.st_mode & S_IFMT) == S_IFDIR && metadata.st_uid == geteuid()
    }

    private static func isSecureDirectory(_ directoryURL: URL) -> Bool {
        var metadata = stat()
        guard lstat(directoryURL.path, &metadata) == 0 else {
            return false
        }
        return (metadata.st_mode & S_IFMT) == S_IFDIR
            && metadata.st_uid == geteuid()
            && (metadata.st_mode & mode_t(0o777)) == mode_t(0o700)
    }

    private static func isSecureStateFile(_ stateURL: URL) -> Bool {
        var metadata = stat()
        guard lstat(stateURL.path, &metadata) == 0 else {
            return false
        }
        return (metadata.st_mode & S_IFMT) == S_IFREG
            && metadata.st_uid == geteuid()
            && (metadata.st_mode & mode_t(0o777)) == mode_t(0o600)
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
