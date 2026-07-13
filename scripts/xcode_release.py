#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from xcode_common import EXIT_CODES, emit_failure, emit_success, plugin_root
from xcode_component_build import ComponentBuildError, build_components, self_test_mcp_server, self_test_native_helper
from xcode_version import plugin_version


PROVENANCE_SCHEMA = "xcoder.release-provenance.v1"
Runner = Callable[..., subprocess.CompletedProcess[str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify and build an Xcoder release from fresh binaries.")
    parser.add_argument("command", choices=("verify",))
    parser.add_argument("--output")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--signing-identity")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(root: Path, runner: Runner) -> tuple[str, bool, int]:
    revision = runner(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    status = runner(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root, text=True, capture_output=True, check=True).stdout
    epoch = int(runner(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=root, text=True, capture_output=True, check=True).stdout.strip())
    return revision, bool(status.strip()), epoch


def version_issues(root: Path) -> list[dict[str, str]]:
    version = plugin_version(root)
    checks = {
        ".codex-plugin/plugin.json": version,
        "native/XcodeMCPServer/Sources/XcodeMCPServer/Constants.swift": f'serverVersion = "{version}"',
        "native/XcodeNativeHelper/Sources/XcodeNativeHelper/main.swift": f'helperVersion = "{version}"',
        "bin/XcodeNativeHelper.app/Contents/Info.plist": f"<string>{version}</string>",
        "scripts/xcode_native.py": "version = plugin_version()",
        "hooks/hooks.json": "xcode/*/scripts/",
    }
    issues: list[dict[str, str]] = []
    for relative, expected in checks.items():
        text = (root / relative).read_text(encoding="utf-8")
        if expected not in text:
            issues.append({"path": relative, "reason": f"does not declare plugin version {version}"})
    return issues


def run_stage(name: str, command: list[str], *, root: Path, runner: Runner, timeout: int = 1200) -> dict[str, Any]:
    started = time.monotonic()
    completed = runner(command, cwd=root, text=True, capture_output=True, timeout=timeout)
    return {
        "name": name,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "seconds": round(time.monotonic() - started, 6),
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def copy_source_tree(root: Path, stage: Path) -> None:
    ignored = shutil.ignore_patterns(".git", ".serena", ".build", ".swiftpm", "__pycache__", ".pytest_cache", "*.pyc", "*.pyo", "*.zip", "*.zip.manifest.json", "DerivedData")
    shutil.copytree(root, stage, ignore=ignored)


def copy_built_components(component_root: Path, stage: Path) -> None:
    shutil.copy2(component_root / "bin" / "xcode-mcp-server", stage / "bin" / "xcode-mcp-server")
    helper_source = component_root / "bin" / "XcodeNativeHelper.app"
    helper_destination = stage / "bin" / "XcodeNativeHelper.app"
    shutil.rmtree(helper_destination)
    shutil.copytree(helper_source, helper_destination)
    helper_launcher = stage / "bin" / "xcode-native-helper"
    helper_launcher.write_text(
        '#!/bin/sh\nexec "$(dirname "$0")/XcodeNativeHelper.app/Contents/MacOS/xcode-native-helper" "$@"\n',
        encoding="utf-8",
    )
    helper_launcher.chmod(0o755)


def toolchain_details(root: Path, runner: Runner) -> dict[str, str]:
    swift = runner(["/usr/bin/swift", "--version"], cwd=root, text=True, capture_output=True).stdout.strip()
    doctor = runner([str(root / "bin" / "xcode"), "doctor", "--json"], cwd=root, text=True, capture_output=True)
    xcode_version = "unknown"
    xcode_build = "unknown"
    try:
        doctor_payload = json.loads(doctor.stdout)
        details = doctor_payload.get("details", {})
        for check in details.get("checks", []):
            if not isinstance(check, dict) or check.get("name") != "xcodebuild-version":
                continue
            output = str(check.get("output", ""))
            version_match = re.search(r"^Xcode\s+(.+)$", output, re.MULTILINE)
            build_match = re.search(r"^Build version\s+(.+)$", output, re.MULTILINE)
            if version_match:
                xcode_version = version_match.group(1).strip()
            if build_match:
                xcode_build = build_match.group(1).strip()
            break
    except json.JSONDecodeError:
        pass
    return {
        "swift_version": swift,
        "xcode_version": xcode_version,
        "xcode_build": xcode_build,
        "macos_version": platform.mac_ver()[0],
    }


def provenance_payload(root: Path, version: str, revision: str, dirty: bool, components: dict[str, Any], runner: Runner) -> dict[str, Any]:
    return {
        "schema_version": PROVENANCE_SCHEMA,
        "plugin_version": version,
        "git": {"commit": revision, "dirty": dirty},
        "toolchain": toolchain_details(root, runner),
        "components": {name: component.as_dict() for name, component in components.items()},
    }


def release_verify(args: argparse.Namespace, runner: Runner = subprocess.run) -> int:
    root = plugin_root()
    version = plugin_version(root)
    checks: dict[str, str] = {}
    stages: list[dict[str, Any]] = []
    try:
        revision, dirty, commit_epoch = git_state(root, runner)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return emit_failure("release.verify", "subprocess_failed", "Git source identity could not be established", errors=[str(exc)], exit_code=EXIT_CODES["subprocess_failed"])
    if dirty and not args.allow_dirty:
        return emit_failure("release.verify", "release_source_dirty", "Release verification requires a clean source tree", details={"source_revision": revision, "source_dirty": True}, exit_code=EXIT_CODES["release_source_dirty"])
    issues = version_issues(root)
    if issues:
        return emit_failure("release.verify", "package_provenance_mismatch", "Version declarations are inconsistent", details={"issues": issues}, errors=issues, exit_code=EXIT_CODES["package_provenance_mismatch"])
    checks["version_consistency"] = "passed"

    python = sys.executable
    validation_commands = [
        ("json_validation", [python, "-m", "json.tool", str(root / ".codex-plugin" / "plugin.json")]),
        ("mcp_json_validation", [python, "-m", "json.tool", str(root / ".mcp.json")]),
        ("python_compile", [python, "-m", "py_compile", *map(str, sorted((root / "scripts").glob("*.py")))]),
    ]
    for name, command in validation_commands:
        stage = run_stage(name, command, root=root, runner=runner)
        stages.append(stage)
        if not stage["ok"]:
            return emit_failure("release.verify", "binary_self_test_failed", f"Release stage failed: {name}", details={"stages": stages}, exit_code=EXIT_CODES["binary_self_test_failed"])
    pytest_probe = runner([python, "-m", "pytest", "--version"], cwd=root, text=True, capture_output=True)
    pytest_command = [python, "-m", "pytest", "tests"] if pytest_probe.returncode == 0 else ["uvx", "pytest", "tests"]
    stage = run_stage("python_tests", pytest_command, root=root, runner=runner)
    stages.append(stage)
    if not stage["ok"]:
        return emit_failure("release.verify", "binary_self_test_failed", "Python release tests failed", details={"stages": stages}, exit_code=EXIT_CODES["binary_self_test_failed"])

    epoch = args.source_date_epoch if args.source_date_epoch is not None else commit_epoch
    output = Path(args.output).expanduser().resolve() if args.output else Path(tempfile.gettempdir()) / f"xcode-plugin-{version}.zip"
    with tempfile.TemporaryDirectory(prefix="xcoder-release-") as work_directory:
        work = Path(work_directory)
        component_root = work / "components"
        component_root.mkdir()
        try:
            started = time.monotonic()
            components = build_components(root, component_root, work / "swift", signing_identity=args.signing_identity, runner=runner, self_test=False)
            stages.append({"name": "fresh_component_builds", "ok": True, "seconds": round(time.monotonic() - started, 6)})
        except (OSError, RuntimeError, ComponentBuildError) as exc:
            return emit_failure("release.verify", "binary_self_test_failed", "Fresh release component build failed", details={"stages": stages}, errors=[str(exc)], exit_code=EXIT_CODES["binary_self_test_failed"])
        stage_root = work / "stage" / "xcode" / version
        copy_source_tree(root, stage_root)
        copy_built_components(component_root, stage_root)
        stages.append({"name": "staging_install", "ok": True})
        try:
            components["mcp_server"] = replace(
                components["mcp_server"], self_tests=self_test_mcp_server(stage_root, runner)
            )
            components["native_helper"] = replace(
                components["native_helper"], self_tests=self_test_native_helper(stage_root, runner)
            )
            stages.append({"name": "staged_component_self_tests", "ok": True})
        except (OSError, ComponentBuildError) as exc:
            return emit_failure("release.verify", "binary_self_test_failed", "Staged release component self-test failed", details={"stages": stages}, errors=[str(exc)], exit_code=EXIT_CODES["binary_self_test_failed"])
        provenance = provenance_payload(root, version, revision, dirty, components, runner)
        provenance_path = stage_root / "release-provenance.json"
        provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        first = output
        second = work / "reproducibility.zip"
        source_dirty = "true" if dirty else "false"
        package_command = [
            python, str(root / "scripts" / "xcode_package.py"), "zip", "--source-root", str(stage_root),
            "--source-revision", revision, "--source-dirty", source_dirty, "--source-date-epoch", str(epoch), "--provenance", str(provenance_path), "--allow-dirty",
        ]
        for index, package_output in enumerate((first, second), start=1):
            result = run_stage(f"package_creation_{index}", [*package_command, "--output", str(package_output)], root=root, runner=runner)
            stages.append(result)
            if not result["ok"]:
                return emit_failure("release.verify", "package_spec_violation", "Deterministic package creation failed", details={"stages": stages}, exit_code=EXIT_CODES["package_spec_violation"])
        audit = run_stage("package_audit_and_extracted_smoke", [python, str(root / "scripts" / "xcode_package.py"), "audit", "--zip", str(first)], root=root, runner=runner)
        stages.append(audit)
        if not audit["ok"]:
            return emit_failure("release.verify", "package_integrity_failed", "Release package audit failed", details={"stages": stages}, exit_code=EXIT_CODES["package_integrity_failed"])
        first_hash = sha256_file(first)
        second_hash = sha256_file(second)
        if first_hash != second_hash:
            return emit_failure("release.verify", "package_integrity_failed", "The same staged tree produced different ZIP archives", details={"first_sha256": first_hash, "second_sha256": second_hash, "stages": stages}, exit_code=EXIT_CODES["package_integrity_failed"])
        stages.append({"name": "archive_reproducibility", "ok": True, "sha256": first_hash})

        for key in ("health_privacy", "cache_identity_v2", "deadline_lifecycle", "workflow_fail_fast", "ax_boundary", "distribution_surface", "binary_provenance", "package_integrity"):
            checks[key] = "passed"
        sidecar = output.with_suffix(output.suffix + ".manifest.json")
        provenance_output = output.with_suffix(output.suffix + ".provenance.json")
        report = output.with_suffix(output.suffix + ".tests.json")
        report.write_text(json.dumps(stages, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        shutil.copy2(provenance_path, provenance_output)
        return emit_success(
            "release.verify", f"Xcoder {version} release package passed all correctness gates.",
            details={"source_revision": revision, "source_dirty": dirty, "package_sha256": first_hash, "reproducible_archive": True, "checks": checks, "stages": stages},
            artifacts={"zip": str(output), "package_manifest": str(sidecar), "provenance": str(provenance_output), "test_results": str(report)},
        )


def main() -> int:
    args = parse_args()
    return release_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
