#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


MAX_TEXT_LENGTH = 500
RECORD_ROOT = Path.home() / ".codex" / "xcode" / "artifacts" / "hook-records"


def redact(text: str) -> str:
    redacted = text.replace(str(Path.home()), "~")
    patterns = [
        (r"(?i)(api[_-]?key|token|secret|password)=([^\s]+)", r"\1=<redacted>"),
        (r"(?i)(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    if len(redacted) > MAX_TEXT_LENGTH:
        return redacted[:MAX_TEXT_LENGTH] + "...<truncated>"
    return redacted


def nested_get(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_present(event: dict[str, Any], paths: list[tuple[str, ...]]) -> Any:
    for path in paths:
        value = nested_get(event, *path)
        if value is not None:
            return value
    return None


def tool_name(event: dict[str, Any]) -> str:
    value = first_present(
        event,
        [
            ("tool_name",),
            ("toolName",),
            ("name",),
            ("tool", "name"),
            ("toolUse", "name"),
        ],
    )
    return str(value or "")


def command_text(event: dict[str, Any]) -> str:
    value = first_present(
        event,
        [
            ("tool_input", "command"),
            ("toolInput", "command"),
            ("input", "command"),
            ("arguments", "command"),
            ("params", "command"),
        ],
    )
    return str(value or "")


def exit_code(event: dict[str, Any]) -> int | None:
    value = first_present(
        event,
        [
            ("exit_code",),
            ("exitCode",),
            ("tool_response", "exit_code"),
            ("toolResponse", "exitCode"),
            ("response", "exit_code"),
            ("result", "exit_code"),
        ],
    )
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def succeeded(event: dict[str, Any]) -> bool:
    code = exit_code(event)
    if code is not None:
        return code == 0
    value = first_present(
        event,
        [
            ("success",),
            ("ok",),
            ("tool_response", "success"),
            ("toolResponse", "success"),
            ("result", "success"),
            ("result", "ok"),
        ],
    )
    return value is True


def is_xcoder_event(event: dict[str, Any]) -> bool:
    name = tool_name(event)
    if name.startswith("mcp__xcode__"):
        return True

    command = command_text(event)
    if not command:
        return False

    normalized = command.replace("\\", "/")
    return bool(
        re.search(r"(^|\s)(\./)?bin/xcode(\s|$)", normalized)
        or "/bin/xcode " in normalized
        or re.search(r"(^|\s)(\./)?bin/xcode-mcp(\s|$)", normalized)
        or "/bin/xcode-mcp" in normalized
    )


def record_for(event: dict[str, Any]) -> dict[str, Any] | None:
    if not is_xcoder_event(event) or not succeeded(event):
        return None

    name = tool_name(event)
    command = command_text(event)
    record: dict[str, Any] = {
        "schema_version": "xcode-post-tool-hook.v0.1",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool_name": name,
        "exit_code": exit_code(event),
    }
    if command:
        record["command_excerpt"] = redact(command)
    return record


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0

    record = record_for(event)
    if record is None:
        return 0

    RECORD_ROOT.mkdir(parents=True, exist_ok=True)
    path = RECORD_ROOT / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-post-tool.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
