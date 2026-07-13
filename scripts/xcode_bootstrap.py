#!/usr/bin/env python3

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path
from typing import Any

from xcode_common import (
    EXIT_CODES,
    create_artifact_dir,
    emit_failure,
    emit_success,
    plugin_root,
    run_command,
    write_json,
    write_text,
)


MIN_MACOS_VERSION = "14.0"
SUCCESS_SUMMARY = "Xcoder MCP server is built, executable, and locally validated."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and validate the bundled Xcoder MCP server.")
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope. Without this, print a concise human summary.")
    return parser.parse_args()


def version_ge(current: str, required: str) -> bool:
    def parts(value: str) -> list[int]:
        result: list[int] = []
        for raw in value.split(".")[:3]:
            try:
                result.append(int(raw))
            except ValueError:
                result.append(0)
        return (result + [0, 0, 0])[:3]

    return parts(current) >= parts(required)


def run_step(name: str, command: list[str], *, artifact_dir: Path, cwd: Path | None = None, timeout_seconds: int | None = None) -> dict[str, Any]:
    result = run_command(command, cwd=cwd, timeout_seconds=timeout_seconds)
    stdout_path = artifact_dir / f"{name}.stdout.txt"
    stderr_path = artifact_dir / f"{name}.stderr.txt"
    write_text(stdout_path, result["stdout"])
    write_text(stderr_path, result["stderr"])
    return {
        "name": name,
        "ok": result["exit_code"] == 0,
        "exit_code": result["exit_code"],
        "timed_out": result.get("timed_out", False),
        "artifacts": {
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
    }


def fail(
    summary: str,
    *,
    exit_code: int,
    json_output: bool,
    artifact_dir: Path,
    steps: list[dict[str, Any]],
) -> int:
    details = {
        "plugin_root": str(plugin_root()),
        "minimum_macos_version": MIN_MACOS_VERSION,
        "steps": steps,
    }
    write_json(artifact_dir / "steps.json", steps)
    if json_output:
        return emit_failure(
            "mcp-bootstrap",
            "mcp_bootstrap_failed",
            summary,
            details=details,
            artifacts={"artifact_dir": str(artifact_dir), "steps": str(artifact_dir / "steps.json")},
            errors=[summary],
            next_actions=[
                "Inspect the artifact stdout/stderr files for the failed step.",
                "Retry bin/xcode mcp bootstrap --json after fixing the local toolchain issue.",
                "If it still fails, report compact redacted diagnostics at https://github.com/AmrMohamad/Xcoder/issues.",
            ],
            exit_code=exit_code,
            artifact_dir=artifact_dir,
        )
    print(summary, file=sys.stderr)
    return exit_code


def main() -> int:
    args = parse_args()
    root = plugin_root()
    artifact_dir = create_artifact_dir("mcp-bootstrap", root / ".codex" / "xcode" / "artifacts")
    exec_path = root / "bin" / "xcode-mcp-server"
    steps: list[dict[str, Any]] = []

    def step(name: str, command: list[str], *, cwd: Path | None = None, timeout_seconds: int | None = None, summary: str, exit_code: int) -> bool:
        item = run_step(name, command, artifact_dir=artifact_dir, cwd=cwd, timeout_seconds=timeout_seconds)
        steps.append(item)
        if item["ok"]:
            return True
        raise BootstrapStepFailed(summary, exit_code)

    try:
        step("plugin-json", ["/usr/bin/python3", "-m", "json.tool", str(root / ".codex-plugin" / "plugin.json")], summary="Plugin manifest JSON is invalid.", exit_code=2)
        step("mcp-json", ["/usr/bin/python3", "-m", "json.tool", str(root / ".mcp.json")], summary="MCP config JSON is invalid.", exit_code=2)
        step("python-compile", ["/usr/bin/python3", "-m", "py_compile", *map(str, sorted((root / "scripts").glob("*.py")))], summary="Python command modules did not compile.", exit_code=2)
        step("chmod-public-bin", ["/bin/chmod", "+x", str(root / "bin" / "xcode"), str(root / "bin" / "xcode-mcp")], summary="Could not make public plugin launchers executable.", exit_code=4)
        step("host-macos-version", ["/usr/bin/sw_vers", "-productVersion"], summary="Could not read the host macOS version.", exit_code=64)
        current_macos_version = platform.mac_ver()[0] or "unknown"
        if current_macos_version == "unknown" or not version_ge(current_macos_version, MIN_MACOS_VERSION):
            raise BootstrapStepFailed(
                f"xcode-mcp-server requires macOS {MIN_MACOS_VERSION} or newer; current macOS is {current_macos_version}.",
                64,
            )
        step("xcode-select", ["/usr/bin/xcode-select", "-p"], summary="xcode-select does not point at an available developer directory.", exit_code=2)
        step("swift-version", ["/usr/bin/swift", "--version"], summary="Swift toolchain is not available.", exit_code=2)
        step(
            "fresh-component-build",
            [
                "/usr/bin/python3",
                str(root / "scripts" / "xcode_component_build.py"),
                "--component",
                "mcp-server",
                "--stage",
                str(root),
                "--json",
            ],
            summary="SwiftPM could not freshly build, install, and self-test the bundled MCP server.",
            exit_code=2,
            timeout_seconds=1200,
        )
        step("mcp-version", [str(exec_path), "--version", "--json"], summary="Built MCP server did not return version JSON.", exit_code=60)
        step("mcp-doctor", [str(exec_path), "--doctor", "--json"], summary="Built MCP server self-doctor failed.", exit_code=60)
        step("mcp-list-tools", [str(exec_path), "--list-tools", "--json"], summary="Built MCP server did not list tools.", exit_code=60)
        step("plugin-doctor", [str(root / "bin" / "xcode"), "doctor", "--json"], summary="Plugin doctor failed after MCP bootstrap.", exit_code=60)
    except BootstrapStepFailed as exc:
        return fail(str(exc), exit_code=exc.exit_code, json_output=args.json, artifact_dir=artifact_dir, steps=steps)

    write_json(artifact_dir / "steps.json", steps)
    if args.json:
        return emit_success(
            "mcp-bootstrap",
            SUCCESS_SUMMARY,
            details={
                "plugin_root": str(root),
                "minimum_macos_version": MIN_MACOS_VERSION,
                "steps": steps,
            },
            artifacts={"artifact_dir": str(artifact_dir), "steps": str(artifact_dir / "steps.json")},
            warnings=["Restart Codex after bootstrap so .mcp.json is reloaded and mcp__xcode__* tools become visible."],
            next_actions=["Restart Codex and verify the mcp__xcode__* namespace is visible."],
            artifact_dir=artifact_dir,
        )
    print(SUCCESS_SUMMARY)
    return 0


class BootstrapStepFailed(Exception):
    def __init__(self, summary: str, exit_code: int) -> None:
        super().__init__(summary)
        self.exit_code = exit_code


if __name__ == "__main__":
    raise SystemExit(main())
