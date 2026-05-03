---
name: xcode-results
description: Summarize .xcresult bundles using xcresulttool get test-results, build-results, log, and content-availability.
---

# Xcode Results

Use this skill when Codex needs compact result summaries from `.xcresult` bundles produced by Xcode or `xcodebuild`.

In explicit `@xcode` GUI-first mode, use this skill after an IDE or plugin-routed build/test produced an `.xcresult`. Do not use raw `xcresulttool` directly; use `bin/xcode results`.

## Rules

- Prefer structured `xcresulttool` summaries over raw log parsing.
- Use `test-summary` for pass/fail and failure inventory.
- Preserve raw `xcresulttool` output as an artifact path.
- Never paste `.xcresult` contents or raw nested result JSON into chat.
- Missing bundles return `xcresult_missing`; corrupt/unreadable bundles return `xcresult_corrupt`.

## Commands

```bash
bin/xcode results --path /path/to/Test.xcresult --kind test-summary --json
bin/xcode results --path /path/to/Test.xcresult --kind build-results --json
bin/xcode results --path /path/to/Test.xcresult --kind content-availability --json
bin/xcode results --path /path/to/Test.xcresult --kind log --log-type build --json
```

## Output Contract

`test-summary` returns normalized totals/failures and artifact paths for raw output.
