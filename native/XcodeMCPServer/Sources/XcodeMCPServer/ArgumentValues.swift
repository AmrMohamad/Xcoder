import Foundation
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

    static func appendOptionalStringOrJSON(_ value: Value?, flag: String, key: String, to argv: inout [String]) throws {
        guard let value else {
            return
        }
        if let raw = value.stringValue, !raw.isEmpty {
            argv.append(flag)
            argv.append(raw)
            return
        }
        let raw = try jsonString(value, key: key)
        argv.append(flag)
        argv.append(raw)
    }

    static func jsonString(_ value: Value, key: String) throws -> String {
        let object = try jsonObject(value, key: key)
        guard JSONSerialization.isValidJSONObject(object) else {
            throw XcodeToolError.usage("\(key) must be JSON-serializable")
        }
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    private static func jsonObject(_ value: Value, key: String) throws -> Any {
        switch value {
        case .null:
            return NSNull()
        case .bool(let raw):
            return raw
        case .int(let raw):
            return raw
        case .double(let raw):
            return raw
        case .string(let raw):
            return raw
        case .array(let values):
            return try values.map { try jsonObject($0, key: key) }
        case .object(let values):
            var object: [String: Any] = [:]
            for (childKey, childValue) in values {
                object[childKey] = try jsonObject(childValue, key: key)
            }
            return object
        case .data:
            throw XcodeToolError.usage("\(key) cannot contain binary data")
        }
    }
}
