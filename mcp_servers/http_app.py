"""Authenticated localhost Streamable HTTP entry point for the MCP tools."""

from __future__ import annotations

import os
import secrets
from typing import Final, Optional

import uvicorn
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp_servers import equity_screening


TOKEN_ENV: Final = "EQUITY_MCP_TOKEN"
READ_SCOPE: Final = "equity:read"
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8000
MIN_TOKEN_LENGTH: Final = 32
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})


class StaticTokenVerifier(TokenVerifier):
    """Verify one locally provisioned bearer token in constant time."""

    def __init__(self, expected_token: str) -> None:
        self._expected_token = expected_token

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        if not secrets.compare_digest(token, self._expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="local-equity-client",
            scopes=[READ_SCOPE],
        )


def _resolve_token(token: Optional[str]) -> str:
    resolved = os.getenv(TOKEN_ENV) if token is None else token
    if not isinstance(resolved, str) or not resolved:
        raise RuntimeError(
            f"{TOKEN_ENV} is required to launch the authenticated MCP server"
        )
    if any(character.isspace() for character in resolved):
        raise RuntimeError(f"{TOKEN_ENV} must not contain whitespace")
    if len(resolved) < MIN_TOKEN_LENGTH:
        raise RuntimeError(
            f"{TOKEN_ENV} must contain at least {MIN_TOKEN_LENGTH} characters"
        )
    return resolved


def _local_base_url(host: str, port: int) -> str:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("The authenticated MCP server must bind to a loopback host")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 through 65535")
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}:{port}"


def _build_server(token: str, base_url: str) -> MCPServer:
    source = equity_screening.mcp
    server = MCPServer(
        name=source.name,
        title=source.title,
        description=source.description,
        instructions=source.instructions,
        website_url=source.website_url,
        icons=source.icons,
        version=source.version,
        token_verifier=StaticTokenVerifier(token),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(base_url),
            # This localhost entry point uses an out-of-band, pre-provisioned
            # bearer token. It is not an OAuth authorization server, so do not
            # advertise RFC 9728 discovery metadata that points back to itself.
            resource_server_url=None,
            required_scopes=[READ_SCOPE],
        ),
    )
    equity_screening.register_tools(server)

    @server.custom_route(
        "/healthz",
        methods=["GET"],
        include_in_schema=False,
    )
    async def healthz(request: Request) -> Response:
        del request
        return JSONResponse(
            {"status": "ok", "server_version": server.version},
            headers={"Cache-Control": "no-store"},
        )

    return server


def create_app(
    token: Optional[str] = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> Starlette:
    """Create a fail-closed, authenticated Streamable HTTP application."""

    resolved_token = _resolve_token(token)
    base_url = _local_base_url(host, port)
    server = _build_server(resolved_token, base_url)
    app = server.streamable_http_app(
        host=host,
        json_response=True,
        stateless_http=True,
    )
    app.state.mcp_server = server
    return app


def main() -> None:
    """Launch the authenticated MCP server on localhost."""

    uvicorn.run(
        create_app(),
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
