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

    static func failure(errorType: String, summary: String, details: [String: Any]? = nil, nextActions: [String] = []) -> String {
        let recovery = RecoveryCatalog.metadata(for: errorType)
        var enrichedDetails = details ?? [:]
        for (key, value) in recovery.dictionary where enrichedDetails[key] == nil {
            enrichedDetails[key] = value
        }
        var payload: [String: Any] = [
            "schema_version": XcodeMCPConstants.pluginEnvelopeSchemaVersion,
            "ok": false,
            "status": "failure",
            "error_type": errorType,
            "command_name": "mcp",
            "summary": summary,
            "artifacts": [:],
            "warnings": [],
            "errors": [
                [
                    "error_type": errorType,
                    "message": summary,
                    "recovery": recovery.recovery,
                    "transient": recovery.transient,
                    "retry_after_seconds": recovery.retryAfterSeconds.map { $0 as Any } ?? NSNull()
                ]
            ],
            "next_actions": nextActions
        ]
        payload["details"] = enrichedDetails
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

    static func compactRedactedText(_ text: String, limit: Int = 1200) -> String {
        compactText(redactedText(text), limit: limit)
    }

    static func redactedArguments(_ arguments: [String]) -> [String] {
        var result: [String] = []
        var redactNext = false

        for argument in arguments {
            if redactNext {
                result.append("<redacted>")
                redactNext = false
                continue
            }

            if let redactedInline = redactedInlineFlag(argument) {
                result.append(redactedInline)
                continue
            }

            result.append(redactedText(argument))
            if sensitiveArgumentFlags.contains(argument) {
                redactNext = true
            }
        }

        return result
    }

    static func redactedText(_ text: String) -> String {
        var redacted = text
        let replacements: [(pattern: String, template: String)] = [
            (#"(?i)("[^"]*(?:api_key_path|api_key_id|issuer_id|apiKey|apiIssuer|credentials_ref)[^"]*"\s*:\s*")([^"]*)(")"#, "$1<redacted>$3"),
            (#"(?i)(--(?:api-key-path|api-key-id|issuer-id|credentials-ref|apiKey|apiIssuer|api_key_path|api_key_id|issuer_id)(?:=|\s+))([^\s"']+)"#, "$1<redacted>"),
            (#"[^\s"']*AuthKey_[^\s"']*\.p8"#, "<redacted>")
        ]
        for replacement in replacements {
            redacted = replace(pattern: replacement.pattern, in: redacted, with: replacement.template)
        }
        return redacted
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

    private static let sensitiveArgumentFlags: Set<String> = [
        "--api-key-path",
        "--api-key-id",
        "--issuer-id",
        "--credentials-ref",
        "--apiKey",
        "--apiIssuer",
        "--api_key_path",
        "--api_key_id",
        "--issuer_id"
    ]

    private static func redactedInlineFlag(_ argument: String) -> String? {
        for flag in sensitiveArgumentFlags {
            let prefix = "\(flag)="
            if argument.hasPrefix(prefix) {
                return "\(prefix)<redacted>"
            }
        }
        return nil
    }

    private static func replace(pattern: String, in text: String, with template: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return text
        }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        return regex.stringByReplacingMatches(in: text, options: [], range: range, withTemplate: template)
    }
}
