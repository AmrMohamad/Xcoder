#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from xcode_common import EXIT_CODES, compact_output, emit_failure, emit_success, native_helper_path as resolve_native_helper_path, plugin_root, run_command, normalize_path
from xcode_ide_menu_catalog import (
    DESTRUCTIVE,
    EXTERNAL_EFFECT,
    MENU_ACTIONS,
    MENU_ACTIONS_BY_ID,
    UNSUPPORTED_DYNAMIC,
    MenuAction,
)


SCRIPT_TIMEOUT_PADDING = 20
VALID_ACTIONS = {"build", "clean", "test", "run", "debug", "stop"}
EXPECTED_DISTRIBUTION_STEP_TITLE = "Select a method for distribution:"
DEFAULT_MAX_SAFE_STEPS = 4
DISTRIBUTION_METHODS = [
    "App Store Connect",
    "TestFlight Internal Only",
    "Release Testing",
    "Enterprise",
    "Debugging",
    "Custom",
]
CUSTOM_DISTRIBUTION_ROUTES = [
    "App Store Connect",
    "Release Testing",
    "Enterprise",
    "Debugging",
]
CUSTOM_ROUTE_TITLE_PREFIXES = {
    "App Store Connect": "App Store Connect,",
    "Release Testing": "Release Testing,",
    "Enterprise": "Enterprise,",
    "Debugging": "Debugging,",
}
METHOD_DESCRIPTION_HINTS = {
    "App Store Connect": ["upload app to app store connect"],
    "TestFlight Internal Only": ["internal testing with testflight"],
    "Release Testing": ["ad hoc distribute to registered devices"],
    "Enterprise": ["distribute to an enterprise organization"],
    "Debugging": ["development signing to registered devices"],
    "Custom": ["use custom options"],
}
METHOD_CONFIRM_BUTTONS = {
    "App Store Connect": "Distribute",
    "TestFlight Internal Only": "Distribute",
    "Release Testing": "Distribute",
    "Enterprise": "Distribute",
    "Debugging": "Distribute",
    "Custom": "Next",
}
FINAL_DISTRIBUTION_ACTION_TITLES = {
    "Distribute",
    "Export",
    "Upload",
    "Submit",
}
SAFE_DISTRIBUTION_NAVIGATION_TITLES = {
    "Cancel",
    "Previous",
    "Back",
}
SAFE_PROBE_READY_TITLES = {
    "Next",
    *FINAL_DISTRIBUTION_ACTION_TITLES,
}
PHASE_KIND_METHOD_SELECTION = "method_selection"
PHASE_KIND_CUSTOM_METHOD_SELECTION = "custom_method_selection"
PHASE_KIND_CUSTOM_DESTINATION_SELECTION = "custom_destination_selection"
PHASE_KIND_CUSTOM_OPTIONS = "custom_options"
PHASE_KIND_REVIEW = "review"
PHASE_KIND_ERROR = "error"
PHASE_KIND_DOWNSTREAM = "downstream_distribution"
CUSTOM_DESTINATION_VALUES = {
    "upload": "Upload",
    "export": "Export",
}
CHECKBOX_OPTION_TITLES = {
    "strip_swift_symbols": "Strip Swift symbols",
    "include_manifest": "Include manifest for over-the-air installation",
}
PHASE_CATALOG: dict[str, dict[str, Any]] = {
    EXPECTED_DISTRIBUTION_STEP_TITLE: {
        "phase_id": "distribution_method_selection",
        "phase_kind": PHASE_KIND_METHOD_SELECTION,
        "route_context": {"top_level_method": None, "custom_route": None},
    },
    "Upload for App Store Connect:": {
        "phase_id": "upload_for_app_store_connect",
        "phase_kind": PHASE_KIND_DOWNSTREAM,
        "route_context": {"top_level_method": "App Store Connect", "custom_route": None},
    },
    "Upload for TestFlight (Internal Testing Only):": {
        "phase_id": "upload_for_testflight_internal_only",
        "phase_kind": PHASE_KIND_DOWNSTREAM,
        "route_context": {"top_level_method": "TestFlight Internal Only", "custom_route": None},
    },
    "Export for Release Testing (Ad Hoc):": {
        "phase_id": "export_for_release_testing_ad_hoc",
        "phase_kind": PHASE_KIND_DOWNSTREAM,
        "route_context": {"top_level_method": "Release Testing", "custom_route": None},
    },
    "Export for Enterprise Distribution:": {
        "phase_id": "export_for_enterprise_distribution",
        "phase_kind": PHASE_KIND_DOWNSTREAM,
        "route_context": {"top_level_method": "Enterprise", "custom_route": None},
    },
    "Export for Debugging (Release Testing):": {
        "phase_id": "export_for_debugging_release_testing",
        "phase_kind": PHASE_KIND_DOWNSTREAM,
        "route_context": {"top_level_method": "Debugging", "custom_route": None},
    },
    "Select a method of distribution:": {
        "phase_id": "custom_distribution_route_selection",
        "phase_kind": PHASE_KIND_CUSTOM_METHOD_SELECTION,
        "route_context": {"top_level_method": "Custom", "custom_route": None},
    },
    "Select a destination:": {
        "phase_id": "custom_app_store_connect_destination_selection",
        "phase_kind": PHASE_KIND_CUSTOM_DESTINATION_SELECTION,
        "route_context": {"top_level_method": "Custom", "custom_route": "App Store Connect"},
    },
    "Release Testing distribution options:": {
        "phase_id": "custom_release_testing_distribution_options",
        "phase_kind": PHASE_KIND_CUSTOM_OPTIONS,
        "route_context": {"top_level_method": "Custom", "custom_route": "Release Testing"},
    },
    "Enterprise distribution options:": {
        "phase_id": "custom_enterprise_distribution_options",
        "phase_kind": PHASE_KIND_CUSTOM_OPTIONS,
        "route_context": {"top_level_method": "Custom", "custom_route": "Enterprise"},
    },
    "Debugging distribution options:": {
        "phase_id": "custom_debugging_distribution_options",
        "phase_kind": PHASE_KIND_CUSTOM_OPTIONS,
        "route_context": {"top_level_method": "Custom", "custom_route": "Debugging"},
    },
    "Preparing app:": {
        "phase_id": "preparing_app",
        "phase_kind": PHASE_KIND_DOWNSTREAM,
        "route_context": {"top_level_method": None, "custom_route": None},
    },
    "Preparing app record:": {
        "phase_id": "preparing_app_record",
        "phase_kind": PHASE_KIND_DOWNSTREAM,
        "route_context": {"top_level_method": None, "custom_route": None},
    },
    "Review MazayaStg.ipa content:": {
        "phase_id": "review_ipa_content",
        "phase_kind": PHASE_KIND_REVIEW,
        "route_context": {"top_level_method": None, "custom_route": None},
    },
    "An error was encountered:": {
        "phase_id": "distribution_error",
        "phase_kind": PHASE_KIND_ERROR,
        "route_context": {"top_level_method": None, "custom_route": None},
    },
}


def apple_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_osascript(script: str, timeout: int = 60) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["osascript", "-"],
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"osascript timed out after {timeout}s",
        }


