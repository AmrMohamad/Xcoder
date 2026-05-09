import Foundation
import XCTest
@testable import XcodeMCPServer

final class ServerHealthTests: XCTestCase {
    func testHealthJSONReportsIdleState() async throws {
        let registry = ActiveProcessRegistry()
        let payload = try decode(await ServerHealth.healthJSON(registry: registry, startedAt: Date()))

        XCTAssertEqual(payload["schema_version"] as? String, "xcode-mcp-server.health.v0.1")
        XCTAssertEqual(payload["server"] as? String, XcodeMCPConstants.serverName)
        XCTAssertEqual(payload["version"] as? String, XcodeMCPConstants.serverVersion)
        XCTAssertEqual(payload["tool_running"] as? Bool, false)
        XCTAssertEqual(payload["queued_tool_count"] as? Int, 0)
        XCTAssertTrue(payload["active_child_pid"] is NSNull)
        XCTAssertNotNil(payload["pid"] as? Int)
    }

    func testHealthJSONReportsActiveChildState() async throws {
        let registry = ActiveProcessRegistry()
        let executor = ProcessExecutor(
            executableURL: URL(fileURLWithPath: "/bin/sh"),
            currentDirectoryURL: temporaryDirectory(),
            registry: registry
        )

        let task = Task {
            try await executor.run(arguments: ["-c", "sleep 1"], timeoutSeconds: 5)
        }
        _ = try await waitForActiveProcess(registry)

        let payload = try decode(await ServerHealth.healthJSON(registry: registry, startedAt: Date()))
        XCTAssertNotNil(payload["active_child_pid"] as? Int)
        XCTAssertNotNil(payload["active_child_started_at"] as? String)
        XCTAssertNotNil(payload["active_child_argv_summary"] as? [String])

        _ = try await task.value
    }

    func testPublishedHealthReportsRunningServerState() async throws {
        let registry = ActiveProcessRegistry()
        let stateURL = temporaryDirectory().appendingPathComponent("health.json")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = ["-c", "sleep 5"]
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        try process.run()
        defer {
            if process.isRunning {
                process.terminate()
            }
        }

        await registry.markToolRunning(true)
        await registry.register(processID: process.processIdentifier, arguments: ["doctor", "--json"])
        await ServerHealth.publishRuntimeHealth(registry: registry, startedAt: Date().addingTimeInterval(-2), stateURL: stateURL)

        let payload = try decode(await ServerHealth.publishedOrProbeHealthJSON(stateURL: stateURL))
        XCTAssertEqual(payload["health_source"] as? String, "published_running_server")
        XCTAssertEqual(payload["observed_running_server"] as? Bool, true)
        XCTAssertEqual(payload["active_child_pid"] as? Int, Int(process.processIdentifier))
        XCTAssertEqual(payload["tool_running"] as? Bool, true)
        XCTAssertNotNil(payload["state_age_seconds"] as? Double)
    }

    func testPublishedHealthFallsBackWhenStateIsStale() async throws {
        let stateURL = temporaryDirectory().appendingPathComponent("health.json")
        let stalePayload: [String: Any] = [
            "schema_version": "xcode-mcp-server.health.v0.1",
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "pid": Int(ProcessInfo.processInfo.processIdentifier),
            "state_updated_at_epoch": Date().addingTimeInterval(-60).timeIntervalSince1970
        ]
        let data = try JSONSerialization.data(withJSONObject: stalePayload)
        try data.write(to: stateURL)

        let payload = try decode(await ServerHealth.publishedOrProbeHealthJSON(stateURL: stateURL))
        XCTAssertEqual(payload["health_source"] as? String, "self_probe")
        XCTAssertEqual(payload["observed_running_server"] as? Bool, false)
    }

    private func decode(_ json: String) throws -> [String: Any] {
        let data = try XCTUnwrap(json.data(using: .utf8))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func waitForActiveProcess(_ registry: ActiveProcessRegistry) async throws -> ProcessRegistrySnapshot {
        for _ in 0..<50 {
            let snapshot = await registry.snapshot()
            if snapshot.activeProcess != nil {
                return snapshot
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Timed out waiting for active process")
        return await registry.snapshot()
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
