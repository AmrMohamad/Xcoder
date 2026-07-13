# Xcoder 0.6.0

Xcoder 0.6 is a correctness, security, and lifecycle release. It preserves the
public `xcode-plugin.v0.3` command envelope while adding versioned health,
cache, package-manifest, and release-provenance contracts.

The native helper supports narrowly scoped Accessibility mutation for typed
menu, button, control, and Organizer workflows. It does not expose arbitrary
UI execution, selectors, coordinate input, or keyboard synthesis through MCP.

The first 0.6 CLI build may create a new DerivedData leaf. Unversioned cache
metadata is preserved but is not considered proof of compatibility. Inspect
the migration state with `bin/xcode cache inspect --json`.

Release artifacts must be produced with `bin/xcode release verify --json`.
That command builds both native binaries from source, self-tests the staged
components, creates and audits a deterministic archive twice, and verifies
that the archive hashes match.