def parse_kv(stdout: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or "\t" not in line:
            continue
        key, value = line.split("\t", 1)
        if value.lower() == "true":
            values[key] = True
        elif value.lower() == "false":
            values[key] = False
        else:
            try:
                values[key] = int(value)
            except ValueError:
                values[key] = value
    return values


def payload(
    status: str,
    summary: str,
    *,
    data: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    exit_code: int = 0,
    error_type: str | None = None,
) -> int:
    command_name = "ide"
    details = data or {}
    if status == "success":
        return emit_success(command_name, summary, details=details, artifacts=artifacts, warnings=warnings, next_actions=next_actions)
    if status == "timeout":
        return emit_failure(
            command_name,
            "command_timeout",
            summary,
            details=details,
            artifacts=artifacts,
            warnings=warnings,
            next_actions=next_actions,
            exit_code=EXIT_CODES["command_timeout"],
        )
    return emit_failure(
        command_name,
        error_type or "xcode_ide_automation_failed",
        summary,
        details=details,
        artifacts=artifacts,
        warnings=warnings,
        errors=warnings or [],
        next_actions=next_actions,
        exit_code=exit_code or EXIT_CODES.get(error_type or "xcode_ide_automation_failed", 1),
    )


def classify_osascript_error(result: dict[str, Any]) -> tuple[str, int]:
    text = f"{result.get('stdout') or ''}\n{result.get('stderr') or ''}"
    if result.get("exit_code") == 124:
        return "command_timeout", EXIT_CODES["command_timeout"]
    markers = {
        "XCODE_PLUGIN_XCODE_NOT_RUNNING": "xcode_not_running",
        "XCODE_PLUGIN_NO_WORKSPACE": "no_workspace",
        "XCODE_PLUGIN_MULTIPLE_WORKSPACES": "multiple_workspaces_ambiguous",
        "XCODE_PLUGIN_WORKSPACE_NOT_FOUND": "no_workspace",
        "XCODE_PLUGIN_SCHEME_NOT_FOUND": "scheme_not_found",
        "XCODE_PLUGIN_DESTINATION_NOT_FOUND": "destination_not_found",
        "XCODE_PLUGIN_DESTINATION_AMBIGUOUS": "destination_ambiguous",
        "XCODE_PLUGIN_WORKSPACE_PATH_UNREADABLE": "xcode_ide_automation_failed",
        "XCODE_PLUGIN_MENU_PATH_NOT_FOUND": "xcode_menu_item_not_found",
        "XCODE_PLUGIN_MENU_ITEM_DISABLED": "xcode_menu_item_disabled",
    }
    for marker, error_type in markers.items():
        if marker in text:
            return error_type, EXIT_CODES.get(error_type, 1)
    return "xcode_ide_automation_failed", result.get("exit_code") or EXIT_CODES["xcode_ide_automation_failed"]


def finish_from_osascript(
    result: dict[str, Any],
    success_summary: str,
    *,
    failure_summary: str = "Xcode IDE automation failed",
    next_actions: list[str] | None = None,
    extra_warnings: list[str] | None = None,
    extra_data: dict[str, Any] | None = None,
) -> int:
    data = parse_kv(result["stdout"])
    if extra_data:
        data.update(extra_data)
    warnings: list[str] = list(extra_warnings or [])
    if result["stderr"].strip():
        warnings.append(result["stderr"].strip())
    if result["exit_code"] != 0:
        error_type, mapped_exit = classify_osascript_error(result)
        return payload(
            "failure",
            failure_summary,
            data=data,
            warnings=warnings or [result["stderr"].strip()],
            next_actions=next_actions
            or [
                "Grant Automation permission for Codex/Terminal to control Xcode if macOS prompts.",
                "Open an Xcode workspace or project before using workspace-specific commands.",
            ],
            exit_code=mapped_exit,
            error_type=error_type,
        )
    return payload("success", success_summary, data=data, warnings=warnings, next_actions=next_actions)


def native_helper_path() -> Path:
    return resolve_native_helper_path()


def native_preflight(*, require: bool, include_ax: bool) -> tuple[int | None, list[str], dict[str, Any]]:
    helper = native_helper_path()
    details: dict[str, Any] = {"helper_path": str(helper), "required": require, "ax_checked": include_ax}
    warnings: list[str] = []
    if not helper.exists() or not helper.is_file() or not (helper.stat().st_mode & 0o111):
        message = "Native helper is not built in bin/XcodeNativeHelper.app or bin/xcode-native-helper."
        if require:
            return (
                payload(
                    "failure",
                    "Native helper is required but unavailable",
                    data=details,
                    warnings=[message],
                    next_actions=["Build native/XcodeNativeHelper, then run bin/xcode native helper bundle --json."],
                    exit_code=EXIT_CODES["native_helper_unavailable"],
                    error_type="native_helper_unavailable",
                ),
                warnings,
                details,
            )
        warnings.append(message)
        return None, warnings, details

    state = run_command([str(helper), "app", "xcode-state", "--json"], timeout_seconds=20)
    details["xcode_state_exit_code"] = state["exit_code"]
    if state["exit_code"] == 0:
        try:
            details["xcode_state"] = json.loads(state["stdout"]).get("summary")
        except json.JSONDecodeError:
            warnings.append("Native helper xcode-state output was not valid JSON.")
    elif require:
        return (
            payload(
                "failure",
                "Native helper Xcode state preflight failed",
                data=details,
                warnings=[compact_output(state["stderr"] or state["stdout"])],
                exit_code=EXIT_CODES["native_helper_failed"],
                error_type="native_helper_failed",
            ),
            warnings,
            details,
        )
    else:
        warnings.append("Native helper Xcode state preflight failed; continuing with AppleScript/JXA.")

    if not include_ax:
        return None, warnings, details

    ax = run_command([str(plugin_root() / "bin" / "xcode"), "native", "ax", "xcode-windows", "--json"], timeout_seconds=25)
    details["ax_exit_code"] = ax["exit_code"]
    try:
        ax_json = json.loads(ax["stdout"])
        details["ax"] = ax_json.get("summary")
    except json.JSONDecodeError:
        ax_json = None
        if ax["stdout"].strip() or ax["stderr"].strip():
            warnings.append("Native helper AX output was not valid JSON.")

    if ax["exit_code"] == EXIT_CODES["permission_denied"]:
        message = "Native helper could not inspect Xcode windows because Accessibility is not trusted."
        permission_actions = [
            "Use mcp__xcode__.xcode_native_permissions_request, or run bin/xcode native permissions request --json, then approve XcodeNativeHelper.app in System Settings.",
            "Retry the IDE command after xcode_native_permissions_status reports accessibility_trusted=true.",
        ]
        if require:
            return (
                payload(
                    "failure",
                    message,
                    data=details,
                    next_actions=permission_actions,
                    exit_code=EXIT_CODES["permission_denied"],
                    error_type="permission_denied",
                ),
                warnings,
                details,
            )
        warnings.append(message)
        details["permission_recovery"] = permission_actions
        return None, warnings, details

    if ax["exit_code"] != 0:
        message = "Native helper AX preflight failed."
        error_type = "native_helper_failed"
        if isinstance(ax_json, dict):
            error_type = str(ax_json.get("error_type") or error_type)
            if isinstance(ax_json.get("summary"), str):
                message = str(ax_json["summary"])
        if require:
            return (
                payload(
                    "failure",
                    message,
                    data=details,
                    warnings=[compact_output(ax["stderr"] or ax["stdout"])],
                    exit_code=EXIT_CODES.get(error_type, EXIT_CODES["native_helper_failed"]),
                    error_type=error_type,
                ),
                warnings,
                details,
            )
        warnings.append(message)
        return None, warnings, details

    summary = ax_json.get("summary") if isinstance(ax_json, dict) else {}
    blockers = summary.get("modal_blockers") if isinstance(summary, dict) else None
    if blockers:
        return (
            payload(
                "failure",
                "Xcode has a modal window or sheet that may block IDE automation",
                data={"native_preflight": details, "modal_blockers": blockers},
                warnings=warnings,
                next_actions=["Bring Xcode forward and resolve the blocking dialog, then retry the IDE command."],
                exit_code=EXIT_CODES["xcode_modal_blocking"],
                error_type="xcode_modal_blocking",
            ),
            warnings,
            details,
        )
    return None, warnings, details


def workspace_selector_script(workspace_path: str | None = None) -> str:
    if workspace_path:
        requested_original = str(Path(workspace_path).expanduser())
        requested_normalized = str(normalize_path(workspace_path))
    else:
        requested_original = ""
        requested_normalized = ""
    return f"""
set requestedWorkspacePath to {apple_string(requested_normalized)}
set requestedWorkspacePathOriginal to {apple_string(requested_original)}
set requestedWorkspacePathTrimmed to requestedWorkspacePath
if requestedWorkspacePathTrimmed ends with "/" then set requestedWorkspacePathTrimmed to text 1 thru -2 of requestedWorkspacePathTrimmed
if (count workspace documents) is 0 then error "XCODE_PLUGIN_NO_WORKSPACE"
if requestedWorkspacePath is "" then
    if (count workspace documents) > 1 then error "XCODE_PLUGIN_MULTIPLE_WORKSPACES"
    set w to active workspace document
else
    set matchedWorkspace to missing value
    repeat with candidateWorkspace in workspace documents
        set candidatePath to ""
        try
            set candidatePath to POSIX path of (file of candidateWorkspace as alias)
        on error
            error "XCODE_PLUGIN_WORKSPACE_PATH_UNREADABLE"
        end try
        try
            set candidateNormalized to do shell script "/usr/bin/realpath " & quoted form of candidatePath
        on error
            set candidateNormalized to candidatePath
        end try
        set candidateNormalizedTrimmed to candidateNormalized
        if candidateNormalizedTrimmed ends with "/" then set candidateNormalizedTrimmed to text 1 thru -2 of candidateNormalizedTrimmed
        if candidateNormalized is requestedWorkspacePath or candidateNormalizedTrimmed is requestedWorkspacePathTrimmed or candidatePath is requestedWorkspacePathOriginal then
            set matchedWorkspace to candidateWorkspace
            exit repeat
        end if
    end repeat
    if matchedWorkspace is missing value then error "XCODE_PLUGIN_WORKSPACE_NOT_FOUND"
    set w to matchedWorkspace
end if
"""


def status_command() -> int:
    script = """
set out to ""
tell application "System Events"
    set xcodeRunning to exists process "Xcode"
    set out to out & "running\t" & (xcodeRunning as text) & linefeed
    if xcodeRunning then
        set out to out & "frontmost\t" & ((frontmost of process "Xcode") as text) & linefeed
    end if
end tell
if xcodeRunning then
    tell application "Xcode"
        set out to out & "workspace_count\t" & ((count workspace documents) as text) & linefeed
        try
            set w to active workspace document
            set out to out & "active_workspace_name\t" & (name of w as text) & linefeed
            set out to out & "active_workspace_loaded\t" & ((loaded of w) as text) & linefeed
            try
                set out to out & "active_workspace_path\t" & (POSIX path of (file of w as alias)) & linefeed
            end try
        end try
    end tell
end if
return out
"""
    return finish_from_osascript(result=run_osascript(script), success_summary="Xcode process state inspected")


def activate_command() -> int:
    script = """
tell application "Xcode" to activate
delay 0.2
set out to ""
tell application "System Events"
    set out to out & "running\t" & ((exists process "Xcode") as text) & linefeed
    set out to out & "frontmost\t" & ((frontmost of process "Xcode") as text) & linefeed
end tell
tell application "Xcode"
    set out to out & "workspace_count\t" & ((count workspace documents) as text) & linefeed
end tell
return out
"""
    return finish_from_osascript(result=run_osascript(script), success_summary="Xcode activated")


def open_workspace_command(path: str, timeout_seconds: int) -> int:
    resolved = str(Path(path).expanduser())
    if not Path(resolved).exists():
        return payload(
            "failure",
            "Workspace/project path does not exist",
            data={"path": resolved},
            next_actions=["Pass an existing .xcodeproj or .xcworkspace path."],
            exit_code=EXIT_CODES["workspace_open_failed"],
            error_type="workspace_open_failed",
        )
    script = f"""
tell application "Xcode"
    activate
    open POSIX file {apple_string(resolved)}
    set w to active workspace document
    repeat {max(timeout_seconds * 2, 1)} times
        if loaded of w is true then exit repeat
        delay 0.5
    end repeat
    set out to "active_workspace_name\t" & (name of w as text) & linefeed
    set out to out & "active_workspace_loaded\t" & ((loaded of w) as text) & linefeed
    try
        set out to out & "active_workspace_path\t" & (POSIX path of (file of w as alias)) & linefeed
    end try
    set out to out & "scheme_count\t" & ((count schemes of w) as text) & linefeed
    set out to out & "destination_count\t" & ((count run destinations of w) as text) & linefeed
    return out
end tell
"""
    return finish_from_osascript(
        result=run_osascript(script, timeout=timeout_seconds + SCRIPT_TIMEOUT_PADDING),
        success_summary="Workspace opened in Xcode",
    )


def list_workspaces_command() -> int:
    script = """
tell application "Xcode"
    set out to ""
    repeat with w in workspace documents
        set workspaceName to ""
        set workspaceLoaded to ""
        set workspacePath to ""
        set workspaceNormalized to ""
        try
            set workspaceName to name of w as text
        end try
        try
            set workspaceLoaded to loaded of w as text
        end try
        try
            set workspacePath to POSIX path of (file of w as alias)
            try
                set workspaceNormalized to do shell script "/usr/bin/realpath " & quoted form of workspacePath
            on error
                set workspaceNormalized to workspacePath
            end try
        end try
        set out to out & "workspace\t" & workspaceName & tab & workspaceLoaded & tab & workspacePath & tab & workspaceNormalized & linefeed
    end repeat
    return out
end tell
"""
    result = run_osascript(script)
    if result["exit_code"] == 0:
        workspaces = []
        for line in result["stdout"].splitlines():
            if line.startswith("workspace\t"):
                _, body = line.split("\t", 1)
                parts = (body.split("\t") + ["", "", "", ""])[:4]
                workspaces.append({"name": parts[0], "loaded": parts[1].lower() == "true", "path": parts[2], "normalized_path": parts[3]})
        return payload("success", "Xcode workspaces listed", data={"workspaces": workspaces})
    return finish_from_osascript(result, "Xcode workspaces listed", failure_summary="Unable to list Xcode workspaces")


def workspace_info_command(workspace_path: str | None = None) -> int:
    selector = workspace_selector_script(workspace_path)
    script = f"""
tell application "Xcode"
    {selector}
    set out to "active_workspace_name\t" & (name of w as text) & linefeed
    set out to out & "active_workspace_loaded\t" & ((loaded of w) as text) & linefeed
    try
        set out to out & "active_workspace_path\t" & (POSIX path of (file of w as alias)) & linefeed
    end try
    try
        set out to out & "active_scheme\t" & (name of active scheme of w as text) & linefeed
    on error errMsg
        set out to out & "active_scheme_error\t" & errMsg & linefeed
    end try
    try
        set d to active run destination of w
        set out to out & "active_destination_name\t" & (name of d as text) & linefeed
        set out to out & "active_destination_platform\t" & (platform of d as text) & linefeed
        try
            set out to out & "active_destination_device\t" & (name of device of d as text) & linefeed
        end try
    on error errMsg
        set out to out & "active_destination_error\t" & errMsg & linefeed
    end try
    set out to out & "scheme_count\t" & ((count schemes of w) as text) & linefeed
    set out to out & "destination_count\t" & ((count run destinations of w) as text) & linefeed
    return out
end tell
"""
    return finish_from_osascript(result=run_osascript(script), success_summary="Active Xcode workspace inspected")


def preflight_command(
    *,
    workspace_path: str | None = None,
    scheme: str | None = None,
    destination_name: str | None = None,
    destination_id: str | None = None,
    require_native_preflight: bool = False,
) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=require_native_preflight, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    selector = workspace_selector_script(workspace_path)
    scheme_line = f"set requestedScheme to {apple_string(scheme or '')}"
    destination_name_line = f"set requestedDestinationName to {apple_string(destination_name or '')}"
    destination_id_line = f"set requestedDestinationId to {apple_string(destination_id or '')}"
    script = f"""
tell application "Xcode"
    {selector}
    {scheme_line}
    {destination_name_line}
    {destination_id_line}
    set out to "workspace_name\t" & (name of w as text) & linefeed
    set out to out & "workspace_loaded\t" & ((loaded of w) as text) & linefeed
    try
        set out to out & "workspace_path\t" & (POSIX path of (file of w as alias)) & linefeed
    end try

    set schemeFound to false
    if requestedScheme is "" then
        try
            set out to out & "active_scheme\t" & (name of active scheme of w as text) & linefeed
            set schemeFound to true
        end try
    else
        repeat with s in schemes of w
            if (name of s as text) is requestedScheme then set schemeFound to true
        end repeat
        set out to out & "requested_scheme\t" & requestedScheme & linefeed
    end if
    set out to out & "scheme_available\t" & (schemeFound as text) & linefeed
    if schemeFound is false then error "XCODE_PLUGIN_SCHEME_NOT_FOUND"

    set destinationFound to false
    set destinationMatchCount to 0
    if requestedDestinationName is "" and requestedDestinationId is "" then
        try
            set d to active run destination of w
            set out to out & "active_destination_name\t" & (name of d as text) & linefeed
            set out to out & "active_destination_platform\t" & (platform of d as text) & linefeed
            set destinationFound to true
            set destinationMatchCount to 1
        end try
    else
        repeat with d in run destinations of w
            set nameMatches to false
            set idMatches to false
            try
                if requestedDestinationId is not "" and (device identifier of device of d as text) is requestedDestinationId then set idMatches to true
            end try
            try
                if requestedDestinationId is "" and requestedDestinationName is not "" and (name of d as text) is requestedDestinationName then set nameMatches to true
            end try
            if idMatches or nameMatches then
                set destinationFound to true
                set destinationMatchCount to destinationMatchCount + 1
                try
                    set out to out & "matched_destination_name\t" & (name of d as text) & linefeed
                end try
                try
                    set out to out & "matched_destination_platform\t" & (platform of d as text) & linefeed
                end try
            end if
        end repeat
    end if
    set out to out & "destination_available\t" & (destinationFound as text) & linefeed
    set out to out & "destination_match_count\t" & (destinationMatchCount as text) & linefeed
    if destinationMatchCount is 0 then error "XCODE_PLUGIN_DESTINATION_NOT_FOUND"
    if destinationMatchCount > 1 then error "XCODE_PLUGIN_DESTINATION_AMBIGUOUS"
    return out
end tell
"""
    return finish_from_osascript(
        result=run_osascript(script),
        success_summary="Xcode IDE preflight completed",
        failure_summary="Xcode IDE preflight failed",
        extra_warnings=preflight_warnings,
        extra_data={"native_preflight": preflight_details} if preflight_details else None,
        next_actions=[
            "Resolve any modal blockers before running IDE actions.",
            "Pass explicit scheme and destination identifiers when multiple workspaces or destinations are open.",
        ],
    )


def list_schemes_command(workspace_path: str | None = None) -> int:
    selector = workspace_selector_script(workspace_path)
    script = f"""
tell application "Xcode"
    {selector}
    set out to ""
    repeat with s in schemes of w
        set out to out & "scheme\t" & (name of s as text) & linefeed
    end repeat
    return out
end tell
"""
    result = run_osascript(script)
    if result["exit_code"] == 0:
        schemes = []
        for line in result["stdout"].splitlines():
            if line.startswith("scheme\t"):
                schemes.append({"name": line.split("\t", 1)[1]})
        return payload("success", "Xcode schemes listed", data={"schemes": schemes})
    return finish_from_osascript(result, "Xcode schemes listed", failure_summary="Unable to list Xcode schemes")


def list_destinations_command(workspace_path: str | None = None) -> int:
    selector = workspace_selector_script(workspace_path)
    script = f"""
tell application "Xcode"
    {selector}
    set out to ""
    repeat with d in run destinations of w
        set destinationName to ""
        set destinationPlatform to ""
        set destinationArchitecture to ""
        set destinationDevice to ""
        set destinationOS to ""
        try
            set destinationName to name of d as text
        end try
        try
            set destinationPlatform to platform of d as text
        end try
        try
            set destinationArchitecture to architecture of d as text
        end try
        try
            set destinationDevice to name of device of d as text
            set destinationOS to operating system version of device of d as text
        end try
        set out to out & "destination\t" & destinationName & tab & destinationPlatform & tab & destinationArchitecture & tab & destinationDevice & tab & destinationOS & linefeed
    end repeat
    return out
end tell
"""
    result = run_osascript(script)
    if result["exit_code"] == 0:
        destinations = []
        for line in result["stdout"].splitlines():
            if not line.startswith("destination\t"):
                continue
            _, body = line.split("\t", 1)
            parts = (body.split("\t") + ["", "", "", "", ""])[:5]
            destinations.append(
                {
                    "name": parts[0],
                    "platform": parts[1],
                    "architecture": parts[2],
                    "device": parts[3],
                    "os": parts[4],
                }
            )
        return payload("success", "Xcode run destinations listed", data={"destinations": destinations})
    return finish_from_osascript(result, "Xcode run destinations listed", failure_summary="Unable to list Xcode run destinations")


def menu_catalog_command() -> int:
    return payload(
        "success",
        "Xcode IDE menu catalog listed",
        data={
            "menu_action_count": len(MENU_ACTIONS),
            "safety_classes": sorted({item.safety for item in MENU_ACTIONS}),
            "actions": [item.as_dict() for item in MENU_ACTIONS],
        },
    )


def menu_blocked_response(action_item: MenuAction, reason: str, next_actions: list[str] | None = None) -> int:
    data = {"action": action_item.as_dict(), "blocked_reason": reason}
    return payload(
        "failure",
        "Xcode menu action is blocked by the typed menu safety policy",
        data=data,
        next_actions=next_actions
        or [
            "Use xcode_ide_menu_catalog to inspect supported menu actions and safety classes.",
            "Use the preferred typed Xcoder tool when preferred_tool is present.",
        ],
        exit_code=EXIT_CODES["xcode_menu_action_blocked"],
        error_type="xcode_menu_action_blocked",
    )


def menu_press_script(action_item: MenuAction) -> str:
    path = list(action_item.menu_path)
    root = path[0]
    lines = [
        f"set actionId to {apple_string(action_item.action_id)}",
        f"set menuPathText to {apple_string(' > '.join(path))}",
        'tell application "Xcode" to activate',
        "delay 0.1",
        'tell application "System Events"',
        '    if not (exists process "Xcode") then error "XCODE_PLUGIN_XCODE_NOT_RUNNING"',
        '    tell process "Xcode"',
        "        set frontmost to true",
        f"        if not (exists menu bar item {apple_string(root)} of menu bar 1) then error \"XCODE_PLUGIN_MENU_PATH_NOT_FOUND\"",
        f"        set currentMenu to menu 1 of menu bar item {apple_string(root)} of menu bar 1",
    ]
    for index, label in enumerate(path[1:], start=1):
        lines.append(f"        if not (exists menu item {apple_string(label)} of currentMenu) then error \"XCODE_PLUGIN_MENU_PATH_NOT_FOUND\"")
        lines.append(f"        set targetItem to menu item {apple_string(label)} of currentMenu")
        if index < len(path) - 1:
            lines.append('        if not (exists menu 1 of targetItem) then error "XCODE_PLUGIN_MENU_PATH_NOT_FOUND"')
            lines.append("        set currentMenu to menu 1 of targetItem")
    lines.extend(
        [
            "        set itemEnabled to true",
            "        try",
            "            set itemEnabled to enabled of targetItem",
            "        end try",
            '        if itemEnabled is false then error "XCODE_PLUGIN_MENU_ITEM_DISABLED"',
            '        perform action "AXPress" of targetItem',
            '        return "action_id\t" & actionId & linefeed & "menu_path\t" & menuPathText & linefeed & "performed\ttrue" & linefeed & "enabled_before_press\t" & (itemEnabled as text) & linefeed',
            "    end tell",
            "end tell",
        ]
    )
    return "\n".join(lines)


def native_menu_press(action_item: MenuAction) -> dict[str, Any]:
    menu_path_json = json.dumps(list(action_item.menu_path), separators=(",", ":"))
    return run_command(
        [
            str(plugin_root() / "bin" / "xcode"),
            "native",
            "ax",
            "press-menu",
            "--menu-path-json",
            menu_path_json,
            "--json",
        ],
        timeout_seconds=20,
    )


def native_press_menu_path(menu_path: list[str]) -> dict[str, Any]:
    return run_command(
        [
            str(plugin_root() / "bin" / "xcode"),
            "native",
            "ax",
            "press-menu",
            "--menu-path-json",
            json.dumps(menu_path, separators=(",", ":")),
            "--json",
        ],
        timeout_seconds=20,
    )


def native_ax_inspect(*, window_title_contains: str | None = None, max_depth: int = 4) -> dict[str, Any]:
    command = [
        str(plugin_root() / "bin" / "xcode"),
        "native",
        "ax",
        "inspect",
        "--max-depth",
        str(max_depth),
        "--json",
    ]
    if window_title_contains:
        command.extend(["--window-title-contains", window_title_contains])
    return run_command(command, timeout_seconds=25)


def native_press_button(*, title: str, window_title_contains: str | None = None) -> dict[str, Any]:
    command = [
        str(plugin_root() / "bin" / "xcode"),
        "native",
        "ax",
        "press-button",
        "--title",
        title,
        "--json",
    ]
    if window_title_contains:
        command.extend(["--window-title-contains", window_title_contains])
    return run_command(command, timeout_seconds=20)


def native_press_control(*, title: str, role: str, window_title_contains: str | None = None) -> dict[str, Any]:
    command = [
        str(plugin_root() / "bin" / "xcode"),
        "native",
        "ax",
        "press-control",
        "--role",
        role,
        "--title",
        title,
        "--json",
    ]
    if window_title_contains:
        command.extend(["--window-title-contains", window_title_contains])
    return run_command(command, timeout_seconds=20)


def parse_native_json(result: dict[str, Any]) -> dict[str, Any] | None:
    try:
        parsed = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def finish_native_result(
    result: dict[str, Any],
    *,
    success_summary: str,
    failure_summary: str,
    extra_data: dict[str, Any] | None = None,
    next_actions: list[str] | None = None,
) -> int:
    native_payload = parse_native_json(result)
    data = dict(extra_data or {})
    if native_payload is not None:
        data["native"] = native_payload
    else:
        data["stdout_tail"] = compact_output(result["stdout"])
        data["stderr_tail"] = compact_output(result["stderr"])
    if result["exit_code"] == 0 and isinstance(native_payload, dict) and native_payload.get("ok") is True:
        return payload("success", success_summary, data=data, next_actions=next_actions)
    error_type = "xcode_ide_automation_failed"
    if isinstance(native_payload, dict):
        error_type = str(native_payload.get("error_type") or error_type)
    return payload(
        "failure",
        failure_summary,
        data=data,
        warnings=[compact_output(result["stderr"])] if result["stderr"].strip() else [],
        next_actions=next_actions,
        exit_code=EXIT_CODES.get(error_type, EXIT_CODES["xcode_ide_automation_failed"]),
        error_type=error_type,
    )


def iter_ax_nodes(node: dict[str, Any]) -> Any:
    yield node
    for child in node.get("children", []):
        if isinstance(child, dict):
            yield from iter_ax_nodes(child)


def find_ax_nodes(node: dict[str, Any], *, role: str | None = None, subrole: str | None = None) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for item in iter_ax_nodes(node):
        if role is not None and item.get("role") != role:
            continue
        if subrole is not None and item.get("subrole") != subrole:
            continue
        matches.append(item)
    return matches


def infer_selected_distribution_method(method_buttons: list[dict[str, Any]], description_text: str) -> str | None:
    for item in method_buttons:
        if item.get("selected") is True:
            return str(item["method"])
    lowered = description_text.lower()
    for method, hints in METHOD_DESCRIPTION_HINTS.items():
        if any(hint in lowered for hint in hints):
            return method
    for item in method_buttons:
        method = str(item["method"])
        if method.lower() in lowered:
            return method
    return None


def parse_distribution_sheet(native_payload: dict[str, Any]) -> dict[str, Any] | None:
    summary = native_payload.get("summary")
    if not isinstance(summary, dict):
        return None
    windows = summary.get("windows")
    if not isinstance(windows, list):
        return None
    for window in windows:
        if not isinstance(window, dict):
            continue
        tree = window.get("tree")
        if not isinstance(tree, dict):
            continue
        sheets = find_ax_nodes(tree, role="AXSheet")
        for sheet in sheets:
            step_title = ""
            title_nodes = [
                node for node in iter_ax_nodes(sheet)
                if node.get("identifier") == "Distribution Step Title"
                or node.get("description") == "Distribution Step Title"
            ]
            if title_nodes:
                step_title = str(title_nodes[0].get("value") or "")

            method_buttons: list[dict[str, Any]] = []
            for node in find_ax_nodes(sheet, role="AXButton"):
                description = str(node.get("description") or "").strip()
                if description in DISTRIBUTION_METHODS:
                    method_buttons.append(
                        {
                            "method": description,
                            "enabled": bool(node.get("enabled", False)),
                            "selected": bool(node.get("selected", False)),
                        }
                    )
            if not method_buttons:
                continue

            navigation_buttons = []
            for node in find_ax_nodes(sheet, role="AXButton"):
                title = str(node.get("title") or "").strip()
                if title:
                    navigation_buttons.append(
                        {
                            "title": title,
                            "enabled": bool(node.get("enabled", False)),
                        }
                    )

            static_values = [
                str(node.get("value") or "").strip()
                for node in find_ax_nodes(sheet, role="AXStaticText")
                if str(node.get("value") or "").strip()
            ]
            filtered_values = [value for value in static_values if value != step_title and value not in DISTRIBUTION_METHODS]
            description_text = next((value for value in filtered_values if value.startswith("Use ")), "")
            if not description_text and len(filtered_values) > 4:
                description_text = filtered_values[-1]
            identity_values = [value for value in filtered_values if value != description_text]
            app_identity = {
                "product_name": identity_values[0] if len(identity_values) > 0 else "",
                "bundle_identifier": identity_values[1] if len(identity_values) > 1 else "",
                "version": identity_values[2] if len(identity_values) > 2 else "",
                "platform": identity_values[3] if len(identity_values) > 3 else "",
            }
            return {
                "phase_id": "distribution_method_selection",
                "step_title": step_title,
                "methods": method_buttons,
                "selected_method": infer_selected_distribution_method(method_buttons, description_text),
                "navigation_buttons": navigation_buttons,
                "description_text": description_text,
                "app_identity": app_identity,
                "window_title": str(window.get("title") or ""),
            }
    return None


def validate_distribution_sheet(sheet: dict[str, Any] | None) -> str | None:
    if sheet is None:
        return "Xcode Organizer distribution sheet was not found"
    if sheet.get("step_title") != EXPECTED_DISTRIBUTION_STEP_TITLE:
        return "Organizer is on a different distribution phase than the method-selection sheet"
    return None


def distribution_navigation_button(sheet: dict[str, Any], title: str) -> dict[str, Any] | None:
    for button in sheet.get("navigation_buttons", []):
        if button.get("title") == title:
            return button
    return None


def phase_id_from_title(step_title: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in step_title.strip(":"))
    return "_".join(part for part in cleaned.split("_") if part) or "unknown_distribution_phase"


def infer_custom_route_from_title(title: str) -> str | None:
    for route, prefix in CUSTOM_ROUTE_TITLE_PREFIXES.items():
        if title.startswith(prefix):
            return route
    return None


def phase_definition(step_title: str) -> dict[str, Any] | None:
    return PHASE_CATALOG.get(step_title)


def checkbox_value(node: dict[str, Any]) -> bool:
    value = str(node.get("value") or "").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    return bool(node.get("selected", False))


def ax_bool_from_value(value: str, fallback: bool) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes"}:
        return True
    if lowered in {"0", "false", "no"}:
        return False
    return fallback


def normalize_option_control(
    phase_kind: str,
    route_context: dict[str, Any],
    role: str,
    title: str,
    value: str,
    *,
    enabled: bool,
    selected: bool,
) -> dict[str, Any] | None:
    if role == "AXRadioButton" and route_context.get("custom_route") == "App Store Connect":
        for option_value, option_title in CUSTOM_DESTINATION_VALUES.items():
            if title == option_title:
                normalized_selected = ax_bool_from_value(value, selected)
                return {
                    "option_id": "custom_destination",
                    "value": option_value,
                    "display_title": title,
                    "enabled": enabled,
                    "selected": normalized_selected,
                }
    if role == "AXCheckBox":
        for option_id, option_title in CHECKBOX_OPTION_TITLES.items():
            if title == option_title:
                return {
                    "option_id": option_id,
                    "value": checkbox_value({"value": value, "selected": selected}),
                    "display_title": title,
                    "enabled": enabled,
                    "selected": selected,
                }
    return None


def selected_options_from_controls(controls: list[dict[str, Any]]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for control in controls:
        option_id = control.get("option_id")
        if not option_id:
            continue
        if control.get("role") == "AXRadioButton":
            if control.get("selected") is True:
                selected[str(option_id)] = control.get("value")
        else:
            selected[str(option_id)] = control.get("value")
    return selected


def parse_organizer_distribution_phase(native_payload: dict[str, Any]) -> dict[str, Any] | None:
    method_sheet = parse_distribution_sheet(native_payload)
    if method_sheet is not None:
        return {
            **method_sheet,
            "phase_kind": PHASE_KIND_METHOD_SELECTION,
            "recognized": True,
            "route_context": {"top_level_method": method_sheet.get("selected_method"), "custom_route": None},
            "selected_options": {},
            "error_messages": [],
            "warnings": [],
            "guarded_final_actions": [],
        }

    summary = native_payload.get("summary")
    if not isinstance(summary, dict):
        return None
    windows = summary.get("windows")
    if not isinstance(windows, list):
        return None

    for window in windows:
        if not isinstance(window, dict):
            continue
        tree = window.get("tree")
        if not isinstance(tree, dict):
            continue
        for sheet in find_ax_nodes(tree, role="AXSheet"):
            static_values = [
                str(node.get("value") or "").strip()
                for node in find_ax_nodes(sheet, role="AXStaticText")
                if str(node.get("value") or "").strip()
            ]
            title_nodes = [
                node for node in iter_ax_nodes(sheet)
                if node.get("identifier") == "Distribution Step Title"
                or node.get("description") == "Distribution Step Title"
            ]
            step_title = str(title_nodes[0].get("value") or "").strip() if title_nodes else ""
            if not step_title:
                step_title = next((value for value in static_values if value.endswith(":")), "")
            if not step_title and not static_values:
                continue

            phase_info = phase_definition(step_title)
            buttons: list[dict[str, Any]] = []
            for node in find_ax_nodes(sheet, role="AXButton"):
                title = str(node.get("title") or node.get("description") or "").strip()
                if title:
                    buttons.append(
                        {
                            "title": title,
                            "enabled": bool(node.get("enabled", False)),
                            "selected": bool(node.get("selected", False)),
                        }
                    )
            controls: list[dict[str, Any]] = []
            custom_routes: list[dict[str, Any]] = []
            for node in iter_ax_nodes(sheet):
                role = str(node.get("role") or "")
                if role not in {"AXCheckBox", "AXPopUpButton", "AXTextField", "AXRadioButton"}:
                    continue
                title = str(node.get("title") or node.get("description") or "").strip()
                value = str(node.get("value") or "").strip()
                enabled = bool(node.get("enabled", False))
                selected = bool(node.get("selected", False))
                control: dict[str, Any] = {
                    "role": role,
                    "title": title,
                    "value": value,
                    "enabled": enabled,
                    "selected": selected,
                }
                route_context = dict((phase_info or {}).get("route_context") or {})
                normalized = normalize_option_control(
                    (phase_info or {}).get("phase_kind") or PHASE_KIND_DOWNSTREAM,
                    route_context,
                    role,
                    title,
                    value,
                    enabled=enabled,
                    selected=selected,
                )
                if normalized is not None:
                    control.update(normalized)
                controls.append(control)
                if role == "AXRadioButton":
                    route = infer_custom_route_from_title(title)
                    if route is not None:
                        custom_routes.append(
                            {
                                "route": route,
                                "title": title,
                                "enabled": bool(node.get("enabled", False)),
                                "selected": bool(node.get("selected", False)),
                            }
                        )

            guarded_final_actions = [
                button for button in buttons
                if button.get("enabled") is True and str(button.get("title") or "") in FINAL_DISTRIBUTION_ACTION_TITLES
            ]
            safe_navigation = [
                button for button in buttons
                if str(button.get("title") or "") in SAFE_DISTRIBUTION_NAVIGATION_TITLES
            ]
            progress_text = [
                value for value in static_values
                if value and value != step_title and (
                    value.endswith("...") or value.endswith("…") or value.lower().startswith(("preparing", "signing", "uploading", "exporting"))
                )
            ]
            error_messages = static_values[1:] if step_title == "An error was encountered:" else []
            selected_custom_route = next((item["route"] for item in custom_routes if item.get("selected") is True), None)
            route_context = dict((phase_info or {}).get("route_context") or {})
            if route_context.get("top_level_method") is None and selected_custom_route is not None:
                route_context["top_level_method"] = "Custom"
                route_context["custom_route"] = selected_custom_route
            elif route_context.get("top_level_method") is None and step_title == "Review MazayaStg.ipa content:":
                route_context["top_level_method"] = "Debugging"
            elif route_context.get("top_level_method") is None and step_title == "An error was encountered:":
                route_context["top_level_method"] = "Enterprise"
            return {
                "phase_id": (phase_info or {}).get("phase_id") or phase_id_from_title(step_title),
                "phase_kind": (phase_info or {}).get("phase_kind") or (PHASE_KIND_CUSTOM_METHOD_SELECTION if custom_routes else PHASE_KIND_DOWNSTREAM),
                "step_title": step_title,
                "recognized": phase_info is not None,
                "route_context": route_context,
                "static_text": static_values,
                "buttons": buttons,
                "controls": controls,
                "custom_routes": custom_routes,
                "selected_custom_route": selected_custom_route,
                "selected_options": selected_options_from_controls(controls),
                "error_messages": error_messages,
                "warnings": [] if phase_info is not None else [f"Unrecognized distribution phase: {step_title}"],
                "safe_navigation": safe_navigation,
                "guarded_final_actions": guarded_final_actions,
                "progress_text": progress_text,
                "window_title": str(window.get("title") or ""),
            }
    return None


def inspect_distribution_phase(window_title_contains: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    result = native_ax_inspect(window_title_contains=window_title_contains or "Organizer", max_depth=8)
    native_payload = parse_native_json(result)
    phase = parse_organizer_distribution_phase(native_payload) if isinstance(native_payload, dict) and native_payload.get("ok") is True else None
    return result, phase


def activate_xcode_for_probe() -> None:
    run_command(
        [
            str(plugin_root() / "bin" / "xcode"),
            "ide",
            "activate",
            "--json",
        ],
        timeout_seconds=10,
    )


def parse_option_overrides(raw: str | None) -> dict[str, Any]:
    if raw is None or not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("option_overrides must be a JSON object")
    return parsed


def distribution_phase_has_enabled_button(phase: dict[str, Any] | None, titles: set[str]) -> bool:
    if phase is None:
        return False
    for button in phase.get("buttons", []) + phase.get("navigation_buttons", []):
        if button.get("enabled") is True and str(button.get("title") or "") in titles:
            return True
    return False


def distribution_phase_button(phase: dict[str, Any], title: str) -> dict[str, Any] | None:
    for button in phase.get("buttons", []) + phase.get("navigation_buttons", []):
        if button.get("title") == title:
            return button
    return None


def custom_route_control(phase: dict[str, Any] | None, route: str) -> dict[str, Any] | None:
    if phase is None:
        return None
    for item in phase.get("custom_routes", []):
        if item.get("route") == route:
            return item
    return None


def phase_allows_auto_advance(phase: dict[str, Any] | None) -> bool:
    if phase is None:
        return False
    return phase.get("phase_kind") in {
        PHASE_KIND_DOWNSTREAM,
        PHASE_KIND_CUSTOM_DESTINATION_SELECTION,
        PHASE_KIND_CUSTOM_OPTIONS,
        PHASE_KIND_REVIEW,
    }


def should_stop_probe(phase: dict[str, Any] | None) -> bool:
    if phase is None:
        return True
    if phase.get("recognized") is not True:
        return True
    if phase.get("phase_kind") == PHASE_KIND_ERROR:
        return True
    if phase.get("guarded_final_actions"):
        return True
    return False


def phase_snapshot(phase: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase_id": phase.get("phase_id"),
        "phase_kind": phase.get("phase_kind"),
        "step_title": phase.get("step_title"),
        "recognized": phase.get("recognized"),
        "route_context": phase.get("route_context"),
        "selected_options": phase.get("selected_options"),
        "guarded_final_actions": phase.get("guarded_final_actions"),
    }


def apply_option_overrides_to_phase(
    phase: dict[str, Any],
    option_overrides: dict[str, Any],
    *,
    window_title_contains: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if not option_overrides:
        return phase, None, warnings

    top_level_method = phase.get("route_context", {}).get("top_level_method")
    custom_route = phase.get("route_context", {}).get("custom_route")

    if phase.get("phase_kind") == PHASE_KIND_CUSTOM_DESTINATION_SELECTION and custom_route == "App Store Connect":
        destination = option_overrides.get("custom_destination")
        if destination is not None:
            if destination not in CUSTOM_DESTINATION_VALUES:
                warnings.append(f"Unsupported custom_destination override: {destination}")
                return phase, None, warnings
            if phase.get("selected_options", {}).get("custom_destination") == destination:
                return phase, None, warnings
            if phase.get("selected_options", {}).get("custom_destination") != destination:
                title = CUSTOM_DESTINATION_VALUES[destination]
                result = native_press_control(title=title, role="AXRadioButton", window_title_contains=window_title_contains or "Organizer")
                native_payload = parse_native_json(result)
                if result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
                    return None, {
                        "error_type": "xcode_ide_automation_failed",
                        "summary": f"Failed to apply custom destination override: {destination}",
                        "native": native_payload,
                    }, warnings
                time.sleep(0.2)
                _, refreshed = inspect_distribution_phase(window_title_contains)
                return refreshed, None, warnings
        return phase, None, warnings

    if phase.get("phase_kind") == PHASE_KIND_CUSTOM_OPTIONS and custom_route in {"Release Testing", "Enterprise", "Debugging"}:
        current_phase = phase
        for option_id in ("strip_swift_symbols", "include_manifest"):
            if option_id not in option_overrides:
                continue
            desired = bool(option_overrides[option_id])
            current = current_phase.get("selected_options", {}).get(option_id)
            if current == desired:
                continue
            title = CHECKBOX_OPTION_TITLES[option_id]
            result = native_press_control(title=title, role="AXCheckBox", window_title_contains=window_title_contains or "Organizer")
            native_payload = parse_native_json(result)
            if result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
                return None, {
                    "error_type": "xcode_ide_automation_failed",
                    "summary": f"Failed to apply option override: {option_id}",
                    "native": native_payload,
                }, warnings
            time.sleep(0.2)
            _, refreshed = inspect_distribution_phase(window_title_contains)
            if refreshed is None:
                return None, {
                    "error_type": "xcode_ide_automation_failed",
                    "summary": f"Failed to re-inspect phase after applying option override: {option_id}",
                    "native": native_payload,
                }, warnings
            current_phase = refreshed
        unsupported = sorted(set(option_overrides) - {"strip_swift_symbols", "include_manifest"})
        if unsupported and top_level_method == "Custom":
            warnings.extend([f"Unsupported option override ignored: {key}" for key in unsupported])
        return current_phase, None, warnings

    known_override_keys = {"custom_destination", "strip_swift_symbols", "include_manifest"}
    unsupported = sorted(set(option_overrides) - known_override_keys)
    warnings.extend([f"Option override ignored on phase {phase.get('phase_id')}: {key}" for key in unsupported])
    return phase, None, warnings


def safe_probe_loop(
    *,
    current_phase: dict[str, Any] | None,
    window_title_contains: str | None,
    cancel_after_inspect: bool,
    wait_ready_seconds: int,
    max_safe_steps: int,
    option_overrides: dict[str, Any],
    base_warnings: list[str],
    phase_before: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], list[str], dict[str, Any] | None, bool | None]:
    phase_after = current_phase
    post_payload: dict[str, Any] | None = None
    visited_phases: list[dict[str, Any]] = []
    warnings = list(base_warnings)
    override_native: dict[str, Any] | None = None
    cancel_payload: dict[str, Any] | None = None
    cancel_ok: bool | None = None

    steps_taken = 0
    while phase_after is not None:
        visited_phases.append(phase_snapshot(phase_after))
        if should_stop_probe(phase_after):
            if phase_after.get("guarded_final_actions"):
                warnings.append("Final distribution action is visible after probing; it was not pressed.")
            break
        if not phase_allows_auto_advance(phase_after):
            break

        phase_after, override_error, override_warnings = apply_option_overrides_to_phase(
            phase_after,
            option_overrides,
            window_title_contains=window_title_contains,
        )
        warnings.extend(override_warnings)
        if override_error is not None:
            post_payload = override_error
            phase_after = None
            break
        if phase_after is None:
            break

        wait_deadline = time.monotonic() + max(0, wait_ready_seconds)
        while (
            wait_ready_seconds > 0
            and phase_after is not None
            and phase_allows_auto_advance(phase_after)
            and not distribution_phase_has_enabled_button(phase_after, SAFE_PROBE_READY_TITLES)
            and not should_stop_probe(phase_after)
            and time.monotonic() < wait_deadline
        ):
            time.sleep(1)
            post_result, phase_after = inspect_distribution_phase(window_title_contains)
            post_payload = parse_native_json(post_result)
            if phase_after is not None:
                visited_phases.append(phase_snapshot(phase_after))
            if phase_after is None:
                break

        next_button = distribution_phase_button(phase_after, "Next")
        if next_button is None or not bool(next_button.get("enabled", False)):
            break
        if steps_taken >= max_safe_steps:
            warnings.append(f"Safe probe step budget reached at phase {phase_after.get('phase_id')}.")
            break
        result = native_press_button(title="Next", window_title_contains=window_title_contains or "Organizer")
        override_native = parse_native_json(result)
        if result["exit_code"] != 0 or not isinstance(override_native, dict) or override_native.get("ok") is not True:
            post_payload = override_native
            phase_after = None
            break
        steps_taken += 1
        time.sleep(1)
        activate_xcode_for_probe()
        post_result, phase_after = inspect_distribution_phase(window_title_contains)
        post_payload = parse_native_json(post_result)
        retry_deadline = time.monotonic() + max(1, wait_ready_seconds)
        while phase_after is None and time.monotonic() < retry_deadline:
            time.sleep(1)
            activate_xcode_for_probe()
            post_result, phase_after = inspect_distribution_phase(window_title_contains)
            post_payload = parse_native_json(post_result)
        if phase_after is None:
            break

    if cancel_after_inspect:
        cancel_result = native_press_button(title="Cancel", window_title_contains=window_title_contains or "Organizer")
        cancel_payload = parse_native_json(cancel_result)
        cancel_ok = bool(cancel_result["exit_code"] == 0 and isinstance(cancel_payload, dict) and cancel_payload.get("ok") is True)
        if not cancel_ok:
            warnings.append("Automatic cancel after probe did not verify; inspect the Organizer before continuing.")

    return phase_after, post_payload, visited_phases, warnings, cancel_payload, cancel_ok


def organizer_open_command() -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    result = native_press_menu_path(["Window", "Organizer"])
    return finish_native_result(
        result,
        success_summary="Xcode Organizer opened through the GUI",
        failure_summary="Xcode Organizer could not be opened through the GUI",
        extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "route": "Window > Organizer"},
        next_actions=["Use organizer-inspect to inspect the Organizer UI before pressing distribution controls."],
    )


def organizer_inspect_command(window_title_contains: str | None, max_depth: int) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    result = native_ax_inspect(window_title_contains=window_title_contains or "Organizer", max_depth=max_depth)
    return finish_native_result(
        result,
        success_summary="Xcode Organizer inspected through the GUI",
        failure_summary="Xcode Organizer inspection failed",
        extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings},
        next_actions=["Use organizer-press with a visible enabled button title such as Distribute App."],
    )


def organizer_press_command(button_title: str, window_title_contains: str | None) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    result = native_press_button(title=button_title, window_title_contains=window_title_contains or "Organizer")
    return finish_native_result(
        result,
        success_summary="Xcode Organizer button pressed through the GUI",
        failure_summary="Xcode Organizer button press failed",
        extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "button_title": button_title},
        next_actions=["Use organizer-inspect or xcode_native_windows to inspect the next Organizer distribution step."],
    )


