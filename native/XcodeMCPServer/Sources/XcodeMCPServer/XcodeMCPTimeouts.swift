enum XcodeMCPTimeouts {
    // Codex currently cuts off MCP tool calls at 120s. Keep every MCP
    // subprocess below that so timeout explanations return as plugin envelopes.
    static let protocolSafeToolSeconds = 116

    // The attached IDE run path adds Python/JXA padding around this action
    // timeout, so its inner poll budget must stay lower than the tool budget.
    static let ideRunActionSeconds = 95
    static let ideRunToolSeconds = protocolSafeToolSeconds
}
