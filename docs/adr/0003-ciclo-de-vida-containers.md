# ADR 0003: Ciclo de vida dos contêineres — Efêmero por chamada

**Date:** 2026-06-06
**Status:** Accepted

## Context

Given the stateless execution model (ADR 0002), a container lifecycle strategy must be defined. Options are:

1. **Ephemeral per call:** create → run → destroy on every tool call.
2. **Pre-warmed pool:** keep N idle containers ready, assign one per call, reset after use.
3. **Persistent per image:** one long-lived container per language, execute via `docker exec`.

## Decision

Use ephemeral containers per call (option 1).

## Reasons

**Isolation guarantee:**
Each call starts from the exact image state. There is no risk of a previous execution leaving behind files, environment variables, processes or side effects.

**Simplicity:**
No pool management, no container assignment, no reset logic. The server creates a container, waits for it, reads logs, removes it. The lifecycle is linear and easy to reason about.

**Resource predictability:**
Idle pre-warmed containers consume memory even when unused. Ephemeral containers only consume resources during execution.

**Correctness over latency:**
Container startup for a slim image (Python slim, Node slim) is typically under 300ms — acceptable for a tool call. Correctness and isolation are worth the marginal overhead.

## Trade-offs

- Cold start latency (~200–400ms per call) compared to a pre-warmed pool.
- Each call pays the full container init cost. For tight loops this would be inefficient, but MCP tool calls are not tight loops.

## Implementation notes

- Containers are created with `detach=True`, waited on with a timeout, then removed with `force=True`.
- Container names include a UUID suffix to avoid collisions on concurrent calls.
- If the process times out, the container is killed before removal.
- `docker.containers.run(..., remove=False)` is used so logs can be retrieved before removal.
