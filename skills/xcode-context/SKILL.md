---
name: xcode-context
description: Inspect read-only Xcode project, scheme, and testability context before choosing build, test, simulator, or IDE workflows.
---

# Xcode Context

Use this skill before choosing a build/test workflow when scheme testability or project shape is unknown.

When `@xcode`, `xcode@local`, or another `xcode-*` skill is explicitly mentioned, context is only the read-only first step. After context, choose the GUI path (`bin/xcode native ...` then `bin/xcode ide ...`) unless the user explicitly asks for CLI/headless validation or the GUI path is unavailable.

## Commands

```bash
bin/xcode context --path /path/to/App.xcodeproj --scheme 'App (Debug)' --json
```

## Rules

- This command is read-only.
- If `scheme_testable` is false in GUI-first mode, report the scheme limitation and use IDE build or context diagnosis before considering CLI build-for-testing.
- Use simulator resolve before name-based destinations.

## Output Contract

The summary reports project type, scheme, scheme path, scheme visibility, `scheme_testable`, `testable_reference_count`, and next-action guidance.
