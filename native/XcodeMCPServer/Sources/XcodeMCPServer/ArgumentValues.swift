import MCP

enum ArgumentValues {
    static func findForbiddenKey(in value: Value) -> String? {
        switch value {
        case .object(let object):
            for (key, child) in object {
                if XcodeMCPConstants.forbiddenArgumentKeys.contains(key.lowercased()) {
                    return key
                }
                if let nested = findForbiddenKey(in: child) {
                    return nested
                }
            }
        case .array(let array):
            for child in array {
                if let nested = findForbiddenKey(in: child) {
                    return nested
                }
            }
        default:
            break
        }
        return nil
    }

    static func requiredString(_ value: Value?, key: String) throws -> String {
        guard let raw = value?.stringValue, !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw XcodeToolError.usage("Missing required argument: \(key)")
        }
        return raw
    }

    static func string(_ value: Value?, default defaultValue: String) -> String {
        guard let raw = value?.stringValue, !raw.isEmpty else {
            return defaultValue
        }
        return raw
    }

    static func int(_ value: Value?, default defaultValue: Int) -> Int {
        value?.intValue ?? defaultValue
    }

    static func bool(_ value: Value?, default defaultValue: Bool) -> Bool {
        value?.boolValue ?? defaultValue
    }

    static func stringArray(_ value: Value?) -> [String]? {
        guard case .array(let values) = value else {
            return nil
        }
        return values.compactMap(\.stringValue).filter { !$0.isEmpty }
    }

    static func appendOptionalString(_ value: Value?, flag: String, to argv: inout [String]) {
        guard let raw = value?.stringValue, !raw.isEmpty else {
            return
        }
        argv.append(flag)
        argv.append(raw)
    }
}
