# Native helper capabilities

Generated from scripts/xcode_native_capabilities.py. Do not edit manually.

## Supported native commands

| Command | Permission | Behavior | Safety | Public MCP exposure |
| --- | --- | --- | --- | --- |
| app xcode-state | none | read | readOnly | xcode_native_state |
| ax xcode-windows | Accessibility | read | readOnly | xcode_native_windows |
| ax press-menu | Accessibility | guarded mutation | stateChange | xcode_ide_menu_perform |
| ax press-button | Accessibility | guarded mutation | stateChange | typed Organizer routes only |
| ax press-control | Accessibility | guarded mutation | stateChange | typed Organizer routes only |

## Capability groups

### read

- xcode_state
- installed_xcodes
- ax_windows
- ax_inspect

### mutation

- typed_menu_press
- unique_button_press
- typed_control_press

### unsupported

- coordinate_input
- keyboard_synthesis
- raw_mcp_ax_selector
- arbitrary_shell_execution
- developer_tool_execution

The helper never exposes raw AX selectors through MCP. Mutation is limited to typed, uniquely resolved controls.
