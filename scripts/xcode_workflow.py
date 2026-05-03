#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from xcode_common import EXIT_CODES, compact_output, create_artifact_dir, emit_failure, emit_success, plugin_root, run_command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="High-level Xcode plugin workflows that compose bin/xcode commands.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_app = subparsers.add_parser("run-app", help="GUI-first build and run workflow for an iOS app.")
    run_app.add_argument("--project-path", required=True)
    run_app.add_argument("--scheme", required=True)
    run_app.add_argument("--simulator-name", default="iPhone SE (3rd generation)")
    run_app.add_argument("--runtime", default=None)
    run_app.add_argument("--destination-id", default=None)
    run_app.add_argument("--configuration", default="Debug")
    run_app.add_argument("--timeout-seconds", type=int, default=900)
    run_app.add_argument("--no-cli-fallback", action="store_true")
    return parser.parse_args()


def xcode_bin() -> Path:
    return plugin_root() / "bin" / "xcode"


def call_plugin(args: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    return run_command([str(xcode_bin()), *args], timeout_seconds=timeout_seconds, cwd=plugin_root())


def parse_envelope(result: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None


def result_succeeded(result: dict[str, Any]) -> bool:
    envelope = parse_envelope(result)
    if isinstance(envelope, dict):
        return result["exit_code"] == 0 and bool(envelope.get("ok"))
    return result["exit_code"] == 0


def step_record(name: str, result: dict[str, Any]) -> dict[str, Any]:
    envelope = parse_envelope(result)
    record: dict[str, Any] = {
        "name": name,
        "exit_code": result["exit_code"],
        "ok": bool(envelope.get("ok")) if isinstance(envelope, dict) else result["exit_code"] == 0,
        "summary": envelope.get("summary") if isinstance(envelope, dict) else result.get("summary") or compact_output(result["stdout"] or result["stderr"], 1200),
    }
    if isinstance(envelope, dict):
        record["error_type"] = envelope.get("error_type")
        record["artifacts"] = envelope.get("artifacts") or {}
        if envelope.get("warnings"):
            record["warnings"] = envelope.get("warnings")
    else:
        if result.get("artifacts"):
            record["artifacts"] = result["artifacts"]
        if result.get("stdout_tail"):
            record["stdout_tail"] = result["stdout_tail"]
        if result.get("stderr_tail"):
            record["stderr_tail"] = result["stderr_tail"]
        elif result.get("stderr"):
            record["stderr"] = compact_output(result["stderr"], 1200)
        if result.get("timed_out"):
            record["timed_out"] = True
    return record


def destination_from_resolve(result: dict[str, Any]) -> str | None:
    envelope = parse_envelope(result)
    if not isinstance(envelope, dict) or not envelope.get("ok"):
        return None
    details = envelope.get("details") or {}
    return details.get("udid") or (details.get("device") or {}).get("udid")


def compact_file_tail(path: Path, limit: int = 1200) -> str:
    if not path.exists() or not path.is_file():
        return ""
    data = path.read_bytes()
    if len(data) > limit:
        data = data[-limit:]
    return compact_output(data.decode("utf-8", errors="replace"), limit)


def call_plugin_capture(args: list[str], *, timeout_seconds: int, artifact_dir: Path, stem: str) -> dict[str, Any]:
    stdout_log = artifact_dir / f"{stem}.stdout.log"
    stderr_log = artifact_dir / f"{stem}.stderr.log"
    command = [str(xcode_bin()), *args]
    started = time.monotonic()
    timed_out = False

    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open("w", encoding="utf-8") as stderr_handle:
        try:
            process = subprocess.Popen(
                command,
                cwd=plugin_root(),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            stderr_handle.write(str(exc))
            return {
                "command": command,
                "exit_code": 127,
                "stdout": "",
                "stderr": str(exc),
                "timed_out": False,
                "elapsed_seconds": time.monotonic() - started,
                "summary": "Plugin command could not be launched",
                "artifacts": {"artifact_dir": str(artifact_dir), "stdout_log": str(stdout_log), "stderr_log": str(stderr_log)},
            }

        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:
                process.terminate()
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception:
                    process.kill()
                exit_code = process.wait()
            if exit_code == 0:
                exit_code = EXIT_CODES["command_timeout"]

    elapsed = time.monotonic() - started
    return {
        "command": command,
        "exit_code": exit_code,
        "stdout": "",
        "stderr": "",
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "summary": "Plugin-routed CLI build completed" if exit_code == 0 else "Plugin-routed CLI build failed",
        "artifacts": {"artifact_dir": str(artifact_dir), "stdout_log": str(stdout_log), "stderr_log": str(stderr_log)},
        "stdout_tail": compact_file_tail(stdout_log),
        "stderr_tail": compact_file_tail(stderr_log),
    }


def run_app_command(args: argparse.Namespace) -> int:
    project_path = str(Path(args.project_path).expanduser())
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []
    allow_cli_fallback = not args.no_cli_fallback

    native_state = call_plugin(["native", "app", "xcode-state", "--json"], timeout_seconds=20)
    steps.append(step_record("native_state", native_state))

    native_windows = call_plugin(["native", "ax", "xcode-windows", "--json"], timeout_seconds=30)
    steps.append(step_record("native_windows", native_windows))

    destination_id = args.destination_id
    if not destination_id:
        resolve_args = ["simulator", "resolve", "--name", args.simulator_name, "--json"]
        if args.runtime:
            resolve_args.extend(["--runtime", args.runtime])
        resolved = call_plugin(resolve_args, timeout_seconds=30)
        steps.append(step_record("simulator_resolve", resolved))
        destination_id = destination_from_resolve(resolved)
        if not destination_id:
            return emit_failure(
                "workflow",
                "destination_not_found",
                "Unable to resolve requested simulator before running app",
                details={"steps": steps, "simulator_name": args.simulator_name, "runtime": args.runtime},
                warnings=warnings,
                next_actions=["Pass --destination-id or use bin/xcode simulator resolve --json to choose an available simulator."],
                exit_code=EXIT_CODES["destination_not_found"],
            )

    preflight_args = [
        "ide",
        "preflight",
        "--workspace-path",
        project_path,
        "--scheme",
        args.scheme,
        "--destination-id",
        destination_id,
        "--json",
    ]
    preflight = call_plugin(preflight_args, timeout_seconds=45)
    steps.append(step_record("ide_preflight", preflight))
    if not result_succeeded(preflight):
        return emit_failure(
            "workflow",
            "xcode_ide_automation_failed",
            "Xcode IDE preflight failed before build/run",
            details={"project_path": project_path, "scheme": args.scheme, "destination_id": destination_id, "steps": steps},
            warnings=warnings,
            next_actions=["Resolve Xcode IDE preflight errors, then retry the workflow."],
            exit_code=EXIT_CODES["xcode_ide_automation_failed"],
        )

    build_args = [
        "ide",
        "scheme-action",
        "--action",
        "build",
        "--workspace-path",
        project_path,
        "--scheme",
        args.scheme,
        "--destination-id",
        destination_id,
        "--timeout-seconds",
        str(min(args.timeout_seconds, 600)),
        "--require-native-preflight",
        "--json",
    ]
    build = call_plugin(build_args, timeout_seconds=min(args.timeout_seconds, 650))
    steps.append(step_record("ide_build", build))

    run_args = [
        "ide",
        "scheme-action",
        "--action",
        "run",
        "--workspace-path",
        project_path,
        "--scheme",
        args.scheme,
        "--destination-id",
        destination_id,
        "--timeout-seconds",
        str(min(args.timeout_seconds, 180)),
        "--require-native-preflight",
        "--json",
    ]
    run = call_plugin(run_args, timeout_seconds=min(args.timeout_seconds, 220))
    steps.append(step_record("ide_run", run))

    if result_succeeded(build) and result_succeeded(run):
        return emit_success(
            "workflow",
            "App built and run through Xcode IDE workflow",
            details={
                "project_path": project_path,
                "scheme": args.scheme,
                "destination_id": destination_id,
                "configuration": args.configuration,
                "steps": steps,
            },
            warnings=warnings,
            next_actions=["Use simulator screenshots or app logs only when explicitly needed."],
        )

    if not allow_cli_fallback:
        return emit_failure(
            "workflow",
            "xcode_ide_automation_failed",
            "Xcode IDE build/run workflow failed and CLI fallback is disabled",
            details={"project_path": project_path, "scheme": args.scheme, "destination_id": destination_id, "steps": steps},
            warnings=warnings,
            next_actions=["Resolve Xcode IDE preflight/build/run errors, then retry."],
            exit_code=EXIT_CODES["xcode_ide_automation_failed"],
        )

    fallback_args = [
        "build",
        "--project" if project_path.endswith(".xcodeproj") else "--workspace",
        project_path,
        "--scheme",
        args.scheme,
        "--configuration",
        args.configuration,
        "--destination",
        f"platform=iOS Simulator,id={destination_id}",
        "--action",
        "build",
    ]
    artifact_dir = create_artifact_dir("workflow-run-app")
    fallback = call_plugin_capture(fallback_args, timeout_seconds=args.timeout_seconds, artifact_dir=artifact_dir, stem="plugin-cli-build-fallback")
    steps.append(step_record("plugin_cli_build_fallback", fallback))
    if fallback["exit_code"] == 0:
        return emit_success(
            "workflow",
            "Xcode IDE run failed, but plugin-routed CLI build fallback completed",
            details={"project_path": project_path, "scheme": args.scheme, "destination_id": destination_id, "steps": steps},
            artifacts={"artifact_dir": str(artifact_dir)},
            warnings=[*warnings, "GUI run path did not complete; fallback only validated build through bin/xcode build."],
            next_actions=["Fix IDE automation readiness before expecting Xcode.app Run behavior."],
        )
    return emit_failure(
        "workflow",
        "xcode_ide_automation_failed",
        "Xcode IDE run workflow and plugin-routed CLI build fallback failed",
        details={"project_path": project_path, "scheme": args.scheme, "destination_id": destination_id, "steps": steps},
        artifacts={"artifact_dir": str(artifact_dir)},
        warnings=warnings,
        next_actions=["Inspect step artifacts and run bin/xcode ide preflight --json after resolving Xcode UI blockers."],
        exit_code=EXIT_CODES["xcode_ide_automation_failed"],
    )


def main() -> int:
    args = parse_args()
    if args.command == "run-app":
        return run_app_command(args)
    return emit_failure("workflow", "usage_error", "Unknown workflow command", exit_code=EXIT_CODES["usage_error"])


if __name__ == "__main__":
    raise SystemExit(main())
