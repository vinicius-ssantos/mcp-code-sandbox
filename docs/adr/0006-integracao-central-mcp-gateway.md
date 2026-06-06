# ADR 0006: Integração com central-mcp-gateway

**Date:** 2026-06-06
**Status:** Accepted

## Context

Long term, `mcp-code-sandbox` should be reachable through
`central-mcp-gateway`, located locally at
`C:\Users\vinicius\Documents\workspace\central-mcp-gateway`.

This project is a specialized MCP server for isolated code execution. The
gateway is the central entrypoint for public clients and already owns tool
allowlisting, routing, OAuth scopes, rate limits, confirmation policy, audit
metadata and upstream failure handling.

The sandbox can run via `stdio`, `sse` or `streamable-http`. The gateway's
current static upstream client calls upstream MCP servers over HTTP JSON-RPC and
injects bearer credentials per upstream.

## Decision

Integrate `mcp-code-sandbox` as a private static upstream named `sandbox` in
`central-mcp-gateway`.

The recommended transport is local `streamable-http`:

```text
http://127.0.0.1:8765/mcp
```

The sandbox server remains host-based, as defined by ADR 0005. It must not be
containerized just to satisfy gateway deployment convenience, because it needs
direct Docker daemon access without mounting the Docker socket into a container.

The gateway should expose namespaced public tools:

```text
sandbox.run_code
sandbox.run_file
sandbox.run_command
```

These public names map to upstream tool names:

```text
run_code
run_file
run_command
```

## Security and policy

`mcp-code-sandbox` keeps its local security boundary:

- Docker containers have no network;
- filesystem is read-only;
- `/tmp` is the only writable path;
- CPU, memory and timeout limits are enforced by this server;
- HTTP transport requires `Authorization: Bearer <SANDBOX_API_KEY>`;
- the server binds to `127.0.0.1` by default.

`central-mcp-gateway` owns client-facing policy:

- public allowlist;
- OAuth scopes;
- client or tenant-specific allowlists;
- rate limiting;
- confirmation requirements;
- audit categories.

`sandbox.run_command` is the highest-risk tool and should be disabled or require
human confirmation by default. `sandbox.run_code` and `sandbox.run_file` execute
arbitrary user code but inside the sandbox boundary; they should still require a
dedicated scope such as `sandbox:run` and should not be available to broad
public clients by default.

## Required gateway changes

The gateway needs a static upstream entry for `sandbox`, including:

- `GATEWAY_UPSTREAM_SANDBOX_URL`;
- `GATEWAY_SANDBOX_API_KEY`;
- `sandbox` in the upstream registry;
- catalog entries for `sandbox.run_code`, `sandbox.run_file` and optionally
  `sandbox.run_command`;
- schemas for sandbox tool inputs or reuse of the existing flexible schema;
- secret validation for the sandbox upstream.

## Consequences

- The sandbox remains simple, focused and auditable.
- The gateway can centrally hide, rename, rate-limit and audit sandbox tools.
- End-to-end local development requires two host processes: the sandbox MCP
  server and the central gateway.
- Gateway support requires code changes in `central-mcp-gateway`; dynamic
  upstream registration is not the preferred path for this server because the
  sandbox tools are not read-only.
