#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xcode_common import (
    EXIT_CODES,
    compact_output,
    emit_failure,
    emit_success,
    normalize_path,
    plugin_root,
    redacted_home_path,
    run_command,
)


SUPPORTED_HELPER_SCHEMA = "xcode-native-helper.v0.1"


def helper_path() -> Path:
    return plugin_root() / "bin" / "xcode-native-helper"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run optional native macOS/Xcode helper commands.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    subparsers = parser.add_subparsers(dest="group", required=True)

    helper = subparsers.add_parser("helper", help="Inspect the native helper.")
    helper_sub = helper.add_subparsers(dest="command", required=True)
    helper_sub.add_parser("version", help="Print native helper version metadata.")

    permissions = subparsers.add_parser("permissions", help="Inspect or request native permissions.")
    permissions_sub = permissions.add_subparsers(dest="command", required=True)
    permissions_sub.add_parser("status", help="Read Accessibility permission state without prompting.")
    permissions_sub.add_parser("request", help="Explicitly ask macOS to show the Accessibility permission prompt.")

    app = subparsers.add_parser("app", help="Inspect or control the Xcode app process.")
    app_sub = app.add_subparsers(dest="command", required=True)
    xcode_state = app_sub.add_parser("xcode-state", help="Inspect Xcode running/frontmost/process state.")
    xcode_state.add_argument("--include-paths", action="store_true", help="Include full local paths instead of redacted paths.")
    installed = app_sub.add_parser("installed-xcodes", help="List installed Xcode apps visible in standard application folders.")
    installed.add_argument("--include-paths", action="store_true", help="Include full local paths instead of redacted paths.")
    app_sub.add_parser("activate-xcode", help="Activate an already running Xcode app.")
    open_workspace = app_sub.add_parser("open-workspace", help="Open an .xcodeproj or .xcworkspace through NSWorkspace.")
    open_workspace.add_argument("--path", required=True)

    ax = subparsers.add_parser("ax", help="Read Xcode Accessibility window state.")
    ax_sub = ax.add_subparsers(dest="command", required=True)
    ax_windows = ax_sub.add_parser("xcode-windows", help="Read Xcode windows/sheets/modal blockers without mutation.")
    ax_windows.add_argument("--include-paths", action="store_true", help="Include full local document paths instead of redacted basenames.")

    return parser.parse_args()


def command_name(args: argparse.Namespace) -> str:
    return f"native.{args.group}.{args.command}"


def helper_argv(args: argparse.Namespace) -> list[str]:
    argv = [args.group, args.command]
    if args.group == "app" and args.command == "open-workspace":
        argv.extend(["--path", args.path])
    argv.append("--json")
    return argv


def include_paths(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "include_paths", False))


def helper_timeout(args: argparse.Namespace) -> int:
    if args.group == "helper" or args.group == "permissions":
        return 5
    if args.group == "ax":
        return 10
    if args.group == "app" and args.command in {"activate-xcode", "open-workspace"}:
        return 15
    return 5


def preflight_args(args: argparse.Namespace) -> int | None:
    if args.group == "app" and args.command == "open-workspace":
        path = normalize_path(args.path)
        suffix = path.suffix.lower()
        if suffix not in {".xcodeproj", ".xcworkspace"}:
            return emit_failure(
                command_name(args),
                "path_violation",
                "Native open-workspace only accepts .xcodeproj or .xcworkspace paths",
                details={"path": redacted_home_path(str(path)), "suffix": suffix},
                exit_code=EXIT_CODES["path_violation"],
            )
        if not path.exists() or not path.is_dir():
            return emit_failure(
                command_name(args),
                "workspace_open_failed",
                "Workspace/project path does not exist or is not a directory",
                details={"path": redacted_home_path(str(path))},
                exit_code=EXIT_CODES["workspace_open_failed"],
            )
        args.path = str(path)
    return None


def basename_from_file_url(value: str) -> str:
    if value.startswith("file://"):
        return Path(value.removeprefix("file://")).name
    return Path(value).name if value.startswith("/") else value


