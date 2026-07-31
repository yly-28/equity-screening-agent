from __future__ import annotations

import logging

import httpx2
import pytest
from mcp import Client, ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from mcp_servers import equity_screening
from mcp_servers.http_app import TOKEN_ENV, create_app


BASE_URL = "http://127.0.0.1:8000"
TEST_TOKEN = "unit-test-equity-mcp-token-0123456789abcdef"
MCP_CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "screen_stocks", "arguments": {}},
}


@pytest.fixture
def http_app():
    return create_app(TEST_TOKEN)


@pytest.fixture
def http_client(http_app):
    with TestClient(http_app, base_url=BASE_URL) as client:
        yield client


def test_app_factory_fails_closed_without_token(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)

    with pytest.raises(RuntimeError, match=f"{TOKEN_ENV} is required"):
        create_app()
    with pytest.raises(RuntimeError, match=f"{TOKEN_ENV} is required"):
        create_app("")


@pytest.mark.parametrize("token", ["too-short", "contains whitespace 012345678901234567890123"])
def test_app_factory_rejects_weak_or_malformed_tokens(token) -> None:
    with pytest.raises(RuntimeError, match=TOKEN_ENV):
        create_app(token)


def test_environment_token_authenticates_without_being_exposed(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV, TEST_TOKEN)
    app = create_app()

    with TestClient(app, base_url=BASE_URL) as client:
        response = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "unknown", "params": {}},
        )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601
    assert TEST_TOKEN not in response.text


def test_healthz_is_public_static_and_has_no_cors(http_client) -> None:
    response = http_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "server_version": "0.2.0"}
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in response.headers
    assert TEST_TOKEN not in response.text


def test_local_bearer_mode_does_not_advertise_fake_oauth_metadata(
    http_client,
) -> None:
    response = http_client.get(
        "/.well-known/oauth-protected-resource/mcp"
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer wrong-token"],
)
def test_authentication_rejects_before_service_dispatch(
    http_client,
    monkeypatch,
    authorization,
) -> None:
    calls: list[dict[str, object]] = []

    def forbidden_dispatch(**kwargs):
        calls.append(kwargs)
        raise AssertionError("service must not run before authentication")

    monkeypatch.setattr(
        equity_screening,
        "screen_stocks_service",
        forbidden_dispatch,
    )
    headers = {} if authorization is None else {"Authorization": authorization}

    response = http_client.post("/mcp", headers=headers, json=MCP_CALL)

    assert response.status_code == 401
    assert response.json() == {
        "error": "invalid_token",
        "error_description": "Authentication required",
    }
    assert response.headers["www-authenticate"].startswith("Bearer ")
    assert calls == []


def test_authentication_does_not_log_bearer_tokens(
    http_client,
    caplog,
) -> None:
    wrong_token = "wrong-sensitive-token"
    caplog.set_level(logging.DEBUG)

    response = http_client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {wrong_token}"},
        json=MCP_CALL,
    )

    assert response.status_code == 401
    assert TEST_TOKEN not in caplog.text
    assert wrong_token not in caplog.text
    assert TEST_TOKEN not in response.text
    assert wrong_token not in response.text


