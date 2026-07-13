# ADR 0005: Release binary provenance

## Status

Accepted for Xcoder 0.6.

## Problem

Packaging directly from the mutable checkout can include stale binaries that were not built or tested from the revision represented by the archive.

## Decision

Release verification tests source, builds release components, installs them into an isolated staging tree, self-tests staged binaries, records `xcoder.release-provenance.v1`, creates `xcoder.package-manifest.v1`, writes a deterministic ZIP, audits it, smoke-tests extraction, and rebuilds the ZIP from the same stage to compare hashes.

Archive reproducibility uses sorted entries, normalized modes, a fixed compression policy, and timestamps derived from `SOURCE_DATE_EPOCH`. It does not claim independently compiled Mach-O files are byte reproducible.

## Rejected alternatives

- Package checked-in binaries: provenance is unproven.
- Rebuild after packaging: tests a different artifact.
- Require compiler-level Mach-O reproducibility in 0.6: separate signing/toolchain concern.

## Security implications

Release mode rejects dirty source, verifies package entry hashes and modes, scans high-confidence secret artifacts, validates codesigning where required, and never falls back to stale binaries after build failure.

## Compatibility

Development packaging may use `--allow-dirty` and records that state. The public command envelope remains `xcode-plugin.v0.3`.

## Testable invariants

- Staged, manifested, and extracted binary hashes agree.
- Package creation cannot run before fresh release builds and self-tests.
- A clean staged tree produces an identical ZIP twice.
- Release mode rejects dirty source.
