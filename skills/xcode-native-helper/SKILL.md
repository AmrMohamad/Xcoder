---
name: xcode-native-helper
description: Use the optional Swift native helper for fast Xcode process state, Accessibility permission status, workspace opening, AX inspection, and guarded typed menu/button/control mutation.
---

# Xcode Native Helper

Use this skill when Xcode IDE automation needs native macOS preflight signal before AppleScript/JXA actions, or when the user asks whether Xcode is running/frontmost, which Xcode app is active, or whether Accessibility is ready.

When `@xcode`, `xcode@local`, or another `xcode-*` skill is explicitly mentioned, run native preflight before GUI mutation whenever possible. This is how the plugin proves it is working with Xcode.app instead of bypassing the GUI.

## Commands

```bash
bin/xcode native helper version --json
bin/xcode native helper identity --json
bin/xcode native helper bundle --json
bin/xcode native helper sign --json
bin/xcode native permissions status --json
bin/xcode native permissions request --json
bin/xcode native app xcode-state --json
bin/xcode native app installed-xcodes --json
bin/xcode native app activate-xcode --json
bin/xcode native app open-workspace --path /path/to/App.xcodeproj --json
bin/xcode native ax xcode-windows --json
bin/xcode native ax xcode-windows --include-paths --json
```

MCP exposes the same permission boundary through `xcode_native_permissions_status` and `xcode_native_permissions_request`.

## Rules

- `permissions status` must not trigger a macOS prompt.
- `permissions request` may trigger the macOS Accessibility prompt and should only be used when explicitly requested.
- Missing Accessibility permission must not block normal build/test/run paths unless native preflight is explicitly required.
- If Accessibility shows enabled in System Settings but `permissions status` still returns false, inspect `helper identity`; ad-hoc/cdhash-only or non-bundled helpers should be repaired with `helper bundle` before requesting permission again.
- AX and permission commands should run through `XcodeNativeHelper.app` via LaunchServices when the bundle exists. Direct child-process execution can inherit Codex's responsible process and return false even when the helper app is trusted.
- `app xcode-state` does not require Accessibility permission.
- `app activate-xcode` is best-effort. If macOS refuses foreground activation, it must return `xcode_activation_failed` with exit `24`.
- `ax xcode-windows` is read-only and may exit `4` when Accessibility is not trusted.
- Home paths and AX document paths are redacted by default. Use `--include-paths` only when the user explicitly needs full local paths.
- Do not use the helper for build/test/simulator/result logic.
- Do not use AX to press buttons, change schemes, change destinations, or parse live build progress in v0.3.

## Build

```bash
cd native/XcodeNativeHelper
swift build -c release
install -m 755 .build/release/xcode-native-helper ../../bin/xcode-native-helper
../../bin/xcode native helper bundle --json
```

## Output Contract

The Swift binary emits the small `xcode-native-helper.v0.1` JSON shape. The public `bin/xcode native ...` path normalizes that into the plugin `xcode-plugin.v0.3` envelope.
