#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from xcode_common import (
    EXIT_CODES,
    assert_path_inside,
    compact_output,
    create_artifact_dir,
    emit_failure,
    emit_success,
    normalize_path,
    run_command,
    write_json,
)


UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic JSON xcrun simctl workflows.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    parser.add_argument("--artifact-dir", default=None, help="Base artifact directory. Defaults to .codex/xcode/artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List devices, runtimes, and device types.")
    list_parser.add_argument("--devices-only", action="store_true")

    resolve_parser = subparsers.add_parser("resolve", help="Resolve a simulator name/runtime to exactly one UDID.")
    resolve_parser.add_argument("--name", required=True)
    resolve_parser.add_argument("--runtime", default=None, help="Runtime substring, for example 'iOS 18.5'.")
    resolve_parser.add_argument("--fixture", default=None, help="Fixture JSON matching 'simctl list devices --json'.")

    prepare_parser = subparsers.add_parser("prepare", help="Boot and optionally wait for a simulator by UDID.")
    prepare_parser.add_argument("--udid", required=True)
    prepare_parser.add_argument("--boot", action="store_true")
    prepare_parser.add_argument("--wait-ready", action="store_true")
    prepare_parser.add_argument("--timeout-seconds", type=int, default=120)

    boot_parser = subparsers.add_parser("boot", help="Boot a simulator device.")
    add_device_args(boot_parser)

    shutdown_parser = subparsers.add_parser("shutdown", help="Shut down a simulator device.")
    add_device_args(shutdown_parser)

    subparsers.add_parser("open", help="Open Simulator.app.")

    install_parser = subparsers.add_parser("install", help="Install an .app bundle on a simulator.")
    add_device_args(install_parser, default_booted=True)
    install_parser.add_argument("--app", required=True)

    launch_parser = subparsers.add_parser("launch", help="Launch an installed app by bundle id.")
    add_device_args(launch_parser, default_booted=True)
    launch_parser.add_argument("--bundle-id", required=True)
    launch_parser.add_argument("arguments", nargs=argparse.REMAINDER)

    terminate_parser = subparsers.add_parser("terminate", help="Terminate an app by bundle id.")
    add_device_args(terminate_parser, default_booted=True)
    terminate_parser.add_argument("--bundle-id", required=True)

    screenshot_parser = subparsers.add_parser("screenshot", help="Capture a simulator screenshot.")
    add_device_args(screenshot_parser, default_booted=True)
    screenshot_parser.add_argument("--output", default=None)
    screenshot_parser.add_argument("--allow-any-output-path", action="store_true")

    return parser.parse_args()


def add_device_args(parser: argparse.ArgumentParser, *, default_booted: bool = False) -> None:
    parser.add_argument("--udid", default=None, help="Simulator UDID. Preferred for v0.3 lifecycle commands.")
    parser.add_argument("--device", default="booted" if default_booted else None, help="Legacy UDID/name/'booted' alias.")
    parser.add_argument("--name", default=None, help="Simulator name alias. Fails when ambiguous.")
    parser.add_argument("--runtime", default=None, help="Runtime substring used with --name.")


