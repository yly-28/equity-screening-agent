from __future__ import annotations

import socket
from pathlib import Path

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from app import stock_screener
from src import scoring_contract, screening
from src.scoring_contract import ScoringContractError


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app/stock_screener.py"
STREAMLIT_CONFIG_PATH = ROOT / ".streamlit/config.toml"
FACTOR_NAMES = (
    "momentum",
    "quality",
    "valuation",
    "risk",
    "sector_strength",
)


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("UI test attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


def _stock(
    ticker: str,
    rank: int,
    mode_score: float,
    *,
    warnings: list[str] | None = None,
    missing_inputs: list[str] | None = None,
) -> dict[str, object]:
    factor_scores = {
        "momentum": 80.0,
        "quality": 70.0,
        "valuation": 60.0,
        "risk": 50.0,
        "sector_strength": 40.0,
    }
    return {
        "rank": rank,
        "ticker": ticker,
        "company_name": f"{ticker} Company",
        "cik": "0000000001",
        "sector": "Information Technology",
        "industry": "Synthetic Industry",
        "screening_mode": "balanced",
        "mode_score": mode_score,
        "factor_scores": factor_scores,
        "effective_factor_weights": {
            factor_name: 0.2 for factor_name in FACTOR_NAMES
        },
        "available_factors": list(FACTOR_NAMES),
        "price": 125.0,
        "market_cap_proxy": 100_000_000_000.0,
        "average_volume_20d": 2_000_000.0,
        "average_volume_20d_label": "20-day average share volume",
        "data_sources": {
            "market": "twelve_data",
            "fundamentals": "sec_companyfacts",
        },
        "data_dates": {
            "as_of_date": "2026-07-13",
            "price_data_end": "2026-07-10",
            "fundamental_period_end": "2025-12-31",
            "fundamental_filed_date": "2026-02-15",
            "annual_revenue_period_end": "2025-12-31",
            "annual_net_income_period_end": "2025-12-31",
            "profit_margin_period_end": "2025-12-31",
            "roe_period_end": "2025-12-31",
            "leverage_period_end": "2025-12-31",
            "free_cash_flow_period_end": "2025-12-31",
            "shares_outstanding_period_end": "2026-01-31",
        },
        "missing_inputs": missing_inputs or [],
        "warnings": warnings or [],
        "strengths": [
            {
                "code": "high_factor_score:momentum",
                "factor": "Momentum",
                "score": 80.0,
                "summary": "Strong stored Momentum evidence.",
            }
        ],
        "risks": [
            {
                "code": "low_factor_score:sector_strength",
                "factor": "Sector Strength",
                "score": 40.0,
                "summary": "Weak stored Sector Strength evidence.",
            }
        ],
        "reason_codes": [
            "ranked_by_stored_score:balanced",
            "passes_requested_filters",
        ],
        "next_research_questions": [
            "What could change the stored evidence on the next snapshot?"
        ],
    }


def _result(
    *,
    stocks: list[dict[str, object]] | None = None,
    unknown_tickers: list[str] | None = None,
    exclusions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    stock_rows = stocks if stocks is not None else [_stock("AAA", 1, 88.0)]
    exclusion_rows = exclusions or []
    unknown = unknown_tickers or []
    return {
        "service": "screen_stocks",
        "accepted_run_id": "accepted_scores",
        "scoring_contract_version": "1.0.2",
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
        "as_of_date": "2026-07-13",
        "universe": "sp500",
        "requested_tickers": [],
        "unknown_tickers": unknown,
        "mode": "balanced",
        "filters": {
            "sectors": [],
            "minimum_price": None,
            "minimum_market_cap_proxy": None,
            "minimum_average_volume_20d": None,
            "top_n": 20,
        },
        "field_labels": {
            "price": "Latest adjusted daily price",
            "market_cap_proxy": (
                "Price times validated shares outstanding proxy"
            ),
            "average_volume_20d": "20-day average share volume",
            "risk_score": "Higher means lower measured risk",
        },
        "candidate_count": len(stock_rows) + len(exclusion_rows),
        "ranking_eligible_count": len(stock_rows),
        "candidate_count_before_top_n": len(stock_rows),
        "returned_count": len(stock_rows),
        "truncated_count": 0,
        "excluded_count": len(exclusion_rows),
        "mode_ineligible_count": 0,
        "filter_excluded_count": len(exclusion_rows),
        "top_n_excluded_count": 0,
        "unknown_ticker_count": len(unknown),
        "exclusion_reason_counts": {},
        "stocks": stock_rows,
        "exclusions": exclusion_rows,
    }


def _app() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    return at.radio(key="view").set_value("Screen Stocks").run()


def _submit(at: AppTest) -> AppTest:
    return at.button(key="run_screen").click().run()


def _dataframe_with_column(at: AppTest, column: str):
    return next(
        element.value
        for element in at.dataframe
        if column in element.value.columns
    )


def test_streamlit_usage_telemetry_is_disabled() -> None:
    config = STREAMLIT_CONFIG_PATH.read_text(encoding="utf-8")

    assert "[browser]" in config
    assert "gatherUsageStats = false" in config


def test_execute_screening_forwards_base_arguments_unchanged(
    monkeypatch,
) -> None:
    request = {
        "universe": "custom",
        "custom_tickers": [" aapl ", "MSFT", "aapl"],
        "mode": "value",
        "sectors": ["Financials", "Information Technology"],
        "minimum_price": 12.5,
        "minimum_market_cap_proxy": 2_500_000_000.0,
        "minimum_average_volume_20d": 345_000.0,
        "top_n": 7,
    }
    sentinel = _result()
    calls: list[dict[str, object]] = []

    def fake_screen_stocks(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = stock_screener.execute_screening(request)

    assert result is sentinel
    assert calls == [request]
    assert tuple(calls[0]) == (
        "universe",
        "custom_tickers",
        "mode",
        "sectors",
        "minimum_price",
        "minimum_market_cap_proxy",
        "minimum_average_volume_20d",
        "top_n",
    )


def test_display_projections_preserve_service_order_scores_and_exclusions() -> None:
    stocks = [_stock("ZZZ", 2, 12.25), _stock("AAA", 1, 99.75)]
    exclusions = [
        {
            "ticker": "SECOND",
            "company_name": "Second Company",
            "sector": "Energy",
            "screening_mode": "balanced",
            "mode_score": 42.0,
            "stage": "requested_filters",
            "reasons": ["below_minimum:price"],
        },
        {
            "ticker": "FIRST",
            "company_name": "First Company",
            "sector": "Financials",
            "screening_mode": "balanced",
            "mode_score": 41.0,
            "stage": "top_n",
            "reasons": ["outside_top_n"],
        },
    ]
    result = _result(stocks=stocks, exclusions=exclusions)

    ranked = stock_screener.ranked_company_rows(result)
    excluded = stock_screener.exclusion_rows(result)

    assert [row["Ticker"] for row in ranked] == ["ZZZ", "AAA"]
    assert [row["Selected mode score"] for row in ranked] == [12.25, 99.75]
    assert [row["Momentum"] for row in ranked] == [80.0, 80.0]
    assert [row["Ticker"] for row in excluded] == ["SECOND", "FIRST"]
    assert [row["Exclusion reasons"] for row in excluded] == [
        "below_minimum:price",
        "outside_top_n",
    ]


def test_app_controls_map_to_all_screening_arguments(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_screen_stocks(**kwargs):
        calls.append(kwargs)
        result = _result()
        result["universe"] = kwargs["universe"]
        result["mode"] = kwargs["mode"]
        result["filters"] = {
            "sectors": kwargs["sectors"] or [],
            "minimum_price": kwargs["minimum_price"],
            "minimum_market_cap_proxy": kwargs[
                "minimum_market_cap_proxy"
            ],
            "minimum_average_volume_20d": kwargs[
                "minimum_average_volume_20d"
            ],
            "top_n": kwargs["top_n"],
        }
        return result

    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)
    at = _app()
    assert calls == []

    at.selectbox(key="universe").set_value("custom").run()
    at.text_area(key="custom_tickers").set_value(" aapl \nMSFT\naapl").run()
    at.selectbox(key="mode").set_value("value").run()
    at.multiselect(key="sectors").set_value(
        ["Financials", "Information Technology"]
    ).run()
    at.number_input(key="minimum_price").set_value(12.5).run()
    at.number_input(key="minimum_market_cap_proxy").set_value(
        2_500_000_000.0
    ).run()
    at.number_input(key="minimum_average_volume_20d").set_value(
        345_000.0
    ).run()
    factor_minimums = {
        "momentum": 55.0,
        "quality": 60.0,
        "valuation": 65.0,
        "risk": 70.0,
        "sector_strength": 75.0,
    }
    for factor_name, value in factor_minimums.items():
        at.number_input(key=f"minimum_factor_{factor_name}").set_value(
            value
        ).run()
    at.number_input(key="top_n").set_value(7).run()
    at = _submit(at)

    assert not at.exception
    assert calls == [
        {
            "universe": "custom",
            "custom_tickers": [" aapl ", "MSFT", "aapl"],
            "mode": "value",
            "sectors": ["Financials", "Information Technology"],
            "minimum_price": 12.5,
            "minimum_market_cap_proxy": 2_500_000_000.0,
            "minimum_average_volume_20d": 345_000.0,
            "minimum_factor_scores": factor_minimums,
            "top_n": 7,
        }
    ]


def test_app_renders_results_without_filtering_scoring_or_reordering(
    monkeypatch,
) -> None:
    stocks = [
        _stock(
            "ZZZ",
            2,
            12.25,
            warnings=["synthetic_quality_warning"],
            missing_inputs=["annual_pe_proxy"],
        ),
        _stock("AAA", 1, 99.75),
    ]
    exclusions = [
        {
            "ticker": "OUT",
            "company_name": "Excluded Company",
            "sector": "Energy",
            "screening_mode": "balanced",
            "mode_score": 77.0,
            "stage": "requested_filters",
            "reasons": ["below_minimum:price"],
        }
    ]
    response = _result(
        stocks=stocks,
        unknown_tickers=["UNKNOWN"],
        exclusions=exclusions,
    )
    monkeypatch.setattr(
        screening, "screen_stocks", lambda **kwargs: response
    )

    at = _submit(_app())

    assert not at.exception
    ranked = _dataframe_with_column(at, "Selected mode score")
    excluded = _dataframe_with_column(at, "Exclusion reasons")
    unknown = _dataframe_with_column(at, "Unknown custom ticker")

    assert ranked["Ticker"].tolist() == ["ZZZ", "AAA"]
    assert ranked["Selected mode score"].tolist() == [12.25, 99.75]
    assert excluded["Ticker"].tolist() == ["OUT"]
    assert excluded["Exclusion reasons"].tolist() == ["below_minimum:price"]
    assert unknown["Unknown custom ticker"].tolist() == ["UNKNOWN"]
    assert ranked["Market data date"].tolist() == ["2026-07-10", "2026-07-10"]
    assert ranked["Warnings"].tolist() == ["synthetic_quality_warning", ""]
    assert ranked["Top strength"].iloc[0] == "Strong stored Momentum evidence."
    assert ranked["Top risk"].iloc[0] == "Weak stored Sector Strength evidence."
    assert any("UNKNOWN" in warning.value for warning in at.warning)
    metrics = {item.label: item.value for item in at.metric}
    assert metrics["Accepted run ID"] == "accepted_scores"
    assert metrics["As-of date"] == "2026-07-13"
    assert "Market-cap proxy (USD)" in ranked.columns
    assert "20-day average share volume" in ranked.columns
    assert "Risk (higher = lower measured risk)" in ranked.columns


def test_app_uses_only_screen_stocks_data_boundary(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fail(*args, **kwargs):
        raise AssertionError("UI bypassed screen_stocks")

    def fake_screen_stocks(**kwargs):
        calls.append(kwargs)
        return _result()

    monkeypatch.setattr(
        scoring_contract, "load_accepted_scoring_run", fail
    )
    monkeypatch.setattr(pd, "read_parquet", fail)
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    at = _submit(_app())

    assert not at.exception
    assert len(calls) == 1
    assert _dataframe_with_column(at, "Selected mode score")[
        "Ticker"
    ].tolist() == ["AAA"]


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (
            screening.ScreeningValidationError("bad request"),
            "Invalid screening request: bad request",
        ),
        (
            screening.ScreeningDataError("missing evidence"),
            "Accepted screening data error: missing evidence",
        ),
        (
            ScoringContractError("hash mismatch"),
            "Accepted scoring run could not be verified: hash mismatch",
        ),
    ],
)
def test_app_surfaces_known_errors_without_internal_traceback(
    monkeypatch,
    error: Exception,
    expected_message: str,
) -> None:
    def fail_screen(**kwargs):
        raise error

    monkeypatch.setattr(screening, "screen_stocks", fail_screen)

    at = _submit(_app())

    assert not at.exception
    assert [item.value for item in at.error] == [expected_message]


def test_app_handles_empty_results_unknown_tickers_and_exclusions(
    monkeypatch,
) -> None:
    exclusion = {
        "ticker": "AAA",
        "company_name": "AAA Company",
        "sector": "Information Technology",
        "screening_mode": "balanced",
        "mode_score": 88.0,
        "stage": "requested_filters",
        "reasons": ["below_minimum:price"],
    }
    response = _result(
        stocks=[],
        unknown_tickers=["UNKNOWN"],
        exclusions=[exclusion],
    )
    monkeypatch.setattr(
        screening, "screen_stocks", lambda **kwargs: response
    )

    at = _submit(_app())

    assert not at.exception
    assert any(
        "No ranked companies matched" in item.value for item in at.info
    )
    assert _dataframe_with_column(at, "Unknown custom ticker")[
        "Unknown custom ticker"
    ].tolist() == ["UNKNOWN"]
    assert _dataframe_with_column(at, "Exclusion reasons")[
        "Exclusion reasons"
    ].tolist() == ["below_minimum:price"]
