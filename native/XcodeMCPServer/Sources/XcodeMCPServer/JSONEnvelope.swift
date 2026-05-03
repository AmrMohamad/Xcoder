import Foundation

enum JSONEnvelope {
    static func versionJSON() -> String {
        compactJSONString([
            "schema_version": XcodeMCPConstants.mcpServerSchemaVersion,
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "plugin_envelope_schema_version": XcodeMCPConstants.pluginEnvelopeSchemaVersion,
            "sdk": XcodeMCPConstants.sdkName,
            "sdk_version": XcodeMCPConstants.sdkVersion,
            "minimum_macos_version": XcodeMCPConstants.minimumMacOSVersion
        ])
    }

    static func failure(errorType: String, summary: String, details: [String: Any]? = nil) -> String {
        var payload: [String: Any] = [
            "schema_version": XcodeMCPConstants.pluginEnvelopeSchemaVersion,
            "ok": false,
            "status": "failure",
            "error_type": errorType,
            "command_name": "mcp",
            "summary": summary,
            "artifacts": [:],
            "warnings": [],
            "errors": [],
            "next_actions": []
        ]
        if let details {
            payload["details"] = details
        }
        return compactJSONString(payload)
    }

    static func compactValidatedJSON(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let data = trimmed.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              JSONSerialization.isValidJSONObject(object),
              let output = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let string = String(data: output, encoding: .utf8)
        else {
            return nil
        }
        return string
    }

    static func compactText(_ text: String, limit: Int = 1200) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.count <= limit {
            return trimmed
        }
        return String(trimmed.prefix(limit)) + "...<truncated>"
    }

    static func compactJSONString(_ object: Any) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let string = String(data: data, encoding: .utf8)
        else {
            return "{}"
        }
        return string
    }
}
