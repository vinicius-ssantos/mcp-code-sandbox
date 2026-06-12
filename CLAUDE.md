# CLAUDE.md - mcp-code-sandbox

## What this project is

An MCP server that runs code in ephemeral Docker containers. The server is a Python process on the host; sandbox containers are managed through the Docker SDK.

Read the ADRs in `docs/adr/` before changing architecture, lifecycle or security behavior.

## Key commands

### Build sandbox images

```bash
docker compose --profile build build
```

### Install server dependencies

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

### Run the server

```bash
python -m server.main
```

HTTP transport:

```bash
SANDBOX_API_KEY=<key> python -m server.main --transport streamable-http --host 127.0.0.1 --port 8765
```

### Run tests

```bash
pytest tests/
```

## File structure

```text
server/main.py      MCP entrypoint and transport configuration
server/tools.py     MCP-facing tool adapter layer
server/sandbox.py   Container lifecycle, limits, language registry
images/             One Dockerfile per sandbox language
docs/adr/           Architecture decision records
tests/              Unit tests for pure sandbox behavior
```

## Adding a new language

1. Create `images/Dockerfile.<lang>`.
2. Add a build service to `docker-compose.yml` under the `build` profile.
3. Register the image, run command and file name in `IMAGES`, `RUN_COMMANDS` and `FILE_NAMES` in `server/sandbox.py`.
4. Rebuild images with `docker compose --profile build build`.
5. Add tests.

## Changing resource limits

All runtime limits live near the top of `server/sandbox.py`:

- `TIMEOUT_SECONDS`
- `MEMORY_LIMIT`
- `CPU_PERIOD`
- `CPU_QUOTA`
- `TMPFS`
- `MAX_OUTPUT_BYTES` (env: `SANDBOX_MAX_OUTPUT_BYTES`)
- `MAX_PROJECT_FILES` / `MAX_PROJECT_BYTES` (env: `SANDBOX_MAX_PROJECT_FILES`, `SANDBOX_MAX_PROJECT_BYTES`)
- `MAX_CONCURRENT_EXECUTIONS` (env: `SANDBOX_MAX_CONCURRENT`)

Do not raise these without updating the security rationale in ADR 0004.

## Security rules

- Never mount the host Docker socket into a sandbox container.
- Never set `network_mode` to anything other than `none`.
- Never disable `read_only=True` without a documented ADR.
- Never remove the non-root `sandbox` user from images.
- Never commit `.env` or any real `SANDBOX_API_KEY`.
