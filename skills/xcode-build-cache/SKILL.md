---
name: xcode-build-cache
description: Run local Xcode CLI builds and tests through the plugin shared-cache xcodebuild wrapper with compact v0.3 JSON, dry-run parity, focused tests, and explicit trusted-fast controls.
---

# Xcode Build Cache

Use this skill when Codex needs to build, test, or validate an Xcode project/workspace from the command line. This is the default path for builds and tests unless the user specifically needs the open Xcode IDE window.

## Rules

- Prefer `bin/xcode build` for normal build/test validation.
- Keep the old `xcode-cli-shared-cache-build` skill untouched; this plugin carries the runner forward locally.
- Use `--dry-run --json` first when planning a command or checking parity.
- Keep `trusted-fast` explicit. It requires `--trusted-fast --trust-reason`.
- Write large logs to files and report paths, not full logs.

## Commands

Dry run:

```bash
bin/xcode build --workspace App.xcworkspace --scheme App --destination 'platform=iOS Simulator,id=<UDID>' --action build --dry-run --json
```

Focused test:

```bash
bin/xcode build --workspace App.xcworkspace --scheme App --destination 'platform=iOS Simulator,id=<UDID>' --action test --only-testing AppTests/TestCase/testExample --json
```

Build-for-testing then test-without-building:

```bash
bin/xcode build --workspace App.xcworkspace --scheme App --destination 'platform=iOS Simulator,id=<UDID>' --action build-for-testing --json
bin/xcode build --workspace App.xcworkspace --scheme App --destination 'platform=iOS Simulator,id=<UDID>' --action test-without-building --auto-xctestrun --json
```

Trusted-fast dry run:

```bash
bin/xcode build --workspace App.xcworkspace --scheme App --destination 'platform=iOS Simulator,id=<UDID>' --action build --optimization-profile trusted-fast --trusted-fast --trust-reason "local reviewed repo" --dry-run --json
```

## Output Contract

Every command reachable through `bin/xcode` returns the v0.3 envelope with `schema_version`, `ok`, `status`, `error_type`, `command_name`, `summary`, `artifacts`, `warnings`, `errors`, and `next_actions`.
