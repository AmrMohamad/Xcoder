#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from xcode_common import EXIT_CODES, compact_output, emit_failure, emit_success, normalize_path, plugin_identity, plugin_root, redacted_home_path, run_command


REQUIRED_XCODEBUILD_FLAGS = [
    "-parallelizeTargets",
    "-jobs",
    "-hideShellScriptEnvironment",
    "-clonedSourcePackagesDirPath",
    "-disableAutomaticPackageResolution",
    "-skipPackageUpdates",
    "-skipPackagePluginValidation",
    "-skipMacroValidation",
    "-packageCachePath",
    "-showBuildTimingSummary",
]

REQUIRED_SDEF_TERMS = [
    "workspace document",
    "active workspace document",
    "active scheme",
    "active run destination",
    "scheme action result",
    "build log",
    "build error",
    "build warning",
    "test failure",
    '<command name="build"',
    '<command name="run"',
    '<command name="test"',
    '<command name="debug"',
]

REQUIRED_SIMCTL_TERMS = ["boot", "install", "launch", "terminate", "io", "list", "shutdown"]
MINIMUM_NATIVE_MACOS_VERSION = "14.0"
ISSUES_URL = "https://github.com/AmrMohamad/Xcoder/issues"


def parse_version(value: str) -> tuple[int, int, int]:
    parts = []
    for part in value.strip().split(".")[:3]:
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def version_at_least(current: str, minimum: str) -> bool:
    return parse_version(current) >= parse_version(minimum)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the local Xcode toolchain and xcode plugin assumptions.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    parser.add_argument("--strict", action="store_true", help="Treat optional IDE automation warnings as failures.")
    parser.add_argument("--checks", default=None, help="Optional comma-separated check names requested by MCP callers; currently informational.")
    parser.add_argument("--artifact-dir", default=None, help="Reserved for future doctor artifacts.")
    return parser.parse_args()


def selected_xcode_app(developer_dir: str | None) -> str | None:
    if not developer_dir:
        return None
    path = Path(developer_dir)
    if path.name == "Developer" and path.parent.name == "Contents":
        return str(path.parent.parent)
    return None


def add_check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    status: str,
    exit_code: int | None = None,
    output: str | None = None,
    **extra: Any,
) -> None:
    item: dict[str, Any] = {"name": name, "status": status}
    if exit_code is not None:
        item["exit_code"] = exit_code
    if output:
        item["output"] = output
    item.update(extra)
    checks.append(item)


def native_helper_path() -> Path:
    return plugin_root() / "bin" / "xcode-native-helper"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def helper_identity_details(helper: Path) -> dict[str, Any]:
    archs = run_command(["lipo", "-archs", str(helper)], timeout_seconds=10)
    codesign = run_command(["codesign", "-dv", str(helper)], timeout_seconds=10)
    spctl = run_command(["spctl", "-a", "-vv", str(helper)], timeout_seconds=10)
    build_version = run_command(["vtool", "-show-build", str(helper)], timeout_seconds=10)
    quarantine = run_command(["xattr", "-p", "com.apple.quarantine", str(helper)], timeout_seconds=10)
    codesign_text = compact_output(codesign["stdout"] + codesign["stderr"], 2000)
    return {
        "helper_path": redacted_home_path(str(helper)),
        "helper_sha256": file_sha256(helper),
        "arch_slices": archs["stdout"].split() if archs["exit_code"] == 0 else [],
        "codesign": {
            "present": codesign["exit_code"] == 0,
            "adhoc": "Signature=adhoc" in codesign_text or "Signature=Ad Hoc" in codesign_text,
            "output": codesign_text,
        },
        "spctl": {
            "exit_code": spctl["exit_code"],
            "accepted": spctl["exit_code"] == 0,
            "output": compact_output(spctl["stdout"] + spctl["stderr"], 1200),
            "local_rejection_is_expected": spctl["exit_code"] != 0,
        },
        "mach_o_build_version": {
            "exit_code": build_version["exit_code"],
            "output": compact_output(build_version["stdout"] + build_version["stderr"], 1200),
        },
        "quarantine_xattr_present": quarantine["exit_code"] == 0,
        "same_binary_invoked_by_native_adapter": True,
    }


