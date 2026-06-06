# central-mcp-gateway Integration

This project should be integrated as a private static upstream behind
`central-mcp-gateway`.

See [ADR 0006](adr/0006-integracao-central-mcp-gateway.md) for the decision.

## Run the sandbox upstream

Build images:

```bash
docker compose --profile build build
```

Run the sandbox as a local streamable HTTP MCP server:

```powershell
$env:SANDBOX_API_KEY="<shared-local-secret>"
.\.venv\Scripts\python -m server.main --transport streamable-http --host 127.0.0.1 --port 8765
```

The upstream MCP endpoint is:

```text
http://127.0.0.1:8765/mcp
```

## Gateway environment proposal

`central-mcp-gateway` should add these environment variables:

```text
GATEWAY_UPSTREAM_SANDBOX_URL=http://127.0.0.1:8765/mcp
GATEWAY_SANDBOX_API_KEY=<same value as SANDBOX_API_KEY>
```

If the gateway chooses to reuse its generic internal bearer token, set
`SANDBOX_API_KEY` equal to `GATEWAY_MCP_BEARER_TOKEN`. A dedicated
`GATEWAY_SANDBOX_API_KEY` is clearer because sandbox execution is higher risk
than read-only upstreams.

## Gateway catalog proposal

Recommended public tool entries:

```yaml
sandbox.run_code:
  upstream_key: sandbox
  upstream_tool_name: run_code
  description: Run a Python, Node or Java snippet in an isolated Docker sandbox.
  schema_type: flexible
  required_scope: sandbox:run
  risk_level: high-risk-write
  requires_confirmation: false
  timeout_seconds: 35.0
  retry_count: 0
  audit_category: sandbox_execution

sandbox.run_file:
  upstream_key: sandbox
  upstream_tool_name: run_file
  description: Run a multi-file project in an isolated Docker sandbox.
  schema_type: flexible
  required_scope: sandbox:run
  risk_level: high-risk-write
  requires_confirmation: false
  timeout_seconds: 35.0
  retry_count: 0
  audit_category: sandbox_execution

sandbox.run_command:
  upstream_key: sandbox
  upstream_tool_name: run_command
  description: Run an arbitrary shell command in an isolated Docker sandbox.
  schema_type: flexible
  required_scope: sandbox:admin
  risk_level: destructive
  requires_confirmation: true
  confirmation_mode: human
  confirmation_prompt: >-
    This will execute an arbitrary shell command inside the sandbox. Confirm
    only after reviewing the command and expected side effects.
  timeout_seconds: 35.0
  retry_count: 0
  audit_category: sandbox_execution
  disabled: true
```

`sandbox.run_command` should stay disabled until the gateway has a human
confirmation path enabled for the client that needs it.

## Gateway allowlist proposal

Add only the minimum sandbox tools needed by a client:

```text
GATEWAY_TOOL_ALLOWLIST=...,sandbox.run_code,sandbox.run_file
```

Avoid adding `sandbox.run_command` to broad client allowlists.
