# ADR 0004: MCP request deadlines

## Status

Accepted for Xcoder 0.6.

## Problem

Relative subprocess timeouts begin only after queue acquisition, so queued calls can exceed their advertised MCP budget. Cancellation accounting is split across paths and can leak waiters or process resources.

## Decision

Each request receives one `ContinuousClock.Instant` deadline at call receipt. The same absolute deadline covers validation, queueing, launch, execution, output drain, and response construction, with a two-second response reserve. The default synchronous request budget is 50 seconds. A bounded actor-isolated FIFO queue completes each waiter exactly once.

## Rejected alternatives

- Stack independent relative timeouts: budgets do not compose.
- Increase a global timeout: still fails with shorter clients and long queues.
- Unbounded queue: permits resource exhaustion.

## Security implications

Cancellation removes queued work or terminates the active descendant process tree, closes output pipes, unregisters health state, and releases execution ownership. Queue depth is capped at eight.

## Compatibility

`command_timeout` remains the public timeout category. Additive details identify the timeout stage and timing. Queue saturation uses `xcode_busy`.

## Testable invariants

- Queue wait consumes the request budget.
- Expired queued requests never launch a process.
- Cancellation and completion races never double-resume.
- The registry and queue return to idle after every exit path.
