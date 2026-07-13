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
mcp__xcode__xcode_native_permissions_status
mcp__xcode__xcode_native_helper_identity
mcp__xcode__xcode_native_helper_bundle
mcp__xcode__xcode_native_permissions_request
mcp__xcode__xcode_native_windows
mcp__xcode__xcode_ide_status
mcp__xcode__xcode_ide_workspace_info
mcp__xcode__xcode_ide_list_schemes
mcp__xcode__xcode_ide_list_destinations
mcp__xcode__xcode_ide_menu_catalog
mcp__xcode__xcode_ide_menu_perform
mcp__xcode__xcode_ide_preflight
mcp__xcode__xcode_ide_build
mcp__xcode__xcode_ide_test
mcp__xcode__xcode_ide_run
mcp__xcode__xcode_run_app
mcp__xcode__xcode_archive
mcp__xcode__xcode_export_archive
mcp__xcode__xcode_upload_archive
mcp__xcode__xcode_distribute
mcp__xcode__xcode_simulator_resolve
mcp__xcode__xcode_results_summary
mcp__xcode__xcode_warnings_summary
mcp__xcode__xcode_help
```

These tools are wrappers over `bin/xcode`. They are the primary discovery surface, not a separate Xcode implementation.

Use `xcode_help` when Codex needs canonical local guidance before choosing a route. Supported topics are `first-time`, `ide-vs-cli`, `fail-recovery`, `scheme-not-testable`, `destination-ambiguous`, `build-json`, `distribution`, and `package-release`.

Use `xcode_ide_menu_catalog` to inspect the typed Xcode menu map. Use `xcode_ide_menu_perform` only with an `action_id` returned by that catalog. The menu performer never accepts raw menu paths or arbitrary Accessibility selectors. Destructive menu actions are rejected unless `allow_destructive` is true; external-effect and dynamic project-specific menu entries are cataloged but intentionally blocked in this pass. Prefer existing typed tools such as `xcode_ide_build`, `xcode_ide_test`, `xcode_ide_run`, `xcode_ide_list_schemes`, and `xcode_ide_list_destinations` over menu pressing when those routes exist.

For MCP process diagnostics, use `bin/xcode mcp health --json`. Health is intentionally CLI-only; when a stdio server is running it reads the server's lightweight published state file and reports that server's pid, uptime, RSS when available, active child pid, queued tool count, and running state. If no fresh running-server state exists, the command reports a one-shot `self_probe` payload instead of inventing active-child state.

`xcode_ide_run` is an attached IDE run action, so its MCP poll timeout is capped below Codex's protocol call limit. If a real app run needs more time than that, use the plugin-routed `bin/xcode workflow run-app --json` path from a shell command instead of retrying the MCP run call with a larger timeout.

Long-running MCP wrappers such as `xcode_ide_build`, `xcode_ide_test`, and `xcode_run_app` also use a protocol-safe MCP subprocess budget. When the underlying Xcode operation is still running near the MCP call limit, Xcoder returns an `ok:false` `command_timeout` envelope with recovery guidance instead of letting Codex surface a transport timeout. Use the equivalent `bin/xcode ... --json` command when a full build, test, or run is expected to exceed the MCP call budget.

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
bin/xcode ide menu-catalog --json
bin/xcode ide menu-perform --action-id view.navigator.project --json
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

`bin/xcode build --json` emits one clean `xcode-plugin.v0.3` envelope on stdout. Raw build stdout/stderr are written to artifact logs referenced from the envelope.

## Distribution

Distribution is GUI-only. `xcode_archive` starts Xcode's Product > Archive menu action after native window/modal preflight. Organizer steps are handled by typed GUI tools: `xcode_organizer_open`, `xcode_organizer_inspect`, and `xcode_organizer_press`. The distribution-method sheet now has a safer phase-specific route through `xcode_organizer_distribution_inspect`, `xcode_organizer_distribution_select_method`, and `xcode_organizer_distribution_confirm`. Downstream route screens are inspected with `xcode_organizer_distribution_step_inspect`; `xcode_organizer_distribution_probe_method` can enter one route, inspect its next screen, and cancel out by default before pressing any final upload/export action. The nested Custom route sheet is handled through `xcode_organizer_distribution_select_custom_route` and `xcode_organizer_distribution_probe_custom_route`. Command-line archive/export/upload is blocked; `xcode_export_archive`, `xcode_upload_archive`, and `xcode_distribute` remain guarded until the full form-specific Organizer workflow is implemented.

```bash
bin/xcode distribution archive \
  --workspace-path App.xcworkspace \
  --scheme App \
  --dry-run \
  --json

bin/xcode ide organizer-open --json
bin/xcode ide organizer-inspect --window-title-contains Organizer --json
bin/xcode ide organizer-distribution-inspect --json
bin/xcode ide organizer-distribution-select --method 'App Store Connect' --json
bin/xcode ide organizer-distribution-confirm --expected-method 'App Store Connect' --json
```

`xcode_export_archive`, `xcode_upload_archive`, and `xcode_distribute` return `xcode_distribution_requires_gui` instead of running command-line export/upload.

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

Use native helper commands for fast app-state observation and only the documented typed mutation routes:

```bash
bin/xcode native helper version --json
bin/xcode native permissions status --json
bin/xcode native app xcode-state --json
bin/xcode native app installed-xcodes --json
bin/xcode native ax xcode-windows --json
```

`native ax xcode-windows` needs Accessibility permission. When `bin/XcodeNativeHelper.app` exists, the adapter launches that bundle through LaunchServices so macOS evaluates the trusted helper app instead of the parent Codex process. If permission is still missing, the command should fail with `permission_denied`, not mutate anything.
