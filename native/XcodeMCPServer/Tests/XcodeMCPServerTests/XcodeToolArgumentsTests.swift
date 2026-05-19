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
            "xcode_ide_preflight",
            "xcode_ide_build",
            "xcode_ide_test",
            "xcode_ide_run",
            "xcode_run_app",
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
