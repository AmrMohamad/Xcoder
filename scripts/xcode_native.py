#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from xcode_native_capabilities import capability_report
from xcode_common import (
    EXIT_CODES,
    compact_output,
    emit_failure,
    emit_success,
    native_helper_bundle_executable_path,
    native_helper_bundle_path,
    native_helper_legacy_executable_path,
    native_helper_path,
    normalize_path,
    plugin_root,
    plugin_version,
    redacted_home_path,
    run_command,
)


SUPPORTED_HELPER_SCHEMA = "xcode-native-helper.v0.1"
DEFAULT_HELPER_IDENTIFIER = "com.amrmohamad.xcoder.native-helper"
HELPER_APP_DISPLAY_NAME = "xcode-native-helper"


def helper_path() -> Path:
    return native_helper_path()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run optional native macOS/Xcode helper commands.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    subparsers = parser.add_subparsers(dest="group", required=True)

    helper = subparsers.add_parser("helper", help="Inspect the native helper.")
    helper_sub = helper.add_subparsers(dest="command", required=True)
    helper_sub.add_parser("version", help="Print native helper version metadata.")
    helper_sub.add_parser("identity", help="Print native helper code-signing identity metadata.")
    helper_sign = helper_sub.add_parser("sign", help="Sign the native helper with a stable local code-signing identity.")
    helper_sign.add_argument("--identity", default=None, help="Code-signing identity name or hash. Defaults to the first Apple Development identity.")
    helper_sign.add_argument("--identifier", default=DEFAULT_HELPER_IDENTIFIER, help="Stable code-signing identifier for TCC matching.")
    helper_bundle = helper_sub.add_parser("bundle", help="Package the native helper as a signed .app bundle for durable TCC matching.")
    helper_bundle.add_argument("--identity", default=None, help="Code-signing identity name or hash. Defaults to the first Apple Development identity.")
    helper_bundle.add_argument("--identifier", default=DEFAULT_HELPER_IDENTIFIER, help="Bundle identifier for TCC and LaunchServices matching.")

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
    ax_press_menu = ax_sub.add_parser("press-menu", help="Press a typed Xcode menu path through the trusted native helper.")
    ax_press_menu.add_argument("--menu-path-json", required=True, help="JSON array of menu labels, for example [\"Product\", \"Archive\"].")
    ax_inspect = ax_sub.add_parser("inspect", help="Inspect a filtered Xcode AX tree through the trusted native helper.")
    ax_inspect.add_argument("--window-title-contains", default=None)
    ax_inspect.add_argument("--max-depth", type=int, default=3)
    ax_inspect.add_argument("--max-children", type=int, default=80)
    ax_press_button = ax_sub.add_parser("press-button", help="Press a named Xcode button through the trusted native helper.")
    ax_press_button.add_argument("--title", required=True)
    ax_press_button.add_argument("--window-title-contains", default=None)
    ax_press_control = ax_sub.add_parser("press-control", help="Press a named Xcode AX control through the trusted native helper.")
    ax_press_control.add_argument("--role", choices=["AXRadioButton", "AXCheckBox", "AXPopUpButton"], required=True)
    ax_press_control.add_argument("--title", required=True)
    ax_press_control.add_argument("--window-title-contains", default=None)

    return parser.parse_args()


def command_name(args: argparse.Namespace) -> str:
    return f"native.{args.group}.{args.command}"


def helper_argv(args: argparse.Namespace) -> list[str]:
    argv = [args.group, args.command]
    if args.group == "app" and args.command == "open-workspace":
        argv.extend(["--path", args.path])
    if args.group == "ax" and args.command == "press-menu":
        argv.extend(["--menu-path-json", args.menu_path_json])
    if args.group == "ax" and args.command == "inspect":
        if args.window_title_contains:
            argv.extend(["--window-title-contains", args.window_title_contains])
        argv.extend(["--max-depth", str(args.max_depth), "--max-children", str(args.max_children)])
    if args.group == "ax" and args.command == "press-button":
        argv.extend(["--title", args.title])
        if args.window_title_contains:
            argv.extend(["--window-title-contains", args.window_title_contains])
    if args.group == "ax" and args.command == "press-control":
        argv.extend(["--role", args.role, "--title", args.title])
        if args.window_title_contains:
            argv.extend(["--window-title-contains", args.window_title_contains])
    argv.append("--json")
    return argv


