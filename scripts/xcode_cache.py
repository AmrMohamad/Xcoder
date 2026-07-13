#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xcode_cache_identity import CACHE_IDENTITY_SCHEMA
from xcode_common import EXIT_CODES, emit_failure, emit_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Xcoder DerivedData cache metadata without mutating it.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--derived-data-root", default="~/Library/Developer/Xcode/DerivedData")
    inspect.add_argument("--json", action="store_true")
    return parser.parse_args()


def inspect_command(root: Path) -> int:
    shared = root.expanduser().resolve(strict=False) / "_codex_cli_shared"
    records: list[dict[str, object]] = []
    if shared.is_dir():
        for metadata_path in sorted(shared.rglob(".codex-xcode-cache.json")):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                schema = payload.get("schema_version", "unversioned")
                records.append(
                    {
                        "cache_leaf": metadata_path.parent.name,
                        "schema_version": schema,
                        "compatible_schema": schema == CACHE_IDENTITY_SCHEMA,
                        "metadata_valid": isinstance(payload, dict),
                    }
                )
            except (OSError, json.JSONDecodeError):
                records.append(
                    {
                        "cache_leaf": metadata_path.parent.name,
                        "schema_version": "corrupt",
                        "compatible_schema": False,
                        "metadata_valid": False,
                    }
                )
    return emit_success(
        "cache.inspect",
        "Xcoder cache metadata inspected without mutation",
        details={
            "schema_version": CACHE_IDENTITY_SCHEMA,
            "cache_count": len(records),
            "compatible_count": sum(record["compatible_schema"] is True for record in records),
            "legacy_or_corrupt_count": sum(record["compatible_schema"] is not True for record in records),
            "caches": records,
        },
    )


def main() -> int:
    args = parse_args()
    if args.command == "inspect":
        return inspect_command(Path(args.derived_data_root))
    return emit_failure("cache", "usage_error", "Unknown cache command", exit_code=EXIT_CODES["usage_error"])


if __name__ == "__main__":
    raise SystemExit(main())
