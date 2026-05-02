---
name: xcode-workflows
description: Choose the right Xcode plugin flow for CLI builds, IDE-controlled tests, simulator work, result summaries, warnings, context, and diagnostics.
---

# Xcode Workflows

Use this skill to choose between the plugin’s build, context, IDE, simulator, results, warning, and doctor workflows.

## Decision Table

- Unknown project/scheme state: use `bin/xcode context`.
- Normal build/test validation: use `bin/xcode build`.
- Open Xcode window state, scheme selection, destination selection, or IDE test/run/debug: use `bin/xcode ide`.
- Native Xcode process state, Accessibility readiness, installed Xcode apps, or blocking window inspection: use `bin/xcode native`.
- Simulator inventory, resolve, boot, install, launch, terminate, or screenshot: use `bin/xcode simulator`.
- `.xcresult` summaries: use `bin/xcode results`.
- xcodebuild log warnings/errors: use `bin/xcode warnings summarize`.
- Toolchain, permissions, SDEF, or optional `mcpbridge` diagnosis: use `bin/xcode doctor`.

## Standard Flow

```bash
bin/xcode doctor --json
bin/xcode native app xcode-state --json
bin/xcode context --path /path/to/App.xcodeproj --scheme 'App (Debug)' --json
bin/xcode simulator resolve --name "iPhone SE (3rd generation)" --runtime "iOS 18.5" --json
bin/xcode build --project /path/to/App.xcodeproj --scheme 'App (Debug)' --destination 'platform=iOS Simulator,id=<UDID>' --action build --dry-run --json
bin/xcode build --project /path/to/App.xcodeproj --scheme 'App (Debug)' --destination 'platform=iOS Simulator,id=<UDID>' --action build --json
bin/xcode warnings summarize --log .codex/xcode/artifacts/<run>/stderr.log --json
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
