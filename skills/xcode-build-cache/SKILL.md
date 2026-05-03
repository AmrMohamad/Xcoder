---
name: xcode-build-cache
description: Use plugin-routed CLI build/test support only when GUI-first Xcode.app automation is not the requested path, not possible, or explicitly bypassed by the user.
---

# Xcode Build Cache

Use this skill when Codex needs plugin-routed command-line build/test support after the GUI path has been considered.

When the user explicitly mentions `@xcode`, `xcode@local`, or asks this plugin to control Xcode, GUI-first mode is active. In GUI-first mode, do not start with `bin/xcode build`. Start with `bin/xcode native ...` and `bin/xcode ide ...`, then use `bin/xcode build` only when:

- the user explicitly asks for CLI/headless validation,
- Xcode.app GUI control is unavailable or blocked,
- the IDE action cannot produce the needed artifact,
- a deterministic fallback is needed after reporting the GUI limitation.

## Rules

- Never run bare `xcodebuild`; this skill owns build/test CLI work through `bin/xcode build`.
- In explicit plugin invocations, prefer `bin/xcode ide scheme-action` for build/test/run/debug before CLI fallback.
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
