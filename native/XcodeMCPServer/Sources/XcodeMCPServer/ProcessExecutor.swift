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

        return try await waitForProcessOrTimeout(
            process,
            stdoutPipe: stdoutPipe,
            stderrPipe: stderrPipe,
            timeoutSeconds: timeoutSeconds
        )
    }
}

private func waitForProcessOrTimeout(
    _ process: Process,
    stdoutPipe: Pipe,
    stderrPipe: Pipe,
    timeoutSeconds: Int
) async throws -> ProcessResult {
    try await withCheckedThrowingContinuation { continuation in
        let completion = ProcessCompletionGate()
        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .utility))

        process.terminationHandler = { _ in
            completion.runOnce {
                timer.cancel()
                let (stdout, stderr) = drainOutput(stdoutPipe: stdoutPipe, stderrPipe: stderrPipe)
                continuation.resume(returning: ProcessResult(exitCode: Int(process.terminationStatus), stdout: stdout, stderr: stderr))
            }
        }

        timer.schedule(deadline: .now() + .seconds(max(timeoutSeconds, 1)))
        timer.setEventHandler {
            completion.runOnce {
                terminateProcessTree(process)
                process.waitUntilExit()
                _ = drainOutput(stdoutPipe: stdoutPipe, stderrPipe: stderrPipe)
                continuation.resume(throwing: XcodeToolError.timeout)
            }
        }
        timer.resume()

        if !process.isRunning {
            completion.runOnce {
                timer.cancel()
                let (stdout, stderr) = drainOutput(stdoutPipe: stdoutPipe, stderrPipe: stderrPipe)
                continuation.resume(returning: ProcessResult(exitCode: Int(process.terminationStatus), stdout: stdout, stderr: stderr))
            }
        }
    }
}

private final class ProcessCompletionGate: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false

    func runOnce(_ body: @Sendable () -> Void) {
        lock.lock()
        if completed {
            lock.unlock()
            return
        }
        completed = true
        lock.unlock()
        body()
    }
}

private func drainOutput(stdoutPipe: Pipe, stderrPipe: Pipe) -> (String, String) {
    let stdout = String(data: stdoutPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    let stderr = String(data: stderrPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    return (stdout, stderr)
}

private func terminateProcessTree(_ process: Process) {
    let rootPID = process.processIdentifier
    let children = descendantProcessIDs(of: rootPID)

    for pid in children.reversed() where processIsAlive(pid) {
        kill(pid, SIGTERM)
    }
    if process.isRunning {
        process.terminate()
    }

    Thread.sleep(forTimeInterval: 1.0)

    for pid in children.reversed() where processIsAlive(pid) {
        kill(pid, SIGKILL)
    }
    if process.isRunning {
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

private func processIsAlive(_ pid: pid_t) -> Bool {
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
