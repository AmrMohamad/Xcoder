#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xcode_common import (
    EXIT_CODES,
    compact_output,
    create_artifact_dir,
    emit_failure,
    emit_success,
    normalize_path,
    run_command,
    write_json,
    write_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize .xcresult bundles with xcresulttool.")
    argv = sys.argv[1:]
    if argv and argv[0] == "summarize":
        argv = argv[1:]
    parser.add_argument("--path", required=True, help="Path to an .xcresult bundle.")
    parser.add_argument("--kind", choices=["test-summary", "build-results", "content-availability", "log"], default="test-summary")
    parser.add_argument("--log-type", default="build", choices=["build", "action", "console"])
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    return parser.parse_args(argv)


def command_for(kind: str, path: Path, log_type: str) -> list[str]:
    base = ["xcrun", "xcresulttool", "get"]
    if kind == "test-summary":
        return [*base, "test-results", "summary", "--path", str(path), "--compact"]
    if kind == "build-results":
        return [*base, "build-results", "--path", str(path), "--compact"]
    if kind == "content-availability":
        return [*base, "content-availability", "--path", str(path), "--compact"]
    return [*base, "log", "--path", str(path), "--type", log_type, "--compact"]


def first_int(raw: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, int):
            return value
    return None


def walk(value: Any) -> list[Any]:
    items = [value]
    if isinstance(value, dict):
        for child in value.values():
            items.extend(walk(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(walk(child))
    return items


def normalize_test_summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "result": raw.get("result") or raw.get("status") or raw.get("testStatus") or "unknown",
        "total_tests": first_int(raw, ["total_tests", "totalTestCount", "testCount", "totalCount"]),
        "passed_tests": first_int(raw, ["passed_tests", "passedTestCount", "passedCount"]),
        "failed_tests": first_int(raw, ["failed_tests", "failedTestCount", "failureCount", "failedCount"]),
        "skipped_tests": first_int(raw, ["skipped_tests", "skippedTestCount", "skipCount", "skippedCount"]),
        "expected_failures": first_int(raw, ["expected_failures", "expectedFailureCount"]),
        "failures": [],
    }
    failures: list[dict[str, Any]] = []
    for item in walk(raw):
        if not isinstance(item, dict):
            continue
        status = str(item.get("result") or item.get("status") or item.get("testStatus") or "").lower()
        has_failure_text = any(key in item for key in ["failureText", "failureMessage", "message", "issueSummary"])
        if "fail" in status or ("testName" in item and has_failure_text):
            failures.append(
                {
                    "test_name": item.get("testName") or item.get("name") or item.get("identifier"),
                    "status": item.get("result") or item.get("status") or item.get("testStatus"),
                    "message": item.get("failureText") or item.get("failureMessage") or item.get("message") or item.get("issueSummary"),
                    "file": item.get("fileName") or item.get("documentLocationInCreatingWorkspace", {}).get("url") if isinstance(item.get("documentLocationInCreatingWorkspace"), dict) else item.get("fileName"),
                    "line": item.get("lineNumber") or item.get("line"),
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for failure in failures:
        key = json.dumps(failure, sort_keys=True)
        if key not in seen:
            seen.add(key)
            deduped.append(failure)
    summary["failures"] = deduped
    if summary["failed_tests"] is None:
        summary["failed_tests"] = len(deduped)
    for key in ["total_tests", "passed_tests", "skipped_tests", "expected_failures"]:
        if summary[key] is None:
            summary[key] = 0
    return summary


def main() -> int:
    args = parse_args()
    result_path = normalize_path(args.path)
    artifact_dir = create_artifact_dir("results", args.artifact_dir)
    if not result_path.exists():
        return emit_failure(
            "results",
            "xcresult_missing",
            ".xcresult path does not exist",
            details={"path": str(result_path)},
            next_actions=["Pass the path from xcodebuild -resultBundlePath or Xcode's result bundle export."],
            exit_code=EXIT_CODES["xcresult_missing"],
            artifact_dir=artifact_dir,
        )

    command = command_for(args.kind, result_path, args.log_type)
    write_json(artifact_dir / "command.json", {"command": command, "path": str(result_path), "kind": args.kind})
    result = run_command(command, timeout_seconds=args.timeout_seconds)
    warnings = [compact_output(result["stderr"])] if result["stderr"].strip() else []
    artifacts: dict[str, Any] = {"artifact_dir": str(artifact_dir), "command": str(artifact_dir / "command.json")}

    if result["exit_code"] != 0:
        error_type = "command_timeout" if result.get("timed_out") else "xcresult_corrupt"
        write_text(artifact_dir / "stderr.log", result["stderr"])
        artifacts["stderr_log"] = str(artifact_dir / "stderr.log")
        return emit_failure(
            "results",
            error_type,
            f"xcresult {args.kind} summary failed",
            details={"path": str(result_path), "kind": args.kind, "exit_code": result["exit_code"]},
            artifacts=artifacts,
            warnings=warnings,
            errors=[compact_output(result["stderr"] or result["stdout"])],
            next_actions=["Verify the .xcresult bundle exists and matches the installed Xcode version."],
            exit_code=EXIT_CODES.get(error_type, result["exit_code"] or 1),
            artifact_dir=artifact_dir,
        )

    stdout = result["stdout"].strip()
    if not stdout:
        return emit_failure("results", "xcresult_corrupt", "xcresulttool returned empty output", artifacts=artifacts, exit_code=EXIT_CODES["xcresult_corrupt"], artifact_dir=artifact_dir)

    try:
        raw = json.loads(stdout)
        raw_path = artifact_dir / f"raw-xcresulttool-{args.kind}.json"
        write_json(raw_path, raw)
        artifacts["raw_xcresulttool_json"] = str(raw_path)
    except json.JSONDecodeError:
        raw_path = artifact_dir / f"raw-xcresulttool-{args.kind}.txt"
        write_text(raw_path, stdout)
        artifacts["raw_output"] = str(raw_path)
        return emit_success(
            "results",
            f"xcresult {args.kind} output captured",
            details={"path": str(result_path), "kind": args.kind},
            artifacts=artifacts,
            warnings=[*warnings, "xcresulttool output was not JSON; raw output was written to an artifact."],
            artifact_dir=artifact_dir,
        )

    details: dict[str, Any] = {"path": str(result_path), "kind": args.kind}
    if args.kind == "test-summary":
        details["summary"] = normalize_test_summary(raw)
    else:
        details["summary"] = {"result": "captured", "kind": args.kind}

    return emit_success(
        "results",
        f"xcresult {args.kind} summarized",
        details=details,
        artifacts=artifacts,
        warnings=warnings,
        next_actions=[
            "Use test-summary for compact pass/fail information.",
            "Open raw_xcresulttool_json only when detailed schema inspection is needed.",
        ],
        artifact_dir=artifact_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
