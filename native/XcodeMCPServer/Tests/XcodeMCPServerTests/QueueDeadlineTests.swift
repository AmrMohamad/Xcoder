import Foundation
import XCTest
@testable import XcodeMCPServer

final class QueueDeadlineTests: XCTestCase {
    func testQueuedRequestDeadlineIncludesQueueAndNeverLaunchesSecondProcess() async throws {
        let fixture = try makeFixture(sleepSeconds: 0.6)
        let registry = ActiveProcessRegistry()
        let bridge = XcodeBridge(
            paths: fixture.paths,
            registry: registry,
            requestBudgetOverride: .milliseconds(250),
            responseReserve: .milliseconds(20)
        )

        let first = Task { try await bridge.callTool(name: "xcode_doctor", arguments: nil) }
        try await waitForToolRunning(registry)
        let second = Task { try await bridge.callTool(name: "xcode_doctor", arguments: nil) }

        let secondResult = try await second.value
        XCTAssertTrue(secondResult.json.contains(#""timeout_stage":"queue""#))
        XCTAssertTrue(secondResult.json.contains(#""process_launched":false"#))
        _ = try await first.value
        try await waitForIdle(registry)

        XCTAssertEqual(try launchCount(fixture.marker), 1)
    }

    func testQueueBackpressureDoesNotAddAnotherWaiter() async throws {
        let fixture = try makeFixture(sleepSeconds: 0.5)
        let registry = ActiveProcessRegistry()
        let bridge = XcodeBridge(
            paths: fixture.paths,
            registry: registry,
            requestBudgetOverride: .seconds(2),
            responseReserve: .milliseconds(20),
            maximumQueuedOperations: 1
        )

        let first = Task { try await bridge.callTool(name: "xcode_doctor", arguments: nil) }
        try await waitForToolRunning(registry)
        let second = Task { try await bridge.callTool(name: "xcode_doctor", arguments: nil) }
        try await waitForQueuedCount(registry, expected: 1)
        let third = try await bridge.callTool(name: "xcode_doctor", arguments: nil)

        XCTAssertTrue(third.json.contains(#""error_type":"xcode_busy""#))
        XCTAssertTrue(third.json.contains(#""queued_tool_count":1"#))
        try await waitForQueuedCount(registry, expected: 1)
        _ = try await first.value
        _ = try await second.value
        try await waitForIdle(registry)
    }

    func testManyCancelledWaitersReturnQueueToEmpty() async throws {
        let fixture = try makeFixture(sleepSeconds: 0.6)
        let registry = ActiveProcessRegistry()
        let bridge = XcodeBridge(
            paths: fixture.paths,
            registry: registry,
            requestBudgetOverride: .seconds(2),
            responseReserve: .milliseconds(20),
            maximumQueuedOperations: 128
        )

        let first = Task { try await bridge.callTool(name: "xcode_doctor", arguments: nil) }
        try await waitForToolRunning(registry)
        let waiters = (0..<100).map { _ in
            Task { try await bridge.callTool(name: "xcode_doctor", arguments: nil) }
        }
        try await waitForQueuedCount(registry, expected: 100)
        waiters.forEach { $0.cancel() }
        for waiter in waiters {
            do {
                _ = try await waiter.value
                XCTFail("Expected cancellation")
            } catch is CancellationError {
            }
        }
        try await waitForQueuedCount(registry, expected: 0)
        _ = try await first.value
        try await waitForIdle(registry)
        XCTAssertEqual(try launchCount(fixture.marker), 1)
    }

    private func makeFixture(sleepSeconds: Double) throws -> (paths: PluginPaths, marker: URL) {
        let root = temporaryDirectory()
        let bin = root.appendingPathComponent("bin", isDirectory: true)
        try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
        let marker = root.appendingPathComponent("launches.txt")
        let executable = bin.appendingPathComponent("xcode")
        try """
        #!/bin/sh
        echo "$$" >> "\(marker.path)"
        sleep \(sleepSeconds)
        printf '{"schema_version":"xcode-plugin.v0.3","ok":true,"command_name":"doctor","summary":"ok"}\\n'
        """.write(to: executable, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
        return (
            PluginPaths(executablePath: bin.appendingPathComponent("xcode-mcp-server").path),
            marker
        )
    }

    private func launchCount(_ marker: URL) throws -> Int {
        guard FileManager.default.fileExists(atPath: marker.path) else {
            return 0
        }
        return try String(contentsOf: marker, encoding: .utf8)
            .split(whereSeparator: \.isNewline)
            .count
    }

    private func waitForToolRunning(_ registry: ActiveProcessRegistry) async throws {
        for _ in 0..<100 {
            if await registry.snapshot().isToolRunning {
                return
            }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Timed out waiting for active tool")
    }

    private func waitForQueuedCount(_ registry: ActiveProcessRegistry, expected: Int) async throws {
        for _ in 0..<200 {
            if await registry.snapshot().queuedToolCount == expected {
                return
            }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Timed out waiting for queue count \(expected)")
    }

    private func waitForIdle(_ registry: ActiveProcessRegistry) async throws {
        for _ in 0..<200 {
            let snapshot = await registry.snapshot()
            if !snapshot.isToolRunning && snapshot.queuedToolCount == 0 && snapshot.activeProcess == nil {
                return
            }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Timed out waiting for idle registry")
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
