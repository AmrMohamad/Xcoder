import MCP
import XCTest
@testable import XcodeMCPServer

final class XcodeToolArgumentsTests: XCTestCase {
    func testApprovedToolNamesExist() {
        let expected = Set([
            "xcode_doctor",
            "xcode_native_state",
            "xcode_native_permissions_status",
            "xcode_native_helper_identity",
            "xcode_native_helper_bundle",
            "xcode_native_permissions_request",
            "xcode_native_windows",
            "xcode_ide_status",
            "xcode_ide_workspace_info",
            "xcode_ide_list_schemes",
            "xcode_ide_list_destinations",
            "xcode_ide_menu_catalog",
            "xcode_ide_menu_perform",
            "xcode_organizer_open",
            "xcode_organizer_inspect",
            "xcode_organizer_press",
            "xcode_organizer_distribution_inspect",
            "xcode_organizer_distribution_select_method",
            "xcode_organizer_distribution_confirm",
            "xcode_organizer_distribution_step_inspect",
            "xcode_organizer_distribution_probe_method",
            "xcode_organizer_distribution_select_custom_route",
            "xcode_organizer_distribution_probe_custom_route",
            "xcode_ide_preflight",
            "xcode_ide_build",
            "xcode_ide_test",
            "xcode_ide_run",
            "xcode_run_app",
            "xcode_archive",
            "xcode_export_archive",
            "xcode_upload_archive",
            "xcode_distribute",
            "xcode_simulator_resolve",
            "xcode_results_summary",
            "xcode_warnings_summary",
            "xcode_help"
        ])
        XCTAssertEqual(Set(XcodeToolCatalog.all.map(\.name)), expected)
    }

