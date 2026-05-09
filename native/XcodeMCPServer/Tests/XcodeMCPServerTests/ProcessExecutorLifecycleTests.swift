import Darwin
import Foundation
import XCTest
@testable import XcodeMCPServer

final class ProcessExecutorLifecycleTests: XCTestCase {
    func testLargeStdoutAndStderrAreDrainedWhileProcessRuns() async throws {
        let registry = ActiveProcessRegistry()
        let executor = ProcessExecutor(
            executableURL: URL(fileURLWithPath: "/usr/bin/python3"),
            currentDirectoryURL: temporaryDirectory(),
            registry: registry
        )

        let code = "import sys; sys.stdout.write('o' * 200000); sys.stderr.write('e' * 200000)"
        let result = try await executor.run(arguments: ["-c", code], timeoutSeconds: 10)

        XCTAssertEqual(result.exitCode, 0)
        XCTAssertEqual(result.stdout.count, 200000)
        XCTAssertEqual(result.stderr.count, 200000)
        let snapshot = await registry.snapshot()
        XCTAssertNil(snapshot.activeProcess)
    }

    func testTimeoutKillsChildProcessTreeAndClearsRegistry() async throws {
        let registry = ActiveProcessRegistry()
        let directory = temporaryDirectory()
        let marker = directory.appendingPathComponent("child.pid")
        let executor = ProcessExecutor(
            executableURL: URL(fileURLWithPath: "/bin/sh"),
            currentDirectoryURL: directory,
            registry: registry
        )

        do {
            _ = try await executor.run(
                arguments: ["-c", "sleep 30 & echo $! > child.pid; wait"],
                timeoutSeconds: 1
            )
            XCTFail("Expected timeout")
        } catch XcodeToolError.timeout {
        }

        let pidText = try String(contentsOf: marker, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        let childPID = pid_t(pidText) ?? -1
        try await Task.sleep(nanoseconds: 1_000_000_000)

        XCTAssertGreaterThan(childPID, 0)
        XCTAssertNotEqual(kill(childPID, 0), 0)
        let snapshot = await registry.snapshot()
        XCTAssertNil(snapshot.activeProcess)
    }

    func testRegistryTracksActiveProcessDuringExecutionAndClearsAfterSuccess() async throws {
        let registry = ActiveProcessRegistry()
        let executor = ProcessExecutor(
            executableURL: URL(fileURLWithPath: "/bin/sh"),
            currentDirectoryURL: temporaryDirectory(),
            registry: registry
        )

        let task = Task {
            try await executor.run(arguments: ["-c", "sleep 1; echo done"], timeoutSeconds: 5)
        }
        let activeSnapshot = try await waitForActiveProcess(registry)
        XCTAssertNotNil(activeSnapshot.activeProcess)

        let result = try await task.value
        XCTAssertEqual(result.stdout.trimmingCharacters(in: .whitespacesAndNewlines), "done")
        let finalSnapshot = await registry.snapshot()
        XCTAssertNil(finalSnapshot.activeProcess)
    }

    func testRegistryTerminationKillsActiveProcessTree() async throws {
        let registry = ActiveProcessRegistry()
        let directory = temporaryDirectory()
        let marker = directory.appendingPathComponent("child.pid")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = ["-c", "sleep 30 & echo $! > child.pid; wait"]
        process.currentDirectoryURL = directory
        process.standardOutput = Pipe()
        process.standardError = Pipe()

        try process.run()
        await registry.register(processID: process.processIdentifier, arguments: ["doctor", "--json"])
        try await waitForFile(marker)

        let childPID = pid_t(try String(contentsOf: marker, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)) ?? -1
        await registry.terminateActiveProcessTree()
        try await Task.sleep(nanoseconds: 1_000_000_000)

        XCTAssertGreaterThan(childPID, 0)
        XCTAssertFalse(process.isRunning)
        XCTAssertNotEqual(kill(childPID, 0), 0)
        let snapshot = await registry.snapshot()
        XCTAssertNil(snapshot.activeProcess)
        XCTAssertFalse(snapshot.isToolRunning)
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

    private func waitForFile(_ url: URL) async throws {
        for _ in 0..<50 {
            if FileManager.default.fileExists(atPath: url.path) {
                return
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Timed out waiting for file \(url.path)")
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
