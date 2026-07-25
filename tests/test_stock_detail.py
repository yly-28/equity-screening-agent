from __future__ import annotations

import json
import socket
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests

import src.stock_detail as stock_detail
from src.scoring_contract import AcceptedScoringRun
from src.stock_detail import (
    StockDetailDataError,
    StockDetailNotFoundError,
    StockDetailValidationError,
    get_stock_detail,
)


FACTOR_NAMES = (
    "momentum",
    "quality",
    "valuation",
    "risk",
    "sector_strength",
)
MODE_NAMES = ("balanced", "growth", "value", "low_risk")
EXPECTED_FACTOR_METRICS = {
    "momentum": (
        "return_1m",
        "return_3m",
        "return_6m",
        "ma20_gap",
        "ma50_gap",
        "volume_trend",
    ),
    "quality": (
        "revenue_growth",
        "profit_margin",
        "roe",
        "free_cash_flow_margin",
    ),
    "valuation": ("annual_pe_proxy",),
    "risk": (
        "volatility_20d",
        "volatility_60d",
        "beta_1y",
        "liabilities_to_equity",
        "max_drawdown_1y",
    ),
    "sector_strength": ("sector_median:relative_strength_3m",),
}


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("stock-detail test attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


def _json_weights(names: tuple[str, ...] | list[str]) -> str:
    if not names:
        return "{}"
    weight = 1.0 / len(names)
    return json.dumps({name: weight for name in names})


def _row(
    ticker: str = "AAA",
    *,
    company_name: str | None = None,
    eligible_for_scoring: bool = True,
) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": ticker,
        "company_name": company_name or f"{ticker} Company",
        "sector": "Information Technology",
        "industry": "Synthetic Systems",
        "cik": "0000000123",
        "sec_entity_name": f"{ticker} LEGAL ENTITY",
        "as_of_date": "2026-07-13",
        "market_data_source": "twelve_data",
        "price_data_start": "2025-06-09",
        "price_data_end": "2026-07-10",
        "market_data_age_days": 3,
        "fundamental_data_source": "sec_companyfacts",
        "fundamental_period_end": "2025-12-31",
        "fundamental_filed_date": "2026-02-15",
        "fundamental_age_days": 148,
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income_period_end": "2025-12-31",
        "profit_margin_period_end": "2025-12-31",
        "roe_period_end": "2025-12-31",
        "leverage_period_end": "2025-12-31",
        "free_cash_flow_period_end": "2025-12-31",
        "shares_outstanding_period_end": "2026-01-31",
        "data_quality_flags": np.array(
            ["synthetic_quality_warning"], dtype=object
        ),
        "missing_fields": np.array([], dtype=object),
        "stale_fundamental_metrics": np.array(["roe"], dtype=object),
        "exclusion_reasons": np.array([], dtype=object),
        "eligible_for_scoring": eligible_for_scoring,
        "market_error": None,
        "fundamental_error": None,
        "history_rows": 273,
        "duplicate_date_count": 0,
        "missing_ohlcv_row_count": 0,
        "nonpositive_price_row_count": 0,
        "extreme_daily_move_count": 0,
        "unadjusted_price_warning": True,
        "input_feature_run_id": "accepted_features",
        "input_contract_version": "1.0.0",
        "sector_strength_source_value": 0.075,
        "sector_strength_member_count": 73,
        "revenue_source_tag": "Revenue",
        "revenue_basis_warning": None,
        "revenue_growth_quality_warning": None,
        "net_income_source_tag": "NetIncomeLoss",
        "profit_margin_quality_warning": None,
        "equity_source_tag": "StockholdersEquity",
        "equity_quality_warning": None,
        "liabilities_source_tag": "Liabilities",
        "cash_flow_source_tag": "OperatingCashFlow",
        "shares_source_tag": "EntityCommonStockSharesOutstanding",
        "shares_quality_warning": None,
        "capex_source_tag": "CapitalExpenditure",
    }

    market_values = {
        "price": 125.5,
        "average_volume_20d": 2_500_000.0,
        "return_1d": 0.012,
        "return_1m": 0.11,
        "return_3m": 0.22,
        "return_6m": 0.33,
        "relative_strength_3m": 0.09,
        "volatility_20d": 0.21,
        "volatility_60d": 0.24,
        "max_drawdown_1y": -0.18,
        "ma20_gap": 0.04,
        "ma50_gap": 0.07,
        "volume_trend": 0.15,
        "beta_1y": 0.82,
    }
    row.update(market_values)

    fundamental_values = {
        "annual_revenue": 10_000_000_000.0,
        "annual_net_income": 1_000_000_000.0,
        "revenue_growth": 0.12,
        "profit_margin": 0.10,
        "profit_margin_raw": 0.10,
        "roe": 0.18,
        "liabilities_to_equity": 0.65,
        "annual_free_cash_flow": 900_000_000.0,
        "free_cash_flow_margin": 0.09,
        "shares_outstanding": 500_000_000.0,
        "market_cap_proxy": 62_750_000_000.0,
        "annual_pe_proxy": 62.75,
        "annual_capex": np.nan,
        "annual_diluted_eps": 2.0,
        "annual_operating_cash_flow": 1_100_000_000.0,
        "stockholders_equity": 5_000_000_000.0,
        "total_assets": 12_000_000_000.0,
        "total_liabilities": 7_000_000_000.0,
    }
    row.update(fundamental_values)

    metric_score = 51.0
    for factor_name, metrics in EXPECTED_FACTOR_METRICS.items():
        if factor_name == "sector_strength":
            continue
        for metric_name in metrics:
            raw_value = float(row[metric_name])
            row.update(
                {
                    f"{metric_name}_scoring_input": raw_value + 0.001,
                    f"{metric_name}_winsorized": raw_value + 0.002,
                    f"{metric_name}_score": metric_score,
                    f"{metric_name}_available": True,
                    f"{metric_name}_unavailable_reason": None,
                }
            )
            metric_score += 1.0

    factor_scores = {
        "momentum": 82.0,
        "quality": 75.0,
        "valuation": 61.0,
        "risk": 20.0,
        "sector_strength": 72.0,
    }
    for factor_name, metrics in EXPECTED_FACTOR_METRICS.items():
        row.update(
            {
                f"{factor_name}_score": factor_scores[factor_name],
                f"{factor_name}_component_count": len(metrics),
                f"{factor_name}_available_components": np.array(
                    metrics, dtype=object
                ),
                f"{factor_name}_effective_metric_weights": _json_weights(
                    list(metrics)
                ),
                f"{factor_name}_unavailable_reason": None,
            }
        )

    for index, mode_name in enumerate(MODE_NAMES):
        row.update(
            {
                f"{mode_name}_score": 80.0 + index,
                f"{mode_name}_factor_count": len(FACTOR_NAMES),
                f"{mode_name}_available_factors": np.array(
                    FACTOR_NAMES, dtype=object
                ),
                f"{mode_name}_effective_factor_weights": _json_weights(
                    list(FACTOR_NAMES)
                ),
                f"{mode_name}_unavailable_reason": None,
                f"{mode_name}_eligible_for_ranking": True,
                f"{mode_name}_ranking_exclusion_reasons": np.array(
                    [], dtype=object
                ),
            }
        )
    return row


