# First-Use MCP Bootstrap

Use this runbook when Xcoder is installed for the first time, when Codex does not show the `mcp__xcode__*` tools, or when `bin/xcode doctor --json` reports an MCP server problem.

Codex must not bypass this bootstrap with raw `xcodebuild`, `xcrun simctl`, `osascript`, `open -a Xcode`, or another Xcode MCP server. The first usable path is the bundled Swift MCP server, which is a thin facade over `bin/xcode`.

## Requirements

- macOS 14.0 or newer.
- Xcode command line tools selected through `xcode-select`.
- SwiftPM available through the selected Xcode toolchain.
- Plugin root contains `.mcp.json`, `bin/xcode`, `bin/xcode-mcp`, and `native/XcodeMCPServer/Package.swift`.

## Bootstrap Commands

Run from the plugin root:

```bash
bin/xcode mcp bootstrap --json
```

That one command validates plugin JSON, compiles Python command modules, checks macOS/Xcode/Swift availability, resolves and builds the Swift MCP server, installs `bin/xcode-mcp-server`, makes public launchers executable, and runs the MCP and plugin doctor checks.

The same action is also available directly through the MCP launcher:

```bash
bin/xcode-mcp --bootstrap --json
```

The expanded manual sequence below is kept for debugging only:

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

Expected MCP tools:

```text
xcode_doctor
xcode_native_state
xcode_native_windows
xcode_ide_preflight
xcode_ide_build
xcode_ide_run
xcode_run_app
xcode_simulator_resolve
xcode_results_summary
xcode_warnings_summary
```

## Fire Up The Stdio Server

After the build succeeds, the configured entry point is:

```bash
bin/xcode-mcp --stdio
```

Codex starts this process through `.mcp.json`:

```json
{
  "mcpServers": {
    "xcode": {
      "command": "./bin/xcode-mcp",
      "args": ["--stdio"]
    }
  }
}
```

Do not point `.mcp.json` at `swift run`. The server must be built once, copied to `bin/xcode-mcp-server`, made executable, and launched through `bin/xcode-mcp`.

For a local smoke test without Codex UI, run:

```bash
python3 - <<'PY'
import json
import subprocess
import sys

process = subprocess.Popen(
    ["bin/xcode-mcp", "--stdio"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

requests = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "xcoder-smoke", "version": "0.1"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]

for item in requests:
    process.stdin.write(json.dumps(item) + "\n")
process.stdin.flush()
process.stdin.close()

tools = None
for line in process.stdout:
    data = json.loads(line)
    if data.get("id") == 2:
        tools = data.get("result", {}).get("tools", [])
        break

process.terminate()
process.wait(timeout=5)

names = [tool.get("name") for tool in tools or []]
print("tool_count", len(names))
print("\n".join(names))
if len(names) != 10:
    sys.exit(1)
PY
```

## Repair Rules

- If `bin/xcode-mcp` is not executable, run `chmod +x bin/xcode-mcp`.
- If `bin/xcode-mcp-server` is missing or not executable, rebuild it with SwiftPM and copy it to `bin/`.
- If `bin/xcode-mcp` reports macOS is too old, stop. The Swift MCP server requires macOS 14.0 or newer.
- If SwiftPM dependency resolution fails, retry `swift package resolve --package-path native/XcodeMCPServer`, then rebuild.
- If `bin/xcode-mcp --list-tools --json` works but Codex still does not show `mcp__xcode__*`, run `codex mcp list` and verify an enabled `xcode` server points at the current installed `bin/xcode-mcp`.
- If the local marketplace still points at an older deleted cache version, update the local marketplace entry to the current installed version, then quit and reopen Codex.
- If plugin marketplace loading is unavailable in the current runtime, add a direct Codex MCP entry that points at the installed wrapper:

```toml
[mcp_servers.xcode]
command = "/absolute/path/to/xcode/0.4.0/bin/xcode-mcp"
args = ["--stdio"]
enabled = true
```

- After any marketplace or `config.toml` change, quit and reopen Codex, then start a new thread. Existing threads keep the tool registry they were created with.
- If `bin/xcode doctor --json` fails, fix required checks before running Xcode workflows.

## Required Issue Report

If the first-use bootstrap still fails after the repair rules above, Codex must report the problem at:

```text
https://github.com/AmrMohamad/Xcoder/issues
```

When GitHub issue creation is available, open an issue. When the runtime cannot authenticate or create issues, produce a ready-to-submit issue body and give the user the URL above.

The issue must include:

- Xcoder version from `bin/xcode --version --json`.
- macOS version from `sw_vers -productVersion`.
- Xcode path from `xcode-select -p`.
- Swift version from `swift --version`.
- Whether `.mcp.json`, `bin/xcode-mcp`, and `bin/xcode-mcp-server` exist.
- Redacted output from `bin/xcode-mcp --doctor --json`.
- Redacted output from `bin/xcode doctor --json`.
- The exact failing command and exit code.

Do not include secrets, signing identities, full build logs, `.xcresult` bundles, screenshots, simulator diagnostics, or private source files. Include compact summaries and artifact paths only.
