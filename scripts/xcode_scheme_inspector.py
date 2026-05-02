#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from xcode_common import EXIT_CODES, emit_failure, emit_success


def scheme_roots(container: Path) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    if container.suffix == ".xcodeproj":
        roots.append(("shared", container / "xcshareddata" / "xcschemes"))
        roots.extend(("user", path) for path in sorted((container / "xcuserdata").glob("*.xcuserdatad/xcschemes")))
        return roots
    if container.suffix == ".xcworkspace":
        roots.append(("shared", container / "xcshareddata" / "xcschemes"))
        roots.extend(("user", path) for path in sorted((container / "xcuserdata").glob("*.xcuserdatad/xcschemes")))
        return roots
    roots.append(("directory", container))
    return roots


def buildable(reference: ET.Element | None) -> dict[str, Any]:
    if reference is None:
        return {}
    return {
        "buildable_name": reference.attrib.get("BuildableName"),
        "blueprint_name": reference.attrib.get("BlueprintName"),
        "blueprint_identifier": reference.attrib.get("BlueprintIdentifier"),
        "referenced_container": reference.attrib.get("ReferencedContainer"),
    }


def inspect_scheme(path: Path, visibility: str) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    test_action = root.find("TestAction")
    testables = []
    if test_action is not None:
        for item in test_action.findall("./Testables/TestableReference"):
            reference = item.find("BuildableReference")
            testables.append(
                {
                    "skipped": item.attrib.get("skipped"),
                    "parallelizable": item.attrib.get("parallelizable"),
                    **buildable(reference),
                }
            )

    build_entries = []
    for entry in root.findall("./BuildAction/BuildActionEntries/BuildActionEntry"):
        reference = entry.find("BuildableReference")
        build_entries.append({**entry.attrib, **buildable(reference)})

    return {
        "name": path.stem,
        "path": str(path),
        "visibility": visibility,
        "has_test_action": test_action is not None,
        "test_build_configuration": test_action.attrib.get("buildConfiguration") if test_action is not None else None,
        "testable_count": len(testables),
        "testables": testables,
        "build_entry_count": len(build_entries),
        "build_entries": build_entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Xcode .xcscheme files for testability.")
    parser.add_argument("--path", required=False, help="Path to .xcodeproj, .xcworkspace, xcschemes directory, or .xcscheme.")
    parser.add_argument("--fixture", default=None, help="Fixture .xcscheme path. Alias for --path in tests.")
    parser.add_argument("--scheme", default=None, help="Optional scheme name to filter.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_path = args.path or args.fixture
    if not raw_path:
        return emit_failure("scheme", "usage_error", "Pass --path or --fixture", exit_code=EXIT_CODES["usage_error"])
    target = Path(raw_path).expanduser()
    if not target.exists():
        return emit_failure("scheme", "usage_error", "Scheme container path does not exist", details={"path": str(target)}, exit_code=EXIT_CODES["usage_error"])

    scheme_files: list[tuple[str, Path]] = []
    if target.suffix == ".xcscheme":
        scheme_files.append(("direct", target))
    else:
        for visibility, root in scheme_roots(target):
            if root.exists():
                scheme_files.extend((visibility, path) for path in sorted(root.glob("*.xcscheme")))

    if args.scheme:
        scheme_files = [(visibility, path) for visibility, path in scheme_files if path.stem == args.scheme]

    schemes = []
    warnings = []
    for visibility, path in scheme_files:
        try:
            schemes.append(inspect_scheme(path, visibility))
        except ET.ParseError as exc:
            warnings.append(f"Could not parse {path}: {exc}")

    not_testable = [scheme["name"] for scheme in schemes if scheme["has_test_action"] and scheme["testable_count"] == 0]
    missing_test_action = [scheme["name"] for scheme in schemes if not scheme["has_test_action"]]
    if not_testable:
        warnings.append("Some schemes have a TestAction but no TestableReference entries.")
    if missing_test_action:
        warnings.append("Some schemes do not have a TestAction.")

    details = {"schemes": schemes, "not_testable_schemes": not_testable, "missing_test_action_schemes": missing_test_action}
    if not schemes:
        return emit_failure(
            "scheme",
            "scheme_not_found",
            "No Xcode scheme files found",
            details=details,
            warnings=warnings,
            next_actions=["Confirm the scheme is shared under xcshareddata/xcschemes."],
            exit_code=EXIT_CODES["scheme_not_found"],
        )
    return emit_success(
        "scheme",
        "Xcode scheme files inspected",
        details=details,
        warnings=warnings,
        next_actions=[
            "For not-testable schemes, add the unit/UI test bundle in Product > Scheme > Edit Scheme > Test.",
            "Commit shared .xcscheme changes under xcshareddata/xcschemes when CLI or agents must use them.",
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