def _mode_ineligible_row() -> dict[str, object]:
    row = _row("PSKY", company_name="Paramount Skydance Corporation")
    available = [
        "momentum",
        "quality",
        "risk",
        "sector_strength",
    ]
    row.update(
        {
            "missing_fields": np.array(["annual_pe_proxy"], dtype=object),
            "valuation_score": np.nan,
            "valuation_component_count": 0,
            "valuation_available_components": np.array([], dtype=object),
            "valuation_effective_metric_weights": "{}",
            "valuation_unavailable_reason": "no_available_components",
            "annual_pe_proxy": np.nan,
            "annual_pe_proxy_scoring_input": np.nan,
            "annual_pe_proxy_winsorized": np.nan,
            "annual_pe_proxy_score": np.nan,
            "annual_pe_proxy_available": False,
            "annual_pe_proxy_unavailable_reason": "missing_value",
            "value_score": 42.25,
            "value_factor_count": 4,
            "value_available_factors": np.array(available, dtype=object),
            "value_effective_factor_weights": _json_weights(available),
            "value_unavailable_reason": None,
            "value_eligible_for_ranking": False,
            "value_ranking_exclusion_reasons": np.array(
                ["missing_required_factor:valuation"], dtype=object
            ),
        }
    )
    return row


def _base_ineligible_row() -> dict[str, object]:
    row = _row("ECHO", company_name="EchoStar", eligible_for_scoring=False)
    row.update(
        {
            "data_quality_flags": np.array(
                [
                    "extreme_daily_move",
                    "fundamentals_skipped_market_ineligible",
                ],
                dtype=object,
            ),
            "missing_fields": np.array(
                ["annual_revenue", "annual_net_income"], dtype=object
            ),
            "stale_fundamental_metrics": np.array([], dtype=object),
            "exclusion_reasons": np.array(
                ["extreme_daily_move"], dtype=object
            ),
            "extreme_daily_move_count": 1,
        }
    )
    for factor_name, metrics in EXPECTED_FACTOR_METRICS.items():
        row[f"{factor_name}_score"] = np.nan
        row[f"{factor_name}_component_count"] = 0
        row[f"{factor_name}_available_components"] = np.array(
            [], dtype=object
        )
        row[f"{factor_name}_effective_metric_weights"] = "{}"
        row[f"{factor_name}_unavailable_reason"] = "ineligible_for_scoring"
        if factor_name == "sector_strength":
            continue
        for metric_name in metrics:
            row[f"{metric_name}_scoring_input"] = np.nan
            row[f"{metric_name}_winsorized"] = np.nan
            row[f"{metric_name}_score"] = np.nan
            row[f"{metric_name}_available"] = False
            row[f"{metric_name}_unavailable_reason"] = (
                "ineligible_for_scoring"
            )
    for mode_name in MODE_NAMES:
        row[f"{mode_name}_score"] = np.nan
        row[f"{mode_name}_factor_count"] = 0
        row[f"{mode_name}_available_factors"] = np.array([], dtype=object)
        row[f"{mode_name}_effective_factor_weights"] = "{}"
        row[f"{mode_name}_unavailable_reason"] = "ineligible_for_scoring"
        row[f"{mode_name}_eligible_for_ranking"] = False
        row[f"{mode_name}_ranking_exclusion_reasons"] = np.array(
            ["ineligible_for_scoring"], dtype=object
        )
    return row


