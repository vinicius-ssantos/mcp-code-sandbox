# End-to-End Gateway Integration Test Plan

This plan validates `central-mcp-gateway -> mcp-code-sandbox -> Docker`.

## Prerequisites

- Docker is running.
- Sandbox images are built with `docker compose --profile build build`.
- `mcp-code-sandbox` dependencies are installed.
- `central-mcp-gateway` has implemented the static `sandbox` upstream described
  in ADR 0006.

## Manual smoke

Start sandbox:

```powershell
cd C:\Users\vinicius\PycharmProjects\mcp-code-sandbox
$env:SANDBOX_API_KEY="<shared-local-secret>"
.\.venv\Scripts\python -m server.main --transport streamable-http --host 127.0.0.1 --port 8765
```

Start gateway with:

```text
GATEWAY_UPSTREAM_SANDBOX_URL=http://127.0.0.1:8765/mcp
GATEWAY_SANDBOX_API_KEY=<shared-local-secret>
GATEWAY_TOOL_ALLOWLIST=...,sandbox.run_code,sandbox.run_file
```

Call the gateway MCP endpoint with `sandbox.run_code`:

```json
{
  "language": "python",
  "code": "print('gateway sandbox ok')"
}
```

Expected result contains:

```text
stdout:
gateway sandbox ok

exit_code: 0
```

## Automated test cases

1. Successful Python execution through the gateway.
2. Unsupported language returns a normalized gateway upstream error or sandbox
   tool error without crashing the gateway.
3. Missing or wrong sandbox API key returns `UPSTREAM_AUTH_FAILED`.
4. `sandbox.run_command` is not listed when disabled or absent from the
   allowlist.
5. A timeout returns `exit_code: 124` and `status: timed_out`.

## Ownership

The gateway repo should own tests that assert routing, auth injection,
allowlist, scopes and confirmation behavior.

This repo should own tests that assert sandbox execution, Docker constraints and
tool result formatting.
