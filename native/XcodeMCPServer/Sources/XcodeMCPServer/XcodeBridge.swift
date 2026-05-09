import Foundation
import MCP

struct XcodeBridgeResult {
    let json: String
    let isError: Bool
}

actor XcodeBridge {
    private let processExecutor: ProcessExecutor
    private let registry: ActiveProcessRegistry
    private var isToolRunning = false
    private var executionWaiters: [ExecutionWaiter] = []

    init(paths: PluginPaths = PluginPaths(), registry: ActiveProcessRegistry = .shared) {
        self.registry = registry
        self.processExecutor = ProcessExecutor(
            executableURL: paths.xcodeCLI,
            currentDirectoryURL: paths.pluginRoot,
            registry: registry
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
        try await acquireExecutionSlot()

        let result: ProcessResult
        do {
            try Task.checkCancellation()
            result = try await processExecutor.run(arguments: argv, timeoutSeconds: tool.timeoutSeconds)
        } catch XcodeToolError.timeout {
            await releaseExecutionSlot()
            return timeoutResult(for: tool, argv: argv)
        } catch {
            await releaseExecutionSlot()
            throw error
        }
        await releaseExecutionSlot()

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

    private func timeoutResult(for tool: XcodeToolDefinition, argv: [String]) -> XcodeBridgeResult {
        let summary: String
        let nextActions: [String]
        if tool.name == "xcode_ide_run" {
            summary = "Xcode IDE run did not finish before the MCP-safe timeout. Attached IDE run can stay busy while Xcode launches or attaches to the app, so the MCP server returned this envelope before Codex's protocol timeout."
            nextActions = [
                "Inspect Xcode and Simulator state before retrying.",
                "Use bin/xcode workflow run-app --json for full build/install/launch runs that can exceed the MCP call budget.",
                "Do not increase xcode_ide_run timeout_seconds above the advertised cap; the MCP route will cap it."
            ]
        } else {
            summary = "bin/xcode did not finish before the MCP tool timeout. The MCP server stopped the active subprocess and returned this envelope before the client protocol timeout."
            nextActions = [
                "Inspect bin/xcode mcp health --json for server health.",
                "Retry if recovery metadata marks the failure transient.",
                "Use the equivalent bin/xcode CLI path when the operation is expected to exceed the MCP call budget."
            ]
        }
        return XcodeBridgeResult(json: JSONEnvelope.failure(
            errorType: "command_timeout",
            summary: summary,
            details: [
                "tool_name": tool.name,
                "mcp_tool_timeout_seconds": tool.timeoutSeconds,
                "argv": argv,
                "argv_summary": argv.joined(separator: " ")
            ],
            nextActions: nextActions
        ), isError: false)
    }

    private func acquireExecutionSlot() async throws {
        try Task.checkCancellation()
        if !isToolRunning {
            isToolRunning = true
            await registry.markToolRunning(true)
            return
        }

        let waiterID = UUID()
        await registry.incrementQueuedToolCount()
        do {
            try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { continuation in
                    executionWaiters.append(ExecutionWaiter(id: waiterID, continuation: continuation))
                }
            } onCancel: {
                Task {
                    await self.cancelExecutionWaiter(id: waiterID)
                }
            }
        } catch {
            await registry.decrementQueuedToolCount()
            throw error
        }
        await registry.decrementQueuedToolCount()
    }

    private func releaseExecutionSlot() async {
        if executionWaiters.isEmpty {
            isToolRunning = false
            await registry.markToolRunning(false)
            return
        }

        let next = executionWaiters.removeFirst()
        next.continuation.resume()
    }

    private func cancelExecutionWaiter(id: UUID) async {
        guard let index = executionWaiters.firstIndex(where: { $0.id == id }) else {
            return
        }
        let waiter = executionWaiters.remove(at: index)
        waiter.continuation.resume(throwing: CancellationError())
    }
}

private struct ExecutionWaiter {
    let id: UUID
    let continuation: CheckedContinuation<Void, Error>
}
