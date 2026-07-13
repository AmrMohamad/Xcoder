#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from xcode_native_capabilities import NATIVE_COMMAND_CATALOG, capability_report


def render() -> str:
    capabilities = capability_report()
    lines = [
        "# Native helper capabilities",
        "",
        "Generated from scripts/xcode_native_capabilities.py. Do not edit manually.",
        "",
        "## Supported native commands",
        "",
        "| Command | Permission | Behavior | Safety | Public MCP exposure |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in NATIVE_COMMAND_CATALOG:
        lines.append(
            f"| {item['command']} | {item['permission']} | {item['behavior']} | "
            f"{item['safety']} | {item['public_mcp']} |"
        )
    lines.extend(["", "## Capability groups", ""])
    for group in ("read", "mutation", "unsupported"):
        lines.append(f"### {group}")
        lines.append("")
        lines.extend(f"- {value}" for value in capabilities[group])
        lines.append("")
    lines.extend(
        [
            "The helper never exposes raw AX selectors through MCP. Mutation is limited to typed, uniquely resolved controls.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[1] / "docs" / "generated" / "native-capabilities.md",
    )
    args = parser.parse_args()
    expected = render()
    if args.check:
        return 0 if args.output.exists() and args.output.read_text(encoding="utf-8") == expected else 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
