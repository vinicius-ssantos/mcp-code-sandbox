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
| Volume mounts | Ephemeral Docker volume mounted read-only into the sandbox container | Code is readable, no host path is exposed to the container |

### Host/sandbox boundary limits (added 2026-06-12)

These protect the *server process* from hostile sandbox payloads. Defaults can be lowered freely via environment variables; raising them requires updating this ADR.

| Control | Default | Env var | Reason |
|---|---|---|---|
| Output cap per stream | 1 MiB | `SANDBOX_MAX_OUTPUT_BYTES` | Sandboxed code printing gigabytes would exhaust server RAM and bloat MCP responses. Logs are read as a stream and truncated; results carry `status: output_truncated`. |
| Project file count | 64 | `SANDBOX_MAX_PROJECT_FILES` | The project tar is staged in server memory before upload. |
| Project total size | 8 MiB | `SANDBOX_MAX_PROJECT_BYTES` | Same as above. |
| Concurrent executions | 4 | `SANDBOX_MAX_CONCURRENT` | Each execution costs up to 256 MB + 0.5 CPU on the host; unbounded concurrency is a trivial DoS. Requests over the limit wait up to `SANDBOX_QUEUE_TIMEOUT_SECONDS` (default 30) and then fail with a busy error. |

### Server authentication

Every request must include `Authorization: Bearer <SANDBOX_API_KEY>`.

The key is configured via the `SANDBOX_API_KEY` environment variable, loaded from `.env` (never committed). Requests without a valid key receive `401 Unauthorized`.

### Server binding

The server binds to `127.0.0.1` by default. It is not exposed to the network unless explicitly configured (`SANDBOX_HOST`). External exposure requires a reverse proxy with TLS.

### Docker socket

The Docker socket (`/var/run/docker.sock`) is accessed from the host process directly. It is never mounted into a sandbox container. Mounting the socket into a container would grant the container root-equivalent access to the host.

For the containerized local-development server (see ADR 0005), the socket is no longer mounted into the server container either. Since 2026-06-12 the Compose stack routes the server through `docker-socket-proxy`, which holds the only socket mount (read-only) and exposes just the container/volume API endpoints over an internal TCP network. A compromise of the server process is then limited to the proxied endpoints instead of full daemon control.

### Error responses

Docker daemon error messages can contain host paths and infrastructure details. They are logged server-side with a correlation `error_id`; MCP clients receive only the opaque id.

## What this model does NOT protect against

- Container escape vulnerabilities in the Docker runtime itself. Keep Docker updated.
- Denial of service via many concurrent calls is bounded by the concurrency cap above, but there is no per-client rate limiting or quota; a single authorized client can still keep the queue saturated.
- Data exfiltration via timing side-channels or covert channels. Out of scope for this use case.

## References

- Docker security best practices: https://docs.docker.com/engine/security/
- ADR 0005 for the rationale of running the server on the host.
