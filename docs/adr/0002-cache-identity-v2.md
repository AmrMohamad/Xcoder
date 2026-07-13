# ADR 0002: DerivedData cache identity v2

## Status

Accepted for Xcoder 0.6.

## Problem

The legacy cache resolver validates only one policy field and can reuse the newest same-stem DerivedData folder even when toolchain, project graph, dependencies, or build configuration differ.

## Decision

`xcoder.cache.identity.v2` is the complete compatibility identity. It includes the canonical project path hash, graph/configuration fingerprints, selected Xcode and SDK identity, scheme/configuration/platform/architecture, dependency locks, and optimization/security policy. Compatibility requires structured equality of every hard field. Metadata selection uses an exact compatible match or a deterministic v2 fallback leaf.

Swift source, test source, and asset contents are intentionally excluded from the namespace; Xcode tracks those inputs inside DerivedData.

## Rejected alternatives

- Project name or modification time: collision-prone and incomplete.
- Recursive source hashing: destroys incremental build reuse.
- Rewriting legacy metadata as v2: converts an unproven cache into a false hit.

## Security implications

Shared metadata stores hashes, semantic labels, and basenames rather than private canonical paths. Writes use a cache-local lock and atomic replacement.

## Compatibility

Unversioned metadata is preserved but ignored, causing at most one cold v2 build. Explicit `newest` remains a warned legacy strategy for 0.6.

## Testable invariants

- Any hard-field difference is a miss.
- Symlinks to the same canonical project are hits.
- Source-only edits preserve the namespace.
- Metadata strategy never falls back to an arbitrary same-stem cache.
