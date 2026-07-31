from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

import pandas as pd
import pytest
import requests
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_servers import equity_screening as mcp_server
from src.comparison import ComparisonDataError, ComparisonValidationError
from src.live_analysis import (
    LiveAnalysisDataError,
    LiveAnalysisNotFoundError,
    LiveAnalysisValidationError,
)
from src.overview import OverviewDataError, OverviewValidationError
from src.scoring_contract import ScoringContractError
from src.screening import ScreeningDataError, ScreeningValidationError
from src.stock_detail import (
    StockDetailDataError,
    StockDetailNotFoundError,
    StockDetailValidationError,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("MCP boundary test attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


def _error_text(result) -> str:
    return "\n".join(
        item.text for item in result.content if hasattr(item, "text")
    )


@pytest.mark.anyio
async def test_tool_discovery_exposes_exactly_five_narrow_tools() -> None:
    async with Client(mcp_server.mcp) as client:
        discovered = await client.list_tools()

    assert [tool.name for tool in discovered.tools] == [
        "screen_stocks",
        "get_stock_detail",
        "analyze_ticker",
        "compare_stocks",
        "get_market_overview",
    ]
    by_name = {tool.name: tool for tool in discovered.tools}
    screen_schema = by_name["screen_stocks"].input_schema
    assert tuple(screen_schema["properties"]) == (
        "universe",
        "custom_tickers",
        "mode",
        "sectors",
        "minimum_price",
        "minimum_market_cap_proxy",
        "minimum_average_volume_20d",
        "minimum_factor_scores",
        "top_n",
    )
    assert screen_schema.get("required", []) == []
    detail_schema = by_name["get_stock_detail"].input_schema
    assert tuple(detail_schema["properties"]) == ("ticker", "mode")
    assert detail_schema["required"] == ["ticker"]
    analysis_schema = by_name["analyze_ticker"].input_schema
    assert tuple(analysis_schema["properties"]) == ("ticker", "mode", "refresh")
    assert analysis_schema["required"] == ["ticker"]
    comparison_schema = by_name["compare_stocks"].input_schema
    assert tuple(comparison_schema["properties"]) == ("tickers", "mode")
    assert comparison_schema["required"] == ["tickers"]
    overview_schema = by_name["get_market_overview"].input_schema
    assert tuple(overview_schema["properties"]) == ("mode", "sectors")
    assert overview_schema.get("required", []) == []


@pytest.mark.anyio
async def test_all_screening_arguments_map_directly_to_service(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    sentinel = {"service": "screen_stocks", "stocks": [], "exclusions": []}

    def fake_service(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(mcp_server, "screen_stocks_service", fake_service)
    arguments = {
        "universe": "custom",
        "custom_tickers": [" aapl ", "MSFT", "aapl"],
        "mode": "value",
        "sectors": ["Financials", "Information Technology"],
        "minimum_price": 12.5,
        "minimum_market_cap_proxy": 2_500_000_000.0,
        "minimum_average_volume_20d": 345_000.0,
        "minimum_factor_scores": {"quality": 60.0, "risk": 70.0},
        "top_n": 7,
    }

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool("screen_stocks", arguments)

    assert result.is_error is False
    assert result.structured_content == sentinel
    assert calls == [arguments]
    assert tuple(calls[0]) == tuple(arguments)


@pytest.mark.anyio
async def test_stock_detail_arguments_map_directly_to_service(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    sentinel = {"service": "get_stock_detail", "ticker": "BRK.B", "mode": "value"}

    def fake_service(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(mcp_server, "get_stock_detail_service", fake_service)

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "get_stock_detail",
            {"ticker": " brk.b ", "mode": "value"},
        )

    assert result.is_error is False
    assert result.structured_content == sentinel
    assert calls == [{"ticker": " brk.b ", "mode": "value"}]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "service_name", "arguments", "expected_call"),
    [
        (
            "analyze_ticker",
            "analyze_ticker_service",
            {"ticker": " new ", "mode": "growth", "refresh": True},
            {"ticker": " new ", "mode": "growth", "refresh": True},
        ),
        (
            "compare_stocks",
            "compare_stocks_service",
            {"tickers": [" zzz ", "AAA"], "mode": "low_risk"},
            {"tickers": [" zzz ", "AAA"], "mode": "low_risk"},
        ),
        (
            "get_market_overview",
            "get_market_overview_service",
            {"mode": "value", "sectors": ["Financials"]},
            {"mode": "value", "sectors": ["Financials"]},
        ),
    ],
)
async def test_new_tool_arguments_map_directly_to_services(
    monkeypatch,
    tool_name,
    service_name,
    arguments,
    expected_call,
) -> None:
    calls: list[dict[str, object]] = []
    sentinel = {"service": tool_name, "value": None}

    def fake_service(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(mcp_server, service_name, fake_service)

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is False
    assert result.structured_content == sentinel
    assert calls == [expected_call]


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_refresh", ["true", "yes", 1, 0])
async def test_analyze_ticker_rejects_non_boolean_refresh_before_dispatch(
    monkeypatch,
    invalid_refresh,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_service(**kwargs):
        calls.append(kwargs)
        return {"service": "analyze_ticker"}

    monkeypatch.setattr(mcp_server, "analyze_ticker_service", fake_service)

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "analyze_ticker",
            {"ticker": "MSFT", "refresh": invalid_refresh},
        )

    assert result.is_error is True
    assert "valid boolean" in _error_text(result)
    assert calls == []


@pytest.mark.anyio
async def test_successful_responses_preserve_order_values_and_json_nulls(
    monkeypatch,
) -> None:
    screening_response = {
        "service": "screen_stocks",
        "accepted_run_id": "accepted_scores",
        "stocks": [
            {"rank": 2, "ticker": "ZZZ", "mode_score": 1.25, "value": None},
            {"rank": 1, "ticker": "AAA", "mode_score": 99.75, "value": None},
        ],
        "unknown_tickers": ["UNKNOWN", "MISSING"],
        "warnings": ["synthetic_warning"],
        "exclusions": [
            {"ticker": "SECOND", "reasons": ["below_minimum:price"]},
            {"ticker": "FIRST", "reasons": ["outside_top_n"]},
        ],
    }
    detail_response = {
        "service": "get_stock_detail",
        "ticker": "PSKY",
        "selected_mode": {
            "score": 42.25,
            "eligible_for_ranking": False,
            "ranking_exclusion_reasons": [
                "missing_required_factor:valuation"
            ],
        },
        "factor_scores": {"valuation": None, "momentum": 80.0},
        "quality": {"eligible_for_scoring": True, "warnings": []},
    }
    monkeypatch.setattr(
        mcp_server,
        "screen_stocks_service",
        lambda **kwargs: screening_response,
    )
    monkeypatch.setattr(
        mcp_server,
        "get_stock_detail_service",
        lambda **kwargs: detail_response,
    )

    async with Client(mcp_server.mcp) as client:
        screened = await client.call_tool("screen_stocks", {})
        detail = await client.call_tool(
            "get_stock_detail", {"ticker": "PSKY", "mode": "value"}
        )

    assert screened.structured_content == screening_response
    assert [row["ticker"] for row in screened.structured_content["stocks"]] == [
        "ZZZ",
        "AAA",
    ]
    assert [row["ticker"] for row in screened.structured_content["exclusions"]] == [
        "SECOND",
        "FIRST",
    ]
    assert detail.structured_content == detail_response
    assert json.dumps(screened.structured_content, allow_nan=False)
    assert json.dumps(detail.structured_content, allow_nan=False)


@pytest.mark.anyio
async def test_empty_screening_and_base_ineligible_detail_pass_through(
    monkeypatch,
) -> None:
    empty_screen = {
        "service": "screen_stocks",
        "returned_count": 0,
        "stocks": [],
        "unknown_tickers": ["UNKNOWN"],
        "warnings": ["no_results"],
        "exclusions": [
            {
                "ticker": "AAA",
                "stage": "requested_filters",
                "reasons": ["below_minimum:price"],
            }
        ],
    }
    ineligible_detail = {
        "service": "get_stock_detail",
        "ticker": "ECHO",
        "selected_mode": {
            "score": None,
            "eligible_for_ranking": False,
            "ranking_exclusion_reasons": ["ineligible_for_scoring"],
        },
        "quality": {
            "eligible_for_scoring": False,
            "base_exclusion_reasons": ["extreme_daily_move"],
        },
        "factor_scores": {"risk": None},
    }
    monkeypatch.setattr(
        mcp_server, "screen_stocks_service", lambda **kwargs: empty_screen
    )
    monkeypatch.setattr(
        mcp_server,
        "get_stock_detail_service",
        lambda **kwargs: ineligible_detail,
    )

    async with Client(mcp_server.mcp) as client:
        screened = await client.call_tool("screen_stocks", {})
        detail = await client.call_tool(
            "get_stock_detail", {"ticker": "ECHO"}
        )

    assert screened.structured_content == empty_screen
    assert detail.structured_content == ineligible_detail


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "service_name", "error", "expected"),
    [
        (
            "screen_stocks",
            "screen_stocks_service",
            ScreeningValidationError("top_n must be positive"),
            "Invalid screen_stocks request: top_n must be positive",
        ),
        (
            "screen_stocks",
            "screen_stocks_service",
            ScreeningDataError("missing screening columns"),
            "Accepted screening data error",
        ),
        (
            "screen_stocks",
            "screen_stocks_service",
            ScoringContractError("hash mismatch"),
            "Accepted scoring run verification failed",
        ),
        (
            "get_stock_detail",
            "get_stock_detail_service",
            StockDetailValidationError("bad ticker"),
            "Invalid get_stock_detail request: bad ticker",
        ),
        (
            "get_stock_detail",
            "get_stock_detail_service",
            StockDetailNotFoundError("UNKNOWN was not fetched"),
            "Stock Detail ticker not found: UNKNOWN was not fetched",
        ),
        (
            "get_stock_detail",
            "get_stock_detail_service",
            StockDetailDataError("missing detail columns"),
            "Accepted Stock Detail data error",
        ),
        (
            "get_stock_detail",
            "get_stock_detail_service",
            ScoringContractError("hash mismatch"),
            "Accepted scoring run verification failed",
        ),
    ],
)
async def test_known_failures_become_clear_mcp_tool_errors_without_tracebacks(
    monkeypatch,
    tool_name: str,
    service_name: str,
    error: Exception,
    expected: str,
) -> None:
    def fail(**kwargs):
        raise error

    monkeypatch.setattr(mcp_server, service_name, fail)
    arguments = {} if tool_name == "screen_stocks" else {"ticker": "UNKNOWN"}

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(tool_name, arguments)

    message = _error_text(result)
    assert result.is_error is True
    assert expected in message
    assert "Traceback" not in message
    assert str(ROOT) not in message


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "service_name", "arguments", "error", "expected"),
    [
        (
            "analyze_ticker",
            "analyze_ticker_service",
            {"ticker": "BAD"},
            LiveAnalysisValidationError("bad ticker"),
            "Invalid analyze_ticker request: bad ticker",
        ),
        (
            "analyze_ticker",
            "analyze_ticker_service",
            {"ticker": "MISS"},
            LiveAnalysisNotFoundError("ticker absent"),
            "Ticker analysis not found: ticker absent",
        ),
        (
            "analyze_ticker",
            "analyze_ticker_service",
            {"ticker": "BAD"},
            LiveAnalysisDataError("provider boundary invalid"),
            "Ticker analysis data error",
        ),
        (
            "compare_stocks",
            "compare_stocks_service",
            {"tickers": ["ONLY"]},
            ComparisonValidationError("two tickers required"),
            "Invalid compare_stocks request: two tickers required",
        ),
        (
            "compare_stocks",
            "compare_stocks_service",
            {"tickers": ["AAA", "BBB"]},
            ComparisonDataError("snapshot mismatch"),
            "Accepted comparison data error",
        ),
        (
            "get_market_overview",
            "get_market_overview_service",
            {},
            OverviewValidationError("bad sector"),
            "Invalid get_market_overview request: bad sector",
        ),
        (
            "get_market_overview",
            "get_market_overview_service",
            {},
            OverviewDataError("missing columns"),
            "Accepted overview data error",
        ),
    ],
)
async def test_new_tool_failures_are_concise_without_tracebacks(
    monkeypatch,
    tool_name,
    service_name,
    arguments,
    error,
    expected,
) -> None:
    def fail(**kwargs):
        raise error

    monkeypatch.setattr(mcp_server, service_name, fail)
    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(tool_name, arguments)

    message = _error_text(result)
    assert result.is_error is True
    assert expected in message
    assert "Traceback" not in message
    assert str(ROOT) not in message


