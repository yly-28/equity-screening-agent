"""Deterministic single-security detail over the accepted scoring snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Optional

import pandas as pd

from src import scoring_contract, screening
from src.explanations import FACTOR_FIELDS, build_stock_explanations


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_MODES = screening.SUPPORTED_MODES

FACTOR_METRICS = {
    "momentum": (
        ("return_1m", "1-month return", "decimal_return"),
        ("return_3m", "3-month return", "decimal_return"),
        ("return_6m", "6-month return", "decimal_return"),
        ("ma20_gap", "Price gap to 20-day moving average", "decimal_ratio"),
        ("ma50_gap", "Price gap to 50-day moving average", "decimal_ratio"),
        (
            "volume_trend",
            "20-day versus prior 20-day share-volume trend",
            "decimal_ratio",
        ),
    ),
    "quality": (
        ("revenue_growth", "Annual revenue growth", "decimal_ratio"),
        ("profit_margin", "Profit margin", "decimal_ratio"),
        ("roe", "Return on equity", "decimal_ratio"),
        ("free_cash_flow_margin", "Free-cash-flow margin", "decimal_ratio"),
    ),
    "valuation": (
        ("annual_pe_proxy", "Annual P/E proxy", "ratio"),
    ),
    "risk": (
        ("volatility_20d", "20-day annualized volatility", "annualized_decimal"),
        ("volatility_60d", "60-day annualized volatility", "annualized_decimal"),
        ("beta_1y", "1-year beta", "ratio"),
        ("liabilities_to_equity", "Liabilities to equity", "ratio"),
        ("max_drawdown_1y", "1-year maximum drawdown", "decimal_return"),
    ),
    "sector_strength": (
        (
            "sector_median:relative_strength_3m",
            "Sector median 3-month relative strength",
            "excess_decimal_return",
        ),
    ),
}

MARKET_FEATURES = (
    ("price", "Latest adjusted daily price", "USD"),
    ("average_volume_20d", "20-day average share volume", "shares"),
    ("return_1d", "1-day return", "decimal_return"),
    ("return_1m", "1-month return", "decimal_return"),
    ("return_3m", "3-month return", "decimal_return"),
    ("return_6m", "6-month return", "decimal_return"),
    (
        "relative_strength_3m",
        "3-month relative strength versus SPY",
        "excess_decimal_return",
    ),
    ("volatility_20d", "20-day annualized volatility", "annualized_decimal"),
    ("volatility_60d", "60-day annualized volatility", "annualized_decimal"),
    ("max_drawdown_1y", "1-year maximum drawdown", "decimal_return"),
    ("ma20_gap", "Price gap to 20-day moving average", "decimal_ratio"),
    ("ma50_gap", "Price gap to 50-day moving average", "decimal_ratio"),
    ("volume_trend", "20-day versus prior 20-day share-volume trend", "decimal_ratio"),
    ("beta_1y", "1-year beta", "ratio"),
)

FUNDAMENTAL_METRICS = (
    (
        "annual_revenue",
        "Annual revenue",
        "USD",
        "annual_revenue_period_end",
        "revenue_source_tag",
        "revenue_basis_warning",
    ),
    (
        "annual_net_income",
        "Annual net income",
        "USD",
        "annual_net_income_period_end",
        "net_income_source_tag",
        None,
    ),
    (
        "revenue_growth",
        "Annual revenue growth",
        "decimal_ratio",
        "annual_revenue_period_end",
        "revenue_source_tag",
        "revenue_growth_quality_warning",
    ),
    (
        "profit_margin",
        "Profit margin",
        "decimal_ratio",
        "profit_margin_period_end",
        "revenue_source_tag",
        "profit_margin_quality_warning",
    ),
    (
        "profit_margin_raw",
        "Raw profit margin (audit only)",
        "decimal_ratio",
        "profit_margin_period_end",
        "revenue_source_tag",
        "profit_margin_quality_warning",
    ),
    (
        "roe",
        "Return on equity",
        "decimal_ratio",
        "roe_period_end",
        "equity_source_tag",
        "equity_quality_warning",
    ),
    (
        "liabilities_to_equity",
        "Liabilities-to-equity leverage proxy",
        "ratio",
        "leverage_period_end",
        "liabilities_source_tag",
        "equity_quality_warning",
    ),
    (
        "annual_free_cash_flow",
        "Annual free cash flow",
        "USD",
        "free_cash_flow_period_end",
        "cash_flow_source_tag",
        None,
    ),
    (
        "free_cash_flow_margin",
        "Free-cash-flow margin",
        "decimal_ratio",
        "free_cash_flow_period_end",
        "cash_flow_source_tag",
        None,
    ),
    (
        "shares_outstanding",
        "Validated shares outstanding",
        "shares",
        "shares_outstanding_period_end",
        "shares_source_tag",
        "shares_quality_warning",
    ),
    (
        "market_cap_proxy",
        "Market-cap proxy",
        "USD",
        None,
        "shares_source_tag",
        "shares_quality_warning",
    ),
    (
        "annual_pe_proxy",
        "Annual P/E proxy",
        "ratio",
        None,
        "net_income_source_tag",
        None,
    ),
    (
        "annual_capex",
        "Annual capital expenditure",
        "USD",
        None,
        "capex_source_tag",
        None,
    ),
    (
        "annual_diluted_eps",
        "Annual diluted EPS",
        "USD_per_share",
        None,
        None,
        None,
    ),
    (
        "annual_operating_cash_flow",
        "Annual operating cash flow",
        "USD",
        None,
        "cash_flow_source_tag",
        None,
    ),
    (
        "stockholders_equity",
        "Stockholders' equity",
        "USD",
        None,
        "equity_source_tag",
        "equity_quality_warning",
    ),
    (
        "total_assets",
        "Total assets",
        "USD",
        None,
        None,
        None,
    ),
    (
        "total_liabilities",
        "Total liabilities",
        "USD",
        None,
        "liabilities_source_tag",
        None,
    ),
)

PRICE_HISTORY_REASON = (
    "Daily price rows are not included in the frozen accepted scoring artifact. "
    "The detail service exposes verified history coverage and derived market "
    "features without reading unverified provider caches."
)


class StockDetailValidationError(ValueError):
    """Raised when a stock-detail request is invalid."""


class StockDetailNotFoundError(LookupError):
    """Raised when a ticker is absent from the accepted local snapshot."""


class StockDetailDataError(RuntimeError):
    """Raised when accepted data cannot satisfy the stock-detail schema."""


def _normalize_ticker(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StockDetailValidationError("ticker must be a non-empty string")
    return value.strip().upper()


def _normalize_mode(value: object) -> str:
    try:
        return screening._normalize_choice(  # noqa: SLF001
            value,
            "mode",
            SUPPORTED_MODES,
        )
    except screening.ScreeningValidationError as exc:
        raise StockDetailValidationError(str(exc)) from exc


def _number(value: object) -> Optional[float]:
    return screening._number_or_none(value)  # noqa: SLF001


def _scalar(value: object) -> object:
    return screening._scalar_or_none(value)  # noqa: SLF001


def _string_list(value: object, label: str) -> list[str]:
    try:
        return screening._as_string_list(value, label)  # noqa: SLF001
    except screening.ScreeningDataError as exc:
        raise StockDetailDataError(str(exc)) from exc


def _weights(value: object, label: str) -> dict[str, float]:
    try:
        return screening._parse_weights(value, label)  # noqa: SLF001
    except screening.ScreeningDataError as exc:
        raise StockDetailDataError(str(exc)) from exc


def _boolean(value: object, label: str) -> bool:
    scalar = _scalar(value)
    if not isinstance(scalar, bool):
        raise StockDetailDataError(f"{label} must be boolean")
    return scalar


def _warnings(row: pd.Series) -> list[str]:
    try:
        return screening._warnings(row)  # noqa: SLF001
    except screening.ScreeningDataError as exc:
        raise StockDetailDataError(str(exc)) from exc


def _required_columns(mode: str) -> set[str]:
    columns = {
        "ticker",
        "company_name",
        "sector",
        "industry",
        "cik",
        "as_of_date",
        "market_data_source",
        "price_data_start",
        "price_data_end",
        "market_data_age_days",
        "fundamental_data_source",
        "fundamental_period_end",
        "fundamental_filed_date",
        "fundamental_age_days",
        "data_quality_flags",
        "missing_fields",
        "stale_fundamental_metrics",
        "exclusion_reasons",
        "eligible_for_scoring",
        "market_error",
        "fundamental_error",
        "history_rows",
        "duplicate_date_count",
        "missing_ohlcv_row_count",
        "nonpositive_price_row_count",
        "extreme_daily_move_count",
        "unadjusted_price_warning",
        "input_feature_run_id",
        "input_contract_version",
        f"{mode}_score",
        f"{mode}_factor_count",
        f"{mode}_available_factors",
        f"{mode}_effective_factor_weights",
        f"{mode}_unavailable_reason",
        f"{mode}_eligible_for_ranking",
        f"{mode}_ranking_exclusion_reasons",
        "sector_strength_source_value",
        "sector_strength_member_count",
    }
    columns.update(screening.DATE_FIELDS)
    columns.update(field for field, _, _ in MARKET_FEATURES)
    for (
        field_name,
        _,
        _,
        _,
        source_field,
        warning_field,
    ) in FUNDAMENTAL_METRICS:
        columns.add(field_name)
        if source_field is not None:
            columns.add(source_field)
        if warning_field is not None:
            columns.add(warning_field)

    for factor_name, _ in FACTOR_FIELDS:
        columns.update(
            {
                f"{factor_name}_score",
                f"{factor_name}_component_count",
                f"{factor_name}_available_components",
                f"{factor_name}_effective_metric_weights",
                f"{factor_name}_unavailable_reason",
            }
        )
        if factor_name == "sector_strength":
            continue
        for metric_name, _, _ in FACTOR_METRICS[factor_name]:
            columns.update(
                {
                    metric_name,
                    f"{metric_name}_scoring_input",
                    f"{metric_name}_winsorized",
                    f"{metric_name}_score",
                    f"{metric_name}_available",
                    f"{metric_name}_unavailable_reason",
                }
            )
    return columns


def _factor_component(
    row: pd.Series,
    metric_name: str,
    label: str,
    unit: str,
    effective_weights: Mapping[str, float],
) -> dict[str, object]:
    if metric_name == "sector_median:relative_strength_3m":
        score = _number(row["sector_strength_score"])
        return {
            "metric": metric_name,
            "label": label,
            "unit": unit,
            "raw_value": _number(row["sector_strength_source_value"]),
            "scoring_input": None,
            "winsorized_value": None,
            "score": score,
            "available": score is not None,
            "unavailable_reason": _scalar(
                row["sector_strength_unavailable_reason"]
            ),
            "effective_weight": effective_weights.get(metric_name),
        }

    return {
        "metric": metric_name,
        "label": label,
        "unit": unit,
        "raw_value": _number(row[metric_name]),
        "scoring_input": _number(row[f"{metric_name}_scoring_input"]),
        "winsorized_value": _number(row[f"{metric_name}_winsorized"]),
        "score": _number(row[f"{metric_name}_score"]),
        "available": _boolean(
            row[f"{metric_name}_available"],
            f"{metric_name}_available",
        ),
        "unavailable_reason": _scalar(
            row[f"{metric_name}_unavailable_reason"]
        ),
        "effective_weight": effective_weights.get(metric_name),
    }


def _factor_details(row: pd.Series) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for factor_name, label in FACTOR_FIELDS:
        weights_field = f"{factor_name}_effective_metric_weights"
        weights = _weights(row[weights_field], weights_field)
        details.append(
            {
                "factor": factor_name,
                "label": label,
                "score": _number(row[f"{factor_name}_score"]),
                "component_count": _scalar(
                    row[f"{factor_name}_component_count"]
                ),
                "available_components": _string_list(
                    row[f"{factor_name}_available_components"],
                    f"{factor_name}_available_components",
                ),
                "effective_metric_weights": weights,
                "unavailable_reason": _scalar(
                    row[f"{factor_name}_unavailable_reason"]
                ),
                "components": [
                    _factor_component(
                        row,
                        metric_name,
                        metric_label,
                        unit,
                        weights,
                    )
                    for metric_name, metric_label, unit in FACTOR_METRICS[
                        factor_name
                    ]
                ],
            }
        )
    return details


def _fundamental_rows(row: pd.Series) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (
        field_name,
        label,
        unit,
        period_field,
        source_field,
        warning_field,
    ) in FUNDAMENTAL_METRICS:
        rows.append(
            {
                "field": field_name,
                "label": label,
                "value": _number(row[field_name]),
                "unit": unit,
                "period_end": (
                    _scalar(row[period_field])
                    if period_field is not None
                    else None
                ),
                "period_field": period_field,
                "source_tag": (
                    _scalar(row.get(source_field))
                    if source_field is not None
                    else None
                ),
                "warning": (
                    _scalar(row.get(warning_field))
                    if warning_field is not None
                    else None
                ),
            }
        )
    return rows


def _reason_codes(
    *,
    mode: str,
    eligible_for_scoring: bool,
    eligible_for_ranking: bool,
    ranking_reasons: list[str],
    weights: Mapping[str, float],
    warnings: list[str],
    strengths: list[dict[str, object]],
    risks: list[dict[str, object]],
) -> list[str]:
    codes = [
        "accepted_snapshot_security",
        (
            "eligible_for_scoring"
            if eligible_for_scoring
            else "ineligible_for_scoring"
        ),
        (
            f"eligible_for_ranking:{mode}"
            if eligible_for_ranking
            else f"ineligible_for_ranking:{mode}"
        ),
        *ranking_reasons,
        *(str(item["code"]) for item in strengths),
        *(str(item["code"]) for item in risks),
    ]
    if weights and len(weights) < len(FACTOR_FIELDS):
        codes.append("mode_weights_renormalized")
    if warnings:
        codes.append("quality_warning_present")
    return screening._dedupe_strings(codes)  # noqa: SLF001


def get_stock_detail(
    ticker: str,
    mode: str = "balanced",
) -> dict[str, object]:
    """Return stored features and evidence for one accepted-snapshot security.

    The service loads data only through
    :func:`src.scoring_contract.load_accepted_scoring_run`. It normalizes the
    requested ticker and mode, projects stored accepted values, and never
    fetches providers, reads an arbitrary artifact, or recomputes scores.
    """

    normalized_ticker = _normalize_ticker(ticker)
    normalized_mode = _normalize_mode(mode)
    accepted = scoring_contract.load_accepted_scoring_run(PROJECT_ROOT)
    frame = accepted.scored_matrix

    missing_columns = sorted(
        _required_columns(normalized_mode) - set(frame.columns)
    )
    if missing_columns:
        raise StockDetailDataError(
            "Accepted scored matrix is missing stock-detail columns: "
            + ", ".join(missing_columns)
        )

    matches = frame.loc[
        frame["ticker"].astype(str).str.upper().eq(normalized_ticker)
    ]
    if matches.empty:
        raise StockDetailNotFoundError(
            f"Ticker {normalized_ticker} is not present in the accepted local "
            "S&P 500 snapshot and was not fetched"
        )
    if len(matches) != 1:
        raise StockDetailDataError(
            f"Accepted scored matrix contains {len(matches)} rows for ticker "
            f"{normalized_ticker}"
        )
    row = matches.iloc[0]

    missing_inputs = _string_list(row["missing_fields"], "missing_fields")
    stale_metrics = _string_list(
        row["stale_fundamental_metrics"],
        "stale_fundamental_metrics",
    )
    base_exclusion_reasons = _string_list(
        row["exclusion_reasons"],
        "exclusion_reasons",
    )
    warnings = _warnings(row)
    factor_scores = {
        factor_name: _number(row[f"{factor_name}_score"])
        for factor_name, _ in FACTOR_FIELDS
    }
    strengths, risks, questions = build_stock_explanations(
        factor_scores,
        missing_inputs,
        _scalar(row["fundamental_filed_date"]),
    )

    mode_weights_field = f"{normalized_mode}_effective_factor_weights"
    mode_weights = _weights(row[mode_weights_field], mode_weights_field)
    mode_available_field = f"{normalized_mode}_available_factors"
    available_factors = _string_list(
        row[mode_available_field],
        mode_available_field,
    )
    ranking_reasons_field = (
        f"{normalized_mode}_ranking_exclusion_reasons"
    )
    ranking_reasons = _string_list(
        row[ranking_reasons_field],
        ranking_reasons_field,
    )
    eligible_for_scoring = _boolean(
        row["eligible_for_scoring"],
        "eligible_for_scoring",
    )
    eligible_for_ranking = _boolean(
        row[f"{normalized_mode}_eligible_for_ranking"],
        f"{normalized_mode}_eligible_for_ranking",
    )
    contract_header = accepted.contract.get("scoring_contract", {})
    if not isinstance(contract_header, Mapping):
        contract_header = {}

    return {
        "service": "get_stock_detail",
        "accepted_run_id": accepted.metadata.get("run_id"),
        "scoring_contract_version": contract_header.get("version"),
        "factor_model_version": accepted.metadata.get(
            "factor_model_version"
        ),
        "screening_modes_version": accepted.metadata.get(
            "screening_modes_version"
        ),
        "input_feature_run_id": _scalar(row["input_feature_run_id"]),
        "input_contract_version": _scalar(row["input_contract_version"]),
        "as_of_date": _scalar(accepted.metadata.get("as_of_date")),
        "ticker": normalized_ticker,
        "mode": normalized_mode,
        "identity": {
            "ticker": str(row["ticker"]),
            "company_name": str(row["company_name"]),
            "cik": str(row["cik"]),
            "sector": str(row["sector"]),
            "industry": str(row["industry"]),
            "sec_entity_name": _scalar(row.get("sec_entity_name")),
        },
        "selected_mode": {
            "score": _number(row[f"{normalized_mode}_score"]),
            "factor_count": _scalar(
                row[f"{normalized_mode}_factor_count"]
            ),
            "available_factors": available_factors,
            "effective_factor_weights": mode_weights,
            "unavailable_reason": _scalar(
                row[f"{normalized_mode}_unavailable_reason"]
            ),
            "eligible_for_ranking": eligible_for_ranking,
            "ranking_exclusion_reasons": ranking_reasons,
        },
        "factor_scores": factor_scores,
        "factor_details": _factor_details(row),
        "price_history": {
            "series": [],
            "series_available": False,
            "availability_reason": PRICE_HISTORY_REASON,
            "source": _scalar(row["market_data_source"]),
            "start_date": _scalar(row["price_data_start"]),
            "end_date": _scalar(row["price_data_end"]),
            "history_rows": _scalar(row["history_rows"]),
        },
        "market_snapshot": {
            "price": _number(row["price"]),
            "market_cap_proxy": _number(row["market_cap_proxy"]),
            "average_volume_20d": _number(row["average_volume_20d"]),
        },
        "market_features": [
            {
                "field": field_name,
                "label": label,
                "value": _number(row[field_name]),
                "unit": unit,
            }
            for field_name, label, unit in MARKET_FEATURES
        ],
        "market_quality": {
            "market_data_age_days": _scalar(row["market_data_age_days"]),
            "duplicate_date_count": _scalar(row["duplicate_date_count"]),
            "missing_ohlcv_row_count": _scalar(
                row["missing_ohlcv_row_count"]
            ),
            "nonpositive_price_row_count": _scalar(
                row["nonpositive_price_row_count"]
            ),
            "extreme_daily_move_count": _scalar(
                row["extreme_daily_move_count"]
            ),
            "unadjusted_price_warning": _boolean(
                row["unadjusted_price_warning"],
                "unadjusted_price_warning",
            ),
        },
        "fundamentals": {
            "source": _scalar(row["fundamental_data_source"]),
            "latest_period_end": _scalar(row["fundamental_period_end"]),
            "latest_filed_date": _scalar(row["fundamental_filed_date"]),
            "fundamental_age_days": _scalar(row["fundamental_age_days"]),
            "metrics": _fundamental_rows(row),
        },
        "sector_context": {
            "sector": str(row["sector"]),
            "industry": str(row["industry"]),
            "company_relative_strength_3m": _number(
                row["relative_strength_3m"]
            ),
            "sector_median_relative_strength_3m": _number(
                row["sector_strength_source_value"]
            ),
            "sector_strength_member_count": _scalar(
                row["sector_strength_member_count"]
            ),
            "sector_strength_score": _number(
                row["sector_strength_score"]
            ),
        },
        "data_sources": {
            "market": _scalar(row["market_data_source"]),
            "fundamentals": _scalar(row["fundamental_data_source"]),
        },
        "data_dates": {
            field_name: _scalar(row[field_name])
            for field_name in screening.DATE_FIELDS
        },
        "quality": {
            "eligible_for_scoring": eligible_for_scoring,
            "missing_inputs": missing_inputs,
            "warnings": warnings,
            "stale_fundamental_metrics": stale_metrics,
            "base_exclusion_reasons": base_exclusion_reasons,
            "market_error": _scalar(row["market_error"]),
            "fundamental_error": _scalar(row["fundamental_error"]),
        },
        "strengths": strengths,
        "risks": risks,
        "reason_codes": _reason_codes(
            mode=normalized_mode,
            eligible_for_scoring=eligible_for_scoring,
            eligible_for_ranking=eligible_for_ranking,
            ranking_reasons=ranking_reasons,
            weights=mode_weights,
            warnings=warnings,
            strengths=strengths,
            risks=risks,
        ),
        "next_research_questions": questions,
        "field_labels": {
            "price": "Latest adjusted daily price",
            "market_cap_proxy": (
                "Price times validated shares outstanding proxy"
            ),
            "annual_pe_proxy": (
                "Historical annual earnings proxy, not vendor or forward P/E"
            ),
            "average_volume_20d": screening.AVERAGE_VOLUME_LABEL,
            "risk_score": "Higher means lower measured risk",
            "sector_strength_score": (
                "Higher means stronger measured sector relative strength"
            ),
        },
    }
