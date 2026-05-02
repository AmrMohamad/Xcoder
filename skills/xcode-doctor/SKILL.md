---
name: xcode-doctor
description: Validate local Xcode, xcodebuild, simctl, xcresulttool, JXA, Xcode scripting dictionary, Accessibility readiness, optional native helper status, and optional mcpbridge status.
---

# Xcode Doctor

Use this skill before relying on local Xcode automation or when a build/simulator/result workflow fails for environmental reasons.

## Checks

- Selected Xcode developer directory from `xcode-select -p`.
- `xcodebuild`, `simctl`, `xcresulttool`, `devicectl`, and optional `mcpbridge` discovery.
- JXA smoke test through `osascript`.
- Accessibility UI scripting readiness.
- Optional Swift native helper source, binary, schema, Accessibility status, and Xcode app state.
- Selected Xcode SDEF contracts for workspace documents, schemes, run destinations, scheme action results, and build/test/run/debug commands.
- Required `xcodebuild` flags for cache and package-control behavior.
- Simulator lifecycle commands.
- `xcresulttool get` result-summary commands.

## Command

```bash
bin/xcode doctor --json
bin/xcode doctor --strict --json
```

## Rule

`mcpbridge` is optional. If it is present but crashes on this macOS/Xcode combination, report it as `optional_unavailable` and continue with local scripts. Never mutate `xcode-select`.

The native helper is optional for build/simulator/results flows. Doctor may report it as unavailable, but must not fail unless `--strict` later makes native IDE readiness mandatory. Doctor must never run `bin/xcode native permissions request`.
