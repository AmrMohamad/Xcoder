import Foundation
import Darwin

struct ProcessResult {
    let exitCode: Int
    let stdout: String
    let stderr: String
}

struct ProcessExecutor {
    let executableURL: URL
    let currentDirectoryURL: URL
    let registry: ActiveProcessRegistry

    init(executableURL: URL, currentDirectoryURL: URL, registry: ActiveProcessRegistry = .shared) {
        self.executableURL = executableURL
        self.currentDirectoryURL = currentDirectoryURL
        self.registry = registry
    }

    func run(arguments: [String], timeoutSeconds: Int) async throws -> ProcessResult {
        let clock = ContinuousClock()
        return try await run(
            arguments: arguments,
            deadline: clock.now.advanced(by: .seconds(timeoutSeconds))
        )
    }

    func run(
        arguments: [String],
        deadline: ContinuousClock.Instant,
        operationID: UUID = UUID()
    ) async throws -> ProcessResult {
        guard FileManager.default.isExecutableFile(atPath: executableURL.path) else {
            throw XcodeToolError.subprocess("bin/xcode is not executable at \(executableURL.path)")
        }
        guard ContinuousClock().now < deadline else {
            throw XcodeToolError.timeout(.processLaunch)
        }

        let process = Process()
        process.executableURL = executableURL
        process.arguments = arguments
        process.currentDirectoryURL = currentDirectoryURL
        process.environment = minimalEnvironment()

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        try process.run()
        let processID = process.processIdentifier
        await registry.register(processID: processID, arguments: arguments, operationID: operationID)

        do {
            let result = try await waitForProcessOrTimeout(
                process,
                stdoutPipe: stdoutPipe,
                stderrPipe: stderrPipe,
                deadline: deadline
            )
            await registry.unregister(processID: processID)
            return result
        } catch {
            await registry.unregister(processID: processID)
            throw error
        }
    }
}

private func waitForProcessOrTimeout(
    _ process: Process,
    stdoutPipe: Pipe,
    stderrPipe: Pipe,
    deadline: ContinuousClock.Instant
) async throws -> ProcessResult {
    let stdoutTask = drainOutput(stdoutPipe.fileHandleForReading)
    let stderrTask = drainOutput(stderrPipe.fileHandleForReading)
    let clock = ContinuousClock()

    do {
        return try await withTaskCancellationHandler {
            while process.isRunning {
                if clock.now >= deadline {
                    terminateProcessTree(process)
                    process.waitUntilExit()
                    try? stdoutPipe.fileHandleForReading.close()
                    try? stderrPipe.fileHandleForReading.close()
                    _ = await stdoutTask.value
                    _ = await stderrTask.value
                    throw XcodeToolError.timeout(.execution)
                }
                let nextPoll = min(deadline, clock.now.advanced(by: .milliseconds(50)))
                try await clock.sleep(until: nextPoll)
            }

            let stdout = await stdoutTask.value
            let stderr = await stderrTask.value
            return ProcessResult(exitCode: Int(process.terminationStatus), stdout: stdout, stderr: stderr)
        } onCancel: {
            terminateProcessTree(process)
            try? stdoutPipe.fileHandleForReading.close()
            try? stderrPipe.fileHandleForReading.close()
        }
    } catch {
        if process.isRunning {
            terminateProcessTree(process)
            process.waitUntilExit()
        }
        try? stdoutPipe.fileHandleForReading.close()
        try? stderrPipe.fileHandleForReading.close()
        _ = await stdoutTask.value
        _ = await stderrTask.value
        throw error
    }
}

private let maxCapturedOutputBytes = 8 * 1024 * 1024

private func drainOutput(_ fileHandle: FileHandle) -> Task<String, Never> {
    Task.detached(priority: .utility) {
        var data = Data()
        while true {
            let chunk = fileHandle.availableData
            if chunk.isEmpty {
                break
            }
            appendBounded(&data, chunk, limit: maxCapturedOutputBytes)
        }
        return String(data: data, encoding: .utf8) ?? ""
    }
}

private func appendBounded(_ data: inout Data, _ chunk: Data, limit: Int) {
    guard data.count < limit else {
        return
    }
    let remaining = limit - data.count
    if chunk.count <= remaining {
        data.append(chunk)
    } else {
        data.append(chunk.prefix(remaining))
    }
}

private func terminateProcessTree(_ process: Process) {
    terminateProcessTree(rootPID: process.processIdentifier)
}

func terminateProcessTree(rootPID: pid_t) {
    let children = descendantProcessIDs(of: rootPID)

    for pid in children.reversed() where processIsAlive(pid) {
        kill(pid, SIGTERM)
    }
    if processIsAlive(rootPID) {
        kill(rootPID, SIGTERM)
    }

    Thread.sleep(forTimeInterval: 1.0)

    for pid in children.reversed() where processIsAlive(pid) {
        kill(pid, SIGKILL)
    }
    if processIsAlive(rootPID) {
        kill(rootPID, SIGKILL)
    }
}

private func descendantProcessIDs(of pid: pid_t) -> [pid_t] {
    var result: [pid_t] = []
    for child in childProcessIDs(of: pid) {
        result.append(contentsOf: descendantProcessIDs(of: child))
        result.append(child)
    }
    return result
}

private func childProcessIDs(of pid: pid_t) -> [pid_t] {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
    process.arguments = ["-P", String(pid)]

    let stdoutPipe = Pipe()
    process.standardOutput = stdoutPipe
    process.standardError = Pipe()

    do {
        try process.run()
    } catch {
        return []
    }
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        return []
    }

    let output = String(data: stdoutPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    return output
        .split(whereSeparator: \.isWhitespace)
        .compactMap { pid_t($0) }
}

func processIsAlive(_ pid: pid_t) -> Bool {
    if kill(pid, 0) == 0 {
        return true
    }
    if errno == EPERM {
        return true
    }
    return false
}

private func minimalEnvironment() -> [String: String] {
    var environment: [String: String] = [:]
    for key in ["HOME", "PATH", "DEVELOPER_DIR", "TMPDIR", "SSH_AUTH_SOCK", "LANG", "LC_ALL"] {
        if let value = ProcessInfo.processInfo.environment[key] {
            environment[key] = value
        }
    }
    environment["PATH"] = environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
    return environment
}
