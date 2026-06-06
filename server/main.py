from __future__ import annotations

import argparse
import logging
import os
from secrets import compare_digest

from dotenv import load_dotenv
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP

from .tools import SandboxTools

load_dotenv()


class ApiKeyTokenVerifier:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if compare_digest(token, self._api_key):
            return AccessToken(
                token=token,
                client_id="mcp-code-sandbox-client",
                scopes=["sandbox:run"],
            )
        return None


def create_server(host: str, port: int) -> FastMCP:
    api_key = os.getenv("SANDBOX_API_KEY")
    token_verifier = ApiKeyTokenVerifier(api_key) if api_key else None

    mcp = FastMCP(
        "mcp-code-sandbox",
        host=host,
        port=port,
        token_verifier=token_verifier,
        stateless_http=True,
    )
    tools = SandboxTools()

    @mcp.tool()
    def run_code(language: str, code: str) -> str:
        """Execute a Python, Node or Java snippet in an ephemeral Docker container."""
        return tools.run_code(language, code)

    @mcp.tool()
    def run_command(command: str) -> str:
        """Execute an arbitrary shell command in an ephemeral Docker container."""
        return tools.run_command(command)

    @mcp.tool()
    def run_file(language: str, files: dict[str, str]) -> str:
        """Execute a multi-file Python, Node or Java project in an ephemeral Docker container."""
        return tools.run_file(language, files)

    return mcp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the mcp-code-sandbox MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default=os.getenv("SANDBOX_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("SANDBOX_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SANDBOX_PORT", "8765")))
    parser.add_argument("--log-level", default=os.getenv("SANDBOX_LOG_LEVEL", "INFO"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.transport != "stdio" and not os.getenv("SANDBOX_API_KEY"):
        raise SystemExit("SANDBOX_API_KEY is required for HTTP transports")
    create_server(args.host, args.port).run(transport=args.transport)
