---
name: xcode-ide-automation
description: Control the open Xcode app through AppleScript/JXA for workspace state, scheme/destination selection, and IDE build/test/run/debug actions.
---

# Xcode IDE Automation

Use this skill when the user needs Codex to take control of the Xcode window or validate behavior through the open IDE. Do not use it as the default build system; normal builds/tests go through `xcode-build-cache`.

## Rules

- Use AppleScript/JXA only for Xcode app state and IDE actions that require the open app.
- Prefer `--workspace-path` for every workspace-specific command.
- If multiple workspaces are open and no `--workspace-path` is supplied, fail before changing scheme or destination.
- If `--workspace-path` is supplied and cannot be matched, do not fall back to the active window.
- Prefer `--destination-id`; use `--destination-name` only when it resolves to exactly one run destination.
- Use native preflight when available to detect Xcode process state and blocking windows before IDE mutations.
- Pass `--require-native-preflight` when the command must fail if native preflight is unavailable.
- IDE action timeouts exit `124` and request `stop`.
- Do not depend on XcodeBuildMCP.

## Commands

Inspect and focus Xcode:

```bash
bin/xcode ide status --json
bin/xcode ide activate --json
bin/xcode ide list-workspaces --json
bin/xcode ide workspace-info --workspace-path /path/to/App.xcworkspace --json
```

Open a workspace/project:

```bash
bin/xcode ide open-workspace --path /path/to/App.xcworkspace --timeout-seconds 60 --json
```

List or set active scheme/destination:

```bash
bin/xcode ide list-schemes --workspace-path /path/to/App.xcworkspace --json
bin/xcode ide set-scheme --workspace-path /path/to/App.xcworkspace --name 'App (Debug)' --json
bin/xcode ide list-destinations --workspace-path /path/to/App.xcworkspace --json
bin/xcode ide set-destination --workspace-path /path/to/App.xcworkspace --destination-id <UDID> --json
```

Run IDE actions:

```bash
bin/xcode ide scheme-action --workspace-path /path/to/App.xcworkspace --action build --timeout-seconds 300 --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcworkspace --action test --scheme 'App (Debug)' --destination-id <UDID> --timeout-seconds 300 --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcworkspace --action build --require-native-preflight --timeout-seconds 300 --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcworkspace --action stop --json
```

Diagnose a not-testable scheme:

```bash
bin/xcode context --path /path/to/App.xcodeproj --scheme 'App (Debug)' --json
```

## Output Contract

Every command reachable through `bin/xcode` returns the v0.3 envelope.
