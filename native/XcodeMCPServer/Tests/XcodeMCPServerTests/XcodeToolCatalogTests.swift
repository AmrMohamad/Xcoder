import MCP
import XCTest
@testable import XcodeMCPServer

final class XcodeToolCatalogTests: XCTestCase {
    func testEveryToolHasClosedObjectSchemaAndAnnotations() {
        for definition in XcodeToolCatalog.all {
            guard case .object(let schema) = definition.inputSchema else {
                return XCTFail("\(definition.name) schema is not an object")
            }
            XCTAssertEqual(schema["type"]?.stringValue, "object", definition.name)
            XCTAssertEqual(schema["additionalProperties"]?.boolValue, false, definition.name)
            XCTAssertNotNil(definition.annotations.readOnlyHint, definition.name)
            XCTAssertNotNil(definition.annotations.destructiveHint, definition.name)
            XCTAssertNotNil(definition.annotations.idempotentHint, definition.name)
            XCTAssertNotNil(definition.annotations.openWorldHint, definition.name)
        }
    }

    func testReadOnlyAndMutatingAnnotations() {
        let readOnlyTools = [
            "xcode_doctor",
            "xcode_native_state",
            "xcode_native_permissions_status",
            "xcode_native_helper_identity",
            "xcode_native_windows",
            "xcode_ide_status",
            "xcode_ide_workspace_info",
            "xcode_ide_list_schemes",
            "xcode_ide_list_destinations",
            "xcode_ide_menu_catalog",
            "xcode_organizer_inspect",
            "xcode_organizer_distribution_inspect",
            "xcode_organizer_distribution_step_inspect",
            "xcode_help",
            "xcode_simulator_resolve",
            "xcode_results_summary",
            "xcode_warnings_summary",
            "xcode_ide_preflight"
        ]
        for name in readOnlyTools {
            let annotations = try! XCTUnwrap(XcodeToolCatalog.byName[name]?.annotations)
            XCTAssertEqual(annotations.readOnlyHint, true, name)
            XCTAssertEqual(annotations.destructiveHint, false, name)
            XCTAssertEqual(annotations.idempotentHint, true, name)
        }

        let stateChangingTools = [
            "xcode_ide_build",
            "xcode_ide_test",
            "xcode_ide_run",
            "xcode_run_app",
            "xcode_archive",
            "xcode_ide_menu_perform",
            "xcode_organizer_open",
            "xcode_organizer_press",
            "xcode_organizer_distribution_select_method",
            "xcode_organizer_distribution_confirm",
            "xcode_organizer_distribution_probe_method",
            "xcode_organizer_distribution_select_custom_route",
            "xcode_organizer_distribution_probe_custom_route"
        ]
        for name in stateChangingTools {
            let annotations = try! XCTUnwrap(XcodeToolCatalog.byName[name]?.annotations)
            XCTAssertEqual(annotations.readOnlyHint, false, name)
            XCTAssertEqual(annotations.destructiveHint, false, name)
            XCTAssertEqual(annotations.idempotentHint, false, name)
            XCTAssertEqual(XcodeToolCatalog.byName[name]?.safety, .stateChange, name)
        }

        for name in ["xcode_export_archive", "xcode_upload_archive", "xcode_distribute"] {
            let annotations = try! XCTUnwrap(XcodeToolCatalog.byName[name]?.annotations)
            XCTAssertEqual(annotations.readOnlyHint, false, name)
            XCTAssertEqual(annotations.destructiveHint, true, name)
            XCTAssertEqual(XcodeToolCatalog.byName[name]?.safety, .externalEffect, name)
        }

        for name in ["xcode_native_permissions_request", "xcode_native_helper_bundle"] {
            let permissionPrompt = try! XCTUnwrap(XcodeToolCatalog.byName[name]?.annotations)
            XCTAssertEqual(permissionPrompt.readOnlyHint, false, name)
            XCTAssertEqual(permissionPrompt.destructiveHint, false, name)
            XCTAssertEqual(permissionPrompt.idempotentHint, false, name)
        }
    }

