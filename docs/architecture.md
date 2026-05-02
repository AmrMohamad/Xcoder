# Architecture

![Xcoder icon](images/app-icon.png)

Xcoder keeps Python as the public contract owner. Swift is only an optional native helper for macOS/Xcode state where Python and JXA are weaker.

## Command Flow

```mermaid
flowchart LR
    User["Codex / user request"] --> Skill["Xcoder skill docs"]
    Skill --> CLI["bin/xcode"]
    CLI --> Dispatcher["scripts/xcode.py"]

    Dispatcher --> Build["build\nxcodebuild + shared cache"]
    Dispatcher --> Context["context\nread-only project guidance"]
    Dispatcher --> Sim["simulator\nxcrun simctl"]
    Dispatcher --> Results["results\nxcresulttool"]
    Dispatcher --> Warnings["warnings\nlog parser"]
    Dispatcher --> Doctor["doctor\ntoolchain checks"]
    Dispatcher --> IDE["ide\nosascript / JXA"]
    Dispatcher --> Native["native\nSwift helper adapter"]

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

