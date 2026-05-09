#!/usr/bin/env python3

from __future__ import annotations

import argparse
from typing import Any

from xcode_common import EXIT_CODES, emit_failure, emit_success


TOPICS: dict[str, dict[str, Any]] = {
    "first-time": {
        "title": "First-time MCP bootstrap",
        "summary": "Build and install the bundled Swift MCP server, then restart Codex so the Xcode MCP namespace is reloaded.",
        "commands": ["bin/xcode mcp bootstrap --json"],
        "next_actions": [
            "Run the bootstrap command from the plugin root.",
            "Restart Codex after bootstrap completes.",
            "Verify with bin/xcode mcp list-tools --json.",
        ],
        "source_docs": ["docs/first-use-mcp.md", "docs/workflows.md"],
    },
    "ide-vs-cli": {
        "title": "GUI-first IDE routing",
        "summary": "Prefer MCP tools and bin/xcode ide commands for Xcode.app work. Use plugin-routed CLI fallback only where the workflow explicitly allows it.",
        "commands": [
            "bin/xcode ide status --json",
            "bin/xcode ide preflight --workspace-path <path> --scheme <scheme> --json",
        ],
        "next_actions": [
            "Inspect Xcode state before choosing build, test, or run arguments.",
            "Use xcode_ide_build, xcode_ide_test, or xcode_ide_run through MCP for IDE actions.",
            "For builds or tests that exceed the MCP call budget, use the equivalent bin/xcode ... --json command so Codex can wait outside the MCP transport limit.",
            "For app runs that exceed the MCP call budget, use bin/xcode workflow run-app --json rather than increasing xcode_ide_run timeout_seconds.",
        ],
        "source_docs": ["docs/architecture.md", "docs/workflows.md"],
    },
    "fail-recovery": {
        "title": "Failure recovery metadata",
        "summary": "Failure envelopes include recovery, transient, and retry_after_seconds so Codex can decide whether to retry, ask the user, fix permissions, check environment, or stop.",
        "commands": ["bin/xcode doctor --json"],
        "next_actions": [
            "For recovery=retry, retry after retry_after_seconds when present.",
            "For recovery=user_input, correct arguments or ask the user for missing context.",
            "For recovery=permission or environment, resolve the local host issue before retrying.",
        ],
        "source_docs": ["docs/workflows.md", "docs/validation.md"],
    },
    "scheme-not-testable": {
        "title": "Scheme is not testable",
        "summary": "Use Xcode scheme inspection and IDE discovery before running tests. A scheme may build or run but still lack test action support.",
        "commands": [
            "bin/xcode ide list-schemes --workspace-path <path> --json",
            "bin/xcode scheme --path <path> --scheme <scheme> --json",
        ],
        "next_actions": [
            "Confirm the exact scheme name.",
            "Check whether the scheme has test targets.",
            "Ask the user which testable scheme to use if none is obvious.",
        ],
        "source_docs": ["docs/workflows.md"],
    },
    "destination-ambiguous": {
        "title": "Destination ambiguity",
        "summary": "When multiple Xcode destinations match a name, use discovery tools to choose a stable destination_id.",
        "commands": [
            "bin/xcode ide list-destinations --workspace-path <path> --json",
            "bin/xcode simulator resolve --name \"iPhone\" --json",
        ],
        "next_actions": [
            "Prefer destination_id over destination_name when available.",
            "Pass destination_name only when it uniquely identifies the intended destination.",
        ],
        "source_docs": ["docs/workflows.md"],
    },
    "build-json": {
        "title": "Build JSON machine output",
        "summary": "bin/xcode build --json emits one clean xcode-plugin.v0.3 envelope on stdout. Raw build logs are stored as artifacts instead of mixed into stdout.",
        "commands": ["bin/xcode build --json --dry-run <xcodebuild args>"],
        "next_actions": [
            "Read artifacts.stdout_log and artifacts.stderr_log for raw build output.",
            "Use --dry-run with --json to inspect the resolved command plan without running xcodebuild.",
        ],
        "source_docs": ["docs/workflows.md", "docs/validation.md"],
    },
    "package-release": {
        "title": "Release package gate",
        "summary": "Release zips must be produced by bin/xcode package zip and pass bin/xcode package audit. Finder-created zips are not acceptable.",
        "commands": [
            "bin/xcode package zip --output /tmp/xcode-plugin.zip --json",
            "bin/xcode package audit --zip /tmp/xcode-plugin.zip --json",
        ],
        "next_actions": [
            "Reject archives containing __MACOSX, .DS_Store, __pycache__, .pytest_cache, .codex/xcode/artifacts, build output, or missing package-manifest.json.",
            "Run scripts/release_gate.sh before publishing.",
        ],
        "source_docs": ["docs/validation.md"],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Return static Xcoder routing and recovery guidance.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    parser.add_argument("--topic", default="ide-vs-cli", help="Help topic to return.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    topic = args.topic or "ide-vs-cli"
    if topic not in TOPICS:
        return emit_failure(
            "help",
            "usage_error",
            f"Unknown help topic: {topic}",
            details={"topic": topic, "valid_topics": sorted(TOPICS)},
            next_actions=["Choose one of the valid help topics."],
            exit_code=EXIT_CODES["usage_error"],
        )

    payload = dict(TOPICS[topic])
    payload["topic"] = topic
    return emit_success("help", payload["summary"], details=payload, next_actions=payload["next_actions"])


if __name__ == "__main__":
    raise SystemExit(main())
