#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_ROOT = Path.home() / ".codex" / "tmp" / "xcode-gui-first"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = str(PLUGIN_ROOT / "bin" / "xcode")
TRIGGERS = re.compile(
    r"(@xcode\b|xcode@local\b|\$xcode-[a-z0-9-]+\b|\bxcode-[a-z0-9-]+\b|\bxcode plugin\b)",
    re.IGNORECASE,
)

ADDITIONAL_CONTEXT_TEMPLATE = """Xcode GUI-first plugin routing is active for this turn.

The user explicitly mentioned the Xcode plugin. Treat Xcode.app GUI control as the primary path.

Use terminal only as transport for the plugin dispatcher:
{dispatcher} native ...
{dispatcher} ide ...

Start with GUI evidence such as native app state, AX window/modal inspection, ide status, list-workspaces, and workspace-info. Prefer bin/xcode ide scheme-action for build/test/run/debug.

Do not bypass the plugin with bare xcodebuild, xcrun simctl, simctl, xcresulttool, osascript, open -a Xcode, run_xcode_cli_build.py, or xcode-cli-shared-cache-build.

Use bin/xcode build only after the GUI route is proven unavailable/insufficient, or when the user explicitly asks for CLI/headless validation."""


def read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def state_path(session_id: str, turn_id: str) -> Path:
    safe_session = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "unknown-session")
    safe_turn = re.sub(r"[^A-Za-z0-9_.-]+", "_", turn_id or "unknown-turn")
    return STATE_ROOT / safe_session / f"{safe_turn}.json"


def main() -> int:
    payload = read_payload()
    prompt = str(payload.get("prompt", ""))
    if not TRIGGERS.search(prompt):
        return 0

    session_id = str(payload.get("session_id", "unknown-session"))
    turn_id = str(payload.get("turn_id", "unknown-turn"))
    path = state_path(session_id, turn_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "active": True,
                "session_id": session_id,
                "turn_id": turn_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "prompt_excerpt": prompt[:400],
                "gui_evidence_seen": False,
                "dispatcher_path": DISPATCHER,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": ADDITIONAL_CONTEXT_TEMPLATE.format(dispatcher=DISPATCHER),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