def add_native_helper_checks(checks: list[dict[str, Any]], warnings: list[str], selected_app: str | None) -> None:
    root = plugin_root()
    helper = native_helper_path()
    package = root / "native" / "XcodeNativeHelper" / "Package.swift"
    source = root / "native" / "XcodeNativeHelper" / "Sources" / "XcodeNativeHelper" / "main.swift"

    add_check(
        checks,
        name="native-helper-source",
        status="ok" if package.exists() and source.exists() else "optional_unavailable",
        package=str(package) if package.exists() else None,
        source=str(source) if source.exists() else None,
    )

    swift = run_command(["swift", "--version"], timeout_seconds=20)
    add_check(
        checks,
        name="native-helper-swift-toolchain",
        status="ok" if swift["exit_code"] == 0 else "optional_unavailable",
        exit_code=swift["exit_code"],
        output=compact_output(swift["stdout"] + swift["stderr"], 1200),
    )

    if not helper.exists() or not helper.is_file() or not (helper.stat().st_mode & 0o111):
        add_check(
            checks,
            name="native-helper-binary",
            status="optional_unavailable",
            path=str(helper),
        )
        warnings.append("Native Xcode helper is optional and not currently built at bin/xcode-native-helper.")
        return

    add_check(checks, name="native-helper-binary", status="optional_ok", **helper_identity_details(helper))

    version = run_command([str(helper), "helper", "version", "--json"], timeout_seconds=20)
    version_status = "ok"
    version_details: dict[str, Any] = {"exit_code": version["exit_code"]}
    try:
        version_json = json.loads(version["stdout"])
        version_details["helper"] = version_json.get("summary")
        if version_json.get("schema_version") != "xcode-native-helper.v0.1":
            version_status = "warning"
            warnings.append("Native Xcode helper schema does not match the plugin adapter expectation.")
    except json.JSONDecodeError:
        version_status = "warning"
        version_details["output"] = compact_output(version["stdout"] + version["stderr"], 1200)
        warnings.append("Native Xcode helper version output was not valid JSON.")
    add_check(checks, name="native-helper-version", status=version_status, **version_details)

    permissions = run_command([str(helper), "permissions", "status", "--json"], timeout_seconds=20)
    permissions_status = "ok" if permissions["exit_code"] == 0 else "warning"
    permissions_details: dict[str, Any] = {"exit_code": permissions["exit_code"]}
    try:
        permissions_json = json.loads(permissions["stdout"])
        permissions_details["permissions"] = permissions_json.get("summary")
    except json.JSONDecodeError:
        permissions_status = "warning"
        permissions_details["output"] = compact_output(permissions["stdout"] + permissions["stderr"], 1200)
    add_check(checks, name="native-helper-accessibility-status", status=permissions_status, **permissions_details)

    state = run_command([str(helper), "app", "xcode-state", "--json"], timeout_seconds=20)
    state_status = "ok" if state["exit_code"] == 0 else "warning"
    state_details: dict[str, Any] = {"exit_code": state["exit_code"]}
    try:
        state_json = json.loads(state["stdout"])
        summary = state_json.get("summary") or {}
        state_details["xcode_state"] = summary
        if selected_app and isinstance(summary, dict):
            running_apps = summary.get("running_apps") or []
            running_paths = [str(item.get("bundle_path") or "") for item in running_apps if isinstance(item, dict)]
            selected_normalized = str(normalize_path(selected_app))
            if running_paths and selected_normalized not in {str(normalize_path(item)) for item in running_paths if item}:
                warnings.append("Running Xcode.app does not match the selected xcode-select developer directory.")
                state_details["selected_xcode_app"] = selected_app
                state_details["running_xcode_apps"] = running_paths
                state_status = "warning"
    except json.JSONDecodeError:
        state_status = "warning"
        state_details["output"] = compact_output(state["stdout"] + state["stderr"], 1200)
    add_check(checks, name="native-helper-xcode-state", status=state_status, **state_details)


def add_mcp_server_checks(checks: list[dict[str, Any]], warnings: list[str]) -> None:
    root = plugin_root()
    binary = root / "bin" / "xcode-mcp-server"
    if not binary.exists() or not (binary.stat().st_mode & 0o111):
        warnings.append("Bundled MCP server binary is not currently built at bin/xcode-mcp-server.")
        add_check(checks, name="mcp-server-binary-present", status="failed", path=str(binary))
        return

    add_check(checks, name="mcp-server-binary-signing", status="ok", **helper_identity_details(binary))
    doctor = run_command([str(binary), "--doctor", "--json"], timeout_seconds=20)
    try:
        doctor_json = json.loads(doctor["stdout"])
    except json.JSONDecodeError:
        add_check(
            checks,
            name="mcp-server-self-doctor",
            status="failed",
            exit_code=doctor["exit_code"],
            output=compact_output(doctor["stdout"] + doctor["stderr"], 1600),
        )
        return
    for item in doctor_json.get("checks", []):
        if isinstance(item, dict) and item.get("name"):
            checks.append(item)


