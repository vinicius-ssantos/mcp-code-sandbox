from __future__ import annotations

import argparse
import logging
import os
from secrets import compare_digest

from dotenv import load_dotenv
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, TypeAdapter

from .tools import SandboxTools

load_dotenv()

HTTP_URL_ADAPTER: TypeAdapter[AnyHttpUrl] = TypeAdapter(AnyHttpUrl)


class ApiKeyTokenVerifier:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        # Compare bytes: compare_digest on str rejects non-ASCII input with a
        # TypeError, which would turn a bad token into a 500 instead of a 401.
        if compare_digest(token.encode("utf-8"), self._api_key.encode("utf-8")):
            return AccessToken(
                token=token,
                client_id="mcp-code-sandbox-client",
                scopes=["sandbox:run"],
            )
        return None


def create_server(host: str, port: int) -> FastMCP:
    api_key = os.getenv("SANDBOX_API_KEY")
    token_verifier = ApiKeyTokenVerifier(api_key) if api_key else None
    auth_settings = None
    if api_key:
        resource_server_url = HTTP_URL_ADAPTER.validate_python(f"http://{host}:{port}")
        auth_settings = AuthSettings(
            issuer_url=resource_server_url,
            resource_server_url=resource_server_url,
            required_scopes=["sandbox:run"],
        )
    allowed_hosts = [
        host,
        f"{host}:{port}",
        "localhost",
        f"localhost:{port}",
        "127.0.0.1",
        f"127.0.0.1:{port}",
    ]
    configured_allowed_hosts = [
        item.strip() for item in os.getenv("SANDBOX_ALLOWED_HOSTS", "").split(",") if item.strip()
    ]
    allowed_hosts.extend(configured_allowed_hosts)
    transport_security = TransportSecuritySettings(allowed_hosts=sorted(set(allowed_hosts)))

    mcp = FastMCP(
        "mcp-code-sandbox",
        host=host,
        port=port,
        token_verifier=token_verifier,
        auth=auth_settings,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )
    tools = SandboxTools()

    @mcp.tool()
    def run_code(language: str, code: str) -> str:
        """Execute a code snippet in an ephemeral Docker container.

        Supported languages: python, node, java, bash.

        Java constraint: the public class must be named Main (default package).
        The file is saved as Main.java and executed as `java Main`.
        """
        return tools.run_code(language, code)

    @mcp.tool()
    def run_command(command: str) -> str:
        """Execute an arbitrary shell command in an ephemeral Docker container."""
        return tools.run_command(command)

    @mcp.tool()
    def run_file(language: str, files: dict[str, str]) -> str:
        """Execute a multi-file project in an ephemeral Docker container.

        Supported languages: python, node, java, bash.

        Java constraint: the entry-point class must be named Main (default
        package) and its file must be named Main.java. The project is compiled
        with javac and run as `java Main`.
        """
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
