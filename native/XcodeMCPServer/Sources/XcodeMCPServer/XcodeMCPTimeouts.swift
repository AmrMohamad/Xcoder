enum XcodeMCPTimeouts {
    // The default Codex MCP timeout is 60s. Preserve response time inside it.
    static let protocolSafeToolSeconds = 50
    static let responseReserveSeconds = 2
    static let maximumQueuedOperations = 8

    // The attached IDE run path adds Python/JXA padding around this action
    // timeout, so its inner poll budget must stay lower than the tool budget.
    static let ideRunActionSeconds = 45
    static let ideRunToolSeconds = protocolSafeToolSeconds
}
