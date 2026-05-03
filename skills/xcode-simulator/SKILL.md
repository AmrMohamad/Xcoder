---
name: xcode-simulator
description: Manage Apple simulators with xcrun simctl for list, resolve, boot, prepare, open, install, launch, terminate, screenshot, and shutdown workflows.
---

# Xcode Simulator

Use this skill when Codex needs simulator lifecycle control through Apple’s `xcrun simctl`.

In explicit `@xcode` GUI-first mode, simulator commands are support for Xcode.app automation: resolve/boot/open the simulator, then drive build/test/run/debug through `bin/xcode ide ...` when possible.

## Rules

- Prefer UDIDs for lifecycle commands.
- Resolve name/runtime first; fail if no match or more than one match.
- Do not run bare `xcrun simctl` or `simctl`; use `bin/xcode simulator`.
- Runtime matching accepts aliases such as `iOS 18.5`, `iOS-18-5`, and `com.apple.CoreSimulator.SimRuntime.iOS-18-5`.
- Do not silently pass duplicate simulator names to `simctl`.
- Screenshots default to plugin artifact directories. Arbitrary output paths require `--allow-any-output-path`.
- Keep simulator output compact JSON; return screenshot artifacts by path.

## Commands

```bash
bin/xcode simulator list --devices-only --json
bin/xcode simulator resolve --name "iPhone SE (3rd generation)" --runtime "iOS 18.5" --json
bin/xcode simulator prepare --udid <UDID> --boot --wait-ready --json
bin/xcode simulator open --json
bin/xcode simulator install --udid <UDID> --app /path/to/App.app --json
bin/xcode simulator launch --udid <UDID> --bundle-id com.example.App --json
bin/xcode simulator terminate --udid <UDID> --bundle-id com.example.App --json
bin/xcode simulator screenshot --udid <UDID> --json
```

Fixture duplicate-name validation:

```bash
bin/xcode simulator resolve --fixture tests/fixtures/simctl-list-duplicate-names.json --name "iPhone SE (3rd generation)" --json
```

## Output Contract

Every command reachable through `bin/xcode` returns the v0.3 envelope.
