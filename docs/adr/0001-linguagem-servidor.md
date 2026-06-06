# ADR 0001: Linguagem do servidor MCP — Python

**Date:** 2026-06-06
**Status:** Accepted

## Context

The MCP server needs a host-language implementation. The two realistic options are Python (using the `mcp` SDK) and TypeScript (using `@modelcontextprotocol/sdk`). Both are officially supported by Anthropic.

## Decision

Use Python with the `mcp` SDK (`fastmcp` interface).

## Reasons

- The sandbox images include Python runtimes; keeping the server in the same language reduces the cognitive load when working across server and images.
- The `docker` Python SDK is mature, well-documented and widely used for container management — a better fit than the Node Docker libraries.
- The project owner's primary working language is Python.
- `fastmcp` provides a decorator-based API that keeps tool definitions concise and co-located with their docstrings (which become tool descriptions for the client).

## Trade-offs

- TypeScript would offer stronger static typing out of the box, but `mypy` + type hints cover the same ground in Python.
- Node ecosystem tooling (npm, ts-node) is slightly more portable for frontend-heavy setups, but this project has no frontend.

## References

- `mcp` Python SDK: https://github.com/modelcontextprotocol/python-sdk
- `docker` Python SDK: https://docker-py.readthedocs.io
