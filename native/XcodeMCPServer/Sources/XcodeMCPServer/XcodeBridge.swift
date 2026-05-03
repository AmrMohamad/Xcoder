import MCP

struct XcodeBridgeResult {
    let json: String
    let isError: Bool
}

actor XcodeBridge {
    private let processExecutor: ProcessExecutor
    private var isToolRunning = false
    private var executionWaiters: [CheckedContinuation<Void, Never>] = []

    init(paths: PluginPaths = PluginPaths()) {
        self.processExecutor = ProcessExecutor(
            executableURL: paths.xcodeCLI,
            currentDirectoryURL: paths.pluginRoot
        )
    }

    func callTool(name: String, arguments: [String: Value]?) async throws -> XcodeBridgeResult {
        guard let tool = XcodeToolCatalog.byName[name] else {
            throw XcodeToolError.usage("Unknown Xcode MCP tool: \(name)")
        }

        let args = arguments ?? [:]
        if let forbidden = ArgumentValues.findForbiddenKey(in: .object(args)) {
            throw XcodeToolError.usage("Rejected free-form execution input key: \(forbidden)")
        }

        let argv = try XcodeToolArguments.argv(for: name, arguments: args)
        await acquireExecutionSlot()
        defer {
            releaseExecutionSlot()
        }

        let result = try await processExecutor.run(arguments: argv, timeoutSeconds: tool.timeoutSeconds)

        guard result.exitCode == 0 else {
            if let stdoutJSON = JSONEnvelope.compactValidatedJSON(result.stdout) {
                return XcodeBridgeResult(json: stdoutJSON, isError: true)
            }
            return XcodeBridgeResult(json: JSONEnvelope.failure(
                errorType: "subprocess_failed",
                summary: "bin/xcode returned exit code \(result.exitCode)",
                details: [
                    "exit_code": result.exitCode,
                    "stderr": JSONEnvelope.compactText(result.stderr),
                    "stdout": JSONEnvelope.compactText(result.stdout)
                ]
            ), isError: true)
        }

        guard let json = JSONEnvelope.compactValidatedJSON(result.stdout) else {
            return XcodeBridgeResult(json: JSONEnvelope.failure(
                errorType: "subprocess_failed",
                summary: "bin/xcode did not return valid JSON",
                details: [
                    "stderr": JSONEnvelope.compactText(result.stderr),
                    "stdout": JSONEnvelope.compactText(result.stdout)
                ]
            ), isError: true)
        }
        return XcodeBridgeResult(json: json, isError: false)
    }

    private func acquireExecutionSlot() async {
        if !isToolRunning {
            isToolRunning = true
            return
        }

        await withCheckedContinuation { continuation in
            executionWaiters.append(continuation)
        }
    }

    private func releaseExecutionSlot() {
        if executionWaiters.isEmpty {
            isToolRunning = false
            return
        }

        let next = executionWaiters.removeFirst()
        next.resume()
    }
}
