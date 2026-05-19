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
        "distribution",
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
            name: "xcode_native_permissions_status",
            description: "Check whether the plugin native helper is currently trusted for macOS Accessibility without showing a prompt.",
            timeoutSeconds: 8,
            inputSchema: objectSchema(),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_native_helper_identity",
            description: "Inspect the native helper code-signing identity and whether it is packaged as a TCC-stable app bundle.",
            timeoutSeconds: 8,
            inputSchema: objectSchema(),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_native_helper_bundle",
            description: "Package and sign the native helper as XcodeNativeHelper.app so macOS Accessibility/TCC can bind trust durably.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(),
            annotations: permissionPromptAnnotations
        ),
        .init(
            name: "xcode_native_permissions_request",
            description: "Ask macOS to show the Accessibility permission prompt for the plugin native helper, then return the current trust state. User approval is still required in System Settings.",
            timeoutSeconds: 15,
            inputSchema: objectSchema(),
            annotations: permissionPromptAnnotations
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
            name: "xcode_ide_menu_catalog",
            description: "List the typed Xcode menu action catalog, including stable action ids, shortcuts, safety classes, implementation status, and preferred typed tools where menu pressing is intentionally not used.",
            timeoutSeconds: 10,
            inputSchema: objectSchema(),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_ide_menu_perform",
            description: "Perform one cataloged Xcode menu action by stable action_id. This never accepts raw menu paths or arbitrary AX selectors. Destructive actions require allow_destructive=true.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "action_id": stringSchema(description: "Stable action id from xcode_ide_menu_catalog, such as view.navigator.project or view.debug_area.activate_console."),
                    "allow_destructive": boolSchema(description: "Required for destructive catalog actions such as close, clear, delete, or stop.", defaultValue: false)
                ],
                required: ["action_id"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_organizer_open",
            description: "Open Xcode Organizer through the trusted GUI path using Xcode's Window > Organizer menu item.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_organizer_inspect",
            description: "Inspect the Xcode Organizer GUI through the trusted native Accessibility helper before pressing distribution controls.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer"),
                    "max_depth": intSchema(description: "AX tree depth to inspect.", defaultValue: 4)
                ]
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_organizer_press",
            description: "Press a visible enabled Xcode Organizer button through the trusted GUI path, such as Distribute App.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "button_title": enumStringSchema(description: "Visible Organizer button title to press.", values: ["Distribute App", "Validate App", "Export App", "Done", "Next", "Continue", "Upload", "Cancel"], examples: ["Distribute App"]),
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer")
                ],
                required: ["button_title"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_organizer_distribution_inspect",
            description: "Inspect the Organizer distribution-method sheet as structured data, including the available routes and navigation buttons.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer")
                ]
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_organizer_distribution_select_method",
            description: "Select one distribution method on the Organizer distribution-method sheet through the trusted GUI path.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "method": enumStringSchema(description: "Distribution method to select on the Organizer sheet.", values: ["App Store Connect", "TestFlight Internal Only", "Release Testing", "Enterprise", "Debugging", "Custom"], examples: ["App Store Connect"]),
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer")
                ],
                required: ["method"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_organizer_distribution_confirm",
            description: "Confirm the currently selected distribution method and advance past the Organizer distribution-method phase only when the sheet state is verified.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "expected_method": enumStringSchema(description: "Optional selected method that must match before pressing Distribute.", values: ["App Store Connect", "TestFlight Internal Only", "Release Testing", "Enterprise", "Debugging", "Custom"], examples: ["App Store Connect"]),
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer")
                ]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_organizer_distribution_step_inspect",
            description: "Inspect the current Organizer distribution wizard phase and report visible fields, progress text, navigation, and guarded final actions without pressing anything.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer")
                ]
            ),
            annotations: readOnlyAnnotations
        ),
        .init(
            name: "xcode_organizer_distribution_probe_method",
            description: "Safely enter one Organizer distribution method route, inspect its next screen, and cancel out by default before any final upload/export action.",
            timeoutSeconds: 45,
            inputSchema: objectSchema(
                properties: [
                    "method": enumStringSchema(description: "Distribution method route to probe.", values: ["App Store Connect", "TestFlight Internal Only", "Release Testing", "Enterprise", "Debugging", "Custom"], examples: ["TestFlight Internal Only"]),
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer"),
                    "cancel_after_inspect": boolSchema(description: "Cancel the distribution wizard after inspecting the next route screen.", defaultValue: true),
                    "settle_seconds": intSchema(description: "Seconds to wait after advancing before inspection.", defaultValue: 1),
                    "wait_ready_seconds": intSchema(description: "Additional seconds to poll until the route screen exposes an enabled Next or guarded final action.", defaultValue: 15),
                    "max_safe_steps": intSchema(description: "Maximum number of safe non-final Next advances before the probe stops.", defaultValue: 4),
                    "option_overrides": freeFormObjectSchema(description: "Optional stable option ids to apply during the probe, such as custom_destination, strip_swift_symbols, or include_manifest.")
                ],
                required: ["method"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_organizer_distribution_select_custom_route",
            description: "Select one nested route on the Organizer Custom distribution sheet through the trusted GUI path.",
            timeoutSeconds: 30,
            inputSchema: objectSchema(
                properties: [
                    "route": enumStringSchema(description: "Custom distribution route to select.", values: ["App Store Connect", "Release Testing", "Enterprise", "Debugging"], examples: ["Release Testing"]),
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer")
                ],
                required: ["route"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_organizer_distribution_probe_custom_route",
            description: "Safely enter Custom distribution, choose one nested route, inspect its next screen, and cancel out by default before any final upload/export action.",
            timeoutSeconds: 45,
            inputSchema: objectSchema(
                properties: [
                    "route": enumStringSchema(description: "Custom distribution route to probe.", values: ["App Store Connect", "Release Testing", "Enterprise", "Debugging"], examples: ["Debugging"]),
                    "window_title_contains": stringSchema(description: "Organizer window title filter.", defaultValue: "Organizer"),
                    "cancel_after_inspect": boolSchema(description: "Cancel the distribution wizard after inspecting the custom route screen.", defaultValue: true),
                    "settle_seconds": intSchema(description: "Seconds to wait after advancing before inspection.", defaultValue: 1),
                    "wait_ready_seconds": intSchema(description: "Additional seconds to poll until the custom route screen exposes an enabled Next or guarded final action.", defaultValue: 15),
                    "max_safe_steps": intSchema(description: "Maximum number of safe non-final Next advances before the probe stops.", defaultValue: 4),
                    "option_overrides": freeFormObjectSchema(description: "Optional stable option ids to apply during the probe, such as custom_destination, strip_swift_symbols, or include_manifest.")
                ],
                required: ["route"]
            ),
            annotations: mutatingAnnotations
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
            description: "Build the active or requested Xcode scheme through Xcode.app IDE automation. The MCP wrapper returns before Codex's protocol timeout if the build is still running; use bin/xcode for longer build validations. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\", scheme=\"App\", destination_id=\"...\". 2. workspace_path=\"/Users/me/App/App.xcworkspace\", scheme=\"App\", destination_name=\"iPhone 16\".",
            timeoutSeconds: XcodeMCPTimeouts.protocolSafeToolSeconds,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Scheme to build."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier."),
                    "destination_name": stringSchema(description: "Optional Xcode destination name."),
                    "require_native_preflight": boolSchema(description: "Fail if native AX window/modal inspection is unavailable. Defaults to false so missing Accessibility permission warns instead of blocking the IDE action.", defaultValue: false),
                    "timeout_seconds": intSchema(description: "IDE build timeout in seconds.", defaultValue: 600)
                ],
                required: ["workspace_path", "scheme"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_ide_test",
            description: "Run tests for an open Xcode workspace through Xcode.app. The MCP wrapper returns before Codex's protocol timeout if tests are still running; use bin/xcode for longer test validations. Use this after xcode_ide_preflight succeeds. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\", scheme=\"App\", destination_id=\"...\". 2. workspace_path=\"/Users/me/App/App.xcworkspace\", scheme=\"AppTests\", destination_name=\"iPhone 16\".",
            timeoutSeconds: XcodeMCPTimeouts.protocolSafeToolSeconds,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Scheme to test."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier."),
                    "destination_name": stringSchema(description: "Optional Xcode destination name."),
                    "require_native_preflight": boolSchema(description: "Fail if native AX window/modal inspection is unavailable. Defaults to false so missing Accessibility permission warns instead of blocking the IDE action.", defaultValue: false),
                    "timeout_seconds": intSchema(description: "IDE test timeout in seconds.", defaultValue: 600)
                ],
                required: ["workspace_path", "scheme"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_ide_run",
            description: "Run the active or requested Xcode scheme through Xcode.app IDE automation. This attached run path is MCP-timeout safe; longer run/install workflows should use bin/xcode workflow run-app. Examples: 1. workspace_path=\"/Users/me/App/App.xcodeproj\", scheme=\"App\", destination_id=\"...\". 2. workspace_path=\"/Users/me/App/App.xcworkspace\", scheme=\"App\", destination_name=\"iPhone 16\".",
            timeoutSeconds: XcodeMCPTimeouts.ideRunToolSeconds,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcodeproj or .xcworkspace."),
                    "scheme": stringSchema(description: "Scheme to run."),
                    "destination_id": stringSchema(description: "Optional simulator/device identifier."),
                    "destination_name": stringSchema(description: "Optional Xcode destination name."),
                    "require_native_preflight": boolSchema(description: "Fail if native AX window/modal inspection is unavailable. Defaults to false so missing Accessibility permission warns instead of blocking the IDE action.", defaultValue: false),
                    "timeout_seconds": intSchema(description: "IDE run poll timeout in seconds. Values above 95 are capped so the MCP call returns before Codex's protocol timeout.", defaultValue: XcodeMCPTimeouts.ideRunActionSeconds)
                ],
                required: ["workspace_path", "scheme"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_run_app",
            description: "High-level GUI-first build and run workflow for an iOS app through bin/xcode workflow run-app. The MCP wrapper returns before Codex's protocol timeout if the end-to-end workflow is still running; use bin/xcode workflow run-app --json from a shell command for longer runs.",
            timeoutSeconds: XcodeMCPTimeouts.protocolSafeToolSeconds,
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
            name: "xcode_archive",
            description: "Start an iOS archive through the Xcode GUI Product > Archive action. This tool is GUI-only and does not run command-line archive.",
            timeoutSeconds: XcodeMCPTimeouts.protocolSafeToolSeconds,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcworkspace or .xcodeproj."),
                    "scheme": stringSchema(description: "Scheme to archive."),
                    "configuration": stringSchema(description: "Build configuration.", defaultValue: "Release"),
                    "destination": stringSchema(description: "Archive destination.", defaultValue: "generic/platform=iOS"),
                    "archive_path": stringSchema(description: "Ignored in GUI-only mode; Xcode Organizer owns archive location."),
                    "timeout_seconds": intSchema(description: "GUI archive start timeout in seconds.", defaultValue: 3600),
                    "dry_run": boolSchema(description: "Return the GUI archive plan without pressing Product > Archive.", defaultValue: false),
                    "preflight_only": boolSchema(description: "Run GUI/modal preflight and stop before Product > Archive.", defaultValue: false)
                ],
                required: ["workspace_path", "scheme"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_export_archive",
            description: "Blocked until GUI-only Xcode Organizer export automation is implemented. This tool refuses command-line export.",
            timeoutSeconds: XcodeMCPTimeouts.protocolSafeToolSeconds,
            inputSchema: objectSchema(
                properties: [
                    "archive_path": stringSchema(description: "Path to the .xcarchive."),
                    "export_method": stringSchema(description: "Export method, such as app-store-connect, ad-hoc, enterprise, or development."),
                    "team_id": stringSchema(description: "Apple Developer Team ID. Redacted from output."),
                    "signing_style": enumStringSchema(description: "Export signing style.", values: ["automatic", "manual"], defaultValue: "automatic", examples: ["automatic"]),
                    "export_path": stringSchema(description: "Directory where the IPA should be exported."),
                    "export_options": freeFormObjectSchema(description: "Additional ExportOptions.plist keys to merge before export."),
                    "timeout_seconds": intSchema(description: "Export timeout in seconds for the plugin-routed command.", defaultValue: 1800),
                    "dry_run": boolSchema(description: "Validate export options and return the export plan without exporting.", defaultValue: false),
                    "preflight_only": boolSchema(description: "Alias for dry-run style export preflight.", defaultValue: false)
                ],
                required: ["archive_path", "export_method", "export_path"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_upload_archive",
            description: "Blocked until GUI-only Xcode Organizer upload automation is implemented. This tool refuses command-line upload.",
            timeoutSeconds: XcodeMCPTimeouts.protocolSafeToolSeconds,
            inputSchema: objectSchema(
                properties: [
                    "ipa_path": stringSchema(description: "Path to an exported IPA. Required unless archive_path resolves to an IPA."),
                    "archive_path": stringSchema(description: "Path used for metadata context or an exported directory containing an IPA."),
                    "provider": stringSchema(description: "Optional App Store Connect provider short name."),
                    "api_key_id": stringSchema(description: "App Store Connect API key id. Redacted from output."),
                    "issuer_id": stringSchema(description: "App Store Connect issuer id. Redacted from output."),
                    "api_key_path": stringSchema(description: "Path to the App Store Connect .p8 key. Redacted from output."),
                    "api_key_env": stringSchema(description: "Environment variable whose value is the .p8 key path. Value is redacted."),
                    "timeout_seconds": intSchema(description: "Upload timeout in seconds for the plugin-routed command.", defaultValue: 1800),
                    "dry_run": boolSchema(description: "Validate upload inputs without contacting App Store Connect.", defaultValue: false),
                    "preflight_only": boolSchema(description: "Alias for dry-run upload preflight.", defaultValue: false)
                ],
                required: ["api_key_id", "issuer_id"]
            ),
            annotations: mutatingAnnotations
        ),
        .init(
            name: "xcode_distribute",
            description: "Blocked until the full GUI-only Xcode Organizer archive/export/upload workflow is implemented. This tool refuses command-line distribution.",
            timeoutSeconds: XcodeMCPTimeouts.protocolSafeToolSeconds,
            inputSchema: objectSchema(
                properties: [
                    "workspace_path": stringSchema(description: "Path to .xcworkspace or .xcodeproj."),
                    "scheme": stringSchema(description: "Scheme to archive and distribute."),
                    "export_method": stringSchema(description: "Export method, such as app-store-connect."),
                    "destination_channel": enumStringSchema(description: "Distribution destination.", values: ["testflight", "app-store-connect"], defaultValue: "testflight", examples: ["testflight"]),
                    "team_id": stringSchema(description: "Apple Developer Team ID. Redacted from output."),
                    "credentials_ref": freeFormObjectSchema(description: "Credential reference object with provider, api_key_id, issuer_id, and api_key_path or api_key_env. Secret values are redacted."),
                    "configuration": stringSchema(description: "Build configuration.", defaultValue: "Release"),
                    "destination": stringSchema(description: "Archive destination.", defaultValue: "generic/platform=iOS"),
                    "archive_path": stringSchema(description: "Optional output .xcarchive path."),
                    "export_path": stringSchema(description: "Optional IPA export directory."),
                    "signing_style": enumStringSchema(description: "Export signing style.", values: ["automatic", "manual"], defaultValue: "automatic", examples: ["automatic"]),
                    "timeout_seconds": intSchema(description: "End-to-end timeout in seconds for each plugin-routed step.", defaultValue: 5400),
                    "dry_run": boolSchema(description: "Run guarded preflight and return the plan without archive, export, or upload.", defaultValue: false),
                    "preflight_only": boolSchema(description: "Run guarded preflight and stop before archive/export/upload.", defaultValue: false)
                ],
                required: ["workspace_path", "scheme", "export_method", "destination_channel", "team_id", "credentials_ref"]
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

    private static let permissionPromptAnnotations = Tool.Annotations(
        readOnlyHint: false,
        destructiveHint: false,
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

    private static func freeFormObjectSchema(description: String? = nil) -> Value {
        var object: [String: Value] = [
            "type": .string("object"),
            "additionalProperties": .bool(true)
        ]
        if let description {
            object["description"] = .string(description)
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
