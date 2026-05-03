import Foundation

enum XcodeMCPConstants {
    static let serverName = "xcode"
    static let serverVersion = "0.4.0"
    static let mcpServerSchemaVersion = "xcode-mcp-server.v0.1"
    static let pluginEnvelopeSchemaVersion = "xcode-plugin.v0.3"
    static let sdkName = "modelcontextprotocol/swift-sdk"
    static let sdkVersion = "0.12.0"
    static let minimumMacOSVersion = "14.0"
    static let forbiddenArgumentKeys: Set<String> = ["command", "shell", "args", "script", "raw"]
}

struct PluginPaths {
    let pluginRoot: URL
    let binDirectory: URL
    let xcodeCLI: URL
    let mcpWrapper: URL
    let mcpServer: URL
    let mcpConfig: URL
    let packageSwift: URL
    let packageResolved: URL

    init(executablePath: String = CommandLine.arguments[0]) {
        let executable = URL(fileURLWithPath: executablePath)
        let binDirectory = executable.deletingLastPathComponent()
        let pluginRoot = binDirectory.deletingLastPathComponent()

        self.pluginRoot = pluginRoot
        self.binDirectory = binDirectory
        self.xcodeCLI = pluginRoot.appendingPathComponent("bin/xcode")
        self.mcpWrapper = pluginRoot.appendingPathComponent("bin/xcode-mcp")
        self.mcpServer = pluginRoot.appendingPathComponent("bin/xcode-mcp-server")
        self.mcpConfig = pluginRoot.appendingPathComponent(".mcp.json")
        self.packageSwift = pluginRoot.appendingPathComponent("native/XcodeMCPServer/Package.swift")
        self.packageResolved = pluginRoot.appendingPathComponent("native/XcodeMCPServer/Package.resolved")
    }
}
