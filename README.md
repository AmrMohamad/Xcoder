# Xcoder

![Xcoder local Xcode workflow diagram](docs/images/xcoder-hero.png)

Xcoder is a GUI-first Codex plugin for Xcode workflows. When users explicitly mention `@xcode`, Codex should inspect and control Xcode.app first through callable MCP tools or `bin/xcode native ...` and `bin/xcode ide ...`, then use plugin-routed CLI support only when GUI control cannot answer the task or the user explicitly asks for headless validation.

It does not depend on XcodeBuildMCP. The bundled Swift MCP server is a thin façade over `bin/xcode`; `bin/xcode` and the Python scripts remain the source of truth. The plugin uses Apple tools only behind that plugin boundary: `xcodebuild`, `xcrun simctl`, `xcrun xcresulttool`, `osascript`/JXA, Xcode scripting, and a small optional Swift helper for native app state and read-only Accessibility inspection.

## Requirements

- macOS 14.0 or newer for the bundled Swift native helper and Swift MCP server.
- Xcode command line tools selected through `xcode-select`.
- Codex restart after installing or refreshing the plugin so `.mcp.json` is reloaded.

`bin/xcode-mcp` checks the host macOS version before launching `bin/xcode-mcp-server`. On older macOS it exits with a clear message instead of letting the Swift binary fail opaquely.

## Install

Install from the repository marketplace:

```bash
codex plugin marketplace add AmrMohamad/Xcoder --ref main --sparse .agents/plugins
codex plugin marketplace upgrade xcoder
```

Then open the Codex plugin directory, choose the Xcoder marketplace, and install the `xcode` plugin. In the CLI, open Codex and run `/plugins`.

For local development, clone the repo anywhere:

```bash
git clone git@github.com:AmrMohamad/Xcoder.git
cd Xcoder
chmod +x bin/xcode
bin/xcode --version
bin/xcode doctor --json
```

For an unpacked local checkout, use a marketplace entry with a `./`-prefixed path relative to that marketplace root:

```json
{
  "name": "xcode",
  "source": {
    "source": "local",
    "path": "./"
  },
  "policy": {
    "installation": "AVAILABLE",
    "authentication": "NONE"
  },
  "category": "Developer Tools"
}
```

This follows OpenAI's Codex plugin marketplace format: the plugin manifest lives at `.codex-plugin/plugin.json`, and local `source.path` values are relative to the marketplace root. See [Installation](docs/installation.md) for development, validation, packaging, and optional Swift helper rebuild steps.

## First-Use MCP Bootstrap

On first use, or whenever Codex does not show `mcp__xcode__*` tools, Codex must bootstrap the bundled Swift MCP server before using raw Xcode terminal workflows:

```bash
bin/xcode mcp bootstrap --json
```