def _accepted(frame: pd.DataFrame) -> AcceptedScoringRun:
    return AcceptedScoringRun(
        scored_matrix=frame,
        metadata={
            "run_id": "accepted_scores",
            "as_of_date": "2026-07-13",
            "factor_model_version": "1.0.0",
            "screening_modes_version": "1.0.0",
        },
        quality={},
        contract={"scoring_contract": {"version": "1.0.2"}},
        run_dir=Path("/synthetic/accepted_scores"),
    )


def _install_loader(
    monkeypatch,
    *frames: pd.DataFrame,
) -> list[Path]:
    calls: list[Path] = []
    call_index = 0

    def load(project_root: Path) -> AcceptedScoringRun:
        nonlocal call_index
        calls.append(project_root)
        frame = frames[min(call_index, len(frames) - 1)]
        call_index += 1
        return _accepted(frame)

    monkeypatch.setattr(
        stock_detail.scoring_contract,
        "load_accepted_scoring_run",
        load,
    )
    return calls


def _factor(
    result: dict[str, object],
    factor_name: str,
) -> dict[str, object]:
    return next(
        item
        for item in result["factor_details"]  # type: ignore[union-attr]
        if item["factor"] == factor_name
    )


def _component(
    result: dict[str, object],
    factor_name: str,
    metric_name: str,
) -> dict[str, object]:
    factor = _factor(result, factor_name)
    return next(
        item
        for item in factor["components"]  # type: ignore[union-attr]
        if item["metric"] == metric_name
    )


