#!/usr/bin/env python3

from __future__ import annotations

from typing import Any


ERROR_RECOVERY: dict[str, dict[str, Any]] = {
    "usage_error": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "tool_missing": {"recovery": "environment", "transient": False, "retry_after_seconds": None},
    "permission_denied": {"recovery": "permission", "transient": False, "retry_after_seconds": None},
    "accessibility_not_trusted": {"recovery": "permission", "transient": False, "retry_after_seconds": None},
    "trusted_fast_denied": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "path_violation": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "xcode_not_running": {"recovery": "environment", "transient": True, "retry_after_seconds": None},
    "no_workspace": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "multiple_workspaces_ambiguous": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "scheme_not_found": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "scheme_not_testable": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "destination_not_found": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "destination_ambiguous": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "xcode_ide_automation_failed": {"recovery": "retry", "transient": True, "retry_after_seconds": 5},
    "xcode_modal_blocking": {"recovery": "permission", "transient": False, "retry_after_seconds": None},
    "xcode_activation_failed": {"recovery": "retry", "transient": True, "retry_after_seconds": 3},
    "workspace_open_failed": {"recovery": "environment", "transient": False, "retry_after_seconds": None},
    "simulator_boot_failed": {"recovery": "retry", "transient": True, "retry_after_seconds": 5},
    "install_failed": {"recovery": "retry", "transient": True, "retry_after_seconds": 5},
    "launch_failed": {"recovery": "retry", "transient": True, "retry_after_seconds": 5},
    "xcresult_missing": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "xcresult_corrupt": {"recovery": "permanent", "transient": False, "retry_after_seconds": None},
    "cache_invalid": {"recovery": "user_input", "transient": False, "retry_after_seconds": None},
    "native_helper_unavailable": {"recovery": "environment", "transient": False, "retry_after_seconds": None},
    "native_helper_version_mismatch": {"recovery": "environment", "transient": False, "retry_after_seconds": None},
    "native_helper_failed": {"recovery": "environment", "transient": True, "retry_after_seconds": 3},
    "native_helper_build_failed": {"recovery": "environment", "transient": False, "retry_after_seconds": None},
    "subprocess_failed": {"recovery": "retry", "transient": True, "retry_after_seconds": 3},
    "command_timeout": {"recovery": "retry", "transient": True, "retry_after_seconds": 10},
    "mcp_bootstrap_failed": {"recovery": "environment", "transient": False, "retry_after_seconds": None},
}

UNKNOWN_RECOVERY = {"recovery": "unknown", "transient": False, "retry_after_seconds": None}


def recovery_for_error_type(error_type: str) -> dict[str, Any]:
    return dict(ERROR_RECOVERY.get(error_type, UNKNOWN_RECOVERY))
