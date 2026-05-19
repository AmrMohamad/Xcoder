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
            XCTAssertEqual(definition.annotations.openWorldHint, false, definition.name)
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

        let mutatingTools = ["xcode_ide_build", "xcode_ide_test", "xcode_ide_run", "xcode_run_app", "xcode_ide_menu_perform"]
        for name in mutatingTools {
            let annotations = try! XCTUnwrap(XcodeToolCatalog.byName[name]?.annotations)
            XCTAssertEqual(annotations.readOnlyHint, false, name)
            XCTAssertEqual(annotations.destructiveHint, true, name)
            XCTAssertEqual(annotations.idempotentHint, false, name)
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
        for name in ["xcode_ide_build", "xcode_ide_test", "xcode_ide_run", "xcode_run_app"] {
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
        XCTAssertEqual(timeoutSchema["default"]?.intValue, 95)
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