def load_devices(fixture: str | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if fixture:
        path = Path(fixture).expanduser()
        return json.loads(path.read_text(encoding="utf-8")), warnings
    result = run_command(["xcrun", "simctl", "list", "devices", "--json"], timeout_seconds=60)
    if result["exit_code"] != 0:
        warnings.append(compact_output(result["stderr"] or result["stdout"]))
        return None, warnings
    try:
        return json.loads(result["stdout"]), warnings
    except json.JSONDecodeError:
        warnings.append("simctl list devices --json returned invalid JSON.")
        return None, warnings


def flatten_devices(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    devices = inventory.get("devices", {})
    flattened: list[dict[str, Any]] = []
    if not isinstance(devices, dict):
        return flattened
    for runtime, items in devices.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            flattened.append({**item, "runtime": runtime})
    return flattened


def normalize_runtime_token(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    normalized = normalized.removeprefix("com.apple.coresimulator.simruntime.")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized


def runtime_matches(requested: str | None, actual: str) -> bool:
    if not requested:
        return True
    requested_token = normalize_runtime_token(requested)
    actual_token = normalize_runtime_token(actual)
    if not requested_token:
        return True
    if requested_token == actual_token:
        return True
    return requested_token in actual_token or actual_token.endswith(f"-{requested_token}")


def resolve_matches(name: str, runtime: str | None, inventory: dict[str, Any]) -> list[dict[str, Any]]:
    matches = []
    for device in flatten_devices(inventory):
        if device.get("name") != name:
            continue
        if device.get("isAvailable") is False:
            continue
        device_runtime = str(device.get("runtime") or "")
        if not runtime_matches(runtime, device_runtime):
            continue
        matches.append(device)
    return matches


def resolve_command(name: str, runtime: str | None, fixture: str | None = None) -> int:
    inventory, warnings = load_devices(fixture)
    if inventory is None:
        return emit_failure(
            "simulator",
            "subprocess_failed",
            "Unable to read simulator inventory",
            warnings=warnings,
            exit_code=EXIT_CODES["subprocess_failed"],
        )
    matches = resolve_matches(name, runtime, inventory)
    details = {
        "name": name,
        "runtime": runtime,
        "normalized_runtime": normalize_runtime_token(runtime),
        "match_count": len(matches),
        "matches": matches,
    }
    if not matches:
        return emit_failure(
            "simulator",
            "destination_not_found",
            "No simulator matched the requested name/runtime",
            details=details,
            warnings=warnings,
            next_actions=["Run xcode simulator list --json and choose an available simulator."],
            exit_code=EXIT_CODES["destination_not_found"],
        )
    if len(matches) > 1:
        return emit_failure(
            "simulator",
            "destination_ambiguous",
            "Multiple simulators matched the requested name/runtime",
            details=details,
            warnings=warnings,
            next_actions=["Pass --runtime to narrow the match or use --udid directly."],
            exit_code=EXIT_CODES["destination_ambiguous"],
        )
    device = matches[0]
    return emit_success(
        "simulator",
        "Simulator resolved to one UDID",
        details={"device": device, "udid": device.get("udid"), "runtime": device.get("runtime")},
        warnings=warnings,
    )


def resolve_device_arg(args: argparse.Namespace) -> tuple[str | None, int | None]:
    requested = getattr(args, "udid", None) or getattr(args, "device", None)
    if requested == "booted":
        return "booted", None
    if requested and UUID_RE.match(requested):
        return requested, None
    name = getattr(args, "name", None) or requested
    if not name:
        return None, EXIT_CODES["usage_error"]
    inventory, _ = load_devices(None)
    if inventory is None:
        return None, EXIT_CODES["subprocess_failed"]
    matches = resolve_matches(name, getattr(args, "runtime", None), inventory)
    if not matches:
        return None, EXIT_CODES["destination_not_found"]
    if len(matches) > 1:
        return None, EXIT_CODES["destination_ambiguous"]
    return str(matches[0]["udid"]), None


def finish_simctl(command_name: str, result: dict[str, Any], summary: str, *, success_details: dict[str, Any] | None = None) -> int:
    details = {"command": result["command"], **(success_details or {})}
    warnings = [compact_output(result["stderr"])] if result["stderr"].strip() else []
    if result["exit_code"] == 0:
        if result["stdout"].strip():
            details["stdout"] = compact_output(result["stdout"], 4000)
        return emit_success("simulator", summary, details=details, warnings=warnings)
    error_type = "command_timeout" if result.get("timed_out") else command_name
    if command_name not in EXIT_CODES:
        error_type = "subprocess_failed"
    return emit_failure(
        "simulator",
        error_type,
        f"{summary} failed",
        details=details,
        warnings=warnings,
        errors=[compact_output(result["stderr"] or result["stdout"])],
        exit_code=EXIT_CODES.get(error_type, result["exit_code"] or 1),
    )


def prepare_command(args: argparse.Namespace) -> int:
    artifacts: dict[str, Any] = {}
    details: dict[str, Any] = {"udid": args.udid, "boot_requested": args.boot, "wait_ready": args.wait_ready}
    warnings: list[str] = []
    if args.boot:
        boot = run_command(["xcrun", "simctl", "boot", args.udid], timeout_seconds=60)
        details["boot"] = {"exit_code": boot["exit_code"], "stderr": compact_output(boot["stderr"])}
        if boot["exit_code"] != 0 and "already booted" not in (boot["stderr"] + boot["stdout"]).lower():
            return emit_failure(
                "simulator",
                "simulator_boot_failed",
                "Simulator boot failed",
                details=details,
                warnings=warnings,
                errors=[compact_output(boot["stderr"] or boot["stdout"])],
                exit_code=EXIT_CODES["simulator_boot_failed"],
            )
        if boot["exit_code"] != 0:
            warnings.append("Simulator was already booted.")
    if args.wait_ready:
        bootstatus = run_command(["xcrun", "simctl", "bootstatus", args.udid, "-b"], timeout_seconds=args.timeout_seconds)
        details["bootstatus"] = {"exit_code": bootstatus["exit_code"], "stderr": compact_output(bootstatus["stderr"])}
        if bootstatus["exit_code"] != 0:
            error_type = "command_timeout" if bootstatus.get("timed_out") else "simulator_boot_failed"
            return emit_failure(
                "simulator",
                error_type,
                "Simulator did not become ready",
                details=details,
                artifacts=artifacts,
                errors=[compact_output(bootstatus["stderr"] or bootstatus["stdout"])],
                exit_code=EXIT_CODES[error_type],
            )
    return emit_success("simulator", "Simulator prepared", details=details, artifacts=artifacts, warnings=warnings)


def main() -> int:
    args = parse_args()
    if args.command == "list":
        command = ["xcrun", "simctl", "list", "--json"]
        if args.devices_only:
            command.insert(3, "devices")
        result = run_command(command, timeout_seconds=60)
        warnings = [compact_output(result["stderr"])] if result["stderr"].strip() else []
        if result["exit_code"] != 0:
            return emit_failure("simulator", "subprocess_failed", "Simulator inventory listing failed", warnings=warnings, exit_code=result["exit_code"] or 1)
        try:
            inventory = json.loads(result["stdout"])
        except json.JSONDecodeError:
            return emit_failure("simulator", "subprocess_failed", "simctl output was not valid JSON", warnings=warnings, exit_code=EXIT_CODES["subprocess_failed"])
        return emit_success("simulator", "Simulator inventory listed", details={"simctl": inventory}, warnings=warnings)
    if args.command == "resolve":
        return resolve_command(args.name, args.runtime, args.fixture)
    if args.command == "prepare":
        return prepare_command(args)
    if args.command == "open":
        return finish_simctl("subprocess_failed", run_command(["open", "-a", "Simulator"], timeout_seconds=30), "Simulator.app opened")

    if args.command in {"boot", "shutdown", "install", "launch", "terminate", "screenshot"}:
        udid, error_code = resolve_device_arg(args)
        if error_code is not None or udid is None:
            code_to_error = {
                EXIT_CODES["destination_not_found"]: "destination_not_found",
                EXIT_CODES["destination_ambiguous"]: "destination_ambiguous",
                EXIT_CODES["usage_error"]: "usage_error",
            }
            error_type = code_to_error.get(error_code or EXIT_CODES["usage_error"], "usage_error")
            return emit_failure(
                "simulator",
                error_type,
                "Simulator device could not be resolved",
                details={"requested_device": getattr(args, "device", None), "requested_name": getattr(args, "name", None), "runtime": getattr(args, "runtime", None)},
                next_actions=["Use xcode simulator resolve first, then pass --udid."],
                exit_code=error_code or EXIT_CODES["usage_error"],
            )
        if args.command == "boot":
            return finish_simctl("simulator_boot_failed", run_command(["xcrun", "simctl", "boot", udid], timeout_seconds=60), "Simulator boot requested", success_details={"udid": udid})
        if args.command == "shutdown":
            return finish_simctl("subprocess_failed", run_command(["xcrun", "simctl", "shutdown", udid], timeout_seconds=60), "Simulator shutdown requested", success_details={"udid": udid})
        if args.command == "install":
            app_path = normalize_path(args.app)
            if not app_path.exists():
                return emit_failure("simulator", "install_failed", "App bundle does not exist", details={"app": str(app_path)}, exit_code=EXIT_CODES["install_failed"])
            return finish_simctl("install_failed", run_command(["xcrun", "simctl", "install", udid, str(app_path)], timeout_seconds=120), "App installed on simulator", success_details={"udid": udid, "app": str(app_path)})
        if args.command == "launch":
            forwarded = list(args.arguments)
            if forwarded and forwarded[0] == "--":
                forwarded = forwarded[1:]
            return finish_simctl("launch_failed", run_command(["xcrun", "simctl", "launch", udid, args.bundle_id, *forwarded], timeout_seconds=120), "App launched on simulator", success_details={"udid": udid, "bundle_id": args.bundle_id})
        if args.command == "terminate":
            return finish_simctl("subprocess_failed", run_command(["xcrun", "simctl", "terminate", udid, args.bundle_id], timeout_seconds=60), "App terminated on simulator", success_details={"udid": udid, "bundle_id": args.bundle_id})
        if args.command == "screenshot":
            artifact_dir = create_artifact_dir("simulator-screenshot", args.artifact_dir)
            output = normalize_path(args.output) if args.output else artifact_dir / "screenshot.png"
            if args.output and not args.allow_any_output_path:
                try:
                    assert_path_inside(output, artifact_dir)
                except ValueError as exc:
                    return emit_failure(
                        "simulator",
                        "path_violation",
                        "Screenshot output path is outside the artifact directory",
                        details={"output": str(output), "artifact_dir": str(artifact_dir)},
                        errors=[str(exc)],
                        next_actions=["Omit --output or pass --allow-any-output-path explicitly."],
                        exit_code=EXIT_CODES["path_violation"],
                        artifact_dir=artifact_dir,
                    )
            output.parent.mkdir(parents=True, exist_ok=True)
            result = run_command(["xcrun", "simctl", "io", udid, "screenshot", str(output)], timeout_seconds=60)
            artifacts = {"screenshot": str(output), "artifact_dir": str(artifact_dir)}
            if result["exit_code"] == 0:
                return emit_success("simulator", "Simulator screenshot captured", details={"udid": udid}, artifacts=artifacts, artifact_dir=artifact_dir)
            return emit_failure("simulator", "subprocess_failed", "Simulator screenshot failed", details={"udid": udid}, artifacts=artifacts, errors=[compact_output(result["stderr"] or result["stdout"])], exit_code=result["exit_code"] or 1, artifact_dir=artifact_dir)
    return emit_failure("simulator", "usage_error", "Unknown simulator command", details={"command": args.command}, exit_code=EXIT_CODES["usage_error"])


if __name__ == "__main__":
    raise SystemExit(main())
