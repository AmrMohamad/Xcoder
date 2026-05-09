import Foundation

struct RecoveryMetadata {
    let recovery: String
    let transient: Bool
    let retryAfterSeconds: Int?

    var dictionary: [String: Any] {
        [
            "recovery": recovery,
            "transient": transient,
            "retry_after_seconds": retryAfterSeconds.map { $0 as Any } ?? NSNull()
        ]
    }
}

enum RecoveryCatalog {
    private static let entries: [String: RecoveryMetadata] = [
        "usage_error": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "tool_missing": .init(recovery: "environment", transient: false, retryAfterSeconds: nil),
        "permission_denied": .init(recovery: "permission", transient: false, retryAfterSeconds: nil),
        "accessibility_not_trusted": .init(recovery: "permission", transient: false, retryAfterSeconds: nil),
        "trusted_fast_denied": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "path_violation": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "xcode_not_running": .init(recovery: "environment", transient: true, retryAfterSeconds: nil),
        "no_workspace": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "multiple_workspaces_ambiguous": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "scheme_not_found": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "scheme_not_testable": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "destination_not_found": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "destination_ambiguous": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "xcode_ide_automation_failed": .init(recovery: "retry", transient: true, retryAfterSeconds: 5),
        "xcode_modal_blocking": .init(recovery: "permission", transient: false, retryAfterSeconds: nil),
        "xcode_activation_failed": .init(recovery: "retry", transient: true, retryAfterSeconds: 3),
        "workspace_open_failed": .init(recovery: "environment", transient: false, retryAfterSeconds: nil),
        "simulator_boot_failed": .init(recovery: "retry", transient: true, retryAfterSeconds: 5),
        "install_failed": .init(recovery: "retry", transient: true, retryAfterSeconds: 5),
        "launch_failed": .init(recovery: "retry", transient: true, retryAfterSeconds: 5),
        "xcresult_missing": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "xcresult_corrupt": .init(recovery: "permanent", transient: false, retryAfterSeconds: nil),
        "cache_invalid": .init(recovery: "user_input", transient: false, retryAfterSeconds: nil),
        "native_helper_unavailable": .init(recovery: "environment", transient: false, retryAfterSeconds: nil),
        "native_helper_version_mismatch": .init(recovery: "environment", transient: false, retryAfterSeconds: nil),
        "native_helper_failed": .init(recovery: "environment", transient: true, retryAfterSeconds: 3),
        "native_helper_build_failed": .init(recovery: "environment", transient: false, retryAfterSeconds: nil),
        "subprocess_failed": .init(recovery: "retry", transient: true, retryAfterSeconds: 3),
        "command_timeout": .init(recovery: "retry", transient: true, retryAfterSeconds: 10),
        "mcp_bootstrap_failed": .init(recovery: "environment", transient: false, retryAfterSeconds: nil)
    ]

    static func metadata(for errorType: String) -> RecoveryMetadata {
        entries[errorType] ?? .init(recovery: "unknown", transient: false, retryAfterSeconds: nil)
    }
}
