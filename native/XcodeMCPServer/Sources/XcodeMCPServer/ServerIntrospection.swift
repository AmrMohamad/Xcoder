import Foundation

enum ServerIntrospection {
    static func doctorJSON(paths: PluginPaths = PluginPaths()) -> String {
        let expectedTools = XcodeToolCatalog.all.map(\.name)
        var checks: [[String: Any]] = []
        let currentMacOS = ProcessInfo.processInfo.operatingSystemVersion
        let currentMacOSString = "\(currentMacOS.majorVersion).\(currentMacOS.minorVersion).\(currentMacOS.patchVersion)"

        checks.append([
            "name": "mcp-server-minimum-macos",
            "status": "ok",
            "minimum_macos_version": XcodeMCPConstants.minimumMacOSVersion,
            "package_platform": "macOS 14"
        ])
        checks.append([
            "name": "mcp-server-host-macos-supported",
            "status": macOSVersionIsSupported(currentMacOS) ? "ok" : "failed",
            "current_macos_version": currentMacOSString,
            "minimum_macos_version": XcodeMCPConstants.minimumMacOSVersion
        ])

        checks.append([
            "name": "mcp-config-present",
            "status": fileExists(paths.mcpConfig) && mcpConfigIsValid(paths.mcpConfig) ? "ok" : "failed",
            "path": paths.mcpConfig.path
        ])
        checks.append([
            "name": "mcp-server-wrapper-present",
            "status": isExecutable(paths.mcpWrapper) ? "ok" : "failed",
            "path": paths.mcpWrapper.path
        ])
        checks.append([
            "name": "mcp-server-binary-present",
            "status": isExecutable(paths.mcpServer) ? "ok" : "failed",
            "path": paths.mcpServer.path
        ])
        checks.append([
            "name": "mcp-server-version",
            "status": "ok",
            "version": XcodeMCPConstants.serverVersion,
            "schema_version": XcodeMCPConstants.mcpServerSchemaVersion
        ])
        checks.append([
            "name": "mcp-server-tool-list",
            "status": "ok",
            "tools": expectedTools,
            "missing": []
        ])
        checks.append([
            "name": "mcp-server-sdk-version",
            "status": "ok",
            "sdk": XcodeMCPConstants.sdkName,
            "sdk_version": XcodeMCPConstants.sdkVersion
        ])
        checks.append([
            "name": "mcp-server-package-resolved-present",
            "status": fileExists(paths.packageResolved) ? "ok" : "failed",
            "path": paths.packageResolved.path
        ])
        checks.append([
            "name": "mcp-server-source-present",
            "status": fileExists(paths.packageSwift) ? "ok" : "failed",
            "path": paths.packageSwift.path
        ])

        let failed = checks.compactMap { check -> String? in
            check["status"] as? String == "failed" ? check["name"] as? String : nil
        }

        return JSONEnvelope.compactJSONString([
            "schema_version": XcodeMCPConstants.mcpServerSchemaVersion,
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "minimum_macos_version": XcodeMCPConstants.minimumMacOSVersion,
            "ok": failed.isEmpty,
            "status": failed.isEmpty ? "success" : "failure",
            "checks": checks,
            "errors": failed,
            "expected_tools": expectedTools
        ])
    }

    private static func fileExists(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.path)
    }

    private static func isExecutable(_ url: URL) -> Bool {
        FileManager.default.isExecutableFile(atPath: url.path)
    }

    private static func mcpConfigIsValid(_ url: URL) -> Bool {
        guard let data = try? Data(contentsOf: url),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let servers = object["mcpServers"] as? [String: Any],
              let xcode = servers["xcode"] as? [String: Any],
              xcode["command"] as? String == "./bin/xcode-mcp",
              let args = xcode["args"] as? [String],
              args == ["--stdio"]
        else {
            return false
        }
        return true
    }

    private static func macOSVersionIsSupported(_ version: OperatingSystemVersion) -> Bool {
        if version.majorVersion > 14 {
            return true
        }
        if version.majorVersion == 14 {
            return version.minorVersion >= 0
        }
        return false
    }
}
