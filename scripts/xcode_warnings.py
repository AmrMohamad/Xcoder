#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from xcode_common import EXIT_CODES, create_artifact_dir, emit_failure, emit_success, normalize_path, safe_name, short_hash, write_json


DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>.*?):(?P<line>\d+):(?:(?P<column>\d+):)?\s*(?P<kind>warning|error|note):\s*(?P<message>.*)$",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize xcodebuild warning/error logs.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    parser.add_argument("--artifact-dir", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize = subparsers.add_parser("summarize", help="Parse warnings and errors from an xcodebuild log.")
    summarize.add_argument("--log", required=True)
    summarize.add_argument("--fail-on-new", action="store_true", help="Reserved for baseline diff workflows.")

    baseline = subparsers.add_parser("baseline", help="Create a warning baseline from a log.")
    baseline.add_argument("--log", required=True)
    baseline.add_argument("--output", required=True)

    diff = subparsers.add_parser("diff", help="Diff a log against a baseline.")
    diff.add_argument("--log", required=True)
    diff.add_argument("--baseline", required=True)

    return parser.parse_args()


def parse_log(path: Path) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, raw_line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw_line.strip()
        match = DIAGNOSTIC_RE.match(line)
        if not match:
            continue
        kind = match.group("kind").lower()
        diagnostic = {
            "kind": kind,
            "file": match.group("file"),
            "line": int(match.group("line")),
            "column": int(match.group("column")) if match.group("column") else None,
            "message": match.group("message").strip(),
            "log_line": index,
        }
        diagnostic["signature"] = signature(diagnostic)
        if kind == "warning":
            warnings.append(diagnostic)
        elif kind == "error":
            errors.append(diagnostic)
    groups: dict[str, dict[str, Any]] = {}
    for item in [*warnings, *errors]:
        sig = item["signature"]
        group = groups.setdefault(sig, {"signature": sig, "kind": item["kind"], "message": item["message"], "count": 0, "examples": []})
        group["count"] += 1
        if len(group["examples"]) < 3:
            group["examples"].append(item)
    return {
        "warning_count": len(warnings),
        "error_count": len(errors),
        "warnings": warnings,
        "errors": errors,
        "groups": sorted(groups.values(), key=lambda item: (-item["count"], item["message"])),
    }


def signature(diagnostic: dict[str, Any]) -> str:
    file_name = safe_name(Path(str(diagnostic.get("file") or "")).name)
    message = re.sub(r"\d+", "<n>", str(diagnostic.get("message") or ""))
    return short_hash(f"{diagnostic.get('kind')}|{file_name}|{message}", 16)


def summarize_command(args: argparse.Namespace) -> int:
    log_path = normalize_path(args.log)
    if not log_path.exists():
        return emit_failure(
            "warnings",
            "usage_error",
            "Log file does not exist",
            details={"log": str(log_path)},
            exit_code=EXIT_CODES["usage_error"],
        )
    artifact_dir = create_artifact_dir("warnings", args.artifact_dir)
    summary = parse_log(log_path)
    summary_path = artifact_dir / "warnings.json"
    errors_path = artifact_dir / "errors.json"
    write_json(summary_path, summary)
    write_json(errors_path, {"errors": summary["errors"]})
    return emit_success(
        "warnings",
        "xcodebuild diagnostics summarized",
        details={"log": str(log_path), "summary": {k: summary[k] for k in ["warning_count", "error_count", "groups"]}},
        artifacts={"artifact_dir": str(artifact_dir), "warnings_json": str(summary_path), "errors_json": str(errors_path)},
        next_actions=["Warning summarization does not change the underlying build/test result."],
        artifact_dir=artifact_dir,
    )


def baseline_command(args: argparse.Namespace) -> int:
    log_path = normalize_path(args.log)
    output_path = normalize_path(args.output)
    if not log_path.exists():
        return emit_failure("warnings", "usage_error", "Log file does not exist", details={"log": str(log_path)}, exit_code=EXIT_CODES["usage_error"])
    summary = parse_log(log_path)
    baseline = {"signatures": sorted({item["signature"] for item in [*summary["warnings"], *summary["errors"]]}), "source_log": str(log_path)}
    write_json(output_path, baseline)
    return emit_success("warnings", "Warning baseline created", details={"signature_count": len(baseline["signatures"])}, artifacts={"baseline": str(output_path)})


def diff_command(args: argparse.Namespace) -> int:
    log_path = normalize_path(args.log)
    baseline_path = normalize_path(args.baseline)
    if not log_path.exists() or not baseline_path.exists():
        return emit_failure(
            "warnings",
            "usage_error",
            "Log or baseline file does not exist",
            details={"log": str(log_path), "baseline": str(baseline_path)},
            exit_code=EXIT_CODES["usage_error"],
        )
    summary = parse_log(log_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    old = set(baseline.get("signatures") or [])
    current = {item["signature"] for item in [*summary["warnings"], *summary["errors"]]}
    new = sorted(current - old)
    return emit_success(
        "warnings",
        "Warning baseline diff completed",
        details={"new_signature_count": len(new), "new_signatures": new},
        next_actions=["Use --fail-on-new in a future workflow when new warnings should fail validation."],
    )


def main() -> int:
    args = parse_args()
    if args.command == "summarize":
        return summarize_command(args)
    if args.command == "baseline":
        return baseline_command(args)
    if args.command == "diff":
        return diff_command(args)
    return emit_failure("warnings", "usage_error", "Unknown warnings command", exit_code=EXIT_CODES["usage_error"])


if __name__ == "__main__":
    raise SystemExit(main())
