#!/usr/bin/env python3

from __future__ import annotations

from typing import Any


NATIVE_HELPER_CAPABILITIES: dict[str, list[str]] = {
    "read": ["xcode_state", "installed_xcodes", "ax_windows", "ax_inspect"],
    "mutation": ["typed_menu_press", "unique_button_press", "typed_control_press"],
    "unsupported": [
        "coordinate_input",
        "keyboard_synthesis",
        "raw_mcp_ax_selector",
        "arbitrary_shell_execution",
        "developer_tool_execution",
    ],
}

NATIVE_COMMAND_CATALOG: list[dict[str, Any]] = [
    {
        "command": "app xcode-state",
        "permission": "none",
        "behavior": "read",
        "safety": "readOnly",
        "public_mcp": "xcode_native_state",
    },
    {
        "command": "ax xcode-windows",
        "permission": "Accessibility",
        "behavior": "read",
        "safety": "readOnly",
        "public_mcp": "xcode_native_windows",
    },
    {
        "command": "ax press-menu",
        "permission": "Accessibility",
        "behavior": "guarded mutation",
        "safety": "stateChange",
        "public_mcp": "xcode_ide_menu_perform",
    },
    {
        "command": "ax press-button",
        "permission": "Accessibility",
        "behavior": "guarded mutation",
        "safety": "stateChange",
        "public_mcp": "typed Organizer routes only",
    },
    {
        "command": "ax press-control",
        "permission": "Accessibility",
        "behavior": "guarded mutation",
        "safety": "stateChange",
        "public_mcp": "typed Organizer routes only",
    },
]


def capability_report() -> dict[str, list[str]]:
    return {key: list(values) for key, values in NATIVE_HELPER_CAPABILITIES.items()}
