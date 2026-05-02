#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from xcode_common import EXIT_CODES, emit_failure, emit_success, normalize_path
from xcode_scheme_inspector import inspect_scheme, scheme_roots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect read-only Xcode project context for agent workflow selection.")
    parser.add_argument("--path", required=True, help="Path to .xcodeproj or .xcworkspace.")
    parser.add_argument("--scheme", required=True, help="Scheme name to inspect.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    return parser.parse_args()


def find_scheme(container: Path, scheme: str) -> tuple[str, Path] | None:
    for visibility, root in scheme_roots(container):
        if root.exists():
            candidate = root / f"{scheme}.xcscheme"
            if candidate.exists():
                return visibility, candidate
    return None


def project_type(path: Path) -> str:
    if path.suffix == ".xcodeproj":
        return "xcodeproj"
    if path.suffix == ".xcworkspace":
        return "xcworkspace"
    return "directory"


def main() -> int:
    args = parse_args()
    container = normalize_path(args.path)
    if not container.exists():
        return emit_failure(
            "context",
            "usage_error",
            "Project/workspace path does not exist",
            details={"path": str(container)},
            exit_code=EXIT_CODES["usage_error"],
        )
    found = find_scheme(container, args.scheme)
    if found is None:
        return emit_failure(
            "context",
            "scheme_not_found",
            "Scheme was not found in shared or user scheme locations",
            details={"path": str(container), "scheme": args.scheme},
            next_actions=["Share the scheme or pass an existing scheme name."],
            exit_code=EXIT_CODES["scheme_not_found"],
        )
    visibility, scheme_path = found
    scheme_info = inspect_scheme(scheme_path, visibility)
    scheme_testable = bool(scheme_info["has_test_action"] and scheme_info["testable_count"] > 0)
    summary: dict[str, Any] = {
        "project_type": project_type(container),
        "path": str(container),
        "scheme": args.scheme,
        "scheme_path": str(scheme_path),
        "scheme_visibility": visibility,
        "scheme_testable": scheme_testable,
        "has_test_action": scheme_info["has_test_action"],
        "testable_reference_count": scheme_info["testable_count"],
        "build_entry_count": scheme_info["build_entry_count"],
    }
    next_actions: list[dict[str, Any]] = []
    if not scheme_testable:
        next_actions.append({"label": "Use build instead of test because scheme has no testable references"})
    else:
        next_actions.append({"label": "Use build-for-testing or focused test when validation requires tests"})
    next_actions.append({"label": "Use simulator resolve before build/test when the destination is name-based"})
    return emit_success(
        "context",
        summary,
        details={"scheme": scheme_info},
        next_actions=next_actions,
    )


if __name__ == "__main__":
    raise SystemExit(main())
