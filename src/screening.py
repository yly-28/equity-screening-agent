"""Deterministic screening over the frozen, accepted Phase 3 scores."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src import scoring_contract
from src.explanations import FACTOR_FIELDS, build_stock_explanations


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_UNIVERSES = ("sp500", "custom")
SUPPORTED_MODES = ("balanced", "growth", "value", "low_risk")

DATE_FIELDS = (
    "as_of_date",
    "price_data_end",
    "fundamental_period_end",
    "fundamental_filed_date",
    "annual_revenue_period_end",
    "annual_net_income_period_end",
    "profit_margin_period_end",
    "roe_period_end",
    "leverage_period_end",
    "free_cash_flow_period_end",
    "shares_outstanding_period_end",
)

AVERAGE_VOLUME_LABEL = "20-day average share volume"


class ScreeningValidationError(ValueError):
    """Raised when a screening request is invalid."""


class ScreeningDataError(RuntimeError):
    """Raised when verified scoring data cannot satisfy the service schema."""


def _normalize_choice(value: object, label: str, supported: tuple[str, ...]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScreeningValidationError(f"{label} must be a non-empty string")
    normalized = value.strip().lower()
    if normalized not in supported:
        allowed = ", ".join(supported)
        raise ScreeningValidationError(
            f"Unsupported {label}: {value!r}. Supported values: {allowed}"
        )
    return normalized


def _normalize_threshold(value: object, label: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ScreeningValidationError(
            f"{label} must be a finite non-negative number or None"
        )
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ScreeningValidationError(
            f"{label} must be a finite non-negative number or None"
        )
    return normalized


def _normalize_top_n(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
        raise ScreeningValidationError("top_n must be a positive integer")
    return int(value)


def _normalize_factor_thresholds(value: object) -> dict[str, float]:
    """Validate optional 0-100 minimums for the five stored factor scores."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ScreeningValidationError(
            "minimum_factor_scores must be a mapping of factor names to scores"
        )

    supported = {factor_name for factor_name, _ in FACTOR_FIELDS}
    unknown = sorted(
        str(factor_name) for factor_name in value if factor_name not in supported
    )
    if unknown:
        raise ScreeningValidationError(
            "Unknown factor-score filters: "
            + ", ".join(unknown)
            + ". Supported factors: "
            + ", ".join(sorted(supported))
        )

    normalized: dict[str, float] = {}
    for factor_name, minimum in value.items():
        threshold = _normalize_threshold(
            minimum, f"minimum_factor_scores.{factor_name}"
        )
        if threshold is None:
            continue
        if threshold > 100.0:
            raise ScreeningValidationError(
                f"minimum_factor_scores.{factor_name} must be between 0 and 100"
            )
        normalized[str(factor_name)] = threshold
    return {
        factor_name: normalized[factor_name]
        for factor_name, _ in FACTOR_FIELDS
        if factor_name in normalized
    }


