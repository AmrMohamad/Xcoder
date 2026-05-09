import Foundation

struct ActiveProcessSnapshot {
    let pid: Int32
    let argvSummary: [String]
    let startedAt: Date
}

struct ProcessRegistrySnapshot {
    let activeProcess: ActiveProcessSnapshot?
    let isToolRunning: Bool
    let queuedToolCount: Int
}

actor ActiveProcessRegistry {
    static let shared = ActiveProcessRegistry()

    private var activeProcess: ActiveProcessSnapshot?
    private var toolRunning = false
    private var queuedTools = 0

    func markToolRunning(_ running: Bool) {
        toolRunning = running
    }

    func incrementQueuedToolCount() {
        queuedTools += 1
    }

    func decrementQueuedToolCount() {
        queuedTools = max(queuedTools - 1, 0)
    }

    func register(processID: Int32, arguments: [String]) {
        activeProcess = ActiveProcessSnapshot(
            pid: processID,
            argvSummary: Array(arguments.prefix(8)),
            startedAt: Date()
        )
    }

    func unregister(processID: Int32) {
        if activeProcess?.pid == processID {
            activeProcess = nil
        }
    }

    func terminateActiveProcessTree() {
        guard let processID = activeProcess?.pid else {
            return
        }
        terminateProcessTree(rootPID: processID)
        activeProcess = nil
        toolRunning = false
    }

    func snapshot() -> ProcessRegistrySnapshot {
        ProcessRegistrySnapshot(
            activeProcess: activeProcess,
            isToolRunning: toolRunning,
            queuedToolCount: queuedTools
        )
    }
}
