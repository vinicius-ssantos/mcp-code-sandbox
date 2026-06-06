# mcp-code-sandbox

An MCP server that executes code and shell commands inside isolated, ephemeral Docker containers.

AI clients such as Claude or other agents call MCP tools exposed by this server. For each call, the server creates a fresh container, copies the requested code or project files into it, executes the command, returns stdout, stderr and exit code, then destroys the container.

## Architecture

```text
MCP client
  |
  | MCP over stdio or streamable HTTP
  v
mcp-code-sandbox server (Python, host process by default)
  |
  | Docker SDK
  v
Ephemeral sandbox container
  |
  v
stdout / stderr / exit code
```

The default mode runs the server on the host. Local platform Compose can also run the server as a container by mounting the Docker socket; that mode is intended for development convenience only.

## MCP tools

| Tool | Description |
|---|---|
| `run_code(language, code)` | Run a single-file snippet in Python, Node or Java |
| `run_command(command)` | Run an arbitrary shell command in the Python sandbox image |
| `run_file(language, files)` | Run a multi-file project where `files` maps relative paths to file contents |

Supported languages:

| Language | Image | Entry point |
|---|---|---|
| `python` | `mcp-sandbox-python:local` | `/workspace/main.py` |
| `node` | `mcp-sandbox-node:local` | `/workspace/main.js` |
| `java` | `mcp-sandbox-java:local` | `/workspace/Main.java` with class `Main` |

## Security baseline

- Containers run with `network_mode="none"`.
- Containers run with a read-only filesystem.
- `/tmp` is the only writable area, mounted as a 64 MB tmpfs.
- CPU is capped at 0.5 core.
- Memory is capped at 256 MB with no swap.
- Execution timeout is 30 seconds.
- Containers run as a non-root `sandbox` user.
- Containers are removed immediately after execution.
- HTTP transports require `Authorization: Bearer <SANDBOX_API_KEY>`.
- The server binds to `127.0.0.1` by default.
- In the default host mode, the Docker socket is accessed only by the host server process and is never mounted into sandbox containers.
- In local Compose server mode, the MCP server container mounts the Docker socket so it can create sibling sandbox containers. Do not expose that deployment beyond trusted local development.

See [docs/adr/0004-modelo-seguranca.md](docs/adr/0004-modelo-seguranca.md) for the full security model.

## Setup

### 1. Prerequisites

- Docker running on the host
- Python 3.12+

### 2. Build the sandbox images

```bash
docker compose --profile build build
```

### 3. Install the server

Unix shell:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
```

PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server/requirements.txt
```

### 4. Configure

```bash
cp .env.example .env
```

Set `SANDBOX_API_KEY` in `.env` for HTTP transports:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Run

Stdio transport:

```bash
python -m server.main
```

Streamable HTTP transport:

```bash
SANDBOX_API_KEY=<your-key> python -m server.main --transport streamable-http --host 127.0.0.1 --port 8765
```

PowerShell:

```powershell
$env:SANDBOX_API_KEY="<your-key>"
py -m server.main --transport streamable-http --host 127.0.0.1 --port 8765
```

Containerized local server:

```bash
docker compose --profile build build
SANDBOX_API_KEY=<your-key> docker compose --profile server up --build
```

The containerized server listens on `http://localhost:8766/mcp` and mounts `/var/run/docker.sock`.

## Claude Code configuration

```json
{
  "mcpServers": {
    "code-sandbox": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "server.main"],
      "cwd": "/path/to/mcp-code-sandbox",
      "env": {
        "SANDBOX_API_KEY": "<your-key>"
      }
    }
  }
}
```

## central-mcp-gateway

Long-term integration should route this server behind
`central-mcp-gateway` as a private static upstream named `sandbox`.

See:

- [ADR 0006](docs/adr/0006-integracao-central-mcp-gateway.md)
- [Gateway integration guide](docs/gateway-integration.md)
- [Gateway policy](docs/gateway-policy.md)
- [E2E gateway test plan](docs/e2e-gateway-test-plan.md)

## Tests

```bash
pytest tests/
```

The current unit tests validate pure sandbox helpers and do not require Docker. End-to-end execution requires Docker plus the local sandbox images.

## Files

```text
server/
  main.py          MCP server entrypoint
  sandbox.py       Docker container lifecycle
  tools.py         MCP tool adapter layer
  requirements.txt
images/
  Dockerfile.python
  Dockerfile.node
  Dockerfile.java
Dockerfile.server  Local Compose server image
docker-compose.yml Builds the sandbox images with the build profile
.env.example
docs/adr/           Architecture decision records
AGENTS.md           Guide for AI agents using this MCP server
CLAUDE.md           Guide for Claude Code working in this repo
```
