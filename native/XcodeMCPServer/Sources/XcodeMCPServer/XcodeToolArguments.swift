import MCP

enum XcodeToolArguments {
    static func argv(for toolName: String, arguments: [String: Value]) throws -> [String] {
        switch toolName {
        case "xcode_doctor":
            var argv = ["doctor"]
            if ArgumentValues.bool(arguments["strict"], default: false) {
                argv.append("--strict")
            }
            if let checks = ArgumentValues.stringArray(arguments["checks"]), !checks.isEmpty {
                argv.append("--checks")
                argv.append(checks.joined(separator: ","))
            }
            argv.append("--json")
            return argv
        case "xcode_native_state":
            return ["native", "app", "xcode-state", "--json"]
        case "xcode_native_permissions_status":
            return ["native", "permissions", "status", "--json"]
        case "xcode_native_helper_identity":
            return ["native", "helper", "identity", "--json"]
        case "xcode_native_helper_bundle":
            return ["native", "helper", "bundle", "--json"]
        case "xcode_native_permissions_request":
            return ["native", "permissions", "request", "--json"]
        case "xcode_native_windows":
            return ["native", "ax", "xcode-windows", "--json"]
        case "xcode_ide_status":
            return ["ide", "status", "--json"]
        case "xcode_ide_workspace_info":
            var argv = ["ide", "workspace-info"]
            ArgumentValues.appendOptionalString(arguments["workspace_path"], flag: "--workspace-path", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_ide_list_schemes":
            var argv = ["ide", "list-schemes"]
            ArgumentValues.appendOptionalString(arguments["workspace_path"], flag: "--workspace-path", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_ide_list_destinations":
            var argv = ["ide", "list-destinations"]
            ArgumentValues.appendOptionalString(arguments["workspace_path"], flag: "--workspace-path", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_ide_menu_catalog":
            return ["ide", "menu-catalog", "--json"]
        case "xcode_ide_menu_perform":
            var argv = ["ide", "menu-perform", "--action-id", try ArgumentValues.requiredString(arguments["action_id"], key: "action_id")]
            if ArgumentValues.bool(arguments["allow_destructive"], default: false) {
                argv.append("--allow-destructive")
            }
            argv.append("--json")
            return argv
        case "xcode_ide_preflight":
            var argv = ["ide", "preflight"]
            ArgumentValues.appendOptionalString(arguments["workspace_path"], flag: "--workspace-path", to: &argv)
            ArgumentValues.appendOptionalString(arguments["scheme"], flag: "--scheme", to: &argv)
            ArgumentValues.appendOptionalString(arguments["destination_id"], flag: "--destination-id", to: &argv)
            ArgumentValues.appendOptionalString(arguments["destination_name"], flag: "--destination-name", to: &argv)
            if ArgumentValues.bool(arguments["require_native_preflight"], default: false) {
                argv.append("--require-native-preflight")
            }
            argv.append("--json")
            return argv
        case "xcode_ide_build":
            return try ideActionArguments("build", arguments: arguments, defaultTimeout: 600)
        case "xcode_ide_test":
            return try ideActionArguments("test", arguments: arguments, defaultTimeout: 600)
        case "xcode_ide_run":
            return try ideActionArguments(
                "run",
                arguments: arguments,
                defaultTimeout: XcodeMCPTimeouts.ideRunActionSeconds,
                maxTimeout: XcodeMCPTimeouts.ideRunActionSeconds
            )
        case "xcode_run_app":
            var argv = [
                "workflow", "run-app",
                "--project-path", try ArgumentValues.requiredString(arguments["project_path"], key: "project_path"),
                "--scheme", try ArgumentValues.requiredString(arguments["scheme"], key: "scheme"),
                "--simulator-name", ArgumentValues.string(arguments["simulator_name"], default: "iPhone SE (3rd generation)"),
                "--configuration", ArgumentValues.string(arguments["configuration"], default: "Debug"),
                "--timeout-seconds", String(ArgumentValues.int(arguments["timeout_seconds"], default: 900))
            ]
            ArgumentValues.appendOptionalString(arguments["runtime"], flag: "--runtime", to: &argv)
            ArgumentValues.appendOptionalString(arguments["destination_id"], flag: "--destination-id", to: &argv)
            if !ArgumentValues.bool(arguments["allow_cli_fallback"], default: true) {
                argv.append("--no-cli-fallback")
            }
            argv.append("--json")
            return argv
        case "xcode_simulator_resolve":
            var argv = ["simulator", "resolve", "--name", try ArgumentValues.requiredString(arguments["name"], key: "name")]
            ArgumentValues.appendOptionalString(arguments["runtime"], flag: "--runtime", to: &argv)
            ArgumentValues.appendOptionalString(arguments["fixture"], flag: "--fixture", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_results_summary":
            return [
                "results",
                "summarize",
                "--path", try ArgumentValues.requiredString(arguments["path"], key: "path"),
                "--kind", ArgumentValues.string(arguments["kind"], default: "test-summary"),
                "--log-type", ArgumentValues.string(arguments["log_type"], default: "build"),
                "--timeout-seconds", String(ArgumentValues.int(arguments["timeout_seconds"], default: 60)),
                "--json"
            ]
        case "xcode_warnings_summary":
            var argv = ["warnings", "summarize", "--log", try ArgumentValues.requiredString(arguments["log"], key: "log")]
            if ArgumentValues.bool(arguments["fail_on_new"], default: false) {
                argv.append("--fail-on-new")
            }
            argv.append("--json")
            return argv
        case "xcode_help":
            return [
                "help",
                "--topic", ArgumentValues.string(arguments["topic"], default: "ide-vs-cli"),
                "--json"
            ]
        default:
            throw XcodeToolError.usage("Unknown Xcode MCP tool: \(toolName)")
        }
    }

    private static func ideActionArguments(_ action: String, arguments: [String: Value], defaultTimeout: Int, maxTimeout: Int? = nil) throws -> [String] {
        let requestedTimeout = ArgumentValues.int(arguments["timeout_seconds"], default: defaultTimeout)
        let timeout = maxTimeout.map { min(requestedTimeout, $0) } ?? requestedTimeout
        var argv = [
            "ide", "scheme-action",
            "--action", action,
            "--workspace-path", try ArgumentValues.requiredString(arguments["workspace_path"], key: "workspace_path"),
            "--scheme", try ArgumentValues.requiredString(arguments["scheme"], key: "scheme"),
            "--timeout-seconds", String(timeout)
        ]
        if ArgumentValues.bool(arguments["require_native_preflight"], default: false) {
            argv.append("--require-native-preflight")
        }
        ArgumentValues.appendOptionalString(arguments["destination_id"], flag: "--destination-id", to: &argv)
        ArgumentValues.appendOptionalString(arguments["destination_name"], flag: "--destination-name", to: &argv)
        argv.append("--json")
        return argv
    }
}
