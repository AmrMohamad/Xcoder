import MCP

struct XcodeToolDefinition {
    let name: String
    let description: String
    let timeoutSeconds: Int
    let inputSchema: Value
}

enum XcodeToolCatalog {
    static let all: [XcodeToolDefinition] = [
        .init(
            name: "xcode_doctor",
            description: "Validate local Xcode, plugin, native helper, and MCP server readiness through bin/xcode doctor.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "strict": boolSchema(description: "Treat optional IDE automation warnings as failures.", defaultValue: false),
                    "checks": arraySchema(description: "Optional named doctor checks to focus on when supported by the CLI.", items: stringSchema())
                ]
            )
        ),
        .init(
            name: "xcode_native_state",
            description: "Inspect Xcode process state through the plugin native helper.",
            timeoutSeconds: 8,
            inputSchema: objectSchema()
        ),
        .init(
            name: "xcode_native_windows",
            description: "Inspect top-level Xcode Accessibility windows and modal blockers without UI mutation.",
            timeoutSeconds: 15,
            inputSchema: objectSchema()
        ),
        .init(
            name: "xcode_ide_preflight",
            description: "Check Xcode GUI readiness, workspace, scheme, destination, and native modal blockers before IDE automation.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to an open .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Optional scheme name to verify."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier to verify."),
                    "destination_name": stringSchema(description: "Optional Xcode run destination name to verify."),
                    "require_native_preflight": boolSchema(description: "Fail if the native helper or AX preflight is unavailable.", defaultValue: false)
                ]
            )
        ),
        .init(
            name: "xcode_ide_build",
            description: "Build the active or requested Xcode scheme through Xcode.app IDE automation.",
            timeoutSeconds: 600,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Scheme to build."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier."),
                    "destination_name": stringSchema(description: "Optional Xcode destination name."),
                    "timeout_seconds": intSchema(description: "IDE build timeout in seconds.", defaultValue: 600)
                ],
                required: ["workspace_path", "scheme"]
            )
        ),
        .init(
            name: "xcode_ide_run",
            description: "Run the active or requested Xcode scheme through Xcode.app IDE automation.",
            timeoutSeconds: 180,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Scheme to run."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier."),
                    "destination_name": stringSchema(description: "Optional Xcode destination name."),
                    "timeout_seconds": intSchema(description: "IDE run timeout in seconds.", defaultValue: 180)
                ],
                required: ["workspace_path", "scheme"]
            )
        ),
        .init(
            name: "xcode_run_app",
            description: "High-level GUI-first build and run workflow for an iOS app through bin/xcode workflow run-app.",
            timeoutSeconds: 900,
            inputSchema: objectSchema(
                properties: [
                    "project_path": stringSchema(description: "Path to .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Scheme to build and run."),
                    "simulator_name": stringSchema(description: "Simulator name to resolve when destination_id is not provided.", defaultValue: "iPhone SE (3rd generation)"),
                    "runtime": stringSchema(description: "Optional runtime like iOS 18.5."),
                    "destination_id": stringSchema(description: "Optional simulator UDID; preferred when known."),
                    "configuration": stringSchema(description: "Build configuration.", defaultValue: "Debug"),
                    "allow_cli_fallback": boolSchema(description: "Allow plugin-routed CLI fallback when GUI path fails.", defaultValue: true),
                    "timeout_seconds": intSchema(description: "End-to-end workflow timeout in seconds.", defaultValue: 900)
                ],
                required: ["project_path", "scheme"]
            )
        ),
        .init(
            name: "xcode_simulator_resolve",
            description: "Resolve a simulator name/runtime to exactly one UDID through bin/xcode simulator resolve.",
            timeoutSeconds: 15,
            inputSchema: objectSchema(
                properties: [
                    "name": stringSchema(description: "Simulator device name."),
                    "runtime": stringSchema(description: "Optional runtime like iOS 18.5."),
                    "fixture": stringSchema(description: "Optional fixture JSON for deterministic validation.")
                ],
                required: ["name"]
            )
        ),
        .init(
            name: "xcode_results_summary",
            description: "Summarize an .xcresult bundle through bin/xcode results summarize.",
            timeoutSeconds: 60,
            inputSchema: objectSchema(
                properties: [
                    "path": stringSchema(description: "Path to an .xcresult bundle."),
                    "kind": stringSchema(description: "Summary kind: test-summary, build-results, content-availability, or log.", defaultValue: "test-summary"),
                    "log_type": stringSchema(description: "Log type for kind=log: build, action, or console.", defaultValue: "build"),
                    "timeout_seconds": intSchema(description: "xcresulttool timeout in seconds.", defaultValue: 60)
                ],
                required: ["path"]
            )
        ),
        .init(
            name: "xcode_warnings_summary",
            description: "Summarize xcodebuild warning/error logs through bin/xcode warnings summarize.",
            timeoutSeconds: 60,
            inputSchema: objectSchema(
                properties: [
                    "log": stringSchema(description: "Path to an xcodebuild log file."),
                    "fail_on_new": boolSchema(description: "Reserved baseline-diff flag.", defaultValue: false)
                ],
                required: ["log"]
            )
        )
    ]

    static let byName: [String: XcodeToolDefinition] = Dictionary(uniqueKeysWithValues: all.map { ($0.name, $0) })

    static var mcpTools: [Tool] {
        all.map {
            Tool(
                name: $0.name,
                title: nil,
                description: $0.description,
                inputSchema: $0.inputSchema,
                annotations: nil,
                outputSchema: nil,
                icons: nil
            )
        }
    }

    static func listToolsJSON() -> String {
        JSONEnvelope.compactJSONString([
            "schema_version": XcodeMCPConstants.mcpServerSchemaVersion,
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "tools": all.map {
                [
                    "name": $0.name,
                    "description": $0.description,
                    "timeout_seconds": $0.timeoutSeconds
                ]
            }
        ])
    }

    private static func objectSchema(properties: [String: Value] = [:], required: [String] = []) -> Value {
        var object: [String: Value] = [
            "type": .string("object"),
            "additionalProperties": .bool(false),
            "properties": .object(properties)
        ]
        if !required.isEmpty {
            object["required"] = .array(required.map { .string($0) })
        }
        return .object(object)
    }

    private static func stringSchema(description: String? = nil, defaultValue: String? = nil) -> Value {
        var object: [String: Value] = ["type": .string("string")]
        if let description {
            object["description"] = .string(description)
        }
        if let defaultValue {
            object["default"] = .string(defaultValue)
        }
        return .object(object)
    }

    private static func boolSchema(description: String? = nil, defaultValue: Bool? = nil) -> Value {
        var object: [String: Value] = ["type": .string("boolean")]
        if let description {
            object["description"] = .string(description)
        }
        if let defaultValue {
            object["default"] = .bool(defaultValue)
        }
        return .object(object)
    }

    private static func intSchema(description: String? = nil, defaultValue: Int? = nil) -> Value {
        var object: [String: Value] = ["type": .string("integer")]
        if let description {
            object["description"] = .string(description)
        }
        if let defaultValue {
            object["default"] = .int(defaultValue)
        }
        return .object(object)
    }

    private static func arraySchema(description: String? = nil, items: Value) -> Value {
        var object: [String: Value] = [
            "type": .string("array"),
            "items": items
        ]
        if let description {
            object["description"] = .string(description)
        }
        return .object(object)
    }
}
