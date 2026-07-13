# ADR 0001: Health data classification

## Status

Accepted for Xcoder 0.6.

## Problem

MCP health state is operational telemetry and can outlive a request. Raw argument values can contain credentials, private paths, project names, and embedded JSON secrets. A per-user state file also lets concurrent server instances overwrite one another.

## Decision

Health schema `xcode-mcp-server.health.v0.2` records only semantic command shape: command group, optional subcommand, option names, argument count, operation identifier, process identifier, and timing. It never records argument values. Each server owns one `0600` file in a `0700` per-user instance directory and removes only that file. CLI health aggregates valid live instances.

## Rejected alternatives

- Redacting a denylist of secret flags: newly introduced flags can leak.
- One file per effective user: concurrent servers race and hide one another.
- Writing then changing permissions: creates a disclosure window.

## Security implications

Unsafe command summarization fails closed by omitting command details. Readers reject wrong ownership, permissive modes, stale state, and dead PIDs. New publishers never emit the legacy raw-argv schema.

## Compatibility

The public `xcode-plugin.v0.3` envelope remains unchanged. The health CLI may read legacy v0.1 state for one release only, but it never republishes it.

## Testable invariants

- No input argument value appears in health JSON or the state file.
- Instance directories are `0700`; files are `0600`.
- Concurrent servers do not overwrite one another.
- Stale, dead, foreign-owned, or permissive files are ignored.
