# Architecture

![Xcoder icon](images/app-icon.png)

Xcoder keeps Python as the public contract owner. Swift is used in two narrow places: an optional native helper for macOS/Xcode state where Python and JXA are weaker, and a bundled MCP server that exposes callable tools while delegating all real work to `bin/xcode`.

Explicit plugin invocation is GUI-first: when the user mentions `@xcode`, the agent should inspect and control Xcode.app through `bin/xcode native ...` and `bin/xcode ide ...` before considering plugin-routed CLI fallback.

## Command Flow

```mermaid
flowchart LR
    User["Codex / user request"] --> Skill["Xcoder skill docs"]
    Skill --> MCP["Codex MCP tools\nmcp__xcode__*"]
    MCP --> Server["bin/xcode-mcp-server\nSwift MCP stdio"]
    Server --> CLI["bin/xcode"]
    Skill --> CLI
    CLI --> Dispatcher["scripts/xcode.py"]

    Dispatcher --> Native["native\nSwift helper adapter"]
    Dispatcher --> IDE["ide\nosascript / JXA"]
    Dispatcher --> Build["build\nxcodebuild + shared cache fallback"]
    Dispatcher --> Context["context\nread-only project guidance"]
    Dispatcher --> Sim["simulator\nxcrun simctl"]
    Dispatcher --> Results["results\nxcresulttool"]
    Dispatcher --> Warnings["warnings\nlog parser"]
    Dispatcher --> Doctor["doctor\ntoolchain checks"]
    Dispatcher --> Workflow["workflow\nrun-app orchestration"]
    Dispatcher --> MCPDev["mcp\nbuild/doctor/list-tools"]
    Native --> Helper["bin/xcode-native-helper"]
    Helper --> AppKit["Foundation + AppKit"]
    Helper --> AX["ApplicationServices AX\nread-only"]
```

## JSON Envelope

All public commands return one shape.

```mermaid
flowchart TD
    Command["bin/xcode command"] --> Success{"succeeded?"}
    Success -->|yes| OK["ok: true\nstatus: success\nerror_type: null"]
    Success -->|no| Fail["ok: false\nstatus: failure\nerror_type: typed failure"]
    OK --> Envelope["schema_version\ncommand_name\nsummary\nartifacts\nwarnings\nerrors\nnext_actions"]
    Fail --> Envelope
```

This gives Codex predictable control flow. It can inspect `ok`, `error_type`, `artifacts`, and `next_actions` without scraping prose.

## Native Helper Boundary

```mermaid
flowchart TB
    Native["Swift native helper"] --> Allowed["Allowed"]
    Native --> Forbidden["Forbidden in v0.3"]

    Allowed --> A1["Accessibility trust status/request"]
    Allowed --> A2["Xcode running/frontmost/PID"]
    Allowed --> A3["Installed Xcode app discovery"]
    Allowed --> A4["Activate Xcode best-effort"]
    Allowed --> A5["Open .xcodeproj/.xcworkspace"]
    Allowed --> A6["Read-only top-level AX windows/sheets"]

    Forbidden --> F1["No AXPress"]
    Forbidden --> F2["No keyboard or mouse synthesis"]
    Forbidden --> F3["No scheme/destination selection"]
    Forbidden --> F4["No xcodebuild/simctl/xcresulttool wrappers"]
    Forbidden --> F5["No live build parsing"]
```

The helper emits `xcode-native-helper.v0.1`. The Python adapter normalizes that into the plugin envelope `xcode-plugin.v0.3`.

## MCP Server Boundary

`native/XcodeMCPServer` uses `modelcontextprotocol/swift-sdk` pinned through `Package.resolved`. It is built as a macOS 14+ executable and shipped as `bin/xcode-mcp-server`; runtime startup goes through `bin/xcode-mcp`, which checks the host macOS version before executing the Swift binary. It exposes exactly the first typed Xcode tools:

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

The server is intentionally thin. It validates typed arguments, rejects free-form execution keys such as `command`, `shell`, `args`, `script`, and `raw`, runs `bin/xcode` through `Process` direct argv, enforces MCP-side timeouts, and returns the existing `xcode-plugin.v0.3` envelope as JSON text. It must not call Apple developer tools directly.

Minimum OS policy:

```text
minimum macOS for Swift native binaries: 14.0
doctor check: host-macos-minimum
MCP self-checks: mcp-server-minimum-macos, mcp-server-host-macos-supported
```

## Artifact Policy

```mermaid
flowchart LR
    Build["Build/Test/Simulator/Results command"] --> Dir[".codex/xcode/artifacts/<timestamp-command-id>/"]
    Dir --> Command["command.json"]
    Dir --> Envelope["envelope.json"]
    Dir --> Stdout["stdout.log"]
    Dir --> Stderr["stderr.log"]
    Dir --> Parsed["warnings.json / errors.json"]
    Dir --> Bundle["result.xcresult/ path only"]
```

Raw logs and result bundles are local artifacts. Chat responses should reference paths, not paste large logs.

## Cache Safety

`trusted-fast` is explicit because it can skip package plugin and macro validation. It requires:

```bash
--trusted-fast --trust-reason "..."
```

The build cache identity includes the trusted-fast state, Xcode version, scheme, configuration, and project path hash. A cache metadata mismatch fails instead of reusing silently.
