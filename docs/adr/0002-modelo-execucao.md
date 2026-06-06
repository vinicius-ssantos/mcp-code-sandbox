# ADR 0002: Modelo de execução — Stateless

**Date:** 2026-06-06
**Status:** Accepted

## Context

The server can execute code in one of two models:

- **Stateless:** each tool call creates a fresh container, executes, returns output and destroys the container. No state survives between calls.
- **Session-based:** a session groups multiple calls. Containers persist for the session lifetime, allowing state (installed packages, written files, defined variables) to carry over.

## Decision

Use the stateless model.

## Reasons

**Simplicity and reliability:**
Sessions require lifecycle management — creation, expiry, cleanup on crash. Stateless calls are self-contained: the server can restart at any time without orphaning session state.

**Security:**
A long-lived container accumulates state from previous executions. A stateless container starts from a known, clean image every time, limiting the blast radius of a misbehaving or malicious snippet.

**Predictability for agents:**
Agents that assume shared state across calls produce fragile, order-dependent workflows. Stateless execution forces each call to be self-contained, which produces more robust prompts and more reproducible results.

**Coverage via `run_file`:**
The main use case for sessions is multi-file code. The `run_file` tool accepts a dict of files and mounts them all in a single container, covering that use case without sessions.

**Packages:**
Installing packages that persist between calls is the other common session use case. This can be handled by pre-installing packages in the sandbox image or by including the install step in the same `run_code` call.

## Trade-offs

- Interactive exploration (define a function, call it in the next turn) is not supported. Agents must include all setup in a single call.
- Package installation on every call adds latency. Pre-built images with common packages mitigate this.

## Future

If session support becomes necessary (e.g., for long-running interactive workflows), it should be introduced as a new ADR and implemented as an opt-in mode, keeping stateless as the default.
