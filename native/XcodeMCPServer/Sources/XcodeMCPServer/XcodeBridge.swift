import Foundation
import MCP

struct XcodeBridgeResult {
    let json: String
    let isError: Bool
}

private enum WaiterCompletion: Sendable {
    case acquired
    case cancelled
    case deadlineExceeded
}

private struct ExecutionWaiter {
    let id: UUID
    let continuation: CheckedContinuation<WaiterCompletion, Never>
}

private struct WaiterQueue {
    private var storage: [ExecutionWaiter?] = []
    private var head = 0
    private(set) var count = 0

    mutating func append(_ waiter: ExecutionWaiter) {
        storage.append(waiter)
        count += 1
    }

    mutating func popFirst() -> ExecutionWaiter? {
        while head < storage.count {
            defer {
                head += 1
                compactIfNeeded()
            }
            guard let waiter = storage[head] else {
                continue
            }
            storage[head] = nil
            count -= 1
            return waiter
        }
        compactIfNeeded(force: true)
        return nil
    }

    mutating func remove(id: UUID) -> ExecutionWaiter? {
        guard head < storage.count else {
            return nil
        }
        for index in head..<storage.count {
            guard storage[index]?.id == id else {
                continue
            }
            let waiter = storage[index]
            storage[index] = nil
            count -= 1
            compactIfNeeded()
            return waiter
        }
        return nil
    }

    private mutating func compactIfNeeded(force: Bool = false) {
        guard force || (head > 32 && head * 2 >= storage.count) else {
            return
        }
        storage.removeFirst(head)
        head = 0
    }
}

