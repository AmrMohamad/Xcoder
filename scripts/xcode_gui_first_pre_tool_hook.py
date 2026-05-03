#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Iterable


STATE_ROOT = Path.home() / ".codex" / "tmp" / "xcode-gui-first"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = str(PLUGIN_ROOT / "bin" / "xcode")
GUI_SUBCOMMANDS = {"ide", "native"}
SUPPORT_SUBCOMMANDS = {"doctor", "context", "simulator", "results", "warnings", "package"}
CLI_OK_PROMPT = re.compile(r"\b(cli|headless|terminal|xcodebuild|shared[- ]cache|command[- ]line)\b", re.IGNORECASE)
SHELL_COMMANDS = {"bash", "sh", "zsh"}


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


def load_state(payload: dict) -> tuple[Path, dict] | tuple[None, None]:
    path = state_path(str(payload.get("session_id", "")), str(payload.get("turn_id", "")))
    if not path.exists():
        return None, None
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None


def save_state(path: Path | None, state: dict | None) -> None:
    if path is None or state is None:
        return
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_text(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("command") or tool_input.get("cmd") or "")


def split_segments(command: str) -> Iterable[str]:
    for segment in re.split(r"&&|\|\||\||;|\n", command):
        segment = segment.strip()
        if segment:
            yield segment


def shell_words(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def command_name(word: str) -> str:
    return os.path.basename(word)


def first_command(words: list[str]) -> tuple[str, list[str]]:
    while True:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", words[0]):
            words = words[1:]
        if not words:
            return "", []

        name = command_name(words[0])
        if name in {"time", "command", "exec"}:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
            continue
        if name == "sudo":
            words = words[1:]
            while words and words[0].startswith("-"):
                option = words[0]
                words = words[1:]
                if option in {"-u", "-g", "-h", "-p", "-C", "-T", "-t"} and words:
                    words = words[1:]
            continue
        if name == "env":
            words = words[1:]
            while words:
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", words[0]):
                    words = words[1:]
                    continue
                if words[0] in {"-u", "--unset"} and len(words) > 1:
                    words = words[2:]
                    continue
                if words[0].startswith("--unset=") or words[0].startswith("-"):
                    words = words[1:]
                    continue
                break
            continue
        if name == "arch":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
            continue

        return name, words


def deny(reason: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def is_dispatcher(words: list[str]) -> bool:
    if not words:
        return False
    first = words[0]
    return first == DISPATCHER or first.endswith("/bin/xcode") or command_name(first) == "xcode"


def prompt_allows_cli(state: dict | None) -> bool:
    prompt = str((state or {}).get("prompt_excerpt", ""))
    return bool(CLI_OK_PROMPT.search(prompt))


def classify_dispatcher(words: list[str]) -> str | None:
    if not is_dispatcher(words):
        return None
    for word in words[1:]:
        if word.startswith("-"):
            continue
        return word
    return "help"


def nested_shell_command(name: str, words: list[str]) -> str | None:
    if name not in SHELL_COMMANDS:
        return None
    for index, word in enumerate(words[1:], start=1):
        if word == "-c" and index + 1 < len(words):
            return words[index + 1]
        if word.startswith("-") and "c" in word.lstrip("-") and index + 1 < len(words):
            return words[index + 1]
    return None


def denial_reason_for_command(command: str, state: dict | None) -> str | None:
    for segment in split_segments(command):
        words = shell_words(segment)
        name, words = first_command(words)
        if not name:
            continue

        nested_command = nested_shell_command(name, words)
        if nested_command:
            nested_reason = denial_reason_for_command(nested_command, state)
            if nested_reason:
                return nested_reason
            continue

        subcommand = classify_dispatcher(words)
        if subcommand in GUI_SUBCOMMANDS:
            state["gui_evidence_seen"] = True
            continue
        if subcommand == "build" and not state.get("gui_evidence_seen") and not prompt_allows_cli(state):
            return (
                "Xcode GUI-first mode is active because @xcode was mentioned. Start with "
                "bin/xcode native ... and bin/xcode ide ... before using bin/xcode build, "
                "unless the user explicitly asks for CLI/headless validation."
            )
        if subcommand in SUPPORT_SUBCOMMANDS or subcommand in {"help", "--help", "--version", "version"}:
            continue
        if subcommand is not None:
            continue

        if name == "xcodebuild":
            return "Use the Xcode plugin GUI-first route: bin/xcode ide ... . Do not run bare xcodebuild in an explicit @xcode turn."
        if name == "xcrun" and len(words) > 1 and words[1] == "simctl":
            return "Use bin/xcode simulator ... instead of bare xcrun simctl in an explicit @xcode turn."
        if name == "simctl":
            return "Use bin/xcode simulator ... instead of bare simctl in an explicit @xcode turn."
        if name == "xcresulttool":
            return "Use bin/xcode results ... instead of bare xcresulttool in an explicit @xcode turn."
        if name == "osascript":
            return "Use bin/xcode ide ... or bin/xcode native ... instead of direct osascript in an explicit @xcode turn."
        if name == "open" and "-a" in words and any("xcode" in word.lower() for word in words):
            return "Use bin/xcode ide open-workspace ... or bin/xcode native app open-workspace ... instead of open -a Xcode."
        if name == "run_xcode_cli_build.py" or any(word.endswith("/run_xcode_cli_build.py") for word in words):
            return "Use bin/xcode build ... instead of calling run_xcode_cli_build.py directly."
        if "xcode-cli-shared-cache-build" in command:
            return "Use the active Xcode plugin dispatcher instead of the old xcode-cli-shared-cache-build skill."

    return None


def main() -> int:
    payload = read_payload()
    state_file, state = load_state(payload)
    if not state or not state.get("active"):
        return 0

    command = command_text(payload)
    if not command:
        return 0

    reason = denial_reason_for_command(command, state)
    if reason:
        return deny(reason)

    save_state(state_file, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
