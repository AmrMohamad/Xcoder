# ADR 0003: Native Accessibility mutation boundary

## Status

Accepted for Xcoder 0.6.

## Problem

Documentation described the native helper as read-only while production code performs typed Accessibility presses for Xcode menu and Organizer workflows.

## Decision

The native helper supports read-only observation plus guarded mutation primitives: a pre-resolved menu path, one uniquely matched button, and one uniquely matched typed control. Public MCP tools remain domain-specific and never accept arbitrary AX selectors, roles, coordinates, scripts, or input synthesis.

Tool safety is classified as `readOnly`, `stateChange`, `permissionPrompt`, `destructive`, or `externalEffect`. MCP annotations are derived hints; Xcoder authorization remains authoritative.

## Rejected alternatives

- Remove all mutation: breaks existing typed GUI workflows.
- Publish a generic AX press tool: creates an unbounded UI execution surface.
- Keep read-only documentation: dishonest permission and safety metadata.

## Security implications

Arbitrary shell execution, code evaluation, coordinate input, keyboard synthesis, raw MCP AX selectors, unbounded tree mutation, helper-owned developer-tool execution, and unapproved external distribution remain forbidden.

## Compatibility

Existing typed Organizer/menu tools remain available. Doctor and generated capability documentation now describe their real permission boundary.

## Testable invariants

- Every mutating public tool has a non-read-only safety class.
- Every helper mutation has a typed Python caller.
- No public schema accepts raw AX path/role selector data.
- Generated capability documentation matches the code catalog.
