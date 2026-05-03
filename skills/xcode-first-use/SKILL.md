---
name: xcode-first-use
description: Bootstrap the bundled Swift MCP server the first time Xcoder is used, make it executable, validate the MCP tool namespace, and report unresolved setup failures.
---

# Xcode First Use

Use this skill when:

- Xcoder is installed or refreshed for the first time.
- Codex does not show `mcp__xcode__*` tools.
- `.mcp.json`, `bin/xcode-mcp`, or `bin/xcode-mcp-server` is missing or not executable.
- `bin/xcode doctor --json` reports an MCP server failure.
- The user asks to compile, build, make executable, fire up, or repair Xcoder MCP.

## Mandatory Agent Contract

Codex must bootstrap and validate the bundled MCP server before falling back to raw terminal Xcode workflows.

Codex must not use bare `xcodebuild`, `xcrun simctl`, `simctl`, `xcresulttool`, `osascript`, `open -a Xcode`, XcodeBuildMCP, or another Xcode MCP server to work around a broken Xcoder first-use setup.

If bootstrap fails after local repair, Codex must report the issue at:

```text
https://github.com/AmrMohamad/Xcoder/issues
```

If the runtime can create GitHub issues, open one. If it cannot authenticate or create issues, output a ready-to-submit issue body and the URL.

## Bootstrap

Run from the plugin root:

```bash
bin/xcode mcp bootstrap --json
```

That is the required one-action bootstrap. It validates plugin JSON, compiles Python command modules, verifies macOS/Xcode/Swift availability, resolves and builds the Swift MCP server, installs `bin/xcode-mcp-server`, marks public launchers executable, and runs MCP/plugin doctor checks.

Use the expanded sequence below only when debugging which step failed:

```bash
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 -m json.tool .mcp.json >/dev/null
python3 -m py_compile scripts/*.py

chmod +x bin/xcode bin/xcode-mcp
sw_vers -productVersion
xcode-select -p
swift --version

swift build -c release --package-path native/XcodeMCPServer
cp native/XcodeMCPServer/.build/release/xcode-mcp-server bin/xcode-mcp-server
chmod +x bin/xcode-mcp-server

bin/xcode-mcp --version --json
bin/xcode-mcp --doctor --json
bin/xcode-mcp --list-tools --json
bin/xcode doctor --json
```

Then restart Codex so `.mcp.json` is reloaded.

## Expected Tools

After restart, the Xcoder MCP namespace should expose:

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

## Repair Rules

- Missing or non-executable wrapper: run `chmod +x bin/xcode-mcp`.
- Missing or non-executable server binary: rebuild with SwiftPM, copy to `bin/xcode-mcp-server`, then run `chmod +x`.
- macOS below 14.0: stop and report unsupported host. Do not try to run the Swift server.
- SwiftPM dependency failure: run `swift package resolve --package-path native/XcodeMCPServer`, then rebuild.
- Tool list works but Codex cannot see `mcp__xcode__*`: run `codex mcp list` and verify an enabled `xcode` server points at the current installed `bin/xcode-mcp`.
- If a local marketplace entry still points at an older deleted cache version, update it to the current installed version.
- If plugin marketplace loading is unavailable, add a direct `[mcp_servers.xcode]` entry in `~/.codex/config.toml` pointing at the installed `bin/xcode-mcp`.
- After changing marketplace or MCP config, quit and reopen Codex and start a new thread. Existing threads keep their original tool registry.
- Doctor failure: fix required checks first; optional `mcpbridge` absence is not a blocker.

## Issue Body

For unresolved failures, include:

~~~markdown
## Xcoder MCP first-use failure

### Environment
- Xcoder version:
- macOS version:
- xcode-select path:
- Swift version:

### Files
- .mcp.json present:
- bin/xcode-mcp executable:
- bin/xcode-mcp-server executable:
- native/XcodeMCPServer/Package.resolved present:

### Commands Run
~~~text
python3 -m json.tool .codex-plugin/plugin.json
python3 -m json.tool .mcp.json
python3 -m py_compile scripts/*.py
swift build -c release --package-path native/XcodeMCPServer
bin/xcode-mcp --doctor --json
bin/xcode doctor --json
~~~

### Failure
- Failing command:
- Exit code:
- Compact redacted output:

### Notes
- No full build logs, secrets, screenshots, .xcresult bundles, or private source files are attached.
~~~
