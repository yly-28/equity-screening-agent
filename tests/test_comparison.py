from __future__ import annotations

import json

import pytest
import requests

from src import comparison
from src.stock_detail import (
    StockDetailDataError,
    StockDetailNotFoundError,
    StockDetailValidationError,
)


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("comparison attempted network access")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_network)


def _detail(
    ticker: str,
    score: float | None,
    *,
    eligible: bool = True,
    as_of_date: str = "2026-07-13",
) -> dict[str, object]:
    return {
        "service": "get_stock_detail",
        "accepted_run_id": "accepted_scores",
        "scoring_contract_version": "1.0.2",
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
        "input_feature_run_id": "accepted_features",
        "input_contract_version": "1.0.0",
        "as_of_date": as_of_date,
        "ticker": ticker,
        "mode": "value",
        "identity": {
            "ticker": ticker,
            "company_name": f"Company {ticker}",
            "sector": "Technology",
            "industry": "Software",
            "cik": ticker,
        },
        "selected_mode": {
            "score": score,
            "eligible_for_ranking": eligible,
            "ranking_exclusion_reasons": (
                [] if eligible else ["missing_required_factor:valuation"]
            ),
            "effective_factor_weights": {"quality": 1.0} if score is not None else {},
        },
        "factor_scores": {
            "momentum": score,
            "quality": 50.0,
            "valuation": None,
            "risk": 60.0,
            "sector_strength": 70.0,
        },
        "market_snapshot": {
            "price": None if ticker == "BBB" else 100.0,
            "market_cap_proxy": 1_000_000.0,
            "average_volume_20d": 2_000.0,
        },
        "quality": {
            "eligible_for_scoring": True,
            "missing_inputs": ["annual_pe_proxy"] if not eligible else [],
            "warnings": [],
            "base_exclusion_reasons": [],
        },
        "strengths": [{"code": f"strength:{ticker}"}],
        "risks": [{"code": f"risk:{ticker}"}],
        "data_dates": {
            "as_of_date": as_of_date,
            "price_data_end": "2026-07-10",
            "fundamental_filed_date": None,
        },
    }


def test_comparison_preserves_requested_order_values_nulls_and_ineligibility(
    monkeypatch,
) -> None:
    source = {
        "CCC": _detail("CCC", 12.0),
        "AAA": _detail("AAA", 98.0),
        "BBB": _detail("BBB", 42.0, eligible=False),
    }
    calls: list[tuple[str, str]] = []

    def fake_detail(*, ticker, mode):
        calls.append((ticker, mode))
        return source[ticker]

    monkeypatch.setattr(comparison, "get_stock_detail_service", fake_detail)

    result = comparison.compare_stocks([" ccc ", "AAA", "bbb"], mode="VALUE")

    assert calls == [("CCC", "value"), ("AAA", "value"), ("BBB", "value")]
    assert [item["ticker"] for item in result["items"]] == ["CCC", "AAA", "BBB"]
    assert [item["request_position"] for item in result["items"]] == [1, 2, 3]
    assert result["items"][0]["selected_mode"]["score"] == 12.0
    assert result["items"][1]["selected_mode"]["score"] == 98.0
    assert result["items"][2]["selected_mode"]["eligible_for_ranking"] is False
    assert result["items"][2]["market_snapshot"]["price"] is None
    assert result["ordering"] == "requested_ticker_order"
    assert result["score_treatment"] == "stored_values_preserved_without_reranking"
    assert result["comparison_available"] is True
    json.dumps(result, allow_nan=False)


def test_unknown_tickers_are_explicit_and_remain_in_requested_position(
    monkeypatch,
) -> None:
    def fake_detail(*, ticker, mode):
        if ticker == "UNKNOWN":
            raise StockDetailNotFoundError("UNKNOWN was not fetched")
        return _detail(ticker, 50.0)

    monkeypatch.setattr(comparison, "get_stock_detail_service", fake_detail)

    result = comparison.compare_stocks(["AAA", "unknown", "BBB"], mode="value")

    assert [item["status"] for item in result["items"]] == [
        "available",
        "unknown",
        "available",
    ]
    assert result["items"][1] == {
        "request_position": 2,
        "status": "unknown",
        "ticker": "UNKNOWN",
        "reason_code": "ticker_not_in_accepted_snapshot",
        "message": "UNKNOWN was not fetched",
    }
    assert result["unknown_tickers"] == ["UNKNOWN"]
    assert result["unknown_count"] == 1


@pytest.mark.parametrize(
    "tickers",
    [
        ["AAA"],
        ["A", "B", "C", "D", "E", "F"],
        "AAA,BBB",
        ["AAA", " aaa "],
        ["AAA", ""],
        ["AAA", 123],
    ],
)
def test_comparison_validates_ticker_list_before_service_call(
    monkeypatch,
    tickers,
) -> None:
    monkeypatch.setattr(
        comparison,
        "get_stock_detail_service",
        lambda **kwargs: pytest.fail("detail service should not be called"),
    )

    with pytest.raises(comparison.ComparisonValidationError):
        comparison.compare_stocks(tickers)


def test_comparison_fails_closed_on_mixed_accepted_snapshots(monkeypatch) -> None:
    def fake_detail(*, ticker, mode):
        return _detail(
            ticker,
            50.0,
            as_of_date="2026-07-13" if ticker == "AAA" else "2026-07-14",
        )

    monkeypatch.setattr(comparison, "get_stock_detail_service", fake_detail)

    with pytest.raises(comparison.ComparisonDataError, match="one accepted snapshot"):
        comparison.compare_stocks(["AAA", "BBB"], mode="value")


@pytest.mark.parametrize(
    "detail_error",
    [
        StockDetailDataError("private accepted path: /internal/scores.parquet"),
        StockDetailValidationError("private validation implementation detail"),
    ],
)
def test_comparison_maps_stock_detail_failures_without_leaking_details(
    monkeypatch,
    detail_error,
) -> None:
    def fail_detail(*, ticker, mode):
        raise detail_error

    monkeypatch.setattr(comparison, "get_stock_detail_service", fail_detail)

    with pytest.raises(comparison.ComparisonDataError) as captured:
        comparison.compare_stocks(["AAA", "BBB"], mode="value")

    assert str(captured.value) == (
        "Stock Detail evidence could not be loaded for AAA"
    )
    assert str(detail_error) not in str(captured.value)
    assert captured.value.__cause__ is None