def include_paths(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "include_paths", False))


def helper_timeout(args: argparse.Namespace) -> int:
    if args.group == "helper" and args.command in {"bundle", "sign"}:
        return 30
    if args.group == "helper" or args.group == "permissions":
        return 5
    if args.group == "ax" and args.command in {"press-menu", "press-button", "press-control"}:
        return 15
    if args.group == "ax" and args.command == "inspect":
        return 20
    if args.group == "ax":
        return 10
    if args.group == "app" and args.command in {"activate-xcode", "open-workspace"}:
        return 15
    return 5


def should_launch_via_bundle(args: argparse.Namespace) -> bool:
    return native_helper_bundle_path().exists() and args.group in {"ax", "permissions"}


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


def active_codesign_target() -> Path:
    bundle = native_helper_bundle_path()
    return bundle if bundle.exists() else helper_path()


def helper_bundle_info(identifier: str) -> dict[str, Any]:
    version = plugin_version()
    return {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": HELPER_APP_DISPLAY_NAME,
        "CFBundleExecutable": "xcode-native-helper",
        "CFBundleIdentifier": identifier,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "XcodeNativeHelper",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "14.0",
        "LSUIElement": True,
    }


def write_helper_bundle_info_plist(bundle: Path, *, identifier: str) -> Path:
    contents = bundle / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    info_path = contents / "Info.plist"
    with info_path.open("wb") as stream:
        plistlib.dump(helper_bundle_info(identifier), stream, sort_keys=True)
    return info_path