def organizer_distribution_inspect_command(window_title_contains: str | None) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    result = native_ax_inspect(window_title_contains=window_title_contains or "Organizer", max_depth=7)
    native_payload = parse_native_json(result)
    if result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
        return finish_native_result(
            result,
            success_summary="Xcode Organizer distribution sheet inspected",
            failure_summary="Xcode Organizer distribution sheet inspection failed",
            extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings},
            next_actions=["Use organizer-open or organizer-inspect to verify the current Organizer state."],
        )
    sheet = parse_distribution_sheet(native_payload)
    if sheet is None:
        return payload(
            "failure",
            "Xcode Organizer distribution sheet was not found",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "native": native_payload},
            next_actions=[
                "Open Organizer and press Distribute App before inspecting the distribution-method sheet.",
                "Use organizer-inspect to review the raw Organizer AX tree if the modal shape changed.",
            ],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    return payload(
        "success",
        "Xcode Organizer distribution sheet inspected",
        data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet, "native": native_payload},
        next_actions=[
            "Use organizer-distribution-select --method <method> to choose a distribution route.",
            "Use organizer-press --button-title Distribute when the selected method is correct.",
        ],
    )


def organizer_distribution_select_command(method: str, window_title_contains: str | None) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    inspect_result = native_ax_inspect(window_title_contains=window_title_contains or "Organizer", max_depth=7)
    inspect_payload = parse_native_json(inspect_result)
    sheet_before = parse_distribution_sheet(inspect_payload) if isinstance(inspect_payload, dict) and inspect_payload.get("ok") is True else None
    validation_error = validate_distribution_sheet(sheet_before)
    if validation_error is not None:
        return payload(
            "failure",
            validation_error,
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "native": inspect_payload},
            next_actions=[
                "Use organizer-distribution-inspect to confirm the current Organizer phase before selecting a method.",
                "If Xcode moved to another sheet, do not continue with a stale distribution method command.",
            ],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    method_map = {str(item["method"]): item for item in sheet_before.get("methods", [])}
    if method not in method_map:
        return payload(
            "failure",
            "Requested distribution method is not available on the current Organizer sheet",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "requested_method": method},
            next_actions=["Use organizer-distribution-inspect to choose one of the currently available methods."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    if not bool(method_map[method].get("enabled", False)):
        return payload(
            "failure",
            "Requested distribution method is disabled on the current Organizer sheet",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "requested_method": method},
            next_actions=["Choose an enabled distribution method before continuing."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )
    if sheet_before.get("selected_method") == method:
        return payload(
            "success",
            "Xcode Organizer distribution method already selected",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "requested_method": method},
            next_actions=["Use organizer-distribution-confirm to advance this selected route."],
        )
    result = native_press_button(title=method, window_title_contains=window_title_contains or "Organizer")
    native_payload = parse_native_json(result)
    if result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
        return finish_native_result(
            result,
            success_summary="Xcode Organizer distribution method selected",
            failure_summary="Xcode Organizer distribution method selection failed",
            extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_method": method},
            next_actions=["Use organizer-distribution-inspect to confirm the available methods on the current sheet."],
        )
    post_result = native_ax_inspect(window_title_contains=window_title_contains or "Organizer", max_depth=7)
    post_payload = parse_native_json(post_result)
    distribution_sheet = parse_distribution_sheet(post_payload) if isinstance(post_payload, dict) and post_payload.get("ok") is True else None
    if distribution_sheet is not None and distribution_sheet.get("selected_method") not in {None, method}:
        return payload(
            "failure",
            "Xcode Organizer method selection did not verify the requested route",
            data={
                "native_preflight": preflight_details,
                "warnings": preflight_warnings,
                "requested_method": method,
                "distribution_sheet_before": sheet_before,
                "distribution_sheet": distribution_sheet,
                "native": native_payload,
                "post_inspect": post_payload,
            },
            next_actions=["Use organizer-distribution-inspect to verify which method Xcode currently considers selected."],
            exit_code=EXIT_CODES["xcode_ide_automation_failed"],
            error_type="xcode_ide_automation_failed",
        )
    return payload(
        "success",
        "Xcode Organizer distribution method selected",
        data={
            "native_preflight": preflight_details,
            "warnings": preflight_warnings,
            "requested_method": method,
            "distribution_sheet_before": sheet_before,
            "native": native_payload,
            "distribution_sheet": distribution_sheet,
            "post_inspect": post_payload,
        },
        next_actions=[
            "Verify distribution_sheet.selected_method before continuing.",
            "Use organizer-distribution-confirm to advance this selected route carefully.",
        ],
    )