def _feature(
    result: dict[str, object],
    field_name: str,
) -> dict[str, object]:
    return next(
        item
        for item in result["market_features"]  # type: ignore[union-attr]
        if item["field"] == field_name
    )


def _fundamental(
    result: dict[str, object],
    field_name: str,
) -> dict[str, object]:
    fundamentals = result["fundamentals"]
    return next(
        item
        for item in fundamentals["metrics"]  # type: ignore[union-attr]
        if item["field"] == field_name
    )


def test_success_projects_stored_detail_evidence_without_recomputation(
    monkeypatch,
) -> None:
    frame = pd.DataFrame([_row()])
    calls = _install_loader(monkeypatch, frame)

    result = get_stock_detail("AAA", mode="balanced")

    assert calls == [stock_detail.PROJECT_ROOT]
    assert result["service"] == "get_stock_detail"
    assert result["accepted_run_id"] == "accepted_scores"
    assert result["scoring_contract_version"] == "1.0.2"
    assert result["factor_model_version"] == "1.0.0"
    assert result["screening_modes_version"] == "1.0.0"
    assert result["input_feature_run_id"] == "accepted_features"
    assert result["input_contract_version"] == "1.0.0"
    assert result["as_of_date"] == "2026-07-13"
    assert result["ticker"] == "AAA"
    assert result["mode"] == "balanced"
    assert result["identity"] == {
        "ticker": "AAA",
        "company_name": "AAA Company",
        "cik": "0000000123",
        "sector": "Information Technology",
        "industry": "Synthetic Systems",
        "sec_entity_name": "AAA LEGAL ENTITY",
    }

    selected = result["selected_mode"]
    assert selected["score"] == 80.0
    assert selected["factor_count"] == 5
    assert selected["available_factors"] == list(FACTOR_NAMES)
    assert selected["eligible_for_ranking"] is True
    assert selected["ranking_exclusion_reasons"] == []
    assert sum(selected["effective_factor_weights"].values()) == pytest.approx(
        1.0
    )

    assert list(result["factor_scores"]) == list(FACTOR_NAMES)
    assert result["factor_scores"]["momentum"] == 82.0
    assert [item["factor"] for item in result["factor_details"]] == list(
        FACTOR_NAMES
    )
    assert {
        item["factor"]: tuple(
            component["metric"] for component in item["components"]
        )
        for item in result["factor_details"]
    } == EXPECTED_FACTOR_METRICS

    return_1m = _component(result, "momentum", "return_1m")
    assert return_1m == {
        "metric": "return_1m",
        "label": "1-month return",
        "unit": "decimal_return",
        "raw_value": 0.11,
        "scoring_input": 0.111,
        "winsorized_value": 0.112,
        "score": 51.0,
        "available": True,
        "unavailable_reason": None,
        "effective_weight": pytest.approx(1.0 / 6.0),
    }
    sector_component = _component(
        result,
        "sector_strength",
        "sector_median:relative_strength_3m",
    )
    assert sector_component["raw_value"] == 0.075
    assert sector_component["score"] == 72.0
    assert sector_component["available"] is True

    assert _feature(result, "price")["value"] == 125.5
    assert _feature(result, "average_volume_20d") == {
        "field": "average_volume_20d",
        "label": "20-day average share volume",
        "value": 2_500_000.0,
        "unit": "shares",
    }
    revenue = _fundamental(result, "annual_revenue")
    assert revenue["value"] == 10_000_000_000.0
    assert revenue["period_end"] == "2025-12-31"
    assert revenue["period_field"] == "annual_revenue_period_end"
    assert revenue["source_tag"] == "Revenue"
    assert result["fundamentals"]["latest_filed_date"] == "2026-02-15"
    market_cap_proxy = _fundamental(result, "market_cap_proxy")
    assert market_cap_proxy["period_end"] is None
    assert market_cap_proxy["period_field"] is None
    assert _fundamental(result, "profit_margin_raw")["label"] == (
        "Raw profit margin (audit only)"
    )
    assert _fundamental(result, "annual_capex")["value"] is None

    assert result["sector_context"] == {
        "sector": "Information Technology",
        "industry": "Synthetic Systems",
        "company_relative_strength_3m": 0.09,
        "sector_median_relative_strength_3m": 0.075,
        "sector_strength_member_count": 73,
        "sector_strength_score": 72.0,
    }
    assert result["quality"]["warnings"] == [
        "synthetic_quality_warning",
        "stale_fundamental_metric:roe",
    ]
    assert result["quality"]["stale_fundamental_metrics"] == ["roe"]
    assert result["quality"]["eligible_for_scoring"] is True
    assert any(item["factor"] == "Momentum" for item in result["strengths"])
    assert any(item["factor"] == "Risk" for item in result["risks"])
    assert "eligible_for_ranking:balanced" in result["reason_codes"]
    assert "quality_warning_present" in result["reason_codes"]
    assert result["next_research_questions"]


