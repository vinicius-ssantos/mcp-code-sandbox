# ADR 0005: Onde roda o servidor MCP — Host-based

**Date:** 2026-06-06
**Status:** Accepted

## Context

The MCP server needs to manage Docker containers. Two deployment options were considered:

1. **Host-based:** the server runs as a Python process directly on the host inside a virtualenv.
2. **Containerized:** the server runs inside a Docker container that mounts the host Docker socket (`/var/run/docker.sock`) to manage sibling containers.

## Decision

Run the server on the host (option 1) by default.

For local `personal-platform-infra` Compose development, a containerized server image is allowed as an explicit exception, and must only be used in trusted local development.

**Update 2026-06-12:** the containerized exception no longer mounts `/var/run/docker.sock` into the server. The Compose stack adds a `docker-socket-proxy` sidecar that holds the only (read-only) socket mount and exposes a filtered daemon API (`CONTAINERS`, `VOLUMES`, `POST`, `ALLOW_START`, `ALLOW_RESTARTS`) over an internal network. The server connects via `DOCKER_HOST=tcp://docker-socket-proxy:2375` and runs as a non-root user.

## Reasons

**Security:**
Mounting the Docker socket into a container grants that container root-equivalent access to the host. Any vulnerability in the server code or its dependencies could allow an attacker to create privileged containers, mount host paths, or escape entirely. Since the server executes arbitrary code from AI clients, this attack surface is unacceptable.

**Simplicity:**
A `venv` + `pip install` is simpler to set up, debug and update than a containerized service that manages other containers. There is no `docker-in-docker` complexity, no socket permission issues and no extra compose service to maintain.

**Directness:**
The server calls `docker.from_env()` and gets a client connected to the local daemon. No socket path configuration, no API version negotiation overhead.

**Operational clarity:**
Logs from the server appear directly in the terminal. Restarting is `Ctrl+C` + `python -m server.main`. No `docker compose logs` indirection.

## Trade-offs

- The server is not containerized, so its Python version and dependencies depend on the host environment. A `venv` and a pinned `requirements.txt` mitigate this.
- Updating the server requires updating the host `venv`, not just pulling a new image.
- If the project ever needs to run on a remote machine without direct SSH access, a containerized deployment with careful socket permissions could be revisited as a new ADR.
- The local platform Compose exception trades security isolation for operator convenience. It must not be treated as the production deployment model.

## Relationship to ci-self-hosted-runner

The sandbox images (`mcp-sandbox-python:local`, etc.) are built and managed by this project. The `ci-self-hosted-runner` project owns CI runner images. These are separate concerns and separate image sets — they share a similar base image pattern (`slim-bookworm`) but are not the same containers.