    func testNativePermissionToolsMapToExplicitPermissionCommands() throws {
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_native_permissions_status", arguments: [:]),
            ["native", "permissions", "status", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_native_helper_identity", arguments: [:]),
            ["native", "helper", "identity", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_native_helper_bundle", arguments: [:]),
            ["native", "helper", "bundle", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_native_permissions_request", arguments: [:]),
            ["native", "permissions", "request", "--json"]
        )
    }

    func testRunAppConfigurationIsOnlyForwardedWhenExplicitlyProvided() throws {
        let required: [String: Value] = [
            "project_path": .string("/tmp/App.xcodeproj"),
            "scheme": .string("App")
        ]
        let defaultArguments = try XcodeToolArguments.argv(for: "xcode_run_app", arguments: required)
        XCTAssertFalse(defaultArguments.contains("--configuration"))

        let explicitArguments = try XcodeToolArguments.argv(
            for: "xcode_run_app",
            arguments: required.merging(["configuration": .string("Release")]) { _, new in new }
        )
        let configurationIndex = try XCTUnwrap(explicitArguments.firstIndex(of: "--configuration"))
        XCTAssertEqual(explicitArguments[configurationIndex + 1], "Release")
    }

    func testIdeTestMapsToFixedSchemeAction() throws {
        let argv = try XcodeToolArguments.argv(
            for: "xcode_ide_test",
            arguments: [
                "workspace_path": .string("/tmp/App.xcodeproj"),
                "scheme": .string("AppTests"),
                "destination_id": .string("SIM-123")
            ]
        )

        XCTAssertEqual(
            argv,
            [
                "ide", "scheme-action",
                "--action", "test",
                "--workspace-path", "/tmp/App.xcodeproj",
                "--scheme", "AppTests",
                "--timeout-seconds", "600",
                "--destination-id", "SIM-123",
                "--json"
            ]
        )
    }

    func testIdeRunUsesMcpSafeDefaultTimeout() throws {
        let argv = try XcodeToolArguments.argv(
            for: "xcode_ide_run",
            arguments: [
                "workspace_path": .string("/tmp/App.xcodeproj"),
                "scheme": .string("App"),
                "destination_name": .string("iPhone SE (3rd generation)")
            ]
        )

        XCTAssertEqual(
            argv,
            [
                "ide", "scheme-action",
                "--action", "run",
                "--workspace-path", "/tmp/App.xcodeproj",
                "--scheme", "App",
                "--timeout-seconds", "95",
                "--destination-name", "iPhone SE (3rd generation)",
                "--json"
            ]
        )
    }

    func testIdeActionCanRequireNativePreflightWhenRequested() throws {
        let argv = try XcodeToolArguments.argv(
            for: "xcode_ide_build",
            arguments: [
                "workspace_path": .string("/tmp/App.xcodeproj"),
                "scheme": .string("App"),
                "require_native_preflight": .bool(true)
            ]
        )

        XCTAssertTrue(argv.contains("--require-native-preflight"))
    }

    func testIdeRunCapsRequestedTimeoutBelowMcpClientLimit() throws {
        let argv = try XcodeToolArguments.argv(
            for: "xcode_ide_run",
            arguments: [
                "workspace_path": .string("/tmp/App.xcodeproj"),
                "scheme": .string("App"),
                "timeout_seconds": .int(180)
            ]
        )

        XCTAssertEqual(argv.dropFirst(8).prefix(2), ["--timeout-seconds", "95"])
    }

    func testReadOnlyIdeDiscoveryMappings() throws {
        XCTAssertEqual(try XcodeToolArguments.argv(for: "xcode_ide_status", arguments: [:]), ["ide", "status", "--json"])
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_ide_workspace_info", arguments: ["workspace_path": .string("/tmp/App.xcworkspace")]),
            ["ide", "workspace-info", "--workspace-path", "/tmp/App.xcworkspace", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_ide_list_schemes", arguments: ["workspace_path": .string("/tmp/App.xcodeproj")]),
            ["ide", "list-schemes", "--workspace-path", "/tmp/App.xcodeproj", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_ide_list_destinations", arguments: [:]),
            ["ide", "list-destinations", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_ide_menu_catalog", arguments: [:]),
            ["ide", "menu-catalog", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_ide_menu_perform", arguments: ["action_id": .string("view.navigator.project")]),
            ["ide", "menu-perform", "--action-id", "view.navigator.project", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(
                for: "xcode_ide_menu_perform",
                arguments: ["action_id": .string("debug.console.clear"), "allow_destructive": .bool(true)]
            ),
            ["ide", "menu-perform", "--action-id", "debug.console.clear", "--allow-destructive", "--json"]
        )
    }

    func testHelpMappingDefaultsTopic() throws {
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_help", arguments: [:]),
            ["help", "--topic", "ide-vs-cli", "--json"]
        )
    }

    func testOrganizerToolMappings() throws {
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_open", arguments: [:]),
            ["ide", "organizer-open", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_inspect", arguments: ["window_title_contains": .string("Organizer"), "max_depth": .int(5)]),
            ["ide", "organizer-inspect", "--window-title-contains", "Organizer", "--max-depth", "5", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_press", arguments: ["button_title": .string("Distribute App")]),
            ["ide", "organizer-press", "--button-title", "Distribute App", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_distribution_inspect", arguments: [:]),
            ["ide", "organizer-distribution-inspect", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_distribution_select_method", arguments: ["method": .string("App Store Connect")]),
            ["ide", "organizer-distribution-select", "--method", "App Store Connect", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_distribution_confirm", arguments: ["expected_method": .string("App Store Connect")]),
            ["ide", "organizer-distribution-confirm", "--expected-method", "App Store Connect", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_distribution_step_inspect", arguments: [:]),
            ["ide", "organizer-distribution-step-inspect", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_distribution_probe_method", arguments: ["method": .string("Enterprise")]),
            ["ide", "organizer-distribution-probe-method", "--method", "Enterprise", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(
                for: "xcode_organizer_distribution_probe_method",
                arguments: ["method": .string("Custom"), "cancel_after_inspect": .bool(false), "settle_seconds": .int(2), "wait_ready_seconds": .int(3), "max_safe_steps": .int(5), "option_overrides": .object(["custom_destination": .string("export")])]
            ),
            ["ide", "organizer-distribution-probe-method", "--method", "Custom", "--no-cancel-after-inspect", "--settle-seconds", "2", "--wait-ready-seconds", "3", "--max-safe-steps", "5", "--option-overrides", "{\"custom_destination\":\"export\"}", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(for: "xcode_organizer_distribution_select_custom_route", arguments: ["route": .string("Release Testing")]),
            ["ide", "organizer-distribution-custom-select", "--route", "Release Testing", "--json"]
        )
        XCTAssertEqual(
            try XcodeToolArguments.argv(
                for: "xcode_organizer_distribution_probe_custom_route",
                arguments: ["route": .string("Debugging"), "cancel_after_inspect": .bool(false), "settle_seconds": .int(2), "wait_ready_seconds": .int(4), "max_safe_steps": .int(6), "option_overrides": .object(["strip_swift_symbols": .bool(false), "include_manifest": .bool(true)])]
            ),
            ["ide", "organizer-distribution-probe-custom-route", "--route", "Debugging", "--no-cancel-after-inspect", "--settle-seconds", "2", "--wait-ready-seconds", "4", "--max-safe-steps", "6", "--option-overrides", "{\"include_manifest\":true,\"strip_swift_symbols\":false}", "--json"]
        )
    }

    func testDistributionToolMappings() throws {
        XCTAssertEqual(
            try XcodeToolArguments.argv(
                for: "xcode_archive",
                arguments: [
                    "workspace_path": .string("/tmp/App.xcworkspace"),
                    "scheme": .string("App"),
                    "archive_path": .string("/tmp/App.xcarchive"),
                    "dry_run": .bool(true)
                ]
            ),
            [
                "distribution", "archive",
                "--workspace-path", "/tmp/App.xcworkspace",
                "--scheme", "App",
                "--configuration", "Release",
                "--destination", "generic/platform=iOS",
                "--timeout-seconds", "3600",
                "--archive-path", "/tmp/App.xcarchive",
                "--dry-run",
                "--json"
            ]
        )

        XCTAssertEqual(
            try XcodeToolArguments.argv(
                for: "xcode_export_archive",
                arguments: ["archive_path": .string("/tmp/App.xcarchive")]
            ),
            [
                "distribution", "export-archive",
                "--archive-path", "/tmp/App.xcarchive",
                "--json"
            ]
        )

        XCTAssertEqual(
            try XcodeToolArguments.argv(
                for: "xcode_upload_archive",
                arguments: [
                    "ipa_path": .string("/tmp/App.ipa"),
                    "api_key_id": .string("KEY123"),
                    "issuer_id": .string("ISSUER123")
                ]
            ),
            [
                "distribution", "upload-archive",
                "--ipa-path", "/tmp/App.ipa",
                "--json"
            ]
        )
    }

    func testDistributeNeverForwardsCredentials() throws {
        let argv = try XcodeToolArguments.argv(
            for: "xcode_distribute",
            arguments: [
                "workspace_path": .string("/tmp/App.xcworkspace"),
                "scheme": .string("App"),
                "credentials_ref": .object([
                    "api_key_id": .string("KEY123"),
                    "issuer_id": .string("ISSUER123"),
                    "api_key_env": .string("ASC_KEY_PATH")
                ])
            ]
        )

        XCTAssertEqual(argv, [
            "distribution", "distribute",
            "--workspace-path", "/tmp/App.xcworkspace",
            "--scheme", "App",
            "--json"
        ])
        XCTAssertFalse(argv.joined(separator: " ").contains("KEY123"))
        XCTAssertFalse(argv.joined(separator: " ").contains("ISSUER123"))
    }

    func testMissingRequiredIdeTestArgumentsThrowsUsage() {
        XCTAssertThrowsError(try XcodeToolArguments.argv(for: "xcode_ide_test", arguments: ["workspace_path": .string("/tmp/App.xcodeproj")])) { error in
            guard case XcodeToolError.usage(let message) = error else {
                return XCTFail("Expected usage error, got \(error)")
            }
            XCTAssertTrue(message.contains("scheme"))
        }
    }

    func testNestedForbiddenKeysAreRejected() {
        let arguments: [String: Value] = [
            "workspace_path": .string("/tmp/App.xcodeproj"),
            "nested": .object(["script": .string("osascript")])
        ]
        XCTAssertEqual(ArgumentValues.findForbiddenKey(in: .object(arguments)), "script")
    }
}
