# Workflows

Use this page to choose the right Xcoder path.

When a user explicitly mentions `@xcode`, `xcode@local`, any bundled `xcode-*` skill, or the `xcode` MCP namespace, use GUI-first routing. Prefer callable MCP tools when available, then `bin/xcode` plugin commands. Use `bin/xcode build ...` only as plugin-routed fallback/support after explaining why GUI control cannot satisfy the task, or when the user explicitly asks for CLI/headless validation.

If this is the first use of the plugin, or the `mcp__xcode__*` namespace is missing, run the one-action first-use MCP bootstrap before normal workflows:

```bash
bin/xcode mcp bootstrap --json
```

Then restart Codex. If that still fails after repair, report the problem at [AmrMohamad/Xcoder issues](https://github.com/AmrMohamad/Xcoder/issues) with compact redacted diagnostics.

## Callable MCP Tools

Expected tool names after Codex reload:

```text
mcp__xcode__xcode_doctor
mcp__xcode__xcode_native_state
mcp__xcode__xcode_native_windows
mcp__xcode__xcode_ide_preflight
mcp__xcode__xcode_ide_build
mcp__xcode__xcode_ide_run
mcp__xcode__xcode_run_app
mcp__xcode__xcode_simulator_resolve
mcp__xcode__xcode_results_summary
mcp__xcode__xcode_warnings_summary
```

These tools are wrappers over `bin/xcode`. They are the primary discovery surface, not a separate Xcode implementation.

## Read Project Context First

```bash
bin/xcode context \
  --path App.xcodeproj \
  --scheme App \
  --json
```

Use `context` before test decisions. If a scheme has no testable references, Xcoder should recommend build instead of test.

## GUI-First Flow

```bash
bin/xcode doctor --json
bin/xcode native app xcode-state --json
bin/xcode native ax xcode-windows --json
bin/xcode ide status --json
bin/xcode ide list-workspaces --json
bin/xcode ide workspace-info --workspace-path /path/to/App.xcodeproj --json
bin/xcode ide preflight --workspace-path /path/to/App.xcodeproj --scheme 'App (Debug)' --destination-id <UDID> --json
bin/xcode context --path /path/to/App.xcodeproj --scheme 'App (Debug)' --json
bin/xcode simulator resolve --name "iPhone SE (3rd generation)" --runtime "iOS 18.5" --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcodeproj --action build --scheme 'App (Debug)' --destination-id <UDID> --timeout-seconds 300 --json
bin/xcode workflow run-app --project-path /path/to/App.xcodeproj --scheme 'App (Debug)' --destination-id <UDID> --json
```

Do not bypass Xcoder with bare `xcodebuild`, `xcrun simctl`, `simctl`, `xcresulttool`, `osascript`, `open -a Xcode`, or `xcode-cli-shared-cache-build`.

## CLI Build Fallback

Use CLI build for explicit headless validation or after the GUI route is proven unavailable/insufficient:

```bash
bin/xcode build \
  --project App.xcodeproj \
  --scheme App \
  --destination 'platform=iOS Simulator,id=<UDID>' \
  --action build \
  --json
```

Use dry-run first when you want to inspect the generated command without creating DerivedData/cache folders:

```bash
bin/xcode build \
  --project App.xcodeproj \
  --scheme App \
  --destination 'platform=iOS Simulator,id=<UDID>' \
  --action build \
  --dry-run \
  --json
```

## Build For Testing / Test Without Building

```bash
bin/xcode build \
  --project App.xcodeproj \
  --scheme App \
  --destination 'platform=iOS Simulator,id=<UDID>' \
  --action build-for-testing \
  --json

bin/xcode build \
  --project App.xcodeproj \
  --scheme App \
  --destination 'platform=iOS Simulator,id=<UDID>' \
  --action test-without-building \
  --json
```

## Simulator

Resolve names to UDIDs first:

```bash
bin/xcode simulator resolve \
  --name "iPhone SE (3rd generation)" \
  --runtime "iOS 18.5" \
  --json
```

Then use the UDID:

```bash
bin/xcode simulator prepare --udid <UDID> --boot --wait-ready --json
bin/xcode simulator install --udid <UDID> --app /path/to/App.app --json
bin/xcode simulator launch --udid <UDID> --bundle-id com.example.App --json
bin/xcode simulator screenshot --udid <UDID> --json
```

Name aliases are convenience only. They must resolve uniquely first.

## Results

```bash
bin/xcode results summarize --path /path/to/result.xcresult --kind test-summary --json
bin/xcode results summarize --path /path/to/result.xcresult --kind build-results --json
```

Missing or corrupt bundles map to typed result errors instead of generic subprocess failure.

## Warning Audit

```bash
bin/xcode warnings summarize --log /path/to/xcodebuild.log --json
```

Warning summarization exits `0` even when warnings are found. It does not change the underlying build result.

## IDE Automation

Use IDE automation first when `@xcode` is explicitly mentioned:

```bash
bin/xcode ide status --json
bin/xcode ide list-workspaces --json
bin/xcode ide workspace-info --workspace-path /path/to/App.xcodeproj --json
bin/xcode ide preflight --workspace-path /path/to/App.xcodeproj --scheme App --destination-id <UDID> --json
bin/xcode ide set-scheme --workspace-path /path/to/App.xcodeproj --scheme App --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcodeproj --action test --scheme App --destination-id <UDID> --timeout-seconds 300 --json
```

If `--workspace-path` is supplied, matching is strict. Xcoder should not fall back to the active window if the requested workspace cannot be matched.

## Native State

Use native helper commands for fast, read-only app state:

```bash
bin/xcode native helper version --json
bin/xcode native permissions status --json
bin/xcode native app xcode-state --json
bin/xcode native app installed-xcodes --json
bin/xcode native ax xcode-windows --json
```

`native ax xcode-windows` needs Accessibility permission. If permission is missing, the command should fail with `permission_denied`, not mutate anything.