Then quit and reopen Codex, and start a new thread so MCP tools are loaded from the refreshed process state. If `bin/xcode-mcp --list-tools --json` works but `mcp__xcode__*` is still missing, check `codex mcp list` and the local marketplace entry that points to the installed plugin cache. If bootstrap still fails after local repair, report the failure at [AmrMohamad/Xcoder issues](https://github.com/AmrMohamad/Xcoder/issues) with compact redacted diagnostics. See [First-Use MCP Bootstrap](docs/first-use-mcp.md).

## Quick Use

```bash
bin/xcode --help
bin/xcode --version --json
bin/xcode doctor --json
bin/xcode native app xcode-state --json
bin/xcode native ax xcode-windows --json
swift build -c release --package-path native/XcodeMCPServer
cp native/XcodeMCPServer/.build/release/xcode-mcp-server bin/xcode-mcp-server
bin/xcode-mcp-server --doctor --json
bin/xcode-mcp-server --list-tools --json
bin/xcode ide status --json
bin/xcode ide preflight --workspace-path /path/to/App.xcodeproj --scheme App --destination-id <UDID> --json
bin/xcode ide list-workspaces --json
bin/xcode ide workspace-info --workspace-path /path/to/App.xcodeproj --json
bin/xcode ide scheme-action --workspace-path /path/to/App.xcodeproj --action build --timeout-seconds 300 --json
bin/xcode workflow run-app --project-path App.xcodeproj --scheme App --destination-id <UDID> --json
bin/xcode context --path App.xcodeproj --scheme App --json
bin/xcode simulator resolve --name "iPhone SE (3rd generation)" --runtime "iOS 18.5" --json
bin/xcode build --project App.xcodeproj --scheme App --destination 'platform=iOS Simulator,id=<UDID>' --action build --dry-run --json
```

The terminal is still the transport for `bin/xcode`, but explicit plugin invocation should not bypass Xcoder with bare `xcodebuild`, `xcrun simctl`, `simctl`, `xcresulttool`, `osascript`, `open -a Xcode`, or the old `xcode-cli-shared-cache-build` skill.

Package a clean plugin zip:

```bash
bin/xcode package zip --output /tmp/xcode-plugin-0.4.0.zip --json
bin/xcode package audit --zip /tmp/xcode-plugin-0.4.0.zip --json
```

For v0.4.0 packages:

```bash
bin/xcode package zip --output /tmp/xcode-plugin-0.4.0.zip --json
bin/xcode package audit --zip /tmp/xcode-plugin-0.4.0.zip --json
```

## What It Provides

- `xcode-build-cache`: plugin-routed CLI fallback/support for shared DerivedData and SwiftPM cache builds.
- `xcode-context`: read-only project, scheme, destination, and testability guidance.
- `xcode-simulator`: `simctl` list, resolve, prepare, boot, install, launch, screenshot, terminate, and shutdown flows.
- `xcode-results`: normalized `xcresulttool` summaries.
- `xcode-warning-audit`: xcodebuild warning and error summaries.
- `xcode-doctor`: local Xcode/toolchain/plugin checks.
- `xcode-ide-automation`: AppleScript/JXA control of the open Xcode app for IDE-specific actions.
- `xcode-native-helper`: optional Swift helper for Xcode process state, installed Xcode discovery, permission status, workspace opening, and read-only AX window/modal inspection.
- `xcode-mcp-server`: bundled Swift MCP stdio server exposing typed tools that call `bin/xcode`.
- `xcode-workflows`: GUI-first guidance for choosing IDE, native helper, simulator, results, warnings, doctor, or CLI fallback flows.

## Contract

Every command reachable through `bin/xcode` emits the same JSON envelope:

```json
{
  "schema_version": "xcode-plugin.v0.3",
  "ok": true,
  "status": "success",
  "error_type": null,
  "command_name": "doctor",
  "summary": {},
  "artifacts": {},
  "warnings": [],
  "errors": [],
  "next_actions": []
}
```

Large logs, screenshots, diagnostics, and `.xcresult` data stay on disk. Responses return local artifact paths instead of dumping raw build output into chat.

## Documentation

- [Installation](docs/installation.md)
- [First-Use MCP Bootstrap](docs/first-use-mcp.md)
- [Architecture](docs/architecture.md)
- [Workflows](docs/workflows.md)
- [Validation](docs/validation.md)

## Important Boundaries

- Explicit `@xcode` invocation means GUI-first: inspect and control Xcode.app before using CLI validation.
- `xcodebuild` is a plugin-routed fallback/support path through `bin/xcode build`, not the default response to an explicit plugin mention.
- Simulator commands prefer UDIDs. Name aliases must resolve uniquely first.
- `trusted-fast` requires an explicit trust reason because skipping package plugin and macro validation is security-sensitive.
- The Swift helper is optional and diagnostic-first. It must not run builds, run simulators, parse `.xcresult`, click UI, select schemes, or select destinations.
- The Swift MCP server is callable-tool glue only. It must call `bin/xcode` with direct argv and must not call `xcodebuild`, `simctl`, `xcresulttool`, `osascript`, or `open` directly.
- Both Swift binaries are built for macOS 14.0 or newer. Local ad hoc signatures and `spctl` rejection are acceptable for development; notarization is out of scope.
- Apple `mcpbridge` is optional.