def organizer_distribution_confirm_command(expected_method: str | None, window_title_contains: str | None) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    inspect_result = native_ax_inspect(window_title_contains=window_title_contains or "Organizer", max_depth=7)
    inspect_payload = parse_native_json(inspect_result)
    sheet_before = parse_distribution_sheet(inspect_payload) if isinstance(inspect_payload, dict) and inspect_payload.get("ok") is True else None
    validation_error = validate_distribution_sheet(sheet_before)
    if validation_error is not None:
        return payload(
            "failure",
            validation_error,
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "native": inspect_payload},
            next_actions=["Use organizer-distribution-inspect to confirm the current Organizer phase before pressing Distribute."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    if expected_method and sheet_before.get("selected_method") != expected_method:
        return payload(
            "failure",
            "Selected distribution method does not match the expected method",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "expected_method": expected_method},
            next_actions=["Use organizer-distribution-select to choose the intended method before confirming."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )
    selected_method = str(sheet_before.get("selected_method") or "")
    confirm_title = METHOD_CONFIRM_BUTTONS.get(selected_method)
    if not confirm_title:
        return payload(
            "failure",
            "Selected distribution method does not have a known confirm action",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "selected_method": selected_method},
            next_actions=["Use organizer-distribution-inspect to verify the selected method before continuing."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )
    confirm_button = distribution_navigation_button(sheet_before, confirm_title)
    if confirm_button is None or not bool(confirm_button.get("enabled", False)):
        return payload(
            "failure",
            f"{confirm_title} is not enabled on the current Organizer distribution sheet",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": sheet_before, "selected_method": selected_method},
            next_actions=["Resolve the current distribution sheet state before continuing."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )
    result = native_press_button(title=confirm_title, window_title_contains=window_title_contains or "Organizer")
    native_payload = parse_native_json(result)
    if result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
        return finish_native_result(
            result,
            success_summary="Xcode Organizer distribution phase confirmed",
            failure_summary="Xcode Organizer distribution confirmation failed",
            extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet_before": sheet_before, "expected_method": expected_method},
            next_actions=["Use organizer-distribution-inspect to re-check the current sheet before retrying."],
        )
    time.sleep(0.3)
    post_result = native_ax_inspect(window_title_contains=window_title_contains or "Organizer", max_depth=7)
    post_payload = parse_native_json(post_result)
    sheet_after = parse_distribution_sheet(post_payload) if isinstance(post_payload, dict) and post_payload.get("ok") is True else None
    if sheet_after is not None and sheet_after.get("step_title") == EXPECTED_DISTRIBUTION_STEP_TITLE:
        return payload(
            "failure",
            "Organizer did not advance past the distribution-method selection sheet",
            data={
                "native_preflight": preflight_details,
                "warnings": preflight_warnings,
                "distribution_sheet_before": sheet_before,
                "distribution_sheet": sheet_after,
                "expected_method": expected_method,
                "native": native_payload,
                "post_inspect": post_payload,
            },
            next_actions=["Inspect the current Organizer sheet before retrying Distribute."],
            exit_code=EXIT_CODES["xcode_ide_automation_failed"],
            error_type="xcode_ide_automation_failed",
        )
    return payload(
        "success",
        "Xcode Organizer distribution phase confirmed",
        data={
            "native_preflight": preflight_details,
            "warnings": preflight_warnings,
            "distribution_sheet_before": sheet_before,
            "expected_method": expected_method,
            "confirm_title": confirm_title,
            "native": native_payload,
            "post_inspect": post_payload,
        },
        next_actions=["Inspect the next Organizer phase before entering credentials or upload options."],
    )


def organizer_distribution_step_inspect_command(window_title_contains: str | None) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    inspect_result, phase = inspect_distribution_phase(window_title_contains)
    native_payload = parse_native_json(inspect_result)
    if inspect_result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
        return finish_native_result(
            inspect_result,
            success_summary="Xcode Organizer distribution phase inspected",
            failure_summary="Xcode Organizer distribution phase inspection failed",
            extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings},
            next_actions=["Use organizer-inspect to review the raw Organizer AX tree."],
        )
    if phase is None:
        return payload(
            "failure",
            "Xcode Organizer distribution phase was not found",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "native": native_payload},
            next_actions=["Open the Organizer distribution wizard before inspecting a distribution phase."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    warnings = list(preflight_warnings)
    if phase.get("guarded_final_actions"):
        warnings.append("Final distribution action is visible; this command inspected only and did not press it.")
    return payload(
        "success",
        "Xcode Organizer distribution phase inspected",
        data={"native_preflight": preflight_details, "warnings": warnings, "distribution_phase": phase, "native": native_payload},
        warnings=warnings,
        next_actions=[
            "Use organizer-distribution-probe-method to safely inspect a route and cancel out.",
            "Do not press Upload, Export, or final Distribute unless upload/export is explicitly intended.",
        ],
    )


def organizer_distribution_probe_method_command(
    method: str,
    window_title_contains: str | None,
    *,
    cancel_after_inspect: bool,
    settle_seconds: int,
    wait_ready_seconds: int,
    max_safe_steps: int,
    option_overrides: dict[str, Any],
) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit

    inspect_result, phase_before = inspect_distribution_phase(window_title_contains)
    inspect_payload = parse_native_json(inspect_result)
    method_sheet = parse_distribution_sheet(inspect_payload) if isinstance(inspect_payload, dict) and inspect_payload.get("ok") is True else None
    validation_error = validate_distribution_sheet(method_sheet)
    if validation_error is not None:
        return payload(
            "failure",
            validation_error,
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase_before, "native": inspect_payload},
            next_actions=["Open the distribution-method sheet before probing a method route."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )

    method_map = {str(item["method"]): item for item in method_sheet.get("methods", [])}
    if method not in method_map:
        return payload(
            "failure",
            "Requested distribution method is not available on the current Organizer sheet",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": method_sheet, "requested_method": method},
            next_actions=["Use organizer-distribution-inspect to choose one of the currently available methods."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    if not bool(method_map[method].get("enabled", False)):
        return payload(
            "failure",
            "Requested distribution method is disabled on the current Organizer sheet",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": method_sheet, "requested_method": method},
            next_actions=["Choose an enabled distribution method before probing."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )

    select_payload: dict[str, Any] | None = None
    if method_sheet.get("selected_method") != method:
        select_result = native_press_button(title=method, window_title_contains=window_title_contains or "Organizer")
        select_payload = parse_native_json(select_result)
        if select_result["exit_code"] != 0 or not isinstance(select_payload, dict) or select_payload.get("ok") is not True:
            return finish_native_result(
                select_result,
                success_summary="Xcode Organizer distribution method selected for probing",
                failure_summary="Xcode Organizer distribution method selection failed",
                extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_method": method},
                next_actions=["Use organizer-distribution-inspect to confirm the method-selection sheet state."],
            )
        time.sleep(0.2)
        verify_result, _ = inspect_distribution_phase(window_title_contains)
        verify_payload = parse_native_json(verify_result)
        method_sheet = parse_distribution_sheet(verify_payload) if isinstance(verify_payload, dict) and verify_payload.get("ok") is True else None
        if method_sheet is None or method_sheet.get("selected_method") != method:
            return payload(
                "failure",
                "Xcode Organizer method selection did not verify before probing",
                data={
                    "native_preflight": preflight_details,
                    "warnings": preflight_warnings,
                    "requested_method": method,
                    "distribution_sheet": method_sheet,
                    "select_native": select_payload,
                    "verify_native": verify_payload,
                },
                next_actions=["Use organizer-distribution-inspect to verify which method Xcode currently considers selected."],
                exit_code=EXIT_CODES["xcode_ide_automation_failed"],
                error_type="xcode_ide_automation_failed",
            )

    confirm_title = METHOD_CONFIRM_BUTTONS[method]
    confirm_button = distribution_navigation_button(method_sheet, confirm_title)
    if confirm_button is None or not bool(confirm_button.get("enabled", False)):
        return payload(
            "failure",
            f"{confirm_title} is not enabled for the selected Organizer distribution method",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": method_sheet, "requested_method": method},
            next_actions=["Resolve the current distribution sheet state before probing this route."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )

    advance_result = native_press_button(title=confirm_title, window_title_contains=window_title_contains or "Organizer")
    advance_payload = parse_native_json(advance_result)
    if advance_result["exit_code"] != 0 or not isinstance(advance_payload, dict) or advance_payload.get("ok") is not True:
        return finish_native_result(
            advance_result,
            success_summary="Xcode Organizer distribution method probe advanced",
            failure_summary="Xcode Organizer distribution method probe failed to advance",
            extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_method": method, "confirm_title": confirm_title},
            next_actions=["Use organizer-distribution-inspect to re-check the current sheet before retrying."],
        )

    time.sleep(max(0, settle_seconds))
    _, phase_after = inspect_distribution_phase(window_title_contains)
    phase_after, post_payload, visited_phases, warnings, cancel_payload, cancel_ok = safe_probe_loop(
        current_phase=phase_after,
        window_title_contains=window_title_contains,
        cancel_after_inspect=cancel_after_inspect,
        wait_ready_seconds=wait_ready_seconds,
        max_safe_steps=max_safe_steps,
        option_overrides=option_overrides,
        base_warnings=preflight_warnings,
        phase_before=method_sheet,
    )

    if phase_after is None:
        return payload(
            "failure",
            "Xcode Organizer distribution method probe could not inspect the next phase",
            data={
                "native_preflight": preflight_details,
                "warnings": warnings,
                "requested_method": method,
                "confirm_title": confirm_title,
                "distribution_sheet_before": method_sheet,
                "select_native": select_payload,
                "advance_native": advance_payload,
                "post_inspect": post_payload,
                "visited_phases": visited_phases,
                "option_overrides": option_overrides,
                "max_safe_steps": max_safe_steps,
                "cancel_after_inspect": cancel_after_inspect,
                "wait_ready_seconds": wait_ready_seconds,
                "cancel_ok": cancel_ok,
                "cancel_native": cancel_payload,
            },
            warnings=warnings,
            next_actions=["Use organizer-inspect to inspect the visible Organizer state before continuing."],
            exit_code=EXIT_CODES["xcode_ide_automation_failed"],
            error_type="xcode_ide_automation_failed",
        )

    return payload(
        "success",
        "Xcode Organizer distribution method probed without pressing final upload/export actions",
        data={
            "native_preflight": preflight_details,
            "warnings": warnings,
            "requested_method": method,
            "confirm_title": confirm_title,
            "distribution_sheet_before": method_sheet,
            "select_native": select_payload,
            "advance_native": advance_payload,
            "distribution_phase": phase_after,
            "post_inspect": post_payload,
            "visited_phases": visited_phases,
            "option_overrides": option_overrides,
            "max_safe_steps": max_safe_steps,
            "cancel_after_inspect": cancel_after_inspect,
            "wait_ready_seconds": wait_ready_seconds,
            "cancel_ok": cancel_ok,
            "cancel_native": cancel_payload,
        },
        warnings=warnings,
        next_actions=[
            "Review distribution_phase for the next screen fields and guarded final actions.",
            "Reopen the distribution-method sheet before probing another route.",
        ],
    )


def organizer_distribution_custom_select_command(route: str, window_title_contains: str | None) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit

    inspect_result, phase_before = inspect_distribution_phase(window_title_contains)
    inspect_payload = parse_native_json(inspect_result)
    if phase_before is None or phase_before.get("phase_kind") != "custom_method_selection":
        return payload(
            "failure",
            "Xcode Organizer custom distribution route sheet was not found",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase_before, "native": inspect_payload},
            next_actions=["Select Custom on the distribution-method sheet and press Next before selecting a custom route."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    route_item = custom_route_control(phase_before, route)
    if route_item is None:
        return payload(
            "failure",
            "Requested custom distribution route is not available on the current Organizer sheet",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase_before, "requested_route": route},
            next_actions=["Use organizer-distribution-step-inspect to choose one of the available custom routes."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )
    if not bool(route_item.get("enabled", False)):
        return payload(
            "failure",
            "Requested custom distribution route is disabled on the current Organizer sheet",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase_before, "requested_route": route},
            next_actions=["Choose an enabled custom distribution route before continuing."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )
    if phase_before.get("selected_custom_route") == route:
        return payload(
            "success",
            "Xcode Organizer custom distribution route already selected",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase_before, "requested_route": route},
            next_actions=["Use organizer-distribution-probe-custom-route to safely inspect this custom route's next screen."],
        )

    result = native_press_control(title=str(route_item["title"]), role="AXRadioButton", window_title_contains=window_title_contains or "Organizer")
    native_payload = parse_native_json(result)
    if result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
        return finish_native_result(
            result,
            success_summary="Xcode Organizer custom distribution route selected",
            failure_summary="Xcode Organizer custom distribution route selection failed",
            extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_route": route, "distribution_phase_before": phase_before},
            next_actions=["Use organizer-distribution-step-inspect to confirm the custom route sheet state."],
        )
    time.sleep(0.2)
    post_result, phase_after = inspect_distribution_phase(window_title_contains)
    post_payload = parse_native_json(post_result)
    if phase_after is None or phase_after.get("selected_custom_route") != route:
        return payload(
            "failure",
            "Xcode Organizer custom route selection did not verify the requested route",
            data={
                "native_preflight": preflight_details,
                "warnings": preflight_warnings,
                "requested_route": route,
                "distribution_phase_before": phase_before,
                "distribution_phase": phase_after,
                "native": native_payload,
                "post_inspect": post_payload,
            },
            next_actions=["Use organizer-distribution-step-inspect to verify which custom route Xcode currently considers selected."],
            exit_code=EXIT_CODES["xcode_ide_automation_failed"],
            error_type="xcode_ide_automation_failed",
        )
    return payload(
        "success",
        "Xcode Organizer custom distribution route selected",
        data={
            "native_preflight": preflight_details,
            "warnings": preflight_warnings,
            "requested_route": route,
            "distribution_phase_before": phase_before,
            "distribution_phase": phase_after,
            "native": native_payload,
            "post_inspect": post_payload,
        },
        next_actions=["Use organizer-distribution-probe-custom-route to safely inspect this custom route's next screen."],
    )


def organizer_distribution_probe_custom_route_command(
    route: str,
    window_title_contains: str | None,
    *,
    cancel_after_inspect: bool,
    settle_seconds: int,
    wait_ready_seconds: int,
    max_safe_steps: int,
    option_overrides: dict[str, Any],
) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit

    inspect_result, phase = inspect_distribution_phase(window_title_contains)
    inspect_payload = parse_native_json(inspect_result)
    method_sheet = parse_distribution_sheet(inspect_payload) if isinstance(inspect_payload, dict) and inspect_payload.get("ok") is True else None
    validation_error = validate_distribution_sheet(method_sheet)
    if validation_error is None:
        if method_sheet.get("selected_method") != "Custom":
            result = native_press_button(title="Custom", window_title_contains=window_title_contains or "Organizer")
            native_payload = parse_native_json(result)
            if result["exit_code"] != 0 or not isinstance(native_payload, dict) or native_payload.get("ok") is not True:
                return finish_native_result(
                    result,
                    success_summary="Xcode Organizer Custom method selected for probing",
                    failure_summary="Xcode Organizer Custom method selection failed",
                    extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_custom_route": route},
                    next_actions=["Use organizer-distribution-inspect to confirm the method-selection sheet state."],
                )
            time.sleep(0.2)
            inspect_result, phase = inspect_distribution_phase(window_title_contains)
            inspect_payload = parse_native_json(inspect_result)
            method_sheet = parse_distribution_sheet(inspect_payload) if isinstance(inspect_payload, dict) and inspect_payload.get("ok") is True else None
        next_button = distribution_navigation_button(method_sheet, "Next")
        if next_button is None or not bool(next_button.get("enabled", False)):
            return payload(
                "failure",
                "Next is not enabled for the Custom distribution method",
                data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_sheet": method_sheet, "requested_custom_route": route},
                next_actions=["Use organizer-distribution-inspect to verify the Custom method is selected."],
                exit_code=EXIT_CODES["xcode_menu_item_disabled"],
                error_type="xcode_menu_item_disabled",
            )
        advance_custom_result = native_press_button(title="Next", window_title_contains=window_title_contains or "Organizer")
        advance_custom_payload = parse_native_json(advance_custom_result)
        if advance_custom_result["exit_code"] != 0 or not isinstance(advance_custom_payload, dict) or advance_custom_payload.get("ok") is not True:
            return finish_native_result(
                advance_custom_result,
                success_summary="Xcode Organizer advanced to Custom route selection",
                failure_summary="Xcode Organizer failed to advance to Custom route selection",
                extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_custom_route": route},
                next_actions=["Use organizer-distribution-inspect to re-check the current sheet before retrying."],
            )
        time.sleep(0.3)
        inspect_result, phase = inspect_distribution_phase(window_title_contains)
        inspect_payload = parse_native_json(inspect_result)

    if phase is None or phase.get("phase_kind") != "custom_method_selection":
        return payload(
            "failure",
            "Xcode Organizer custom distribution route sheet was not found",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase, "native": inspect_payload, "requested_custom_route": route},
            next_actions=["Start from the distribution-method sheet or the Custom route selection sheet."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"],
            error_type="xcode_menu_item_not_found",
        )

    route_item = custom_route_control(phase, route)
    if route_item is None or not bool(route_item.get("enabled", False)):
        return payload(
            "failure",
            "Requested custom distribution route is not available or disabled",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase, "requested_custom_route": route},
            next_actions=["Use organizer-distribution-step-inspect to choose one of the available custom routes."],
            exit_code=EXIT_CODES["xcode_menu_item_not_found"] if route_item is None else EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_not_found" if route_item is None else "xcode_menu_item_disabled",
        )

    select_payload: dict[str, Any] | None = None
    if phase.get("selected_custom_route") != route:
        select_result = native_press_control(title=str(route_item["title"]), role="AXRadioButton", window_title_contains=window_title_contains or "Organizer")
        select_payload = parse_native_json(select_result)
        if select_result["exit_code"] != 0 or not isinstance(select_payload, dict) or select_payload.get("ok") is not True:
            return finish_native_result(
                select_result,
                success_summary="Xcode Organizer custom distribution route selected for probing",
                failure_summary="Xcode Organizer custom distribution route selection failed",
                extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_custom_route": route},
                next_actions=["Use organizer-distribution-step-inspect to confirm the custom route sheet state."],
            )
        time.sleep(0.2)
        verify_result, phase = inspect_distribution_phase(window_title_contains)
        verify_payload = parse_native_json(verify_result)
        if phase is None or phase.get("selected_custom_route") != route:
            return payload(
                "failure",
                "Xcode Organizer custom route selection did not verify before probing",
                data={
                    "native_preflight": preflight_details,
                    "warnings": preflight_warnings,
                    "requested_custom_route": route,
                    "distribution_phase": phase,
                    "select_native": select_payload,
                    "verify_native": verify_payload,
                },
                next_actions=["Use organizer-distribution-step-inspect to verify which custom route Xcode currently considers selected."],
                exit_code=EXIT_CODES["xcode_ide_automation_failed"],
                error_type="xcode_ide_automation_failed",
            )

    next_button = distribution_phase_button(phase, "Next")
    if next_button is None or not bool(next_button.get("enabled", False)):
        return payload(
            "failure",
            "Next is not enabled for the selected custom distribution route",
            data={"native_preflight": preflight_details, "warnings": preflight_warnings, "distribution_phase": phase, "requested_custom_route": route},
            next_actions=["Resolve the current custom route sheet state before probing this route."],
            exit_code=EXIT_CODES["xcode_menu_item_disabled"],
            error_type="xcode_menu_item_disabled",
        )

    advance_result = native_press_button(title="Next", window_title_contains=window_title_contains or "Organizer")
    advance_payload = parse_native_json(advance_result)
    if advance_result["exit_code"] != 0 or not isinstance(advance_payload, dict) or advance_payload.get("ok") is not True:
        return finish_native_result(
            advance_result,
            success_summary="Xcode Organizer custom distribution route probe advanced",
            failure_summary="Xcode Organizer custom distribution route probe failed to advance",
            extra_data={"native_preflight": preflight_details, "warnings": preflight_warnings, "requested_custom_route": route},
            next_actions=["Use organizer-distribution-step-inspect to re-check the current sheet before retrying."],
        )

    time.sleep(max(0, settle_seconds))
    _, phase_after = inspect_distribution_phase(window_title_contains)
    phase_after, post_payload, visited_phases, warnings, cancel_payload, cancel_ok = safe_probe_loop(
        current_phase=phase_after,
        window_title_contains=window_title_contains,
        cancel_after_inspect=cancel_after_inspect,
        wait_ready_seconds=wait_ready_seconds,
        max_safe_steps=max_safe_steps,
        option_overrides=option_overrides,
        base_warnings=preflight_warnings,
        phase_before=phase,
    )

    if phase_after is None:
        return payload(
            "failure",
            "Xcode Organizer custom distribution route probe could not inspect the next phase",
            data={
                "native_preflight": preflight_details,
                "warnings": warnings,
                "requested_custom_route": route,
                "distribution_phase_before": phase,
                "select_native": select_payload,
                "advance_native": advance_payload,
                "post_inspect": post_payload,
                "visited_phases": visited_phases,
                "option_overrides": option_overrides,
                "max_safe_steps": max_safe_steps,
                "cancel_after_inspect": cancel_after_inspect,
                "wait_ready_seconds": wait_ready_seconds,
                "cancel_ok": cancel_ok,
                "cancel_native": cancel_payload,
            },
            warnings=warnings,
            next_actions=["Use organizer-inspect to inspect the visible Organizer state before continuing."],
            exit_code=EXIT_CODES["xcode_ide_automation_failed"],
            error_type="xcode_ide_automation_failed",
        )

    return payload(
        "success",
        "Xcode Organizer custom distribution route probed without pressing final upload/export actions",
        data={
            "native_preflight": preflight_details,
            "warnings": warnings,
            "requested_custom_route": route,
            "distribution_phase_before": phase,
            "select_native": select_payload,
            "advance_native": advance_payload,
            "distribution_phase": phase_after,
            "post_inspect": post_payload,
            "visited_phases": visited_phases,
            "option_overrides": option_overrides,
            "max_safe_steps": max_safe_steps,
            "cancel_after_inspect": cancel_after_inspect,
            "wait_ready_seconds": wait_ready_seconds,
            "cancel_ok": cancel_ok,
            "cancel_native": cancel_payload,
        },
        warnings=warnings,
        next_actions=[
            "Review distribution_phase for this custom route's next screen fields and guarded final actions.",
            "Reopen the distribution-method sheet before probing another route.",
        ],
    )


def menu_perform_command(action_id: str, *, allow_destructive: bool = False) -> int:
    action_item = MENU_ACTIONS_BY_ID.get(action_id)
    if action_item is None:
        return payload(
            "failure",
            "Unknown Xcode menu action id",
            data={"action_id": action_id, "known_action_count": len(MENU_ACTIONS)},
            next_actions=["Run bin/xcode ide menu-catalog --json and choose an action_id from the catalog."],
            exit_code=EXIT_CODES["usage_error"],
            error_type="usage_error",
        )
    if action_item.safety in {EXTERNAL_EFFECT, UNSUPPORTED_DYNAMIC}:
        return menu_blocked_response(action_item, action_item.safety)
    if not action_item.implemented:
        next_actions = ["Use xcode_ide_menu_catalog to choose an implemented menu action."]
        if action_item.preferred_tool:
            next_actions.insert(0, f"Use {action_item.preferred_tool} for this workflow instead of menu pressing.")
        return menu_blocked_response(action_item, "not_implemented", next_actions=next_actions)
    if action_item.safety == DESTRUCTIVE and not allow_destructive:
        return menu_blocked_response(
            action_item,
            "destructive_requires_allow_destructive",
            next_actions=["Retry with --allow-destructive only when the destructive Xcode UI action is intentional."],
        )

    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=True, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    native_result = native_menu_press(action_item)
    native_payload: dict[str, Any] | None = None
    try:
        native_payload = json.loads(native_result["stdout"])
    except json.JSONDecodeError:
        native_payload = None
    if native_result["exit_code"] == 0 and isinstance(native_payload, dict) and native_payload.get("ok") is True:
        return payload(
            "success",
            "Xcode menu action performed",
            data={
                "action": action_item.as_dict(),
                "native_preflight": preflight_details,
                "native_menu": native_payload.get("summary") if isinstance(native_payload, dict) else {},
            },
            warnings=preflight_warnings,
            next_actions=["Use xcode_ide_status or xcode_native_windows to inspect Xcode after the menu action."],
        )
    if isinstance(native_payload, dict):
        error_type = str(native_payload.get("error_type") or "xcode_ide_automation_failed")
        return payload(
            "failure",
            "Xcode menu action failed",
            data={
                "action": action_item.as_dict(),
                "native_preflight": preflight_details,
                "native_menu": native_payload,
            },
            warnings=preflight_warnings + [str(native_payload.get("summary") or "Native menu press failed.")],
            next_actions=["Use xcode_ide_status or xcode_native_windows to inspect Xcode after the menu action."],
            exit_code=EXIT_CODES.get(error_type, EXIT_CODES["xcode_ide_automation_failed"]),
            error_type=error_type,
        )
    return finish_from_osascript(
        result=run_osascript(menu_press_script(action_item), timeout=15),
        success_summary="Xcode menu action performed",
        failure_summary="Xcode menu action failed",
        extra_warnings=preflight_warnings,
        extra_data={"action": action_item.as_dict(), "native_preflight": preflight_details},
        next_actions=["Use xcode_ide_status or xcode_native_windows to inspect Xcode after the menu action."],
    )


def archive_command(
    *,
    scheme: str,
    workspace_path: str | None = None,
    timeout_seconds: int = 120,
    require_native_preflight: bool = True,
) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=require_native_preflight, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    selector = workspace_selector_script(workspace_path)
    script = f"""
tell application "Xcode"
    activate
    {selector}
    set requestedScheme to {apple_string(scheme)}
    set schemeFound to false
    repeat with s in schemes of w
        if (name of s as text) is requestedScheme then set schemeFound to true
    end repeat
    if schemeFound is false then error "XCODE_PLUGIN_SCHEME_NOT_FOUND"
    set active scheme of w to scheme requestedScheme of w
    set out to "workspace\t" & (name of w as text) & linefeed
    set out to out & "requested_scheme\t" & requestedScheme & linefeed
    try
        set out to out & "active_scheme\t" & (name of active scheme of w as text) & linefeed
    end try
end tell
delay 0.2
tell application "System Events"
    if not (exists process "Xcode") then error "XCODE_PLUGIN_XCODE_NOT_RUNNING"
    tell process "Xcode"
        set frontmost to true
        if not (exists menu bar item "Product" of menu bar 1) then error "XCODE_PLUGIN_MENU_PATH_NOT_FOUND"
        set productMenu to menu 1 of menu bar item "Product" of menu bar 1
        if not (exists menu item "Archive" of productMenu) then error "XCODE_PLUGIN_MENU_PATH_NOT_FOUND"
        set archiveItem to menu item "Archive" of productMenu
        set itemEnabled to true
        try
            set itemEnabled to enabled of archiveItem
        end try
        if itemEnabled is false then error "XCODE_PLUGIN_MENU_ITEM_DISABLED"
        perform action "AXPress" of archiveItem
        set out to out & "menu_path\tProduct > Archive" & linefeed
        set out to out & "archive_menu_pressed\ttrue" & linefeed
        set out to out & "enabled_before_press\t" & (itemEnabled as text) & linefeed
    end tell
end tell
return out
"""
    return finish_from_osascript(
        result=run_osascript(script, timeout=timeout_seconds + SCRIPT_TIMEOUT_PADDING),
        success_summary="Xcode GUI archive action started",
        failure_summary="Xcode GUI archive action failed",
        extra_warnings=preflight_warnings,
        extra_data={
            "native_preflight": preflight_details,
            "gui_only": True,
            "route": "Product > Archive",
        },
        next_actions=[
            "Watch Xcode's activity area and Organizer for archive completion.",
            "Use xcode_native_windows to detect signing or Organizer modal blockers.",
        ],
    )


def set_scheme_command(name: str, workspace_path: str | None = None, *, require_native_preflight: bool = False) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=require_native_preflight, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    selector = workspace_selector_script(workspace_path)
    script = f"""
tell application "Xcode"
    {selector}
    set foundScheme to false
    repeat with s in schemes of w
        if (name of s as text) is {apple_string(name)} then set foundScheme to true
    end repeat
    if foundScheme is false then error "XCODE_PLUGIN_SCHEME_NOT_FOUND"
    set active scheme of w to scheme {apple_string(name)} of w
    set out to "active_scheme\t" & (name of active scheme of w as text) & linefeed
    return out
end tell
"""
    return finish_from_osascript(
        result=run_osascript(script),
        success_summary="Active Xcode scheme updated",
        extra_warnings=preflight_warnings,
        extra_data={"native_preflight": preflight_details} if preflight_details else None,
    )


def set_destination_command(
    name: str | None = None,
    destination_id: str | None = None,
    workspace_path: str | None = None,
    *,
    require_native_preflight: bool = False,
) -> int:
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=require_native_preflight, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    selector = workspace_selector_script(workspace_path)
    target_name = name or ""
    target_id = destination_id or ""
    script = f"""
tell application "Xcode"
    {selector}
    set targetName to {apple_string(target_name)}
    set targetId to {apple_string(target_id)}
    set matchedDestination to missing value
    set matchCount to 0
    repeat with d in run destinations of w
        set nameMatches to false
        set idMatches to false
        try
            if targetId is not "" and (device identifier of device of d as text) is targetId then set idMatches to true
        end try
        if idMatches then
            set matchedDestination to d
            set matchCount to 1
            exit repeat
        end if
        try
            if targetId is "" and targetName is not "" and (name of d as text) is targetName then set nameMatches to true
        end try
        if nameMatches then
            set matchedDestination to d
            set matchCount to matchCount + 1
        end if
    end repeat
    if matchCount is 0 then error "XCODE_PLUGIN_DESTINATION_NOT_FOUND"
    if matchCount > 1 then error "XCODE_PLUGIN_DESTINATION_AMBIGUOUS"
    set active run destination of w to matchedDestination
    set out to "requested_destination\t" & targetName & linefeed
    set out to out & "requested_destination_id\t" & targetId & linefeed
    try
        set d to active run destination of w
        set out to out & "active_destination_name\t" & (name of d as text) & linefeed
        set out to out & "active_destination_platform\t" & (platform of d as text) & linefeed
    on error errMsg
        set out to out & "active_destination_error\t" & errMsg & linefeed
    end try
    return out
end tell
"""
    return finish_from_osascript(
        result=run_osascript(script),
        success_summary="Requested Xcode run destination set",
        extra_warnings=preflight_warnings,
        extra_data={"native_preflight": preflight_details} if preflight_details else None,
        next_actions=[
            "If active_destination_error is present, Xcode accepted the set request but did not expose readback through scripting.",
            "Pass --destination-name or --destination-id directly to scheme-action when running IDE actions.",
        ],
    )


def scheme_action_command(
    action: str,
    timeout_seconds: int,
    poll_seconds: float,
    *,
    scheme: str | None = None,
    destination_name: str | None = None,
    destination_id: str | None = None,
    workspace_path: str | None = None,
    require_native_preflight: bool = False,
) -> int:
    if action not in VALID_ACTIONS:
        return payload(
            "failure",
            "Unsupported Xcode scheme action",
            data={"action": action, "valid_actions": sorted(VALID_ACTIONS)},
            exit_code=2,
        )
    preflight_exit, preflight_warnings, preflight_details = native_preflight(require=require_native_preflight, include_ax=True)
    if preflight_exit is not None:
        return preflight_exit
    if action == "stop":
        selector = workspace_selector_script(workspace_path)
        script = f"""
tell application "Xcode"
    {selector}
    stop w
    return "action\tstop" & linefeed & "stop_requested\ttrue" & linefeed
end tell
"""
        return finish_from_osascript(result=run_osascript(script), success_summary="Stop requested for active Xcode scheme action")

    repeats = max(int(timeout_seconds / max(poll_seconds, 0.1)), 1)
    poll = max(poll_seconds, 0.1)
    log_dir = Path(tempfile.mkdtemp(prefix="xcode-ide-action-"))
    started = time.time()
    action_line = f"set actionResult to {action} w"
    selector = workspace_selector_script(workspace_path)
    setup_lines = []
    if scheme:
        setup_lines.append(
            f"""
    set foundScheme to false
    repeat with s in schemes of w
        if (name of s as text) is {apple_string(scheme)} then set foundScheme to true
    end repeat
    if foundScheme is false then error "XCODE_PLUGIN_SCHEME_NOT_FOUND"
    set active scheme of w to scheme {apple_string(scheme)} of w
    set out to out & "requested_scheme\t" & {apple_string(scheme)} & linefeed
"""
        )
    if destination_name or destination_id:
        name_line = f"set targetDestinationName to {apple_string(destination_name or '')}"
        id_line = f"set targetDestinationId to {apple_string(destination_id or '')}"
        setup_lines.append(
            f"""
    {name_line}
    {id_line}
    set matchedDestination to missing value
    set matchCount to 0
    repeat with d in run destinations of w
        set nameMatches to false
        set idMatches to false
        try
            if targetDestinationId is not "" and (device identifier of device of d as text) is targetDestinationId then set idMatches to true
        end try
        if idMatches then
            set matchedDestination to d
            set matchCount to 1
            exit repeat
        end if
        try
            if targetDestinationId is "" and targetDestinationName is not "" and (name of d as text) is targetDestinationName then set nameMatches to true
        end try
        if nameMatches then
            set matchedDestination to d
            set matchCount to matchCount + 1
        end if
    end repeat
    if matchCount is 0 then error "XCODE_PLUGIN_DESTINATION_NOT_FOUND"
    if matchCount > 1 then error "XCODE_PLUGIN_DESTINATION_AMBIGUOUS"
    set active run destination of w to matchedDestination
    try
        set out to out & "requested_destination_name\t" & (name of matchedDestination as text) & linefeed
    end try
    try
        set out to out & "requested_destination_platform\t" & (platform of matchedDestination as text) & linefeed
    end try
    try
        set out to out & "requested_destination_device_id\t" & (device identifier of device of matchedDestination as text) & linefeed
    end try
"""
        )
    setup_block = "".join(setup_lines)
    script = f"""
tell application "Xcode"
    activate
    {selector}
    set out to "action\t{action}" & linefeed
    set out to out & "workspace\t" & (name of w as text) & linefeed
    {setup_block}
    try
        set out to out & "scheme\t" & (name of active scheme of w as text) & linefeed
    end try
    {action_line}
    repeat {repeats} times
        delay {poll}
        if completed of actionResult is true then exit repeat
    end repeat
    set didComplete to completed of actionResult
    set out to out & "completed\t" & (didComplete as text) & linefeed
    set out to out & "result_status\t" & ((status of actionResult) as text) & linefeed
    try
        set out to out & "error_message\t" & (error message of actionResult as text) & linefeed
    end try
    try
        set out to out & "build_error_count\t" & ((count build errors of actionResult) as text) & linefeed
    end try
    try
        set out to out & "build_warning_count\t" & ((count build warnings of actionResult) as text) & linefeed
    end try
    try
        set out to out & "analyzer_issue_count\t" & ((count analyzer issues of actionResult) as text) & linefeed
    end try
    try
        set out to out & "test_failure_count\t" & ((count test failures of actionResult) as text) & linefeed
    end try
    if didComplete is false then
        stop w
        set out to out & "stop_requested_after_timeout\ttrue" & linefeed
    end if
    return out
end tell
"""
    result = run_osascript(script, timeout=timeout_seconds + SCRIPT_TIMEOUT_PADDING)
    data = parse_kv(result["stdout"])
    data["elapsed_seconds"] = round(time.time() - started, 2)
    if preflight_details:
        data["native_preflight"] = preflight_details
    warnings = []
    warnings.extend(preflight_warnings)
    if result["stderr"].strip():
        warnings.append(result["stderr"].strip())
    if result["exit_code"] != 0:
        error_type, mapped_exit = classify_osascript_error(result)
        return payload(
            "failure",
            f"Xcode {action} action failed to start or report",
            data=data,
            artifacts={"action_log_dir": str(log_dir)},
            warnings=warnings,
            next_actions=[
                "Confirm the active workspace has a buildable scheme and run destination.",
                "Grant Automation permission if macOS blocked control of Xcode.",
            ],
            exit_code=mapped_exit,
            error_type=error_type,
        )
    if data.get("completed") is False:
        return payload(
            "timeout",
            f"Xcode {action} action was still running after timeout; stop was requested",
            data=data,
            artifacts={"action_log_dir": str(log_dir)},
            warnings=warnings,
            next_actions=["Increase --timeout-seconds for a full IDE action validation."],
        )
    result_status = str(data.get("result_status", "")).lower()
    error_message = str(data.get("error_message", ""))
    next_actions = ["Use xcode-results for .xcresult summaries when an IDE result bundle is available."]
    if "not testable" in error_message.lower() or "not currently configured for the test action" in error_message.lower():
        next_actions = [
            "Run xcode_scheme_inspector.py against the active .xcodeproj/.xcworkspace to verify TestAction entries.",
            "Add the unit/UI test bundle in Product > Scheme > Edit Scheme > Test, then share and commit the scheme.",
        ]
    status = "success" if result_status in {"succeeded", "success"} else "failure"
    return payload(
        status,
        f"Xcode {action} action completed with status {data.get('result_status')}",
        data=data,
        artifacts={"action_log_dir": str(log_dir)},
        warnings=warnings,
        next_actions=next_actions,
        exit_code=0 if status == "success" else 1,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control and inspect the local Xcode IDE through AppleScript.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Inspect whether Xcode is running without launching it.")
    subparsers.add_parser("activate", help="Bring Xcode to the front.")

    workspace_info = subparsers.add_parser("workspace-info", help="Inspect an Xcode workspace document.")
    workspace_info.add_argument("--workspace-path", default=None)

    preflight = subparsers.add_parser("preflight", help="Validate Xcode IDE readiness before scheme actions.")
    preflight.add_argument("--workspace-path", default=None)
    preflight.add_argument("--scheme", default=None)
    preflight.add_argument("--destination-name", default=None)
    preflight.add_argument("--destination-id", default=None)
    preflight.add_argument("--require-native-preflight", action="store_true")

    subparsers.add_parser("list-workspaces", help="List open Xcode workspace documents.")

    open_parser = subparsers.add_parser("open-workspace", help="Open an .xcodeproj or .xcworkspace in Xcode.")
    open_parser.add_argument("--path", required=True)
    open_parser.add_argument("--timeout-seconds", type=int, default=60)

    list_schemes = subparsers.add_parser("list-schemes", help="List schemes in a workspace.")
    list_schemes.add_argument("--workspace-path", default=None)

    list_destinations = subparsers.add_parser("list-destinations", help="List run destinations in a workspace.")
    list_destinations.add_argument("--workspace-path", default=None)

    subparsers.add_parser("menu-catalog", help="List typed Xcode menu actions supported by the plugin.")

    menu_perform = subparsers.add_parser("menu-perform", help="Perform one typed Xcode menu action by stable action id.")
    menu_perform.add_argument("--action-id", required=True)
    menu_perform.add_argument("--allow-destructive", action="store_true")

    subparsers.add_parser("organizer-open", help="Open Xcode Organizer through the trusted GUI path.")

    organizer_inspect = subparsers.add_parser("organizer-inspect", help="Inspect Xcode Organizer through the trusted GUI path.")
    organizer_inspect.add_argument("--window-title-contains", default="Organizer")
    organizer_inspect.add_argument("--max-depth", type=int, default=4)

    organizer_press = subparsers.add_parser("organizer-press", help="Press a visible Organizer button through the trusted GUI path.")
    organizer_press.add_argument("--button-title", required=True)
    organizer_press.add_argument("--window-title-contains", default="Organizer")

    organizer_distribution_inspect = subparsers.add_parser("organizer-distribution-inspect", help="Inspect the Organizer distribution-method sheet through the trusted GUI path.")
    organizer_distribution_inspect.add_argument("--window-title-contains", default="Organizer")

    organizer_distribution_select = subparsers.add_parser("organizer-distribution-select", help="Select a distribution method on the Organizer distribution sheet.")
    organizer_distribution_select.add_argument("--method", choices=DISTRIBUTION_METHODS, required=True)
    organizer_distribution_select.add_argument("--window-title-contains", default="Organizer")

    organizer_distribution_confirm = subparsers.add_parser("organizer-distribution-confirm", help="Confirm the currently selected distribution method and advance this Organizer phase.")
    organizer_distribution_confirm.add_argument("--expected-method", choices=DISTRIBUTION_METHODS, default=None)
    organizer_distribution_confirm.add_argument("--window-title-contains", default="Organizer")

    organizer_distribution_step_inspect = subparsers.add_parser("organizer-distribution-step-inspect", help="Inspect the current Organizer distribution wizard phase through the trusted GUI path.")
    organizer_distribution_step_inspect.add_argument("--window-title-contains", default="Organizer")

    organizer_distribution_probe = subparsers.add_parser("organizer-distribution-probe-method", help="Enter one Organizer distribution method route, inspect its next phase, and cancel out by default.")
    organizer_distribution_probe.add_argument("--method", choices=DISTRIBUTION_METHODS, required=True)
    organizer_distribution_probe.add_argument("--window-title-contains", default="Organizer")
    organizer_distribution_probe.add_argument("--no-cancel-after-inspect", action="store_true")
    organizer_distribution_probe.add_argument("--settle-seconds", type=int, default=1)
    organizer_distribution_probe.add_argument("--wait-ready-seconds", type=int, default=15)
    organizer_distribution_probe.add_argument("--max-safe-steps", type=int, default=DEFAULT_MAX_SAFE_STEPS)
    organizer_distribution_probe.add_argument("--option-overrides", default=None)

    organizer_distribution_custom_select = subparsers.add_parser("organizer-distribution-custom-select", help="Select a route on the Organizer Custom distribution sheet.")
    organizer_distribution_custom_select.add_argument("--route", choices=CUSTOM_DISTRIBUTION_ROUTES, required=True)
    organizer_distribution_custom_select.add_argument("--window-title-contains", default="Organizer")

    organizer_distribution_custom_probe = subparsers.add_parser("organizer-distribution-probe-custom-route", help="Enter Custom distribution, choose one nested route, inspect its next phase, and cancel out by default.")
    organizer_distribution_custom_probe.add_argument("--route", choices=CUSTOM_DISTRIBUTION_ROUTES, required=True)
    organizer_distribution_custom_probe.add_argument("--window-title-contains", default="Organizer")
    organizer_distribution_custom_probe.add_argument("--no-cancel-after-inspect", action="store_true")
    organizer_distribution_custom_probe.add_argument("--settle-seconds", type=int, default=1)
    organizer_distribution_custom_probe.add_argument("--wait-ready-seconds", type=int, default=15)
    organizer_distribution_custom_probe.add_argument("--max-safe-steps", type=int, default=DEFAULT_MAX_SAFE_STEPS)
    organizer_distribution_custom_probe.add_argument("--option-overrides", default=None)

    archive_parser = subparsers.add_parser("archive", help="Start Product > Archive through the Xcode GUI.")
    archive_parser.add_argument("--scheme", required=True)
    archive_parser.add_argument("--workspace-path", default=None)
    archive_parser.add_argument("--timeout-seconds", type=int, default=120)
    archive_parser.add_argument("--require-native-preflight", action="store_true", default=True)

    scheme_parser = subparsers.add_parser("set-scheme", help="Set the active Xcode scheme by exact name.")
    scheme_parser.add_argument("--name", required=True)
    scheme_parser.add_argument("--workspace-path", default=None)
    scheme_parser.add_argument("--require-native-preflight", action="store_true")

    destination_parser = subparsers.add_parser("set-destination", help="Set the active Xcode run destination by exact name.")
    destination_parser.add_argument("--name", default=None)
    destination_parser.add_argument("--destination-id", default=None)
    destination_parser.add_argument("--workspace-path", default=None)
    destination_parser.add_argument("--require-native-preflight", action="store_true")

    action_parser = subparsers.add_parser("scheme-action", help="Run an Xcode IDE scheme action and poll its result.")
    action_parser.add_argument("--action", choices=sorted(VALID_ACTIONS), required=True)
    action_parser.add_argument("--scheme", default=None, help="Optional scheme name to set immediately before the action.")
    action_parser.add_argument("--destination-name", default=None, help="Optional run destination name to set before the action.")
    action_parser.add_argument("--destination-id", default=None, help="Optional device identifier to match before the action.")
    action_parser.add_argument("--workspace-path", default=None)
    action_parser.add_argument("--timeout-seconds", type=int, default=120)
    action_parser.add_argument("--poll-seconds", type=float, default=0.5)
    action_parser.add_argument("--require-native-preflight", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    option_overrides: dict[str, Any] = {}
    if getattr(args, "option_overrides", None) is not None:
        try:
            option_overrides = parse_option_overrides(args.option_overrides)
        except ValueError as exc:
            return payload("failure", str(exc), data={}, exit_code=EXIT_CODES["usage_error"], error_type="usage_error")
    if args.command == "status":
        return status_command()
    if args.command == "activate":
        return activate_command()
    if args.command == "open-workspace":
        return open_workspace_command(args.path, args.timeout_seconds)
    if args.command == "workspace-info":
        return workspace_info_command(args.workspace_path)
    if args.command == "preflight":
        return preflight_command(
            workspace_path=args.workspace_path,
            scheme=args.scheme,
            destination_name=args.destination_name,
            destination_id=args.destination_id,
            require_native_preflight=args.require_native_preflight,
        )
    if args.command == "list-workspaces":
        return list_workspaces_command()
    if args.command == "list-schemes":
        return list_schemes_command(args.workspace_path)
    if args.command == "list-destinations":
        return list_destinations_command(args.workspace_path)
    if args.command == "menu-catalog":
        return menu_catalog_command()
    if args.command == "menu-perform":
        return menu_perform_command(args.action_id, allow_destructive=args.allow_destructive)
    if args.command == "organizer-open":
        return organizer_open_command()
    if args.command == "organizer-inspect":
        return organizer_inspect_command(args.window_title_contains, args.max_depth)
    if args.command == "organizer-press":
        return organizer_press_command(args.button_title, args.window_title_contains)
    if args.command == "organizer-distribution-inspect":
        return organizer_distribution_inspect_command(args.window_title_contains)
    if args.command == "organizer-distribution-select":
        return organizer_distribution_select_command(args.method, args.window_title_contains)
    if args.command == "organizer-distribution-confirm":
        return organizer_distribution_confirm_command(args.expected_method, args.window_title_contains)
    if args.command == "organizer-distribution-step-inspect":
        return organizer_distribution_step_inspect_command(args.window_title_contains)
    if args.command == "organizer-distribution-probe-method":
        return organizer_distribution_probe_method_command(
            args.method,
            args.window_title_contains,
            cancel_after_inspect=not args.no_cancel_after_inspect,
            settle_seconds=args.settle_seconds,
            wait_ready_seconds=args.wait_ready_seconds,
            max_safe_steps=args.max_safe_steps,
            option_overrides=option_overrides,
        )
    if args.command == "organizer-distribution-custom-select":
        return organizer_distribution_custom_select_command(args.route, args.window_title_contains)
    if args.command == "organizer-distribution-probe-custom-route":
        return organizer_distribution_probe_custom_route_command(
            args.route,
            args.window_title_contains,
            cancel_after_inspect=not args.no_cancel_after_inspect,
            settle_seconds=args.settle_seconds,
            wait_ready_seconds=args.wait_ready_seconds,
            max_safe_steps=args.max_safe_steps,
            option_overrides=option_overrides,
        )
    if args.command == "archive":
        return archive_command(
            scheme=args.scheme,
            workspace_path=args.workspace_path,
            timeout_seconds=args.timeout_seconds,
            require_native_preflight=args.require_native_preflight,
        )
    if args.command == "set-scheme":
        return set_scheme_command(args.name, args.workspace_path, require_native_preflight=args.require_native_preflight)
    if args.command == "set-destination":
        if not args.name and not args.destination_id:
            return payload("failure", "Pass --destination-id or --name", data={}, exit_code=2, error_type="usage_error")
        return set_destination_command(
            args.name,
            args.destination_id,
            args.workspace_path,
            require_native_preflight=args.require_native_preflight,
        )
    if args.command == "scheme-action":
        return scheme_action_command(
            args.action,
            args.timeout_seconds,
            args.poll_seconds,
            scheme=args.scheme,
            destination_name=args.destination_name,
            destination_id=args.destination_id,
            workspace_path=args.workspace_path,
            require_native_preflight=args.require_native_preflight,
        )
    return payload("failure", "Unknown command", data={"command": args.command}, exit_code=2)


if __name__ == "__main__":
    raise SystemExit(main())
