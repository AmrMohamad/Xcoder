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
        case "xcode_organizer_open":
            return ["ide", "organizer-open", "--json"]
        case "xcode_organizer_inspect":
            var argv = ["ide", "organizer-inspect"]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            argv.append("--max-depth")
            argv.append(String(ArgumentValues.int(arguments["max_depth"], default: 4)))
            argv.append("--json")
            return argv
        case "xcode_organizer_press":
            var argv = [
                "ide", "organizer-press",
                "--button-title", try ArgumentValues.requiredString(arguments["button_title"], key: "button_title")
            ]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_organizer_distribution_inspect":
            var argv = ["ide", "organizer-distribution-inspect"]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_organizer_distribution_select_method":
            var argv = [
                "ide", "organizer-distribution-select",
                "--method", try ArgumentValues.requiredString(arguments["method"], key: "method")
            ]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_organizer_distribution_confirm":
            var argv = ["ide", "organizer-distribution-confirm"]
            ArgumentValues.appendOptionalString(arguments["expected_method"], flag: "--expected-method", to: &argv)
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_organizer_distribution_step_inspect":
            var argv = ["ide", "organizer-distribution-step-inspect"]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_organizer_distribution_probe_method":
            var argv = [
                "ide", "organizer-distribution-probe-method",
                "--method", try ArgumentValues.requiredString(arguments["method"], key: "method")
            ]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            if ArgumentValues.bool(arguments["cancel_after_inspect"], default: true) == false {
                argv.append("--no-cancel-after-inspect")
            }
            let settleSeconds = ArgumentValues.int(arguments["settle_seconds"], default: 1)
            if settleSeconds != 1 {
                argv.append("--settle-seconds")
                argv.append(String(settleSeconds))
            }
            let waitReadySeconds = ArgumentValues.int(arguments["wait_ready_seconds"], default: 15)
            if waitReadySeconds != 15 {
                argv.append("--wait-ready-seconds")
                argv.append(String(waitReadySeconds))
            }
            let maxSafeSteps = ArgumentValues.int(arguments["max_safe_steps"], default: 4)
            if maxSafeSteps != 4 {
                argv.append("--max-safe-steps")
                argv.append(String(maxSafeSteps))
            }
            try ArgumentValues.appendOptionalStringOrJSON(arguments["option_overrides"], flag: "--option-overrides", key: "option_overrides", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_organizer_distribution_select_custom_route":
            var argv = [
                "ide", "organizer-distribution-custom-select",
                "--route", try ArgumentValues.requiredString(arguments["route"], key: "route")
            ]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            argv.append("--json")
            return argv
        case "xcode_organizer_distribution_probe_custom_route":
            var argv = [
                "ide", "organizer-distribution-probe-custom-route",
                "--route", try ArgumentValues.requiredString(arguments["route"], key: "route")
            ]
            ArgumentValues.appendOptionalString(arguments["window_title_contains"], flag: "--window-title-contains", to: &argv)
            if ArgumentValues.bool(arguments["cancel_after_inspect"], default: true) == false {
                argv.append("--no-cancel-after-inspect")
            }
            let settleSeconds = ArgumentValues.int(arguments["settle_seconds"], default: 1)
            if settleSeconds != 1 {
                argv.append("--settle-seconds")
                argv.append(String(settleSeconds))
            }
            let waitReadySeconds = ArgumentValues.int(arguments["wait_ready_seconds"], default: 15)
            if waitReadySeconds != 15 {
                argv.append("--wait-ready-seconds")
                argv.append(String(waitReadySeconds))
            }
            let maxSafeSteps = ArgumentValues.int(arguments["max_safe_steps"], default: 4)
            if maxSafeSteps != 4 {
                argv.append("--max-safe-steps")
                argv.append(String(maxSafeSteps))
            }
            try ArgumentValues.appendOptionalStringOrJSON(arguments["option_overrides"], flag: "--option-overrides", key: "option_overrides", to: &argv)
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
        case "xcode_archive":
            var argv = [
                "distribution", "archive",
                "--workspace-path", try ArgumentValues.requiredString(arguments["workspace_path"], key: "workspace_path"),
                "--scheme", try ArgumentValues.requiredString(arguments["scheme"], key: "scheme"),
                "--configuration", ArgumentValues.string(arguments["configuration"], default: "Release"),
                "--destination", ArgumentValues.string(arguments["destination"], default: "generic/platform=iOS"),
                "--timeout-seconds", String(ArgumentValues.int(arguments["timeout_seconds"], default: 3600))
            ]
            ArgumentValues.appendOptionalString(arguments["archive_path"], flag: "--archive-path", to: &argv)
            appendDistributionModeFlags(arguments, to: &argv)
            argv.append("--json")
            return argv
        case "xcode_export_archive":
            var argv = [
                "distribution", "export-archive",
                "--archive-path", try ArgumentValues.requiredString(arguments["archive_path"], key: "archive_path"),
                "--export-method", try ArgumentValues.requiredString(arguments["export_method"], key: "export_method"),
                "--export-path", try ArgumentValues.requiredString(arguments["export_path"], key: "export_path"),
                "--timeout-seconds", String(ArgumentValues.int(arguments["timeout_seconds"], default: 1800))
            ]
            ArgumentValues.appendOptionalString(arguments["team_id"], flag: "--team-id", to: &argv)
            ArgumentValues.appendOptionalString(arguments["signing_style"], flag: "--signing-style", to: &argv)
            try ArgumentValues.appendOptionalStringOrJSON(arguments["export_options"], flag: "--export-options", key: "export_options", to: &argv)
            appendDistributionModeFlags(arguments, to: &argv)
            argv.append("--json")
            return argv
        case "xcode_upload_archive":
            var argv = [
                "distribution", "upload-archive",
                "--timeout-seconds", String(ArgumentValues.int(arguments["timeout_seconds"], default: 1800))
            ]
            ArgumentValues.appendOptionalString(arguments["ipa_path"], flag: "--ipa-path", to: &argv)
            ArgumentValues.appendOptionalString(arguments["archive_path"], flag: "--archive-path", to: &argv)
            ArgumentValues.appendOptionalString(arguments["provider"], flag: "--provider", to: &argv)
            ArgumentValues.appendOptionalString(arguments["api_key_id"], flag: "--api-key-id", to: &argv)
            ArgumentValues.appendOptionalString(arguments["issuer_id"], flag: "--issuer-id", to: &argv)
            ArgumentValues.appendOptionalString(arguments["api_key_path"], flag: "--api-key-path", to: &argv)
            ArgumentValues.appendOptionalString(arguments["api_key_env"], flag: "--api-key-env", to: &argv)
            appendDistributionModeFlags(arguments, to: &argv)
            argv.append("--json")
            return argv
        case "xcode_distribute":
            var argv = [
                "distribution", "distribute",
                "--workspace-path", try ArgumentValues.requiredString(arguments["workspace_path"], key: "workspace_path"),
                "--scheme", try ArgumentValues.requiredString(arguments["scheme"], key: "scheme"),
                "--export-method", try ArgumentValues.requiredString(arguments["export_method"], key: "export_method"),
                "--destination-channel", try ArgumentValues.requiredString(arguments["destination_channel"], key: "destination_channel"),
                "--team-id", try ArgumentValues.requiredString(arguments["team_id"], key: "team_id"),
                "--configuration", ArgumentValues.string(arguments["configuration"], default: "Release"),
                "--destination", ArgumentValues.string(arguments["destination"], default: "generic/platform=iOS"),
                "--timeout-seconds", String(ArgumentValues.int(arguments["timeout_seconds"], default: 5400))
            ]
            try ArgumentValues.appendOptionalStringOrJSON(arguments["credentials_ref"], flag: "--credentials-ref", key: "credentials_ref", to: &argv)
            ArgumentValues.appendOptionalString(arguments["archive_path"], flag: "--archive-path", to: &argv)
            ArgumentValues.appendOptionalString(arguments["export_path"], flag: "--export-path", to: &argv)
            ArgumentValues.appendOptionalString(arguments["signing_style"], flag: "--signing-style", to: &argv)
            appendDistributionModeFlags(arguments, to: &argv)
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

    private static func appendDistributionModeFlags(_ arguments: [String: Value], to argv: inout [String]) {
        if ArgumentValues.bool(arguments["dry_run"], default: false) {
            argv.append("--dry-run")
        }
        if ArgumentValues.bool(arguments["preflight_only"], default: false) {
            argv.append("--preflight-only")
        }
    }
}
