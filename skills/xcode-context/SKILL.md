---
name: xcode-context
description: Inspect read-only Xcode project, scheme, and testability context before choosing build, test, simulator, or IDE workflows.
---

# Xcode Context

Use this skill before choosing a build/test workflow when scheme testability or project shape is unknown.

## Commands

```bash
bin/xcode context --path /path/to/App.xcodeproj --scheme 'App (Debug)' --json
```

## Rules

- This command is read-only.
- If `scheme_testable` is false, prefer build or build-for-testing diagnosis over `test`.
- Use simulator resolve before name-based destinations.

## Output Contract

The summary reports project type, scheme, scheme path, scheme visibility, `scheme_testable`, `testable_reference_count`, and next-action guidance.