@pytest.mark.anyio
async def test_data_errors_never_expose_paths_or_secret_text(monkeypatch) -> None:
    secret = "sk-internal-sensitive-token"

    def fail(**kwargs):
        raise ScreeningDataError(
            f"cannot read {ROOT}/private.parquet\nTraceback token={secret}"
        )

    monkeypatch.setattr(mcp_server, "screen_stocks_service", fail)
    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool("screen_stocks", {})

    message = _error_text(result)
    assert result.is_error is True
    assert "Accepted screening data error" in message
    assert str(ROOT) not in message
    assert secret not in message
    assert "private.parquet" not in message
    assert "Traceback" not in message


@pytest.mark.anyio
async def test_adapter_has_no_provider_parquet_or_network_boundary(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_service(**kwargs):
        calls.append(kwargs)
        return {"service": "screen_stocks", "stocks": [], "exclusions": []}

    def fail(*args, **kwargs):
        raise AssertionError("MCP adapter bypassed its service boundary")

    monkeypatch.setattr(mcp_server, "screen_stocks_service", fake_service)
    monkeypatch.setattr(pd, "read_parquet", fail)

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool("screen_stocks", {"top_n": 1})

    assert result.is_error is False
    assert calls == [
        {
            "universe": "sp500",
            "custom_tickers": None,
            "mode": "balanced",
            "sectors": None,
            "minimum_price": None,
            "minimum_market_cap_proxy": None,
            "minimum_average_volume_20d": None,
            "minimum_factor_scores": None,
            "top_n": 1,
        }
    ]


@pytest.mark.anyio
async def test_protocol_level_stdio_smoke_discovers_five_tools() -> None:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.equity_screening"],
        cwd=ROOT,
        env=environment,
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            discovered = await session.list_tools()

    assert [tool.name for tool in discovered.tools] == [
        "screen_stocks",
        "get_stock_detail",
        "analyze_ticker",
        "compare_stocks",
        "get_market_overview",
    ]