def redact_native_paths(value: Any, *, include_full_paths: bool, key: str | None = None) -> Any:
    if include_full_paths:
        return value
    if isinstance(value, dict):
        return {item_key: redact_native_paths(item_value, include_full_paths=False, key=item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_native_paths(item, include_full_paths=False, key=key) for item in value]
    if isinstance(value, str):
        if key == "document":
            return basename_from_file_url(value)
        if key in {"bundle_path", "executable_path", "path"}:
            return redacted_home_path(value)
        if value.startswith(str(Path.home())):
            return redacted_home_path(value)
    return value


def unavailable(args: argparse.Namespace, path: Path) -> int:
    return emit_failure(
        command_name(args),
        "native_helper_unavailable",
        "Native helper is not built or executable",
        details={"helper_path": str(path)},
        next_actions=[
            "Build the helper with: cd native/XcodeNativeHelper && swift build -c release",
            "Install the release binary at bin/xcode-native-helper.",
        ],
        exit_code=EXIT_CODES["native_helper_unavailable"],
    )


def parse_helper_json(result: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None, "Native helper returned malformed JSON"
    if not isinstance(data, dict):
        return None, "Native helper JSON was not an object"
    return data, None


def normalize_helper_output(args: argparse.Namespace, native: dict[str, Any], result: dict[str, Any]) -> int:
    schema = str(native.get("schema_version") or "")
    native = redact_native_paths(native, include_full_paths=include_paths(args))
    summary_value = native.get("summary")
    helper_version = native.get("helper_version")
    if helper_version is None and isinstance(summary_value, dict):
        helper_version = summary_value.get("helper_version")
    helper_meta = {
        "schema_version": schema,
        "helper_version": helper_version,
        "exit_code": result["exit_code"],
    }
    details = {
        "native_helper": helper_meta,
        "native": native,
    }
    warnings = list(native.get("warnings") or [])
    if result["stderr"].strip():
        warnings.append(compact_output(result["stderr"]))

    if schema != SUPPORTED_HELPER_SCHEMA:
        return emit_failure(
            command_name(args),
            "native_helper_version_mismatch",
            "Native helper schema is unsupported",
            details=details,
            warnings=warnings,
            errors=[f"expected {SUPPORTED_HELPER_SCHEMA}, got {schema or '<missing>'}"],
            exit_code=EXIT_CODES["native_helper_version_mismatch"],
        )

    ok = bool(native.get("ok"))
    summary = summary_value or ("Native helper command succeeded" if ok else "Native helper command failed")
    if ok and result["exit_code"] == 0:
        return emit_success(command_name(args), summary, details=details, warnings=warnings)

    native_error = str(native.get("error_type") or "native_helper_failed")
    error_type = native_error if native_error in EXIT_CODES else "native_helper_failed"
    return emit_failure(
        command_name(args),
        error_type,
        summary,
        details=details,
        warnings=warnings,
        errors=list(native.get("errors") or []),
        next_actions=list(native.get("next_actions") or []),
        exit_code=EXIT_CODES.get(error_type, result["exit_code"] or EXIT_CODES["native_helper_failed"]),
    )


def main() -> int:
    args = parse_args()
    preflight = preflight_args(args)
    if preflight is not None:
        return preflight
    path = helper_path()
    if not path.exists() or not path.is_file() or not (path.stat().st_mode & 0o111):
        return unavailable(args, path)

    result = run_command([str(path), *helper_argv(args)], timeout_seconds=helper_timeout(args))
    if result.get("timed_out"):
        return emit_failure(
            command_name(args),
            "command_timeout",
            "Native helper command timed out",
            details={"helper_path": str(path), "command": result["command"]},
            warnings=[compact_output(result["stderr"])] if result["stderr"].strip() else [],
            exit_code=EXIT_CODES["command_timeout"],
        )
    if result["exit_code"] == 127:
        return unavailable(args, path)

    native, parse_error = parse_helper_json(result)
    if native is None:
        return emit_failure(
            command_name(args),
            "native_helper_failed",
            parse_error or "Native helper JSON could not be parsed",
            details={"helper_path": str(path), "command": result["command"]},
            warnings=[compact_output(result["stderr"])] if result["stderr"].strip() else [],
            errors=[compact_output(result["stdout"], 1200)] if result["stdout"].strip() else [],
            exit_code=EXIT_CODES["native_helper_failed"],
        )
    return normalize_helper_output(args, native, result)


if __name__ == "__main__":
    raise SystemExit(main())