@pytest.mark.parametrize(
    ("requested_mode", "expected_mode", "expected_score"),
    [
        (" BALANCED ", "balanced", 80.0),
        ("Growth", "growth", 81.0),
        (" VALUE", "value", 82.0),
        ("low_RISK ", "low_risk", 83.0),
    ],
)
def test_normalizes_ticker_and_all_supported_modes(
    monkeypatch,
    requested_mode: str,
    expected_mode: str,
    expected_score: float,
) -> None:
    _install_loader(monkeypatch, pd.DataFrame([_row("AAA")]))

    result = get_stock_detail("  aaa  ", mode=requested_mode)

    assert result["ticker"] == "AAA"
    assert result["identity"]["ticker"] == "AAA"
    assert result["mode"] == expected_mode
    assert result["selected_mode"]["score"] == expected_score


@pytest.mark.parametrize(
    ("ticker", "mode", "expected_message"),
    [
        ("", "balanced", "ticker must be a non-empty string"),
        ("   ", "balanced", "ticker must be a non-empty string"),
        (None, "balanced", "ticker must be a non-empty string"),
        (123, "balanced", "ticker must be a non-empty string"),
        ("AAA", "", "mode must be a non-empty string"),
        ("AAA", None, "mode must be a non-empty string"),
        ("AAA", "high_opportunity", "Unsupported mode"),
    ],
)
def test_invalid_requests_fail_before_loading(
    monkeypatch,
    ticker: object,
    mode: object,
    expected_message: str,
) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("invalid request reached accepted loader")

    monkeypatch.setattr(
        stock_detail.scoring_contract,
        "load_accepted_scoring_run",
        fail,
    )

    with pytest.raises(StockDetailValidationError, match=expected_message):
        get_stock_detail(ticker, mode=mode)  # type: ignore[arg-type]


def test_unknown_ticker_is_reported_without_fetching(
    monkeypatch,
) -> None:
    calls = _install_loader(monkeypatch, pd.DataFrame([_row("AAA")]))

    with pytest.raises(
        StockDetailNotFoundError,
        match=(
            "Ticker MISSING is not present in the accepted local "
            r"S&P 500 snapshot and was not fetched"
        ),
    ):
        get_stock_detail(" missing ")

    assert calls == [stock_detail.PROJECT_ROOT]


