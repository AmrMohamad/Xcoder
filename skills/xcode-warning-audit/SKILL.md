---
name: xcode-warning-audit
description: Summarize xcodebuild warning and error logs without changing the underlying build or test result.
---

# Xcode Warning Audit

Use this skill after a build/test produces a log and Codex needs a compact warning/error inventory.

## Commands

```bash
bin/xcode warnings summarize --log .codex/xcode/artifacts/<run>/stderr.log --json
bin/xcode warnings baseline --log .codex/xcode/artifacts/<run>/stderr.log --output .codex/xcode/warnings-baseline.json --json
bin/xcode warnings diff --log .codex/xcode/artifacts/<run>/stderr.log --baseline .codex/xcode/warnings-baseline.json --json
```

## Rules

- `summarize` exits `0` even when warnings are found.
- Warning parsing never changes the build/test success result.
- Large logs stay on disk; the command returns counts, groups, and artifact paths.