def parse_helper_json(result: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None, "Native helper returned malformed JSON"
    if not isinstance(data, dict):
        return None, "Native helper JSON was not an object"
    return data, None


def run_helper_direct(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    return run_command([str(path), *helper_argv(args)], timeout_seconds=helper_timeout(args))


def run_helper_via_launchservices(args: argparse.Namespace) -> dict[str, Any]:
    bundle = native_helper_bundle_path()
    with tempfile.TemporaryDirectory(prefix="xcode-native-helper-") as tmpdir:
        output_path = Path(tmpdir) / "response.json"
        command = [
            "open",
            "-W",
            "-n",
            str(bundle),
            "--args",
            *helper_argv(args),
            "--output-json-path",
            str(output_path),
        ]
        result = run_command(command, timeout_seconds=helper_timeout(args) + 10)
        stdout = ""
        if output_path.exists():
            stdout = output_path.read_text(encoding="utf-8")
        elif result["stdout"].strip():
            stdout = result["stdout"]
        return {
            **result,
            "stdout": stdout,
            "launchservices": True,
            "bundle_path": str(bundle),
        }


def codesign_identity(path: Path) -> dict[str, Any]:
    result = run_command(["codesign", "-dvvv", "-r-", str(path)], timeout_seconds=10)
    output = compact_output(result["stdout"] + result["stderr"], 4000)
    return {
        "exit_code": result["exit_code"],
        "present": result["exit_code"] == 0,
        "adhoc": "Signature=adhoc" in output or "Signature=Ad Hoc" in output,
        "identifier": extract_codesign_field(output, "Identifier"),
        "team_identifier": extract_codesign_field(output, "TeamIdentifier"),
        "cdhash": extract_codesign_field(output, "CDHash"),
        "designated_requirement": extract_designated_requirement(output),
        "output": output,
    }


def extract_codesign_field(output: str, field: str) -> str | None:
    prefix = f"{field}="
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def extract_designated_requirement(output: str) -> str | None:
    marker = "designated => "
    for line in output.splitlines():
        if line.startswith(marker):
            return line.removeprefix(marker).strip()
    return None


def helper_identity_command(path: Path) -> int:
    target = active_codesign_target()
    identity = codesign_identity(target)
    status = "success" if identity["present"] else "failure"
    summary = "Native helper code-signing identity inspected" if identity["present"] else "Native helper code-signing identity unavailable"
    details = {
        "helper_path": redacted_home_path(str(path)),
        "legacy_helper_path": redacted_home_path(str(native_helper_legacy_executable_path())),
        "bundle_path": redacted_home_path(str(native_helper_bundle_path())),
        "codesign_target": redacted_home_path(str(target)),
        "bundled": native_helper_bundle_path().exists(),
        "codesign": identity,
        "tcc_stable": bool(identity.get("team_identifier")) and not bool(identity.get("adhoc")),
        "capabilities": capability_report(),
    }
    warnings: list[str] = []
    next_actions: list[str] = []
    if identity.get("adhoc"):
        warnings.append("Native helper is ad-hoc signed; macOS Accessibility may show a toggle that does not bind durably to this helper.")
        next_actions.append("Run bin/xcode native helper bundle --json, then request and approve Accessibility again.")
    if not native_helper_bundle_path().exists():
        warnings.append("Native helper is not packaged as an app bundle; LaunchServices/TCC may not match the Accessibility row reliably.")
        next_actions.append("Run bin/xcode native helper bundle --json, then add XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility.")
    if identity["present"]:
        return emit_success("native.helper.identity", summary, details=details, warnings=warnings, next_actions=next_actions)
    return emit_failure(
        "native.helper.identity",
        "native_helper_failed",
        summary,
        details=details,
        warnings=warnings,
        next_actions=next_actions,
        exit_code=EXIT_CODES["native_helper_failed"],
    )


def find_default_signing_identity() -> tuple[str | None, str]:
    result = run_command(["security", "find-identity", "-v", "-p", "codesigning"], timeout_seconds=10)
    output = result["stdout"] + result["stderr"]
    if result["exit_code"] != 0:
        return None, compact_output(output, 4000)
    for line in output.splitlines():
        if "Apple Development:" not in line:
            continue
        parts = line.split('"')
        if len(parts) >= 2:
            return parts[1], compact_output(output, 4000)
    return None, compact_output(output, 4000)


def helper_sign_command(path: Path, *, identity: str | None, identifier: str) -> int:
    target = active_codesign_target()
    selected_identity = identity
    identity_output = ""
    if not selected_identity:
        selected_identity, identity_output = find_default_signing_identity()
    if not selected_identity:
        return emit_failure(
            "native.helper.sign",
            "native_helper_failed",
            "No Apple Development code-signing identity is available for the native helper",
            details={"helper_path": redacted_home_path(str(path)), "identity_lookup": identity_output},
            next_actions=["Install or unlock an Apple Development signing identity, then retry."],
            exit_code=EXIT_CODES["native_helper_failed"],
        )

    sign = run_command(
        [
            "codesign",
            "--force",
            "--sign",
            selected_identity,
            "--identifier",
            identifier,
            str(target),
        ],
        timeout_seconds=30,
    )
    identity_after = codesign_identity(target)
    details = {
        "helper_path": redacted_home_path(str(path)),
        "codesign_target": redacted_home_path(str(target)),
        "bundled": native_helper_bundle_path().exists(),
        "requested_identity": selected_identity,
        "requested_identifier": identifier,
        "codesign_exit_code": sign["exit_code"],
        "codesign_output": compact_output(sign["stdout"] + sign["stderr"], 4000),
        "codesign": identity_after,
        "tcc_stable": bool(identity_after.get("team_identifier")) and not bool(identity_after.get("adhoc")),
    }
    if sign["exit_code"] != 0:
        return emit_failure(
            "native.helper.sign",
            "native_helper_failed",
            "Native helper signing failed",
            details=details,
            exit_code=EXIT_CODES["native_helper_failed"],
        )
    return emit_success(
        "native.helper.sign",
        "Native helper signed with a stable code identity",
        details=details,
        next_actions=[
            "Run bin/xcode native permissions request --json.",
            "Approve XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility.",
            "Verify with bin/xcode native permissions status --json.",
        ],
    )


def helper_bundle_command(path: Path, *, identity: str | None, identifier: str) -> int:
    legacy = native_helper_legacy_executable_path()
    bundle = native_helper_bundle_path()
    bundled_executable = native_helper_bundle_executable_path()
    source = legacy if legacy.exists() else path
    if not source.exists() or not source.is_file():
        return emit_failure(
            "native.helper.bundle",
            "native_helper_unavailable",
            "Native helper executable is not available to package",
            details={
                "legacy_helper_path": redacted_home_path(str(legacy)),
                "active_helper_path": redacted_home_path(str(path)),
                "bundle_path": redacted_home_path(str(bundle)),
            },
            next_actions=["Build native/XcodeNativeHelper and install bin/xcode-native-helper first."],
            exit_code=EXIT_CODES["native_helper_unavailable"],
        )

    selected_identity = identity
    identity_output = ""
    if not selected_identity:
        selected_identity, identity_output = find_default_signing_identity()
    if not selected_identity:
        return emit_failure(
            "native.helper.bundle",
            "native_helper_failed",
            "No Apple Development code-signing identity is available for the native helper bundle",
            details={"identity_lookup": identity_output},
            next_actions=["Install or unlock an Apple Development signing identity, then retry."],
            exit_code=EXIT_CODES["native_helper_failed"],
        )

    macos_dir = bundle / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)
    if source.resolve(strict=False) != bundled_executable.resolve(strict=False):
        shutil.copy2(source, bundled_executable)
    bundled_executable.chmod(0o755)
    info_path = write_helper_bundle_info_plist(bundle, identifier=identifier)
    sign = run_command(
        [
            "codesign",
            "--force",
            "--sign",
            selected_identity,
            "--identifier",
            identifier,
            str(bundle),
        ],
        timeout_seconds=30,
    )
    identity_after = codesign_identity(bundle)
    details = {
        "source_helper_path": redacted_home_path(str(source)),
        "helper_path": redacted_home_path(str(bundled_executable)),
        "legacy_helper_path": redacted_home_path(str(legacy)),
        "bundle_path": redacted_home_path(str(bundle)),
        "info_plist": redacted_home_path(str(info_path)),
        "requested_identity": selected_identity,
        "requested_identifier": identifier,
        "codesign_exit_code": sign["exit_code"],
        "codesign_output": compact_output(sign["stdout"] + sign["stderr"], 4000),
        "codesign": identity_after,
        "tcc_stable": bool(identity_after.get("team_identifier")) and not bool(identity_after.get("adhoc")),
    }
    if sign["exit_code"] != 0:
        return emit_failure(
            "native.helper.bundle",
            "native_helper_failed",
            "Native helper bundle signing failed",
            details=details,
            exit_code=EXIT_CODES["native_helper_failed"],
        )
    return emit_success(
        "native.helper.bundle",
        "Native helper packaged as a signed app bundle",
        details=details,
        next_actions=[
            "Add XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility.",
            "Verify with bin/xcode native permissions status --json.",
        ],
    )


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
    if result.get("launchservices"):
        helper_meta["launchservices"] = True
        helper_meta["bundle_path"] = redacted_home_path(str(result.get("bundle_path") or ""))
    details = {
        "native_helper": helper_meta,
        "native": native,
    }
    warnings = list(native.get("warnings") or [])
    if result["stderr"].strip():
        stderr = compact_output(result["stderr"])
        if not (result.get("launchservices") and "Unable to block on application" in stderr):
            warnings.append(stderr)

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
    if ok and (result["exit_code"] == 0 or result.get("launchservices")):
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

    if args.group == "helper" and args.command == "identity":
        return helper_identity_command(path)
    if args.group == "helper" and args.command == "bundle":
        return helper_bundle_command(path, identity=args.identity, identifier=args.identifier)
    if args.group == "helper" and args.command == "sign":
        return helper_sign_command(path, identity=args.identity, identifier=args.identifier)

    result = run_helper_via_launchservices(args) if should_launch_via_bundle(args) else run_helper_direct(path, args)
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
