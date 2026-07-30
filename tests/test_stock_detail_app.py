from __future__ import annotations

import socket
from pathlib import Path

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from src import scoring_contract, screening, stock_detail
from src.scoring_contract import ScoringContractError


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app/stock_screener.py"


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("Stock Detail UI test attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


def _factor_detail(
    factor: str,
    label: str,
    score: float,
    component: str,
) -> dict[str, object]:
    return {
        "factor": factor,
        "label": label,
        "score": score,
        "component_count": 1,
        "available_components": [component],
        "effective_metric_weights": {component: 1.0},
        "unavailable_reason": None,
        "components": [
            {
                "metric": component,
                "label": f"{label} stored component",
                "unit": "ratio",
                "raw_value": score / 100.0,
                "scoring_input": score / 100.0,
                "winsorized_value": score / 100.0,
                "score": score,
                "available": True,
                "unavailable_reason": None,
                "effective_weight": 1.0,
            }
        ],
    }


def _detail_result() -> dict[str, object]:
    factor_details = [
        _factor_detail("momentum", "Momentum", 81.25, "return_3m"),
        _factor_detail("quality", "Quality", 72.5, "profit_margin"),
        _factor_detail("valuation", "Valuation", 63.75, "annual_pe_proxy"),
        _factor_detail("risk", "Risk", 54.0, "volatility_20d"),
        _factor_detail(
            "sector_strength",
            "Sector Strength",
            45.5,
            "sector_median:relative_strength_3m",
        ),
    ]
    return {
        "service": "get_stock_detail",
        "accepted_run_id": "accepted_scores",
        "scoring_contract_version": "1.0.2",
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
        "input_feature_run_id": "accepted_features",
        "input_contract_version": "1.0.0",
        "as_of_date": "2026-07-13",
        "ticker": "ZZZ",
        "mode": "low_risk",
        "identity": {
            "ticker": "ZZZ",
            "company_name": "ZZZ Company",
            "cik": "0000000001",
            "sector": "Information Technology",
            "industry": "Synthetic Industry",
            "sec_entity_name": "ZZZ COMPANY INC",
        },
        "selected_mode": {
            "score": 37.25,
            "factor_count": 5,
            "available_factors": [
                "momentum",
                "quality",
                "valuation",
                "risk",
                "sector_strength",
            ],
            "effective_factor_weights": {
                "momentum": 0.10,
                "quality": 0.20,
                "valuation": 0.15,
                "risk": 0.45,
                "sector_strength": 0.10,
            },
            "unavailable_reason": "synthetic_mode_warning",
            "eligible_for_ranking": False,
            "ranking_exclusion_reasons": ["synthetic_ranking_exclusion"],
        },
        "factor_scores": {
            detail["factor"]: detail["score"] for detail in factor_details
        },
        "factor_details": factor_details,
        "price_history": {
            "series": [],
            "series_available": False,
            "availability_reason": (
                "Daily price rows are not included in the frozen accepted "
                "scoring artifact. Stored derived features remain available."
            ),
            "source": "twelve_data",
            "start_date": "2025-07-11",
            "end_date": "2026-07-10",
            "history_rows": 250,
        },
        "market_snapshot": {
            "price": 125.0,
            "market_cap_proxy": 100_000_000_000.0,
            "average_volume_20d": 2_000_000.0,
        },
        "market_features": [
            {
                "field": "return_3m",
                "label": "3-month return",
                "value": 0.1234,
                "unit": "decimal_return",
            },
            {
                "field": "average_volume_20d",
                "label": "20-day average share volume",
                "value": 2_000_000.0,
                "unit": "shares",
            },
        ],
        "market_quality": {
            "market_data_age_days": 3,
            "duplicate_date_count": 2,
            "missing_ohlcv_row_count": 1,
            "nonpositive_price_row_count": 0,
            "extreme_daily_move_count": 4,
            "unadjusted_price_warning": True,
        },
        "fundamentals": {
            "source": "sec_companyfacts",
            "latest_period_end": "2025-12-31",
            "latest_filed_date": "2026-02-15",
            "fundamental_age_days": 149,
            "metrics": [
                {
                    "field": "annual_revenue",
                    "label": "Annual revenue",
                    "value": 12_000_000_000.0,
                    "unit": "USD",
                    "period_end": "2025-12-31",
                    "period_field": "annual_revenue_period_end",
                    "source_tag": "RevenueFromContractWithCustomer",
                    "warning": "synthetic_revenue_warning",
                },
                {
                    "field": "market_cap_proxy",
                    "label": "Market-cap proxy",
                    "value": 100_000_000_000.0,
                    "unit": "USD",
                    "period_end": None,
                    "period_field": None,
                    "source_tag": "EntityCommonStockSharesOutstanding",
                    "warning": None,
                },
                {
                    "field": "annual_pe_proxy",
                    "label": "Annual P/E proxy",
                    "value": 19.5,
                    "unit": "ratio",
                    "period_end": None,
                    "period_field": None,
                    "source_tag": "NetIncomeLoss",
                    "warning": None,
                },
            ],
        },
        "sector_context": {
            "sector": "Information Technology",
            "industry": "Synthetic Industry",
            "company_relative_strength_3m": 0.08,
            "sector_median_relative_strength_3m": 0.03,
            "sector_strength_member_count": 68,
            "sector_strength_score": 45.5,
        },
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
        "quality": {
            "eligible_for_scoring": False,
            "missing_inputs": ["annual_pe_proxy"],
            "warnings": ["synthetic_quality_warning"],
            "stale_fundamental_metrics": ["profit_margin"],
            "base_exclusion_reasons": ["extreme_daily_move"],
            "market_error": "synthetic_market_error",
            "fundamental_error": "synthetic_fundamental_error",
        },
        "strengths": [
            {
                "code": "high_factor_score:momentum",
                "factor": "Momentum",
                "score": 81.25,
                "summary": "Strong stored Momentum evidence.",
            }
        ],
        "risks": [
            {
                "code": "low_factor_score:sector_strength",
                "factor": "Sector Strength",
                "score": 45.5,
                "summary": "Weak stored Sector Strength evidence.",
            }
        ],
        "reason_codes": [
            "accepted_snapshot_security",
            "ineligible_for_ranking:low_risk",
        ],
        "next_research_questions": [
            "What could change the stored evidence on the next snapshot?"
        ],
        "field_labels": {
            "price": "Latest adjusted daily price",
            "market_cap_proxy": (
                "Price times validated shares outstanding proxy"
            ),
            "annual_pe_proxy": (
                "Historical annual earnings proxy, not vendor or forward P/E"
            ),
            "average_volume_20d": "20-day average share volume",
            "risk_score": "Higher means lower measured risk",
            "sector_strength_score": (
                "Higher means stronger measured sector relative strength"
            ),
        },
    }


def _app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=10).run()