    func testEnumSchemasExist() throws {
        let resultsSchema = try properties(for: "xcode_results_summary")
        XCTAssertEqual(enumValues(resultsSchema["kind"]), ["test-summary", "build-results", "content-availability", "log"])
        XCTAssertEqual(enumValues(resultsSchema["log_type"]), ["build", "action", "console"])

        let helpSchema = try properties(for: "xcode_help")
        XCTAssertEqual(enumValues(helpSchema["topic"]), XcodeToolCatalog.helpTopics)

        let exportSchema = try properties(for: "xcode_export_archive")
        XCTAssertNil(exportSchema["signing_style"])

        let distributeSchema = try properties(for: "xcode_distribute")
        XCTAssertNil(distributeSchema["destination_channel"])

        let organizerSelectSchema = try properties(for: "xcode_organizer_distribution_select_method")
        XCTAssertEqual(enumValues(organizerSelectSchema["method"]), ["App Store Connect", "TestFlight Internal Only", "Release Testing", "Enterprise", "Debugging", "Custom"])

        let organizerConfirmSchema = try properties(for: "xcode_organizer_distribution_confirm")
        XCTAssertEqual(enumValues(organizerConfirmSchema["expected_method"]), ["App Store Connect", "TestFlight Internal Only", "Release Testing", "Enterprise", "Debugging", "Custom"])

        let organizerProbeSchema = try properties(for: "xcode_organizer_distribution_probe_method")
        XCTAssertEqual(enumValues(organizerProbeSchema["method"]), ["App Store Connect", "TestFlight Internal Only", "Release Testing", "Enterprise", "Debugging", "Custom"])
        XCTAssertNotNil(organizerProbeSchema["max_safe_steps"])
        XCTAssertNotNil(organizerProbeSchema["option_overrides"])

        let organizerCustomSelectSchema = try properties(for: "xcode_organizer_distribution_select_custom_route")
        XCTAssertEqual(enumValues(organizerCustomSelectSchema["route"]), ["App Store Connect", "Release Testing", "Enterprise", "Debugging"])

        let organizerCustomProbeSchema = try properties(for: "xcode_organizer_distribution_probe_custom_route")
        XCTAssertEqual(enumValues(organizerCustomProbeSchema["route"]), ["App Store Connect", "Release Testing", "Enterprise", "Debugging"])
        XCTAssertNotNil(organizerCustomProbeSchema["max_safe_steps"])
        XCTAssertNotNil(organizerCustomProbeSchema["option_overrides"])
    }

    func testMenuPerformSchemaIsTyped() throws {
        let schema = try properties(for: "xcode_ide_menu_perform")
        XCTAssertNotNil(schema["action_id"])
        XCTAssertNotNil(schema["allow_destructive"])
        XCTAssertNil(schema["command"])
        XCTAssertNil(schema["script"])
        XCTAssertNil(schema["raw"])
        XCTAssertNil(schema["args"])
    }

    func testMCPToolsExposeAnnotations() {
        for tool in XcodeToolCatalog.mcpTools {
            XCTAssertFalse(tool.annotations.isEmpty, tool.name)
        }
    }

    func testAllMCPToolTimeoutsStayBelowCodexProtocolLimit() {
        for definition in XcodeToolCatalog.all {
            XCTAssertLessThan(definition.timeoutSeconds, 120, definition.name)
        }
    }

    func testLongRunningMCPToolsUseProtocolSafeWrapperTimeout() throws {
        for name in ["xcode_ide_build", "xcode_ide_test", "xcode_ide_run", "xcode_run_app", "xcode_archive", "xcode_export_archive", "xcode_upload_archive", "xcode_distribute"] {
            let definition = try XCTUnwrap(XcodeToolCatalog.byName[name])
            XCTAssertEqual(definition.timeoutSeconds, XcodeMCPTimeouts.protocolSafeToolSeconds, name)
        }
    }

    func testIdeRunTimeoutSchemaDocumentsInnerCap() throws {
        let definition = try XCTUnwrap(XcodeToolCatalog.byName["xcode_ide_run"])
        XCTAssertEqual(definition.timeoutSeconds, XcodeMCPTimeouts.protocolSafeToolSeconds)

        let schema = try properties(for: "xcode_ide_run")
        guard case .object(let timeoutSchema)? = schema["timeout_seconds"] else {
            return XCTFail("xcode_ide_run timeout_seconds schema missing")
        }
        XCTAssertEqual(timeoutSchema["default"]?.intValue, XcodeMCPTimeouts.ideRunActionSeconds)
        XCTAssertTrue(timeoutSchema["description"]?.stringValue?.contains("capped") == true)
    }

    private func properties(for toolName: String) throws -> [String: Value] {
        let definition = try XCTUnwrap(XcodeToolCatalog.byName[toolName])
        guard case .object(let schema) = definition.inputSchema,
              case .object(let properties)? = schema["properties"]
        else {
            throw NSError(domain: "XcodeToolCatalogTests", code: 1)
        }
        return properties
    }

    private func enumValues(_ schema: Value?) -> [String] {
        guard case .object(let object)? = schema,
              case .array(let values)? = object["enum"]
        else {
            return []
        }
        return values.compactMap(\.stringValue)
    }
}
