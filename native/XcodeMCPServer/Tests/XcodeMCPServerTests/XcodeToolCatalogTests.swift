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
            "xcode_native_windows",
            "xcode_ide_status",
            "xcode_ide_workspace_info",
            "xcode_ide_list_schemes",
            "xcode_ide_list_destinations",
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

        let mutatingTools = ["xcode_ide_build", "xcode_ide_test", "xcode_ide_run", "xcode_run_app"]
        for name in mutatingTools {
            let annotations = try! XCTUnwrap(XcodeToolCatalog.byName[name]?.annotations)
            XCTAssertEqual(annotations.readOnlyHint, false, name)
            XCTAssertEqual(annotations.destructiveHint, true, name)
            XCTAssertEqual(annotations.idempotentHint, false, name)
        }
    }

    func testEnumSchemasExist() throws {
        let resultsSchema = try properties(for: "xcode_results_summary")
        XCTAssertEqual(enumValues(resultsSchema["kind"]), ["test-summary", "build-results", "content-availability", "log"])
        XCTAssertEqual(enumValues(resultsSchema["log_type"]), ["build", "action", "console"])

        let helpSchema = try properties(for: "xcode_help")
        XCTAssertEqual(enumValues(helpSchema["topic"]), XcodeToolCatalog.helpTopics)
    }

    func testMCPToolsExposeAnnotations() {
        for tool in XcodeToolCatalog.mcpTools {
            XCTAssertFalse(tool.annotations.isEmpty, tool.name)
        }
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
