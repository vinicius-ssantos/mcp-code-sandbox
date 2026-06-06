# Gateway Policy for Sandbox Tools

The sandbox server enforces container-level isolation. The gateway must enforce
client-facing access policy.

## Recommended public tools

| Public tool | Upstream tool | Scope | Risk | Default |
|---|---|---|---|---|
| `sandbox.run_code` | `run_code` | `sandbox:run` | `high-risk-write` | Allowed only for trusted clients |
| `sandbox.run_file` | `run_file` | `sandbox:run` | `high-risk-write` | Allowed only for trusted clients |
| `sandbox.run_command` | `run_command` | `sandbox:admin` | `destructive` | Disabled or human-confirmed |

## Rules

- Do not expose sandbox tools to generic public clients by default.
- Require a dedicated sandbox scope instead of reusing `gateway:read`.
- Never retry sandbox executions. Even when containers are isolated, retries can
  duplicate expensive work or hide nondeterministic failures.
- Treat output as untrusted model-visible content. The gateway should keep its
  prompt-injection/trust-boundary annotations active for sandbox results.
- Do not log raw code, file contents or shell commands in gateway audit logs.
- Keep the sandbox HTTP upstream bound to `127.0.0.1` unless it is placed behind
  a trusted local network boundary with TLS and explicit firewall rules.

## Tool-specific notes

`sandbox.run_code` and `sandbox.run_file` execute arbitrary code but within the
container controls defined by ADR 0004. They are appropriate for trusted
developer workflows and agent validation loops.

`sandbox.run_command` accepts arbitrary shell. It is useful for diagnostics
inside the sandbox image, but it is the broadest interface and should require
human confirmation or remain disabled.
