#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from xcode_common import EXIT_CODES, emit_failure, emit_success, plugin_identity, plugin_root, plugin_version


COMMAND_TO_SCRIPT = {
    "build": "xcode_build_cache.py",
    "doctor": "xcode_doctor.py",
    "ide": "xcode_ide_automation.py",
    "simulator": "xcode_simulator.py",
    "results": "xcode_results.py",
    "warnings": "xcode_warnings.py",
    "scheme": "xcode_scheme_inspector.py",
    "context": "xcode_context.py",
    "native": "xcode_native.py",
    "package": "xcode_package.py",
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="bin/xcode",
        description="Local-first Xcode workflows for builds, IDE automation, simulators, results, and diagnostics.",
    )
    root.add_argument("--version", action="store_true", help="Print the xcode plugin version and exit.")
    root.add_argument("--json", action="store_true", help="Emit a JSON envelope for root commands such as --version.")
    root.add_argument("command", nargs="?", choices=sorted(COMMAND_TO_SCRIPT), help="Workflow command to run.")
    root.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for the selected command.")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.version:
        if args.json:
            identity = plugin_identity()
            warnings = []
            if identity["compatibility_cache_alias"]:
                warnings.append("cache_version_alias: manifest version differs from cache path version.")
            return emit_success("version", plugin_version(), details=identity, warnings=warnings)
        print(plugin_version())
        return 0
    if not args.command:
        parser().print_help()
        return 0

    script_name = COMMAND_TO_SCRIPT[args.command]
    if args.command == "build" and any(item in {"-h", "--help"} for item in args.args):
        script_name = "run_xcode_cli_build.py"
    script = plugin_root() / "scripts" / script_name
    if not script.exists():
        return emit_failure(
            args.command,
            "tool_missing",
            f"Command script is missing: {script}",
            errors=[str(script)],
            next_actions=["Reinstall or repair the local xcode plugin."],
            exit_code=EXIT_CODES["tool_missing"],
        )

    forwarded = list(args.args)
    if args.command == "build":
        if "--json" in forwarded and "--json-dry-run" not in forwarded:
            forwarded = ["--json-dry-run" if item == "--json" else item for item in forwarded]
        elif "--json" in forwarded:
            forwarded = [item for item in forwarded if item != "--json"]
    elif "--json" in forwarded:
        forwarded = [item for item in forwarded if item != "--json"]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(script.parent) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    completed = subprocess.run([sys.executable, str(script), *forwarded], env=env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
