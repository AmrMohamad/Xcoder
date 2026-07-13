import Foundation

struct ActiveCommandSummary: Sendable, Equatable {
    let commandGroup: String
    let subcommand: String?
    let optionNames: [String]
    let argumentCount: Int

    private static let allowedSubcommands: [String: Set<String>] = [
        "native": ["app", "permissions", "helper", "ax"],
        "ide": [
            "status", "workspace-info", "list-schemes", "list-destinations", "menu-catalog",
            "menu-perform", "organizer-open", "organizer-inspect", "organizer-press",
            "organizer-distribution-inspect", "organizer-distribution-select",
            "organizer-distribution-confirm", "organizer-distribution-step-inspect",
            "organizer-distribution-probe-method", "organizer-distribution-custom-select",
            "organizer-distribution-probe-custom-route", "preflight", "scheme-action"
        ],
        "workflow": ["run-app"],
        "distribution": ["archive", "export-archive", "upload-archive", "distribute"],
        "simulator": ["resolve"],
        "results": ["summarize"],
        "warnings": ["summarize"]
    ]
    private static let standaloneGroups: Set<String> = ["doctor", "help"]

    static func valueFree(arguments: [String]) -> ActiveCommandSummary? {
        guard !arguments.isEmpty else {
            return nil
        }

        var positional: [String] = []
        var optionNames: [String] = []
        var reachedOptions = false

        for argument in arguments {
            if argument.hasPrefix("--") {
                reachedOptions = true
                let optionName = String(argument.prefix { $0 != "=" })
                if isSafeName(optionName), !optionNames.contains(optionName) {
                    optionNames.append(optionName)
                }
                continue
            }
            if argument.hasPrefix("-") {
                reachedOptions = true
                if isSafeName(argument), !optionNames.contains(argument) {
                    optionNames.append(argument)
                }
                continue
            }
            guard !reachedOptions, positional.count < 2, isSafeName(argument) else {
                continue
            }
            positional.append(argument)
        }

        guard let commandGroup = positional.first,
              allowedSubcommands[commandGroup] != nil || standaloneGroups.contains(commandGroup) else {
            return nil
        }
        let candidateSubcommand = positional.count > 1 ? positional[1] : nil
        let subcommand = candidateSubcommand.flatMap { candidate in
            allowedSubcommands[commandGroup]?.contains(candidate) == true ? candidate : nil
        }
        return ActiveCommandSummary(
            commandGroup: commandGroup,
            subcommand: subcommand,
            optionNames: optionNames,
            argumentCount: arguments.count
        )
    }

    private static func isSafeName(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 64, !value.contains("/"), !value.contains("\\"), !value.contains("=") else {
            return false
        }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || "-_.".unicodeScalars.contains($0)
        }
    }
}

struct ActiveProcessSnapshot: Sendable {
    let pid: Int32
    let operationID: UUID
    let command: ActiveCommandSummary?
    let startedAt: Date
}

struct ProcessRegistrySnapshot: Sendable {
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

    func register(processID: Int32, arguments: [String], operationID: UUID = UUID()) {
        activeProcess = ActiveProcessSnapshot(
            pid: processID,
            operationID: operationID,
            command: ActiveCommandSummary.valueFree(arguments: arguments),
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