def add_macos_support_check(checks: list[dict[str, Any]], warnings: list[str]) -> None:
    if platform.system() != "Darwin":
        add_check(
            checks,
            name="host-macos-minimum",
            status="failed",
            current_system=platform.system(),
            minimum_macos_version=MINIMUM_NATIVE_MACOS_VERSION,
        )
        return
    result = run_command(["sw_vers", "-productVersion"], timeout_seconds=10)
    current = result["stdout"].strip()
    supported = result["exit_code"] == 0 and version_at_least(current, MINIMUM_NATIVE_MACOS_VERSION)
    add_check(
        checks,
        name="host-macos-minimum",
        status="ok" if supported else "failed",
        exit_code=result["exit_code"],
        current_macos_version=current or None,
        minimum_macos_version=MINIMUM_NATIVE_MACOS_VERSION,
        rationale="Swift native helper and bundled MCP server are built for macOS 14 or newer.",
    )
    if not supported:
        warnings.append(f"Xcoder native binaries require macOS {MINIMUM_NATIVE_MACOS_VERSION} or newer.")


def main() -> int:
    args = parse_args()
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    identity = plugin_identity()
    requested_checks = [item.strip() for item in (args.checks or "").split(",") if item.strip()]
    if identity["compatibility_cache_alias"]:
        warnings.append("cache_version_alias: manifest version differs from cache path version.")

    add_check(
        checks,
        name="plugin-cache-identity",
        status="warning" if identity["compatibility_cache_alias"] else "ok",
        **identity,
    )

    add_check(
        checks,
        name="host",
        status="ok",
        summary={
            "machine": platform.machine(),
            "processor": platform.processor(),
            "system": platform.system(),
            "release": platform.release(),
        },
    )
    add_macos_support_check(checks, warnings)

    select_result = run_command(["xcode-select", "-p"], timeout_seconds=20)
    developer_dir = select_result["stdout"].strip() if select_result["exit_code"] == 0 else None
    add_check(
        checks,
        name="xcode-select",
        status="ok" if developer_dir else "failed",
        exit_code=select_result["exit_code"],
        output=compact_output(select_result["stdout"] + select_result["stderr"], 1200),
    )

    xcodebuild_version = run_command(["xcodebuild", "-version"], timeout_seconds=20)
    add_check(
        checks,
        name="xcodebuild-version",
        status="ok" if xcodebuild_version["exit_code"] == 0 else "failed",
        exit_code=xcodebuild_version["exit_code"],
        output=compact_output(xcodebuild_version["stdout"] + xcodebuild_version["stderr"], 1200),
    )

    for tool in ["xcodebuild", "simctl", "xcresulttool", "devicectl", "mcpbridge"]:
        result = run_command(["xcrun", "--find", tool], timeout_seconds=20)
        status = "ok" if result["exit_code"] == 0 else "unavailable"
        if tool == "mcpbridge" and status != "ok":
            warnings.append("xcrun mcpbridge was not found; Apple MCP bridge support is optional.")
        add_check(
            checks,
            name=f"xcrun-find-{tool}",
            status=status,
            exit_code=result["exit_code"],
            path=result["stdout"].strip() or None,
            message=compact_output(result["stdout"] + result["stderr"], 1200) or None,
        )

    jxa = run_command(
        [
            "osascript",
            "-l",
            "JavaScript",
            "-e",
            'JSON.stringify({jxa:true, app: Application.currentApplication().name()})',
        ],
        timeout_seconds=20,
    )
    add_check(
        checks,
        name="jxa-smoke",
        status="ok" if jxa["exit_code"] == 0 else ("failed" if args.strict else "warning"),
        exit_code=jxa["exit_code"],
        output=compact_output(jxa["stdout"] + jxa["stderr"], 1200),
    )

    access = run_command(["osascript", "-e", 'tell application "System Events" to UI elements enabled'], timeout_seconds=20)
    access_ok = access["exit_code"] == 0 and "true" in access["stdout"].lower()
    add_check(
        checks,
        name="accessibility-ui-scripting",
        status="ok" if access_ok else ("failed" if args.strict else "warning"),
        exit_code=access["exit_code"],
        output=compact_output(access["stdout"] + access["stderr"], 1200),
    )
    if not access_ok:
        warnings.append("Accessibility UI scripting is not enabled for the current automation host.")

    xcode_app = selected_xcode_app(developer_dir)
    if xcode_app:
        sdef = run_command(["sdef", xcode_app], timeout_seconds=30)
        sdef_text = (sdef["stdout"] or "") + (sdef["stderr"] or "")
        missing_sdef = [term for term in REQUIRED_SDEF_TERMS if term not in sdef_text]
        sdef_ok = sdef["exit_code"] == 0 and not missing_sdef
        add_check(
            checks,
            name="xcode-sdef-contract",
            status="ok" if sdef_ok else ("failed" if args.strict else "warning"),
            exit_code=sdef["exit_code"],
            selected_xcode_app=xcode_app,
            missing=missing_sdef,
        )
        if not sdef_ok:
            warnings.append("Xcode scripting dictionary did not expose every expected term.")
    else:
        add_check(checks, name="xcode-sdef-contract", status="failed", missing=["selected Xcode.app could not be resolved"])

    xb_help = run_command(["xcodebuild", "-help"], timeout_seconds=30)
    xb_text = (xb_help["stdout"] or "") + (xb_help["stderr"] or "")
    missing_flags = [flag for flag in REQUIRED_XCODEBUILD_FLAGS if flag not in xb_text]
    add_check(
        checks,
        name="xcodebuild-required-flags",
        status="ok" if xb_help["exit_code"] == 0 and not missing_flags else "failed",
        exit_code=xb_help["exit_code"],
        missing=missing_flags,
    )

    simctl = run_command(["xcrun", "simctl", "help"], timeout_seconds=30)
    simctl_text = (simctl["stdout"] or "") + (simctl["stderr"] or "")
    missing_simctl = [term for term in REQUIRED_SIMCTL_TERMS if term not in simctl_text]
    add_check(
        checks,
        name="simctl-lifecycle",
        status="ok" if simctl["exit_code"] == 0 and not missing_simctl else "failed",
        exit_code=simctl["exit_code"],
        missing=missing_simctl,
    )

    xcr = run_command(["xcrun", "xcresulttool", "get", "--help"], timeout_seconds=30)
    xcr_text = (xcr["stdout"] or "") + (xcr["stderr"] or "")
    missing_xcr = [term for term in ["test-results", "build-results", "log", "content-availability"] if term not in xcr_text]
    add_check(
        checks,
        name="xcresulttool-result-summaries",
        status="ok" if xcr["exit_code"] == 0 and not missing_xcr else "failed",
        exit_code=xcr["exit_code"],
        missing=missing_xcr,
    )

    bridge = run_command(["xcrun", "mcpbridge", "--help"], timeout_seconds=10)
    bridge_ok = bridge["exit_code"] == 0
    add_check(
        checks,
        name="mcpbridge-optional",
        status="ok" if bridge_ok else "optional_unavailable",
        exit_code=bridge["exit_code"],
        output=compact_output(bridge["stdout"] + bridge["stderr"], 1600),
    )
    if not bridge_ok:
        warnings.append("Apple mcpbridge is optional and currently unavailable; plugin will use local scripts instead.")

    add_native_helper_checks(checks, warnings, xcode_app)
    add_mcp_server_checks(checks, warnings)

    failed = [item["name"] for item in checks if item["status"] == "failed"]
    details = {
        **identity,
        "checks": checks,
        "requested_checks": requested_checks,
        "selected_developer_dir": developer_dir,
        "selected_xcode_app": xcode_app,
    }
    if failed:
        return emit_failure(
            "doctor",
            "subprocess_failed",
            "Required Xcode checks failed",
            details=details,
            warnings=warnings,
            errors=failed,
            next_actions=[
                "Fix failed required toolchain checks before relying on xcode build workflows.",
                f"If first-use MCP bootstrap still fails after repair, report it at {ISSUES_URL} with compact redacted diagnostics.",
                "Use --strict only when IDE automation readiness should be required.",
            ],
            exit_code=EXIT_CODES["subprocess_failed"],
        )
    return emit_success(
        "doctor",
        "Xcode local toolchain is usable",
        details=details,
        warnings=warnings,
        next_actions=[
            "If mcp__xcode__* tools are not visible, run the first-use MCP bootstrap and restart Codex.",
            "Use xcode build for deterministic CLI builds/tests.",
            "Use xcode ide only when Xcode window state matters.",
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