actor XcodeBridge {
    private let processExecutor: ProcessExecutor
    private let registry: ActiveProcessRegistry
    private let requestBudgetOverride: Duration?
    private let responseReserve: Duration
    private let maximumQueuedOperations: Int
    private var isToolRunning = false
    private var executionWaiters = WaiterQueue()

    init(
        paths: PluginPaths = PluginPaths(),
        registry: ActiveProcessRegistry = .shared,
        requestBudgetOverride: Duration? = nil,
        responseReserve: Duration = .seconds(XcodeMCPTimeouts.responseReserveSeconds),
        maximumQueuedOperations: Int = XcodeMCPTimeouts.maximumQueuedOperations
    ) {
        self.registry = registry
        self.requestBudgetOverride = requestBudgetOverride
        self.responseReserve = responseReserve
        self.maximumQueuedOperations = maximumQueuedOperations
        self.processExecutor = ProcessExecutor(
            executableURL: paths.xcodeCLI,
            currentDirectoryURL: paths.pluginRoot,
            registry: registry
        )
    }

    func callTool(name: String, arguments: [String: Value]?) async throws -> XcodeBridgeResult {
        let clock = ContinuousClock()
        let receivedAt = clock.now
        let receivedAtDate = Date()

        guard let tool = XcodeToolCatalog.byName[name] else {
            throw XcodeToolError.usage("Unknown Xcode MCP tool: \(name)")
        }
        let timeout = requestBudgetOverride ?? .seconds(min(tool.timeoutSeconds, XcodeMCPTimeouts.protocolSafeToolSeconds))
        let budget = RequestBudget(
            receivedAt: receivedAt,
            timeout: timeout,
            responseReserve: responseReserve
        )

        let args = arguments ?? [:]
        if let forbidden = ArgumentValues.findForbiddenKey(in: .object(args)) {
            throw XcodeToolError.usage("Rejected free-form execution input key: \(forbidden)")
        }
        let argv = try XcodeToolArguments.argv(for: name, arguments: args)
        guard budget.hasWorkTimeRemaining(clock: clock) else {
            return timeoutResult(
                for: tool,
                argv: argv,
                stage: .argumentValidation,
                budget: budget,
                receivedAtDate: receivedAtDate,
                queueStartedAt: clock.now,
                queueFinishedAt: clock.now,
                executionStartedAt: nil,
                processLaunched: false
            )
        }

        let queueStartedAt = clock.now
        do {
            try await acquireExecutionSlot(until: budget.workDeadline())
        } catch XcodeToolError.busy(let queued) {
            return busyResult(
                tool: tool,
                queued: queued,
                budget: budget,
                receivedAtDate: receivedAtDate,
                queueStartedAt: queueStartedAt
            )
        } catch XcodeToolError.timeout {
            return timeoutResult(
                for: tool,
                argv: argv,
                stage: .queue,
                budget: budget,
                receivedAtDate: receivedAtDate,
                queueStartedAt: queueStartedAt,
                queueFinishedAt: clock.now,
                executionStartedAt: nil,
                processLaunched: false
            )
        }
        let queueFinishedAt = clock.now

        guard budget.hasWorkTimeRemaining(clock: clock) else {
            await releaseExecutionSlot()
            return timeoutResult(
                for: tool,
                argv: argv,
                stage: .queue,
                budget: budget,
                receivedAtDate: receivedAtDate,
                queueStartedAt: queueStartedAt,
                queueFinishedAt: queueFinishedAt,
                executionStartedAt: nil,
                processLaunched: false
            )
        }

        let executionStartedAt = clock.now
        let result: ProcessResult
        do {
            try Task.checkCancellation()
            result = try await processExecutor.run(
                arguments: argv,
                deadline: budget.workDeadline()
            )
        } catch XcodeToolError.timeout(let stage) {
            await releaseExecutionSlot()
            return timeoutResult(
                for: tool,
                argv: argv,
                stage: stage,
                budget: budget,
                receivedAtDate: receivedAtDate,
                queueStartedAt: queueStartedAt,
                queueFinishedAt: queueFinishedAt,
                executionStartedAt: executionStartedAt,
                processLaunched: true
            )
        } catch {
            await releaseExecutionSlot()
            throw error
        }
        await releaseExecutionSlot()
        let executionFinishedAt = clock.now

        let baseJSON: String
        let isError: Bool
        if result.exitCode != 0 {
            isError = true
            if let stdoutJSON = JSONEnvelope.compactValidatedJSON(result.stdout) {
                baseJSON = stdoutJSON
            } else {
                baseJSON = JSONEnvelope.failure(
                    errorType: "subprocess_failed",
                    summary: "bin/xcode returned exit code \(result.exitCode)",
                    details: [
                        "exit_code": result.exitCode,
                        "stderr": JSONEnvelope.compactRedactedText(result.stderr),
                        "stdout": JSONEnvelope.compactRedactedText(result.stdout)
                    ]
                )
            }
        } else if let json = JSONEnvelope.compactValidatedJSON(result.stdout) {
            baseJSON = json
            isError = false
        } else {
            baseJSON = JSONEnvelope.failure(
                errorType: "subprocess_failed",
                summary: "bin/xcode did not return valid JSON",
                details: [
                    "stderr": JSONEnvelope.compactRedactedText(result.stderr),
                    "stdout": JSONEnvelope.compactRedactedText(result.stdout)
                ]
            )
            isError = true
        }

        let responseStartedAt = clock.now
        guard responseStartedAt < budget.deadline else {
            return timeoutResult(
                for: tool,
                argv: argv,
                stage: .responseEncoding,
                budget: budget,
                receivedAtDate: receivedAtDate,
                queueStartedAt: queueStartedAt,
                queueFinishedAt: queueFinishedAt,
                executionStartedAt: executionStartedAt,
                processLaunched: true
            )
        }
        return XcodeBridgeResult(
            json: addingTiming(
                to: baseJSON,
                receivedAtDate: receivedAtDate,
                requestBudget: budget,
                queueStartedAt: queueStartedAt,
                queueFinishedAt: queueFinishedAt,
                executionStartedAt: executionStartedAt,
                executionFinishedAt: executionFinishedAt,
                responseStartedAt: responseStartedAt,
                responseFinishedAt: clock.now
            ),
            isError: isError
        )
    }

    private func timeoutResult(
        for tool: XcodeToolDefinition,
        argv: [String],
        stage: RequestTimeoutStage,
        budget: RequestBudget,
        receivedAtDate: Date,
        queueStartedAt: ContinuousClock.Instant,
        queueFinishedAt: ContinuousClock.Instant,
        executionStartedAt: ContinuousClock.Instant?,
        processLaunched: Bool
    ) -> XcodeBridgeResult {
        let redactedArgv = JSONEnvelope.redactedArguments(argv)
        let now = ContinuousClock().now
        let queueSeconds = queueStartedAt.duration(to: queueFinishedAt).secondsDouble
        let executionSeconds = executionStartedAt.map { max(0, $0.duration(to: now).secondsDouble) } ?? 0
        let requestSeconds = budget.receivedAt.duration(to: budget.deadline).secondsDouble
        let json = JSONEnvelope.failure(
            errorType: "command_timeout",
            summary: "Xcode MCP request exceeded its absolute deadline during \(stage.rawValue).",
            details: [
                "tool_name": tool.name,
                "timeout_stage": stage.rawValue,
                "request_budget_seconds": requestSeconds,
                "queue_seconds": max(0, queueSeconds),
                "execution_seconds": executionSeconds,
                "process_launched": processLaunched,
                "argv": redactedArgv,
                "argv_summary": redactedArgv.joined(separator: " ")
            ],
            nextActions: [
                "Inspect bin/xcode mcp health --json for server health.",
                "Retry if recovery metadata marks the failure transient.",
                "Use the equivalent bin/xcode CLI path for work that cannot complete inside the synchronous MCP budget."
            ]
        )
        return XcodeBridgeResult(
            json: addingTiming(
                to: json,
                receivedAtDate: receivedAtDate,
                requestBudget: budget,
                queueStartedAt: queueStartedAt,
                queueFinishedAt: queueFinishedAt,
                executionStartedAt: executionStartedAt,
                executionFinishedAt: now,
                responseStartedAt: now,
                responseFinishedAt: now
            ),
            isError: false
        )
    }

    private func busyResult(
        tool: XcodeToolDefinition,
        queued: Int,
        budget: RequestBudget,
        receivedAtDate: Date,
        queueStartedAt: ContinuousClock.Instant
    ) -> XcodeBridgeResult {
        let now = ContinuousClock().now
        let json = JSONEnvelope.failure(
            errorType: "xcode_busy",
            summary: "Xcode MCP execution queue is full.",
            details: [
                "tool_name": tool.name,
                "queued_tool_count": queued,
                "retry_after_seconds": 2
            ]
        )
        return XcodeBridgeResult(
            json: addingTiming(
                to: json,
                receivedAtDate: receivedAtDate,
                requestBudget: budget,
                queueStartedAt: queueStartedAt,
                queueFinishedAt: now,
                executionStartedAt: nil,
                executionFinishedAt: now,
                responseStartedAt: now,
                responseFinishedAt: now
            ),
            isError: false
        )
    }

    private func addingTiming(
        to json: String,
        receivedAtDate: Date,
        requestBudget: RequestBudget,
        queueStartedAt: ContinuousClock.Instant,
        queueFinishedAt: ContinuousClock.Instant,
        executionStartedAt: ContinuousClock.Instant?,
        executionFinishedAt: ContinuousClock.Instant,
        responseStartedAt: ContinuousClock.Instant,
        responseFinishedAt: ContinuousClock.Instant
    ) -> String {
        guard let data = json.data(using: .utf8),
              var payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return json
        }
        payload["timing"] = [
            "received_at": ISO8601DateFormatter().string(from: receivedAtDate),
            "request_budget_seconds": requestBudget.receivedAt.duration(to: requestBudget.deadline).secondsDouble,
            "queue_seconds": max(0, queueStartedAt.duration(to: queueFinishedAt).secondsDouble),
            "execution_seconds": executionStartedAt.map {
                max(0, $0.duration(to: executionFinishedAt).secondsDouble)
            } ?? 0,
            "response_seconds": max(0, responseStartedAt.duration(to: responseFinishedAt).secondsDouble),
            "total_seconds": max(0, requestBudget.receivedAt.duration(to: responseFinishedAt).secondsDouble)
        ]
        return JSONEnvelope.compactJSONString(payload)
    }

    private func acquireExecutionSlot(until deadline: ContinuousClock.Instant) async throws {
        try Task.checkCancellation()
        if !isToolRunning {
            isToolRunning = true
            await registry.markToolRunning(true)
            if Task.isCancelled {
                await releaseExecutionSlot()
                throw CancellationError()
            }
            return
        }
        guard executionWaiters.count < maximumQueuedOperations else {
            throw XcodeToolError.busy(executionWaiters.count)
        }
        guard ContinuousClock().now < deadline else {
            throw XcodeToolError.timeout(.queue)
        }

        let waiterID = UUID()
        await registry.incrementQueuedToolCount()
        var deadlineTask: Task<Void, Never>?
        let completion: WaiterCompletion
        do {
            completion = try await withTaskCancellationHandler {
                try Task.checkCancellation()
                return await withCheckedContinuation { continuation in
                    executionWaiters.append(ExecutionWaiter(id: waiterID, continuation: continuation))
                    deadlineTask = Task {
                        do {
                            try await ContinuousClock().sleep(until: deadline)
                        } catch {
                            return
                        }
                        await self.finishWaiter(id: waiterID, completion: .deadlineExceeded)
                    }
                }
            } onCancel: {
                Task {
                    await self.finishWaiter(id: waiterID, completion: .cancelled)
                }
            }
        } catch {
            await registry.decrementQueuedToolCount()
            throw error
        }
        deadlineTask?.cancel()

        switch completion {
        case .acquired:
            if Task.isCancelled {
                await releaseExecutionSlot()
                throw CancellationError()
            }
        case .cancelled:
            throw CancellationError()
        case .deadlineExceeded:
            throw XcodeToolError.timeout(.queue)
        }
    }

    private func releaseExecutionSlot() async {
        guard let next = executionWaiters.popFirst() else {
            isToolRunning = false
            await registry.markToolRunning(false)
            return
        }
        await completeWaiter(next, completion: .acquired)
    }

    private func finishWaiter(id: UUID, completion: WaiterCompletion) async {
        guard let waiter = executionWaiters.remove(id: id) else {
            return
        }
        await completeWaiter(waiter, completion: completion)
    }

    private func completeWaiter(_ waiter: ExecutionWaiter, completion: WaiterCompletion) async {
        await registry.decrementQueuedToolCount()
        waiter.continuation.resume(returning: completion)
    }
}
