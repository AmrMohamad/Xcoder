import MCP

struct XcodeToolDefinition {
    let name: String
    let description: String
    let timeoutSeconds: Int
    let inputSchema: Value
    let annotations: Tool.Annotations
}

enum XcodeToolCatalog {
    static let helpTopics = [
        "first-time",
        "ide-vs-cli",
        "fail-recovery",
        "scheme-not-testable",
        "destination-ambiguous",
        "build-json",
        "package-release"
    ]

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
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_native_state",
            description: "Inspect Xcode process state through the plugin native helper.",
            timeoutSeconds: 8,
            inputSchema: objectSchema(),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_native_windows",
            description: "Inspect top-level Xcode Accessibility windows and modal blockers without UI mutation.",
            timeoutSeconds: 15,
            inputSchema: objectSchema(),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_ide_status",
            description: "Inspect whether Xcode.app is running, frontmost, and has open workspaces. Use before workspace-specific IDE calls when Codex needs GUI-first state. Examples: 1. {} to check process/workspace state. 2. Use this after xcode_native_state when deciding whether to ask the user to open Xcode.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_ide_workspace_info",
            description: "Inspect the active or requested Xcode workspace document through Xcode.app without mutating UI state. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\". 2. {} when exactly one workspace is open.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Optional path to an open .xcodeproj or .xcworkspace.")
                ]
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_ide_list_schemes",
            description: "List schemes from the active or requested Xcode workspace through Xcode.app. Examples: 1. workspace_path=\"/Users/me/App/App.xcworkspace\". 2. {} when one workspace is open and Codex needs exact scheme names.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Optional path to an open .xcodeproj or .xcworkspace.")
                ]
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_ide_list_destinations",
            description: "List Xcode run destinations for the active or requested workspace. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\". 2. {} before choosing a destination_id for xcode_ide_test.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Optional path to an open .xcodeproj or .xcworkspace.")
                ]
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_ide_preflight",
            description: "Check Xcode GUI readiness, workspace, scheme, destination, and native modal blockers before IDE automation. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\", scheme=\"App\". 2. workspace_path=\"/Users/me/App/App.xcworkspace\", scheme=\"AppTests\", destination_name=\"iPhone 16\".",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to an open .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Optional scheme name to verify."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier to verify."),
                    "destination_name": stringSchema(description: "Optional Xcode run destination name to verify."),
                    "require_native_preflight": boolSchema(description: "Fail if the native helper or AX preflight is unavailable.", defaultValue: false)
                ]
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_ide_build",
            description: "Build the active or requested Xcode scheme through Xcode.app IDE automation. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\", scheme=\"App\", destination_id=\"...\". 2. workspace_path=\"/Users/me/App/App.xcworkspace\", scheme=\"App\", destination_name=\"iPhone 16\".",
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
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_ide_test",
            description: "Run tests for an open Xcode workspace through Xcode.app. Use this after xcode_ide_preflight succeeds. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\", scheme=\"App\", destination_id=\"...\". 2. workspace_path=\"/Users/me/App/App.xcworkspace\", scheme=\"AppTests\", destination_name=\"iPhone 16\".",
            timeoutSeconds: 600,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Scheme to test."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier."),
                    "destination_name": stringSchema(description: "Optional Xcode destination name."),
                    "timeout_seconds": intSchema(description: "IDE test timeout in seconds.", defaultValue: 600)
                ],
                required: ["workspace_path", "scheme"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_ide_run",
            description: "Run the active or requested Xcode scheme through Xcode.app IDE automation. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\", scheme=\"App\", destination_id=\"...\". 2. workspace_path=\"/Users/me/App/App.xcworkspace\", scheme=\"App\", destination_name=\"iPhone 16\".",
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
            ),
            annotations: mutatingAnnotations
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
            ),
            annotations: mutatingAnnotations
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
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_results_summary",
            description: "Summarize an .xcresult bundle through bin/xcode results summarize. Examples: 1. path=\"/tmp/Test.xcresult\", kind=\"test-summary\". 2. path=\"/tmp/Build.xcresult\", kind=\"log\", log_type=\"build\".",
            timeoutSeconds: 60,
            inputSchema: objectSchema(
                properties: [
                    "path": stringSchema(description: "Path to an .xcresult bundle."),
                    "kind": enumStringSchema(description: "Summary kind.", values: ["test-summary", "build-results", "content-availability", "log"], defaultValue: "test-summary", examples: ["test-summary", "build-results"]),
                    "log_type": enumStringSchema(description: "Log type for kind=log.", values: ["build", "action", "console"], defaultValue: "build", examples: ["build"]),
                    "timeout_seconds": intSchema(description: "xcresulttool timeout in seconds.", defaultValue: 60)
                ],
                required: ["path"]
            ),
            annotations: readOnlyAnnotations
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
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_help",
            description: "Return static Xcoder guidance for common agent routing questions. Examples: 1. topic=\"ide-vs-cli\" to choose GUI-first versus CLI fallback. 2. topic=\"build-json\" when Codex needs machine-readable build behavior.",
            timeoutSeconds: 10,
            inputSchema: objectSchema(
                properties: [
                    "topic": enumStringSchema(description: "Help topic to return.", values: helpTopics, defaultValue: "ide-vs-cli", examples: ["ide-vs-cli", "build-json"])
                ]
            ),
            annotations: readOnlyAnnotations
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
                annotations: $0.annotations,
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
                    "timeout_seconds": $0.timeoutSeconds,
                    "annotations": annotationJSON($0.annotations)
                ]
            }
        ])
    }

    private static let readOnlyAnnotations = Tool.Annotations(
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false
    )

    private static let mutatingAnnotations = Tool.Annotations(
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false
    )

    private static func annotationJSON(_ annotations: Tool.Annotations) -> [String: Any] {
        [
            "readOnlyHint": annotations.readOnlyHint ?? false,
            "destructiveHint": annotations.destructiveHint ?? true,
            "idempotentHint": annotations.idempotentHint ?? false,
            "openWorldHint": annotations.openWorldHint ?? true
        ]
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

    private static func stringSchema(description: String? = nil, defaultValue: String? = nil, examples: [String] = []) -> Value {
        var object: [String: Value] = ["type": .string("string")]
        if let description {
            object["description"] = .string(description)
        }
        if let defaultValue {
            object["default"] = .string(defaultValue)
        }
        if !examples.isEmpty {
            object["examples"] = .array(examples.map { .string($0) })
        }
        return .object(object)
    }

    private static func enumStringSchema(
        description: String? = nil,
        values: [String],
        defaultValue: String? = nil,
        examples: [String] = []
    ) -> Value {
        var object: [String: Value] = [
            "type": .string("string"),
            "enum": .array(values.map { .string($0) })
        ]
        if let description {
            object["description"] = .string(description)
        }
        if let defaultValue {
            object["default"] = .string(defaultValue)
        }
        if !examples.isEmpty {
            object["examples"] = .array(examples.map { .string($0) })
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
