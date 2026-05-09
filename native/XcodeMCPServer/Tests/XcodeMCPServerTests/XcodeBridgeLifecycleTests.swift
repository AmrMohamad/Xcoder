import Foundation
import XCTest
@testable import XcodeMCPServer

final class XcodeBridgeLifecycleTests: XCTestCase {
    func testQueuedCallCancellationDoesNotLeakQueueOrLaunchCancelledTool() async throws {
        let root = temporaryDirectory()
        let bin = root.appendingPathComponent("bin", isDirectory: true)
        try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
        let marker = root.appendingPathComponent("launches.txt")
        try writeExecutable(
            at: bin.appendingPathComponent("xcode"),
            contents: """
            #!/bin/sh
            echo "$$" >> "\(marker.path)"
            sleep 1
            printf '{"schema_version":"xcode-plugin.v0.3","ok":true,"command":"doctor","summary":"ok"}\\n'
            """
        )

        let registry = ActiveProcessRegistry()
        let bridge = XcodeBridge(
            paths: PluginPaths(executablePath: bin.appendingPathComponent("xcode-mcp-server").path),
            registry: registry
        )

        let first = Task {
            try await bridge.callTool(name: "xcode_doctor", arguments: nil)
        }
        _ = try await waitForToolRunning(registry)

        let queued = Task {
            try await bridge.callTool(name: "xcode_doctor", arguments: nil)
        }
        try await waitForQueuedToolCount(registry, expected: 1)
        queued.cancel()
        do {
            _ = try await queued.value
            XCTFail("Expected queued call cancellation")
        } catch is CancellationError {
        }
        try await waitForQueuedToolCount(registry, expected: 0)

        let result = try await first.value
        XCTAssertFalse(result.isError)
        try await waitForToolIdle(registry)
        try await Task.sleep(nanoseconds: 300_000_000)

        let launches = try String(contentsOf: marker, encoding: .utf8)
            .split(whereSeparator: \.isNewline)
        XCTAssertEqual(launches.count, 1)
    }

    private func waitForToolRunning(_ registry: ActiveProcessRegistry) async throws -> ProcessRegistrySnapshot {
        for _ in 0..<50 {
            let snapshot = await registry.snapshot()
            if snapshot.isToolRunning {
                return snapshot
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Timed out waiting for tool to run")
        return await registry.snapshot()
    }

    private func waitForToolIdle(_ registry: ActiveProcessRegistry) async throws {
        for _ in 0..<50 {
            let snapshot = await registry.snapshot()
            if !snapshot.isToolRunning {
                return
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Timed out waiting for tool to become idle")
    }

    private func waitForQueuedToolCount(_ registry: ActiveProcessRegistry, expected: Int) async throws {
        for _ in 0..<50 {
            let snapshot = await registry.snapshot()
            if snapshot.queuedToolCount == expected {
                return
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Timed out waiting for queued tool count \(expected)")
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func writeExecutable(at url: URL, contents: String) throws {
        try contents.write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
    }
}
