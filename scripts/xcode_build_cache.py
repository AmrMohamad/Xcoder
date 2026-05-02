#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from xcode_common import (
    EXIT_CODES,
    create_artifact_dir,
    emit_failure,
    emit_success,
    plugin_root,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the plugin-local shared-cache xcodebuild wrapper and return a v0.3 JSON envelope."
    )
    parser.add_argument("--artifact-dir", default=None, help="Base artifact directory. Defaults to .codex/xcode/artifacts.")
    parser.add_argument("--log-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--json-dry-run", action="store_true", help=argparse.SUPPRESS)
    args, runner_args = parser.parse_known_args()
    args.runner_args = runner_args
    if args.runner_args and args.runner_args[0] == "--":
        args.runner_args = args.runner_args[1:]
    if args.json_dry_run and "--json-dry-run" not in args.runner_args:
        args.runner_args.append("--json-dry-run")
    return args


def decode_json_plan(stdout_path: Path) -> dict[str, Any] | None:
    try:
        text = stdout_path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        return json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None


def has_arg(args: list[str], name: str) -> bool:
    return name in args or any(item.startswith(f"{name}=") for item in args)


def main() -> int:
    args = parse_args()
    runner = plugin_root() / "scripts" / "run_xcode_cli_build.py"
    if not runner.exists():
        return emit_failure(
            "build",
            "tool_missing",
            "shared-cache runner is missing",
            errors=[f"Missing runner at {runner}"],
            next_actions=["Reinstall or repair the xcode plugin."],
            exit_code=EXIT_CODES["tool_missing"],
        )

    forwarded = list(args.runner_args)
    is_dry_run = "--dry-run" in forwarded
    if is_dry_run and "--json-dry-run" not in forwarded:
        forwarded.append("--json-dry-run")

    artifact_dir = Path(args.log_dir).expanduser() if args.log_dir else create_artifact_dir("build", args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = artifact_dir / "stdout.log"
    stderr_path = artifact_dir / "stderr.log"
    command_path = artifact_dir / "command.json"

    command = [sys.executable, str(runner), *forwarded]
    write_json(command_path, {"command": command, "cwd": str(Path.cwd())})

    started = time.time()
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        completed = subprocess.run(command, stdout=stdout_file, stderr=stderr_file, text=True)
    elapsed = time.time() - started

    plan = decode_json_plan(stdout_path) if is_dry_run else None
    warnings: list[str] = []
    if completed.returncode == 0 and is_dry_run and plan is None:
        warnings.append("Dry run completed but stdout did not contain a parseable JSON plan.")

    artifacts = {
        "artifact_dir": str(artifact_dir),
        "command": str(command_path),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    details: dict[str, Any] = {
        "exit_code": completed.returncode,
        "dry_run": is_dry_run,
        "runner": str(runner),
    }
    if plan is not None:
        plan_path = artifact_dir / "command-plan.json"
        write_json(plan_path, plan)
        artifacts["json_plan"] = str(plan_path)
        details["plan"] = plan

    if completed.returncode == 0:
        return emit_success(
            "build",
            "xcodebuild wrapper completed",
            details=details,
            artifacts=artifacts,
            warnings=warnings,
            next_actions=[
                "Inspect stderr_log for resolved cache paths and xcodebuild notes.",
                "Inspect stdout_log only when full command output is needed.",
            ],
            artifact_dir=artifact_dir,
            elapsed_seconds=elapsed,
        )

    if completed.returncode == EXIT_CODES["command_timeout"]:
        error_type = "command_timeout"
    elif completed.returncode == EXIT_CODES["trusted_fast_denied"]:
        error_type = "trusted_fast_denied"
    elif completed.returncode == EXIT_CODES["cache_invalid"]:
        error_type = "cache_invalid"
    else:
        error_type = "subprocess_failed"
    return emit_failure(
        "build",
        error_type,
        "xcodebuild wrapper failed",
        details=details,
        artifacts=artifacts,
        warnings=warnings,
        errors=[f"runner exited {completed.returncode}", stderr_path.read_text(encoding="utf-8", errors="replace").strip()],
        next_actions=[
            "Open stderr_log for the xcodebuild diagnostic.",
            "Use xcode context to inspect scheme testability and destination guidance.",
        ],
        exit_code=completed.returncode,
        artifact_dir=artifact_dir,
        elapsed_seconds=elapsed,
    )


if __name__ == "__main__":
    raise SystemExit(main())