def test_duplicate_ticker_match_fails_closed(monkeypatch) -> None:
    frame = pd.DataFrame(
        [
            _row("AAA", company_name="First"),
            _row("aaa", company_name="Second"),
        ]
    )
    _install_loader(monkeypatch, frame)

    with pytest.raises(
        StockDetailDataError,
        match="contains 2 rows for ticker AAA",
    ):
        get_stock_detail("AAA")


@pytest.mark.parametrize(
    "missing_column",
    [
        "return_1m_scoring_input",
        "balanced_effective_factor_weights",
        "fundamental_filed_date",
        "revenue_source_tag",
        "shares_quality_warning",
    ],
)
def test_missing_detail_schema_fails_closed(
    monkeypatch,
    missing_column: str,
) -> None:
    frame = pd.DataFrame([_row()]).drop(columns=[missing_column])
    _install_loader(monkeypatch, frame)

    with pytest.raises(
        StockDetailDataError,
        match=(
            "Accepted scored matrix is missing stock-detail columns: "
            + missing_column
        ),
    ):
        get_stock_detail("AAA")


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_message"),
    [
        (
            "balanced_effective_factor_weights",
            "{not-json",
            "balanced_effective_factor_weights is not valid JSON",
        ),
        (
            "momentum_effective_metric_weights",
            ["not", "a", "mapping"],
            "momentum_effective_metric_weights must be a mapping",
        ),
        (
            "missing_fields",
            "annual_pe_proxy",
            "missing_fields must be a list of strings",
        ),
        (
            "return_1m_available",
            "yes",
            "return_1m_available must be boolean",
        ),
        (
            "eligible_for_scoring",
            1,
            "eligible_for_scoring must be boolean",
        ),
    ],
)
def test_malformed_stored_data_raises_detail_data_error(
    monkeypatch,
    field: str,
    bad_value: object,
    expected_message: str,
) -> None:
    row = _row()
    row[field] = bad_value
    _install_loader(monkeypatch, pd.DataFrame([row]))

    with pytest.raises(StockDetailDataError, match=expected_message):
        get_stock_detail("AAA")


def test_mode_ineligible_detail_preserves_diagnostic_score_and_reasons(
    monkeypatch,
) -> None:
    _install_loader(monkeypatch, pd.DataFrame([_mode_ineligible_row()]))

    result = get_stock_detail("psky", mode="value")

    selected = result["selected_mode"]
    assert selected["score"] == 42.25
    assert selected["factor_count"] == 4
    assert selected["eligible_for_ranking"] is False
    assert selected["ranking_exclusion_reasons"] == [
        "missing_required_factor:valuation"
    ]
    assert selected["available_factors"] == [
        "momentum",
        "quality",
        "risk",
        "sector_strength",
    ]
    assert "valuation" not in selected["effective_factor_weights"]
    assert sum(selected["effective_factor_weights"].values()) == pytest.approx(
        1.0
    )
    assert result["quality"]["eligible_for_scoring"] is True
    assert result["factor_scores"]["valuation"] is None
    valuation = _factor(result, "valuation")
    assert valuation["score"] is None
    assert valuation["component_count"] == 0
    assert valuation["unavailable_reason"] == "no_available_components"
    annual_pe = _component(result, "valuation", "annual_pe_proxy")
    assert annual_pe["available"] is False
    assert annual_pe["raw_value"] is None
    assert annual_pe["unavailable_reason"] == "missing_value"
    assert "ineligible_for_ranking:value" in result["reason_codes"]
    assert "missing_required_factor:valuation" in result["reason_codes"]
    assert "mode_weights_renormalized" in result["reason_codes"]


