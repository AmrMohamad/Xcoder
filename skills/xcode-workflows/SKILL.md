---
name: xcode-workflows
description: Choose the right GUI-first Xcode plugin flow, using Xcode.app IDE/native automation before plugin-routed CLI fallback.
---

# Xcode Workflows

Use this skill to choose between the plugin’s GUI, native, context, simulator, results, warning, doctor, and CLI fallback workflows.

## Explicit Plugin Contract

When the user explicitly mentions `@xcode`, `xcode@local`, or any bundled `xcode-*` skill, enter GUI-first mode.

In GUI-first mode:

- If this is first use, or if `mcp__xcode__*` tools are missing, activate `xcode-first-use` and bootstrap the bundled Swift MCP server before normal Xcode work.
- Start with Xcode.app evidence through `bin/xcode native ...` and `bin/xcode ide ...`.
- Prefer `bin/xcode ide scheme-action` for build, test, run, debug, and stop.
- Use `bin/xcode build` only as plugin-routed fallback/support after explaining why GUI control cannot satisfy the task, or when the user explicitly asks for CLI/headless validation.
- Do not run bare `xcodebuild`, `xcrun simctl`, `simctl`, `xcresulttool`, `osascript`, `open -a Xcode`, or old `xcode-cli-shared-cache-build`.
- If the plugin lacks the needed GUI command, say that plainly and propose the plugin command that should be added.
- If first-use MCP bootstrap still fails after local repair, report the failure at `https://github.com/AmrMohamad/Xcoder/issues` with compact redacted diagnostics.

## Decision Table

- Unknown Xcode GUI state: use `bin/xcode native app xcode-state`, `bin/xcode native ax xcode-windows`, and `bin/xcode ide status`.
- Open Xcode window state, scheme selection, destination selection, or IDE test/run/debug: use `bin/xcode ide`.
- Unknown project/scheme state: use `bin/xcode context`, then return to `bin/xcode ide` when possible.
- Simulator inventory, resolve, boot, install, launch, terminate, or screenshot: use `bin/xcode simulator`.
- `.xcresult` summaries: use `bin/xcode results`.
- xcodebuild log warnings/errors: use `bin/xcode warnings summarize`.
- Toolchain, permissions, SDEF, or optional `mcpbridge` diagnosis: use `bin/xcode doctor`.
- CLI/headless fallback only: use `bin/xcode build`.

## GUI-First Standard Flow

```bash
bin/xcode doctor --json
bin/xcode native app xcode-state --json
bin/xcode native ax xcode-windows --json
bin/xcode ide status --json
bin/xcode ide list-workspaces --json
bin/xcode ide workspace-info --workspace-path /path/to/App.xcodeproj --json
bin/xcode context --path /path/to/App.xcodeproj --scheme 'App (Debug)' --json
bin/xcode simulator resolve --name "iPhone SE (3rd generation)" --runtime "iOS 18.5" --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcodeproj --action build --scheme 'App (Debug)' --destination-id <UDID> --timeout-seconds 300 --json
```

## IDE-Controlled Flow

```bash
bin/xcode ide status --json
bin/xcode native permissions status --json
bin/xcode native ax xcode-windows --json
bin/xcode native ax xcode-windows --include-paths --json
bin/xcode ide activate --json
bin/xcode ide list-workspaces --json
bin/xcode ide workspace-info --workspace-path /path/to/App.xcodeproj --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcodeproj --action test --scheme 'App (Debug)' --destination-id <UDID> --timeout-seconds 300 --json
```

## Boundary

This plugin is local-first and script-backed. It does not depend on XcodeBuildMCP. Apple `mcpbridge` is treated as optional until local compatibility is proven.

The terminal may be used to invoke `bin/xcode`, but explicit plugin use means the agent should not bypass the plugin with direct Apple developer tools.
