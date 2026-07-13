enum XcodeToolError: Error {
    case usage(String)
    case timeout(RequestTimeoutStage)
    case busy(Int)
    case subprocess(String)

    var envelopeJSON: String {
        switch self {
        case .usage(let summary):
            return JSONEnvelope.failure(errorType: "usage_error", summary: summary)
        case .timeout(let stage):
            return JSONEnvelope.failure(
                errorType: "command_timeout",
                summary: "MCP request deadline expired during \(stage.rawValue)",
                details: ["timeout_stage": stage.rawValue]
            )
        case .busy(let queued):
            return JSONEnvelope.failure(
                errorType: "xcode_busy",
                summary: "Xcode MCP execution queue is full",
                details: ["queued_tool_count": queued, "retry_after_seconds": 2]
            )
        case .subprocess(let summary):
            return JSONEnvelope.failure(errorType: "subprocess_failed", summary: summary)
        }
    }
}