def _normalize_custom_tickers(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise ScreeningValidationError(
            "custom_tickers must be an iterable of ticker strings, not one string"
        )
    try:
        values = list(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ScreeningValidationError(
            "custom_tickers must be an iterable of ticker strings"
        ) from exc

    normalized: set[str] = set()
    for ticker in values:
        if not isinstance(ticker, str):
            raise ScreeningValidationError(
                "custom_tickers must contain only strings"
            )
        cleaned = ticker.strip().upper()
        if cleaned:
            normalized.add(cleaned)
    return tuple(sorted(normalized))


def _normalize_sectors(
    value: object,
    known_sectors: tuple[str, ...],
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, bytes):
        raise ScreeningValidationError("sectors must contain sector-name strings")
    else:
        try:
            values = list(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ScreeningValidationError(
                "sectors must be a sector name or an iterable of sector names"
            ) from exc

    by_casefold = {sector.casefold(): sector for sector in known_sectors}
    normalized: set[str] = set()
    unknown: set[str] = set()
    for sector in values:
        if not isinstance(sector, str) or not sector.strip():
            raise ScreeningValidationError(
                "sectors must contain non-empty sector-name strings"
            )
        cleaned = sector.strip()
        canonical = by_casefold.get(cleaned.casefold())
        if canonical is None:
            unknown.add(cleaned)
        else:
            normalized.add(canonical)

    if unknown:
        allowed = ", ".join(known_sectors)
        raise ScreeningValidationError(
            "Unknown sectors: "
            + ", ".join(sorted(unknown))
            + f". Available sectors: {allowed}"
        )
    return tuple(sorted(normalized))


def _number_or_none(value: object) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _scalar_or_none(value: object) -> Any:
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return value


def _as_string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        value = value.tolist()
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        try:
            if bool(pd.isna(value)):
                return []
        except (TypeError, ValueError):
            pass
        raise ScreeningDataError(f"{label} must be a list of strings")
    if any(not isinstance(item, str) for item in value):
        raise ScreeningDataError(f"{label} must contain only strings")
    return _dedupe_strings(value)


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _parse_weights(value: object, label: str) -> dict[str, float]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ScreeningDataError(f"{label} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ScreeningDataError(f"{label} must be a mapping")

    parsed: dict[str, float] = {}
    for factor_name, weight in value.items():
        numeric = _number_or_none(weight)
        if not isinstance(factor_name, str) or numeric is None:
            raise ScreeningDataError(
                f"{label} must map factor names to finite numeric weights"
            )
        parsed[factor_name] = numeric
    return parsed


def _required_columns(mode: str) -> set[str]:
    return {
        "ticker",
        "company_name",
        "sector",
        "industry",
        "cik",
        "price",
        "market_cap_proxy",
        "average_volume_20d",
        "data_quality_flags",
        "missing_fields",
        "stale_fundamental_metrics",
        "exclusion_reasons",
        *DATE_FIELDS,
        *[f"{factor_name}_score" for factor_name, _ in FACTOR_FIELDS],
        f"{mode}_score",
        f"{mode}_eligible_for_ranking",
        f"{mode}_ranking_exclusion_reasons",
        f"{mode}_effective_factor_weights",
        f"{mode}_available_factors",
    }


def _filter_reasons(
    row: pd.Series,
    selected_sectors: tuple[str, ...],
    minimum_price: Optional[float],
    minimum_market_cap_proxy: Optional[float],
    minimum_average_volume_20d: Optional[float],
    minimum_factor_scores: Mapping[str, float],
) -> list[str]:
    reasons: list[str] = []
    if selected_sectors and str(row["sector"]) not in selected_sectors:
        reasons.append("sector_not_selected")

    numeric_filters = (
        ("price", minimum_price),
        ("market_cap_proxy", minimum_market_cap_proxy),
        ("average_volume_20d", minimum_average_volume_20d),
    )
    for field_name, minimum in numeric_filters:
        if minimum is None:
            continue
        value = _number_or_none(row[field_name])
        if value is None:
            reasons.append(f"missing_filter_value:{field_name}")
        elif value < minimum:
            reasons.append(f"below_minimum:{field_name}")
    for factor_name, minimum in minimum_factor_scores.items():
        field_name = f"{factor_name}_score"
        value = _number_or_none(row[field_name])
        if value is None:
            reasons.append(f"missing_filter_value:{field_name}")
        elif value < minimum:
            reasons.append(f"below_minimum:{field_name}")
    return reasons


def _warnings(row: pd.Series) -> list[str]:
    warnings = _as_string_list(row["data_quality_flags"], "data_quality_flags")
    stale = _as_string_list(
        row["stale_fundamental_metrics"], "stale_fundamental_metrics"
    )
    warnings.extend(f"stale_fundamental_metric:{metric}" for metric in stale)
    for error_field in ("market_error", "fundamental_error"):
        if error_field in row:
            error = _scalar_or_none(row[error_field])
            if error:
                warnings.append(f"{error_field}:{error}")
    return _dedupe_strings(warnings)


def _stock_record(
    row: pd.Series,
    mode: str,
    rank: int,
    filters_active: bool,
) -> dict[str, object]:
    mode_score = _number_or_none(row[f"{mode}_score"])
    if mode_score is None:
        raise ScreeningDataError(
            f"Ranking-eligible ticker {row['ticker']} has no finite {mode} score"
        )

    factor_scores = {
        factor_name: _number_or_none(row[f"{factor_name}_score"])
        for factor_name, _ in FACTOR_FIELDS
    }
    missing_inputs = _as_string_list(row["missing_fields"], "missing_fields")
    strengths, risks, questions = build_stock_explanations(
        factor_scores,
        missing_inputs,
        _scalar_or_none(row["fundamental_filed_date"]),
    )
    warnings = _warnings(row)
    weights = _parse_weights(
        row[f"{mode}_effective_factor_weights"],
        f"{mode}_effective_factor_weights",
    )
    available_factors = _as_string_list(
        row[f"{mode}_available_factors"], f"{mode}_available_factors"
    )

    reason_codes = [
        f"ranked_by_stored_score:{mode}",
        "passes_requested_filters" if filters_active else "no_optional_filters",
    ]
    reason_codes.extend(strength["code"] for strength in strengths)
    reason_codes.extend(risk["code"] for risk in risks)
    if len(weights) < len(FACTOR_FIELDS):
        reason_codes.append("mode_weights_renormalized")
    if warnings:
        reason_codes.append("quality_warning_present")

    return {
        "rank": rank,
        "ticker": str(row["ticker"]),
        "company_name": str(row["company_name"]),
        "cik": str(row["cik"]),
        "sector": str(row["sector"]),
        "industry": str(row["industry"]),
        "screening_mode": mode,
        "mode_score": mode_score,
        "factor_scores": factor_scores,
        "effective_factor_weights": weights,
        "available_factors": available_factors,
        "price": _number_or_none(row["price"]),
        "market_cap_proxy": _number_or_none(row["market_cap_proxy"]),
        "average_volume_20d": _number_or_none(row["average_volume_20d"]),
        "average_volume_20d_label": AVERAGE_VOLUME_LABEL,
        "data_sources": {
            "market": _scalar_or_none(row.get("market_data_source")),
            "fundamentals": _scalar_or_none(
                row.get("fundamental_data_source")
            ),
        },
        "data_dates": {
            field_name: _scalar_or_none(row[field_name])
            for field_name in DATE_FIELDS
        },
        "missing_inputs": missing_inputs,
        "warnings": warnings,
        "strengths": strengths,
        "risks": risks,
        "reason_codes": _dedupe_strings(reason_codes),
        "next_research_questions": questions,
    }


def _exclusion_record(
    row: pd.Series,
    mode: str,
    stage: str,
    reasons: list[str],
) -> dict[str, object]:
    return {
        "ticker": str(row["ticker"]),
        "company_name": str(row["company_name"]),
        "sector": str(row["sector"]),
        "screening_mode": mode,
        "mode_score": _number_or_none(row[f"{mode}_score"]),
        "stage": stage,
        "reasons": _dedupe_strings(reasons),
    }


def screen_stocks(
    universe: str = "sp500",
    custom_tickers: Optional[Iterable[str]] = None,
    mode: str = "balanced",
    sectors: Optional[Iterable[str] | str] = None,
    minimum_price: Optional[float] = None,
    minimum_market_cap_proxy: Optional[float] = None,
    minimum_average_volume_20d: Optional[float] = None,
    minimum_factor_scores: Optional[Mapping[str, float]] = None,
    top_n: int = 20,
) -> dict[str, object]:
    """Filter and rank the frozen accepted scoring artifact.

    The service loads data only through
    :func:`src.scoring_contract.load_accepted_scoring_run`. It applies the
    stored mode-ranking eligibility flag first, then requested filters, and
    finally deterministic score/ticker ordering and ``top_n`` truncation.
    Stored scores and effective weights are projected unchanged.
    """

    normalized_universe = _normalize_choice(
        universe, "universe", SUPPORTED_UNIVERSES
    )
    normalized_mode = _normalize_choice(mode, "mode", SUPPORTED_MODES)
    normalized_tickers = _normalize_custom_tickers(custom_tickers)
    normalized_minimum_price = _normalize_threshold(
        minimum_price, "minimum_price"
    )
    normalized_minimum_market_cap = _normalize_threshold(
        minimum_market_cap_proxy, "minimum_market_cap_proxy"
    )
    normalized_minimum_volume = _normalize_threshold(
        minimum_average_volume_20d, "minimum_average_volume_20d"
    )
    normalized_factor_thresholds = _normalize_factor_thresholds(
        minimum_factor_scores
    )
    normalized_top_n = _normalize_top_n(top_n)

    if normalized_universe == "custom" and not normalized_tickers:
        raise ScreeningValidationError(
            "custom_tickers must contain at least one ticker for universe='custom'"
        )
    if normalized_universe == "sp500" and normalized_tickers:
        raise ScreeningValidationError(
            "custom_tickers may only be supplied when universe='custom'"
        )

    accepted = scoring_contract.load_accepted_scoring_run(PROJECT_ROOT)
    frame = accepted.scored_matrix
    missing_columns = sorted(_required_columns(normalized_mode) - set(frame.columns))
    if missing_columns:
        raise ScreeningDataError(
            "Accepted scored matrix is missing screening columns: "
            + ", ".join(missing_columns)
        )

    known_sectors = tuple(
        sorted({str(value) for value in frame["sector"].dropna()})
    )
    normalized_sectors = _normalize_sectors(sectors, known_sectors)

    known_tickers = {str(value) for value in frame["ticker"]}
    if normalized_universe == "custom":
        unknown_tickers = sorted(set(normalized_tickers) - known_tickers)
        requested_known = set(normalized_tickers) & known_tickers
        candidates = frame.loc[frame["ticker"].astype(str).isin(requested_known)]
    else:
        unknown_tickers = []
        candidates = frame

    candidates = candidates.copy(deep=False)
    eligibility_column = f"{normalized_mode}_eligible_for_ranking"
    ranking_reason_column = f"{normalized_mode}_ranking_exclusion_reasons"
    survivors: list[tuple[float, str, pd.Series]] = []
    exclusions: list[dict[str, object]] = []
    ranking_eligible_count = 0
    mode_ineligible_count = 0
    filter_excluded_count = 0

    for _, row in candidates.iterrows():
        if not bool(row[eligibility_column]):
            mode_ineligible_count += 1
            mode_reasons = _as_string_list(
                row[ranking_reason_column], ranking_reason_column
            )
            base_reasons = _as_string_list(
                row["exclusion_reasons"], "exclusion_reasons"
            )
            exclusions.append(
                _exclusion_record(
                    row,
                    normalized_mode,
                    "mode_eligibility",
                    [*mode_reasons, *base_reasons],
                )
            )
            continue

        ranking_eligible_count += 1
        reasons = _filter_reasons(
            row,
            normalized_sectors,
            normalized_minimum_price,
            normalized_minimum_market_cap,
            normalized_minimum_volume,
            normalized_factor_thresholds,
        )
        if reasons:
            filter_excluded_count += 1
            exclusions.append(
                _exclusion_record(
                    row,
                    normalized_mode,
                    "requested_filters",
                    reasons,
                )
            )
            continue

        score = _number_or_none(row[f"{normalized_mode}_score"])
        if score is None:
            raise ScreeningDataError(
                f"Ranking-eligible ticker {row['ticker']} has no finite "
                f"{normalized_mode} score"
            )
        survivors.append((score, str(row["ticker"]), row))

    survivors.sort(key=lambda item: (-item[0], item[1]))
    selected = survivors[:normalized_top_n]
    truncated = survivors[normalized_top_n:]
    for _, _, row in truncated:
        exclusions.append(
            _exclusion_record(
                row,
                normalized_mode,
                "top_n",
                ["outside_top_n"],
            )
        )
    filters_active = bool(
        normalized_sectors
        or normalized_minimum_price is not None
        or normalized_minimum_market_cap is not None
        or normalized_minimum_volume is not None
        or normalized_factor_thresholds
    )
    stocks = [
        _stock_record(row, normalized_mode, rank, filters_active)
        for rank, (_, _, row) in enumerate(selected, start=1)
    ]
    exclusions.sort(key=lambda item: str(item["ticker"]))

    exclusion_reason_counts = Counter(
        reason
        for exclusion in exclusions
        for reason in exclusion["reasons"]  # type: ignore[union-attr]
    )
    contract_header = accepted.contract.get("scoring_contract", {})
    if not isinstance(contract_header, Mapping):
        contract_header = {}

    return {
        "service": "screen_stocks",
        "accepted_run_id": accepted.metadata.get("run_id"),
        "scoring_contract_version": contract_header.get("version"),
        "factor_model_version": accepted.metadata.get("factor_model_version"),
        "screening_modes_version": accepted.metadata.get(
            "screening_modes_version"
        ),
        "as_of_date": _scalar_or_none(accepted.metadata.get("as_of_date")),
        "universe": normalized_universe,
        "requested_tickers": list(normalized_tickers),
        "unknown_tickers": unknown_tickers,
        "mode": normalized_mode,
        "filters": {
            "sectors": list(normalized_sectors),
            "minimum_price": normalized_minimum_price,
            "minimum_market_cap_proxy": normalized_minimum_market_cap,
            "minimum_average_volume_20d": normalized_minimum_volume,
            "minimum_factor_scores": normalized_factor_thresholds,
            "top_n": normalized_top_n,
        },
        "field_labels": {
            "price": "Latest adjusted daily price",
            "market_cap_proxy": "Price times validated shares outstanding proxy",
            "average_volume_20d": AVERAGE_VOLUME_LABEL,
            "risk_score": "Higher means lower measured risk",
        },
        "candidate_count": int(len(candidates)),
        "ranking_eligible_count": ranking_eligible_count,
        "candidate_count_before_top_n": len(survivors),
        "returned_count": len(stocks),
        "truncated_count": len(truncated),
        "excluded_count": len(exclusions),
        "mode_ineligible_count": mode_ineligible_count,
        "filter_excluded_count": filter_excluded_count,
        "top_n_excluded_count": len(truncated),
        "unknown_ticker_count": len(unknown_tickers),
        "exclusion_reason_counts": dict(sorted(exclusion_reason_counts.items())),
        "stocks": stocks,
        "exclusions": exclusions,
    }
