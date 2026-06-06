# ADR 0004: Modelo de segurança

**Date:** 2026-06-06
**Status:** Accepted

## Context

The server executes arbitrary code provided by an AI client inside Docker containers. The threat model includes:

- Malicious or buggy code attempting to escape the container.
- Code attempting to reach the host network or internal services.
- Code consuming excessive CPU, memory or disk.
- Unauthorized clients connecting to the server.

## Decisions

### Container isolation

| Control | Setting | Reason |
|---|---|---|
| Network | `--network none` | No internet, no internal network access |
| Filesystem | `--read-only` | Prevents writes to the container layer |
| Writable tmp | `--tmpfs /tmp:size=64m` | Allows temporary writes without escaping |
| CPU | `--cpu-period 100000 --cpu-quota 50000` | 0.5 CPU max |
| Memory | `--memory 256m --memory-swap 256m` | 256 MB max, no swap |
| Execution timeout | 30 seconds | Server kills container after timeout |
| User | Non-root `sandbox` user in image | Limits damage from container escape |
| Privileged | Not set | No elevated capabilities |
| Volume mounts | Bind-mount of code dir as read-only | Code is readable, host FS is not writable |

### Server authentication

Every request must include `Authorization: Bearer <SANDBOX_API_KEY>`.

The key is configured via the `SANDBOX_API_KEY` environment variable, loaded from `.env` (never committed). Requests without a valid key receive `401 Unauthorized`.

### Server binding

The server binds to `127.0.0.1` by default. It is not exposed to the network unless explicitly configured (`SANDBOX_HOST`). External exposure requires a reverse proxy with TLS.

### Docker socket

The Docker socket (`/var/run/docker.sock`) is accessed from the host process directly. It is never mounted into a container. Mounting the socket into a container would grant the container root-equivalent access to the host.

## What this model does NOT protect against

- Container escape vulnerabilities in the Docker runtime itself. Keep Docker updated.
- Denial of service via many concurrent calls exhausting the host's container capacity. Rate limiting is a future concern.
- Data exfiltration via timing side-channels or covert channels. Out of scope for this use case.

## References

- Docker security best practices: https://docs.docker.com/engine/security/
- ADR 0005 for the rationale of running the server on the host.