@pytest.mark.anyio
async def test_valid_token_discovers_exactly_the_canonical_five_tools(http_app) -> None:
    transport = httpx2.ASGITransport(app=http_app)
    headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    async with http_app.router.lifespan_context(http_app):
        async with httpx2.AsyncClient(
            transport=transport,
            base_url=BASE_URL,
            headers=headers,
        ) as client:
            async with streamable_http_client(
                f"{BASE_URL}/mcp",
                http_client=client,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    discovered = await session.discover()
                    tools = await session.list_tools()

    assert discovered.supported_versions == ["2026-07-28"]
    assert [tool.name for tool in tools.tools] == [
        "screen_stocks",
        "get_stock_detail",
        "analyze_ticker",
        "compare_stocks",
        "get_market_overview",
    ]


@pytest.mark.anyio
async def test_authenticated_http_call_preserves_service_response(
    http_app,
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []
    sentinel = {
        "service": "analyze_ticker",
        "ticker": "ZZZ",
        "live_quote": {"price": None},
        "warnings": ["synthetic_warning"],
    }

    def fake_service(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(equity_screening, "analyze_ticker_service", fake_service)
    transport = httpx2.ASGITransport(app=http_app)
    headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    async with http_app.router.lifespan_context(http_app):
        async with httpx2.AsyncClient(
            transport=transport,
            base_url=BASE_URL,
            headers=headers,
        ) as client:
            async with streamable_http_client(
                f"{BASE_URL}/mcp",
                http_client=client,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "analyze_ticker",
                        {"ticker": " zzz ", "mode": "value", "refresh": True},
                    )

    assert result.is_error is False
    assert result.structured_content == sentinel
    assert calls == [{"ticker": " zzz ", "mode": "value", "refresh": True}]


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_refresh", ["true", "yes", 1, 0])
async def test_authenticated_http_rejects_non_boolean_refresh_before_dispatch(
    http_app,
    monkeypatch,
    invalid_refresh,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_service(**kwargs):
        calls.append(kwargs)
        return {"service": "analyze_ticker"}

    monkeypatch.setattr(equity_screening, "analyze_ticker_service", fake_service)
    transport = httpx2.ASGITransport(app=http_app)
    headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    async with http_app.router.lifespan_context(http_app):
        async with httpx2.AsyncClient(
            transport=transport,
            base_url=BASE_URL,
            headers=headers,
        ) as client:
            async with streamable_http_client(
                f"{BASE_URL}/mcp",
                http_client=client,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "analyze_ticker",
                        {"ticker": "MSFT", "refresh": invalid_refresh},
                    )

    assert result.is_error is True
    assert "valid boolean" in "\n".join(
        item.text for item in result.content if hasattr(item, "text")
    )
    assert calls == []


@pytest.mark.anyio
async def test_stdio_and_http_tool_schemas_match(http_app) -> None:
    transport = httpx2.ASGITransport(app=http_app)
    headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
    async with Client(equity_screening.mcp) as local_client:
        local_tools = (await local_client.list_tools()).tools

    async with http_app.router.lifespan_context(http_app):
        async with httpx2.AsyncClient(
            transport=transport,
            base_url=BASE_URL,
            headers=headers,
        ) as client:
            async with streamable_http_client(
                f"{BASE_URL}/mcp", http_client=client
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    http_tools = (await session.list_tools()).tools

    assert [tool.name for tool in http_tools] == [tool.name for tool in local_tools]
    assert [tool.input_schema for tool in http_tools] == [
        tool.input_schema for tool in local_tools
    ]
    assert [tool.output_schema for tool in http_tools] == [
        tool.output_schema for tool in local_tools
    ]


def test_mcp_rejects_untrusted_host_before_dispatch(
    http_client,
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        equity_screening,
        "screen_stocks_service",
        lambda **kwargs: calls.append(kwargs),
    )

    response = http_client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {TEST_TOKEN}",
            "Host": "attacker.example",
        },
        json=MCP_CALL,
    )

    assert response.status_code == 421
    assert response.text == "Invalid Host header"
    assert calls == []


def test_mcp_rejects_untrusted_origin_before_dispatch(
    http_client,
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        equity_screening,
        "screen_stocks_service",
        lambda **kwargs: calls.append(kwargs),
    )

    response = http_client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {TEST_TOKEN}",
            "Origin": "https://attacker.example",
        },
        json=MCP_CALL,
    )

    assert response.status_code == 403
    assert response.text == "Invalid Origin header"
    assert calls == []


def test_app_rejects_non_loopback_binding() -> None:
    with pytest.raises(ValueError, match="must bind to a loopback host"):
        create_app(TEST_TOKEN, host="0.0.0.0")
