import Foundation
import MCP

@main
struct XcodeMCPServer {
    static func main() async throws {
        let cli = CommandLine.arguments.dropFirst()
        if cli.contains("--version") {
            print(JSONEnvelope.versionJSON())
            return
        }
        if cli.contains("--list-tools") {
            print(XcodeToolCatalog.listToolsJSON())
            return
        }
        if cli.contains("--doctor") {
            print(ServerIntrospection.doctorJSON())
            return
        }
        guard cli.isEmpty || cli.contains("--stdio") else {
            print(JSONEnvelope.failure(errorType: "usage_error", summary: "Use --stdio, --version --json, --list-tools --json, or --doctor --json."))
            Foundation.exit(2)
        }

        let server = Server(
            name: XcodeMCPConstants.serverName,
            version: XcodeMCPConstants.serverVersion,
            capabilities: .init(
                logging: .init(),
                tools: .init(listChanged: true)
            )
        )

        let bridge = XcodeBridge()

        await server.withMethodHandler(ListTools.self) { _ in
            ListTools.Result(tools: XcodeToolCatalog.mcpTools)
        }

        await server.withMethodHandler(CallTool.self) { params in
            do {
                let result = try await bridge.callTool(name: params.name, arguments: params.arguments)
                return CallTool.Result(content: [.text(text: result.json, annotations: nil, _meta: nil)], isError: result.isError)
            } catch let error as XcodeToolError {
                return CallTool.Result(content: [.text(text: error.envelopeJSON, annotations: nil, _meta: nil)], isError: true)
            } catch {
                return CallTool.Result(
                    content: [.text(text: JSONEnvelope.failure(errorType: "native_helper_failed", summary: String(describing: error)), annotations: nil, _meta: nil)],
                    isError: true
                )
            }
        }

        let transport = StdioTransport()
        try await server.start(transport: transport)
        await server.waitUntilCompleted()
    }
}
