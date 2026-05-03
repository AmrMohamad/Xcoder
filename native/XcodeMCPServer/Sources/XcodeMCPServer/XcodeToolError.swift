enum XcodeToolError: Error {
    case usage(String)
    case timeout
    case subprocess(String)

    var envelopeJSON: String {
        switch self {
        case .usage(let summary):
            return JSONEnvelope.failure(errorType: "usage_error", summary: summary)
        case .timeout:
            return JSONEnvelope.failure(errorType: "command_timeout", summary: "MCP wrapper timed out waiting for bin/xcode")
        case .subprocess(let summary):
            return JSONEnvelope.failure(errorType: "subprocess_failed", summary: summary)
        }
    }
}
