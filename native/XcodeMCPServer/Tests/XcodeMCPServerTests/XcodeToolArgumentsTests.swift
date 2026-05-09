import MCP
import XCTest
@testable import XcodeMCPServer

final class XcodeToolArgumentsTests: XCTestCase {
    func testApprovedToolNamesExist() {
        let expected = Set([
            "xcode_doctor",
            "xcode_native_state",
            "xcode_native_windows",
            "xcode_ide_status",
            "xcode_ide_workspace_info",
            "xcode_ide_list_schemes",
            "xcode_ide_list_destinations",
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
                "--require-native-preflight",
                "--destination-id", "SIM-123",
                "--json"
            ]
        )
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