def test_base_ineligible_security_keeps_identity_quality_and_market_evidence(
    monkeypatch,
) -> None:
    _install_loader(monkeypatch, pd.DataFrame([_base_ineligible_row()]))

    result = get_stock_detail("ECHO", mode="balanced")

    assert result["identity"]["company_name"] == "EchoStar"
    assert result["selected_mode"]["score"] is None
    assert result["selected_mode"]["eligible_for_ranking"] is False
    assert result["selected_mode"]["ranking_exclusion_reasons"] == [
        "ineligible_for_scoring"
    ]
    assert all(value is None for value in result["factor_scores"].values())
    assert result["quality"]["eligible_for_scoring"] is False
    assert result["quality"]["base_exclusion_reasons"] == [
        "extreme_daily_move"
    ]
    assert result["quality"]["missing_inputs"] == [
        "annual_revenue",
        "annual_net_income",
    ]
    assert result["quality"]["warnings"] == [
        "extreme_daily_move",
        "fundamentals_skipped_market_ineligible",
    ]
    assert _feature(result, "price")["value"] == 125.5
    assert _component(result, "momentum", "return_1m")["score"] is None
    assert "ineligible_for_scoring" in result["reason_codes"]
    assert "ineligible_for_ranking:balanced" in result["reason_codes"]
    assert "mode_weights_renormalized" not in result["reason_codes"]


def test_output_is_strictly_json_ready_and_converts_nulls(
    monkeypatch,
) -> None:
    row = _mode_ineligible_row()
    row["market_error"] = np.nan
    row["fundamental_error"] = pd.NA
    row["annual_capex"] = np.nan
    _install_loader(monkeypatch, pd.DataFrame([row]))

    result = get_stock_detail("PSKY", mode="value")

    encoded = json.dumps(result, allow_nan=False)
    assert '"annual_capex"' in encoded
    assert _fundamental(result, "annual_capex")["value"] is None
    assert result["quality"]["market_error"] is None
    assert result["quality"]["fundamental_error"] is None


def test_service_uses_only_the_accepted_loader_boundary(
    monkeypatch,
) -> None:
    calls = _install_loader(monkeypatch, pd.DataFrame([_row()]))

    def fail(*args, **kwargs):
        raise AssertionError("stock detail bypassed its accepted service boundary")

    monkeypatch.setattr(pd, "read_parquet", fail)
    monkeypatch.setattr(stock_detail.screening, "screen_stocks", fail)

    result = get_stock_detail("AAA")

    assert result["ticker"] == "AAA"
    assert calls == [stock_detail.PROJECT_ROOT]


def test_frame_preservation_and_result_invariance_to_row_order(
    monkeypatch,
) -> None:
    frame = pd.DataFrame([_row("AAA"), _row("BBB")])
    reordered = frame.iloc[::-1].reset_index(drop=True)
    original = frame.copy(deep=True)
    original_reordered = reordered.copy(deep=True)
    _install_loader(monkeypatch, frame, reordered)

    baseline = get_stock_detail("AAA", mode="growth")
    repeated = get_stock_detail("AAA", mode="growth")

    assert baseline == repeated
    pd.testing.assert_frame_equal(frame, original)
    pd.testing.assert_frame_equal(reordered, original_reordered)


def test_terminology_and_price_history_limit_are_explicit(
    monkeypatch,
) -> None:
    _install_loader(monkeypatch, pd.DataFrame([_row()]))

    result = get_stock_detail("AAA")

    labels = result["field_labels"]
    assert labels["average_volume_20d"] == "20-day average share volume"
    assert labels["market_cap_proxy"] == (
        "Price times validated shares outstanding proxy"
    )
    assert labels["annual_pe_proxy"] == (
        "Historical annual earnings proxy, not vendor or forward P/E"
    )
    assert labels["risk_score"] == "Higher means lower measured risk"
    assert "proxy" in _fundamental(result, "market_cap_proxy")["label"].lower()

    history = result["price_history"]
    assert history["series"] == []
    assert history["series_available"] is False
    assert history["start_date"] == "2025-06-09"
    assert history["end_date"] == "2026-07-10"
    assert history["history_rows"] == 273
    assert "not included in the frozen accepted scoring artifact" in (
        history["availability_reason"]
    )
    assert "without reading unverified provider caches" in (
        history["availability_reason"]
    )
    assert "rank" not in result
    assert "dollar liquidity" not in json.dumps(result).lower()
