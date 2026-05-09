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
        guard FileManager.default.isExecutableFile(atPath: executableURL.path) else {
            throw XcodeToolError.subprocess("bin/xcode is not executable at \(executableURL.path)")
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
        await registry.register(processID: processID, arguments: arguments)

        do {
            let result = try await waitForProcessOrTimeout(
                process,
                stdoutPipe: stdoutPipe,
                stderrPipe: stderrPipe,
                timeoutSeconds: timeoutSeconds
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
    timeoutSeconds: Int
) async throws -> ProcessResult {
    let stdoutTask = drainOutput(stdoutPipe.fileHandleForReading)
    let stderrTask = drainOutput(stderrPipe.fileHandleForReading)
    let timeoutNanoseconds = UInt64(max(timeoutSeconds, 1)) * 1_000_000_000
    let startedAt = DispatchTime.now().uptimeNanoseconds

    return try await withTaskCancellationHandler {
        while process.isRunning {
            if DispatchTime.now().uptimeNanoseconds - startedAt >= timeoutNanoseconds {
                terminateProcessTree(process)
                process.waitUntilExit()
                _ = await stdoutTask.value
                _ = await stderrTask.value
                throw XcodeToolError.timeout
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }

        let stdout = await stdoutTask.value
        let stderr = await stderrTask.value
        return ProcessResult(exitCode: Int(process.terminationStatus), stdout: stdout, stderr: stderr)
    } onCancel: {
        terminateProcessTree(process)
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