def _detail_app() -> AppTest:
    at = _app()
    return at.radio(key="view").set_value("Stock Detail").run()


def _submit_detail(at: AppTest) -> AppTest:
    return at.button(key="load_stock_detail").click().run()


def _dataframe_with_columns(at: AppTest, *columns: str):
    expected = set(columns)
    return next(
        element.value
        for element in at.dataframe
        if expected.issubset(element.value.columns)
    )


def test_default_navigation_preserves_screener_and_calls_no_service(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        screening,
        "screen_stocks",
        lambda **kwargs: calls.append("screen"),
    )
    monkeypatch.setattr(
        stock_detail,
        "get_stock_detail",
        lambda **kwargs: calls.append("detail"),
    )

    at = _app()

    assert not at.exception
    assert at.radio(key="view").value == "Stock Screener"
    assert "run_screen" in [button.key for button in at.button]
    assert "load_stock_detail" not in [button.key for button in at.button]
    assert calls == []


def test_detail_controls_forward_raw_ticker_and_mode_exactly_once(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_stock_detail(**kwargs):
        calls.append(kwargs)
        return _detail_result()

    monkeypatch.setattr(
        stock_detail,
        "get_stock_detail",
        fake_get_stock_detail,
    )
    at = _detail_app()
    assert calls == []

    at.text_input(key="detail_ticker").set_value(" brk.b ").run()
    at.selectbox(key="detail_mode").set_value("value").run()
    at = _submit_detail(at)

    assert not at.exception
    assert calls == [{"ticker": " brk.b ", "mode": "value"}]


def test_detail_ui_uses_only_dedicated_service_boundary(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fail(*args, **kwargs):
        raise AssertionError("Stock Detail UI bypassed its service")

    def fake_get_stock_detail(**kwargs):
        calls.append(kwargs)
        return _detail_result()

    monkeypatch.setattr(
        scoring_contract,
        "load_accepted_scoring_run",
        fail,
    )
    monkeypatch.setattr(pd, "read_parquet", fail)
    monkeypatch.setattr(screening, "screen_stocks", fail)
    monkeypatch.setattr(
        stock_detail,
        "get_stock_detail",
        fake_get_stock_detail,
    )

    at = _detail_app()
    at.text_input(key="detail_ticker").set_value("ZZZ").run()
    at = _submit_detail(at)

    assert not at.exception
    assert calls == [{"ticker": "ZZZ", "mode": "balanced"}]
    assert _dataframe_with_columns(at, "field", "label", "value")[
        "field"
    ].tolist() == ["return_3m", "average_volume_20d"]


def test_detail_rendering_preserves_adversarial_order_and_values(
    monkeypatch,
) -> None:
    response = _detail_result()
    response["mode"] = "balanced"
    response["selected_mode"] = {
        "score": 3.25,
        "factor_count": 2,
        "available_factors": ["risk", "momentum"],
        "effective_factor_weights": {
            "risk": 0.01,
            "momentum": 0.99,
        },
        "unavailable_reason": None,
        "eligible_for_ranking": True,
        "ranking_exclusion_reasons": [],
    }
    response["price_history"] = {
        "series": [
            {"date": "2026-07-02", "adjusted_close": 1.25},
            {"date": "2026-07-01", "adjusted_close": 999.5},
        ],
        "series_available": True,
        "availability_reason": None,
        "source": "synthetic",
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
        "history_rows": 2,
    }
    response["market_features"] = [
        {"field": "second", "label": "Second", "value": -7.5, "unit": "ratio"},
        {"field": "first", "label": "First", "value": 901.0, "unit": "ratio"},
    ]
    fundamentals = response["fundamentals"]
    fundamentals["metrics"] = [  # type: ignore[index]
        {
            "field": "second_fundamental",
            "label": "Second fundamental",
            "value": -22.0,
            "unit": "USD",
            "period_end": "2024-12-31",
            "period_field": "second_period_field",
            "source_tag": "second",
            "warning": None,
        },
        {
            "field": "first_fundamental",
            "label": "First fundamental",
            "value": 111.0,
            "unit": "USD",
            "period_end": "2025-12-31",
            "period_field": "first_period_field",
            "source_tag": "first",
            "warning": None,
        },
    ]
    response["factor_details"] = [
        _factor_detail("risk", "Risk", 1.0, "zeta_component"),
        _factor_detail("momentum", "Momentum", 99.0, "alpha_component"),
    ]
    monkeypatch.setattr(
        stock_detail,
        "get_stock_detail",
        lambda **kwargs: response,
    )

    at = _submit_detail(_detail_app())

    assert not at.exception
    history = _dataframe_with_columns(at, "date", "adjusted_close")
    market = _dataframe_with_columns(at, "field", "label", "value")
    fundamental = _dataframe_with_columns(
        at,
        "field",
        "period_end",
        "period_field",
    )
    factors = _dataframe_with_columns(
        at,
        "Factor",
        "Score",
        "Available component count",
    )
    weights = _dataframe_with_columns(
        at,
        "Factor",
        "Effective factor weight",
    )
    first_components = _dataframe_with_columns(
        at,
        "metric",
        "raw_value",
        "effective_weight",
    )

    assert history["date"].tolist() == ["2026-07-02", "2026-07-01"]
    assert history["adjusted_close"].tolist() == [1.25, 999.5]
    assert market["field"].tolist() == ["second", "first"]
    assert market["value"].tolist() == [-7.5, 901.0]
    assert fundamental["field"].tolist() == [
        "second_fundamental",
        "first_fundamental",
    ]
    assert fundamental["value"].tolist() == [-22.0, 111.0]
    assert factors["Factor"].tolist() == ["Risk", "Momentum"]
    assert factors["Score"].tolist() == [1.0, 99.0]
    assert weights["Factor"].tolist() == [
        "Risk (higher means lower measured risk)",
        "Momentum",
    ]
    assert weights["Effective factor weight"].tolist() == [0.01, 0.99]
    assert first_components["metric"].tolist() == ["zeta_component"]
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Balanced score"] == "3.25"


def test_detail_renders_complete_stored_evidence_and_terminology(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        stock_detail,
        "get_stock_detail",
        lambda **kwargs: _detail_result(),
    )

    at = _submit_detail(_detail_app())

    assert not at.exception
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Accepted run ID"] == "accepted_scores"
    assert metrics["As-of date"] == "2026-07-13"
    assert metrics["Selected mode"] == "Low Risk"
    assert metrics["Mode ranking eligibility"] == "Not eligible"
    assert metrics["Low Risk score"] == "37.25"
    assert metrics["Price-history source"] == "twelve_data"
    assert metrics["Latest fiscal period end"] == "2025-12-31"
    assert metrics["Latest filing across included fundamentals"] == (
        "2026-02-15"
    )
    assert "Market-cap proxy" in metrics
    assert "20-day average share volume" in metrics

    market = _dataframe_with_columns(at, "field", "label", "value")
    fundamentals = _dataframe_with_columns(
        at,
        "field",
        "period_end",
        "period_field",
    )
    factors = _dataframe_with_columns(
        at,
        "Factor",
        "Score",
        "Available component count",
    )
    sector = _dataframe_with_columns(
        at,
        "Sector",
        "Company 3-month relative strength versus SPY",
        "Sector Strength score",
    )
    quality = _dataframe_with_columns(at, "Evidence", "Value")
    dates = _dataframe_with_columns(at, "Relevant date", "Value")

    assert market["field"].tolist() == [
        "return_3m",
        "average_volume_20d",
    ]
    assert fundamentals["field"].tolist() == [
        "annual_revenue",
        "market_cap_proxy",
        "annual_pe_proxy",
    ]
    assert factors["Factor"].tolist() == [
        "Momentum",
        "Quality",
        "Valuation",
        "Risk",
        "Sector Strength",
    ]
    assert sector.iloc[0]["Sector"] == "Information Technology"
    assert sector.iloc[0]["Sector Strength score"] == 45.5
    assert quality["Evidence"].tolist() == [
        "market_data_age_days",
        "duplicate_date_count",
        "missing_ohlcv_row_count",
        "nonpositive_price_row_count",
        "extreme_daily_move_count",
        "unadjusted_price_warning",
    ]
    assert "Market price date" in dates["Relevant date"].tolist()
    assert "Latest fundamental filing date" in dates[
        "Relevant date"
    ].tolist()

    info_text = "\n".join(str(item.value) for item in at.info)
    warning_text = "\n".join(str(item.value) for item in at.warning)
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    caption_text = "\n".join(str(item.value) for item in at.caption)

    assert "Daily price rows are not included" in info_text
    assert "annual_pe_proxy" in info_text
    assert "synthetic_mode_warning" in warning_text
    assert "synthetic_ranking_exclusion" in warning_text
    assert "synthetic_quality_warning" in warning_text
    assert "profit_margin" in warning_text
    assert "extreme_daily_move" in warning_text
    assert "synthetic_market_error" in warning_text
    assert "synthetic_fundamental_error" in warning_text
    assert "Strong stored Momentum evidence." in markdown_text
    assert "Weak stored Sector Strength evidence." in markdown_text
    assert "accepted_snapshot_security" in markdown_text
    assert (
        "What could change the stored evidence on the next snapshot?"
        in markdown_text
    )
    assert "not authoritative market capitalization" in caption_text
    assert "Volume is measured in shares" in caption_text
    assert "higher Risk score means lower measured risk" in caption_text
    assert "stored historical proxies" in caption_text
    assert "snapshot-wide" in caption_text
    assert "Metric-specific filing dates are not stored" in caption_text
    assert "does not create a market or sector overview" in caption_text
    assert "educational and research purposes only" in caption_text


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (
            stock_detail.StockDetailValidationError("bad ticker"),
            "Invalid Stock Detail request: bad ticker",
        ),
        (
            stock_detail.StockDetailNotFoundError("UNKNOWN is absent"),
            "Stock Detail ticker not found: UNKNOWN is absent",
        ),
        (
            stock_detail.StockDetailDataError("missing evidence"),
            "Accepted Stock Detail data error: missing evidence",
        ),
        (
            ScoringContractError("hash mismatch"),
            "Accepted scoring run could not be verified: hash mismatch",
        ),
    ],
)
def test_detail_surfaces_known_errors_without_internal_traceback(
    monkeypatch,
    error: Exception,
    expected_message: str,
) -> None:
    def fail_detail(**kwargs):
        raise error

    monkeypatch.setattr(
        stock_detail,
        "get_stock_detail",
        fail_detail,
    )

    at = _submit_detail(_detail_app())

    assert not at.exception
    assert [item.value for item in at.error] == [expected_message]
