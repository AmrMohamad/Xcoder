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

from xcode_common import EXIT_CODES, compact_output, emit_failure, emit_success, plugin_root, run_command, normalize_path


SCRIPT_TIMEOUT_PADDING = 20
VALID_ACTIONS = {"build", "clean", "test", "run", "debug", "stop"}


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
    return plugin_root() / "bin" / "xcode-native-helper"


def native_preflight(*, require: bool, include_ax: bool) -> tuple[int | None, list[str], dict[str, Any]]:
    helper = native_helper_path()
    details: dict[str, Any] = {"helper_path": str(helper), "required": require, "ax_checked": include_ax}
    warnings: list[str] = []
    if not helper.exists() or not helper.is_file() or not (helper.stat().st_mode & 0o111):
        message = "Native helper is not built at bin/xcode-native-helper."
        if require:
            return (
                payload(
                    "failure",
                    "Native helper is required but unavailable",
                    data=details,
                    warnings=[message],
                    next_actions=["Build native/XcodeNativeHelper and install bin/xcode-native-helper."],
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

    ax = run_command([str(helper), "ax", "xcode-windows", "--json"], timeout_seconds=20)
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
        if require:
            return (
                payload(
                    "failure",
                    message,
                    data=details,
                    next_actions=["Run bin/xcode native permissions request --json if you want macOS to show the Accessibility prompt."],
                    exit_code=EXIT_CODES["permission_denied"],
                    error_type="permission_denied",
                ),
                warnings,
                details,
            )
        warnings.append(message)
        return None, warnings, details

    if ax["exit_code"] != 0:
        message = "Native helper AX preflight failed."
        if require:
            return (
                payload(
                    "failure",
                    message,
                    data=details,
                    warnings=[compact_output(ax["stderr"] or ax["stdout"])],
                    exit_code=EXIT_CODES["native_helper_failed"],
                    error_type="native_helper_failed",
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

    subparsers.add_parser("list-workspaces", help="List open Xcode workspace documents.")

    open_parser = subparsers.add_parser("open-workspace", help="Open an .xcodeproj or .xcworkspace in Xcode.")
    open_parser.add_argument("--path", required=True)
    open_parser.add_argument("--timeout-seconds", type=int, default=60)

    list_schemes = subparsers.add_parser("list-schemes", help="List schemes in a workspace.")
    list_schemes.add_argument("--workspace-path", default=None)

    list_destinations = subparsers.add_parser("list-destinations", help="List run destinations in a workspace.")
    list_destinations.add_argument("--workspace-path", default=None)

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
    if args.command == "status":
        return status_command()
    if args.command == "activate":
        return activate_command()
    if args.command == "open-workspace":
        return open_workspace_command(args.path, args.timeout_seconds)
    if args.command == "workspace-info":
        return workspace_info_command(args.workspace_path)
    if args.command == "list-workspaces":
        return list_workspaces_command()
    if args.command == "list-schemes":
        return list_schemes_command(args.workspace_path)
    if args.command == "list-destinations":
        return list_destinations_command(args.workspace_path)
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
