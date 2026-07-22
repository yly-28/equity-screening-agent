"""Provider-independent assembly and validation of the feature contract."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

import numpy as np
import pandas as pd
import yaml

from src.features import compute_market_features


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_PATH = PROJECT_ROOT / "config/data_contract.yaml"
FIELD_SECTIONS = (
    "identity_fields",
    "provenance_fields",
    "quality_fields",
    "market_fields",
    "fundamental_fields",
    "derived_optional_fields",
)


def load_data_contract(path: Optional[Path] = None) -> Dict[str, object]:
    """Load the machine-readable feature contract."""

    contract_path = Path(path or DEFAULT_CONTRACT_PATH)
    document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "contract" not in document:
        raise ValueError(f"Invalid data contract: {contract_path}")
    return document


def contract_field_specs(
    contract: Optional[Mapping[str, object]] = None,
) -> Dict[str, Mapping[str, object]]:
    """Flatten contract field sections while preserving their declarations."""

    document = contract or load_data_contract()
    fields: Dict[str, Mapping[str, object]] = {}
    for section_name in FIELD_SECTIONS:
        section = document.get(section_name, {})
        if not isinstance(section, Mapping):
            continue
        for field_name, spec in section.items():
            if isinstance(spec, Mapping):
                fields[str(field_name)] = spec
    return fields


DATA_CONTRACT = load_data_contract()
FIELD_SPECS = contract_field_specs(DATA_CONTRACT)
QUALITY_THRESHOLDS = DATA_CONTRACT["quality_thresholds"]
REQUIRED_IDENTITY_FIELDS = ("ticker", "company_name", "sector", "industry", "cik")
REQUIRED_MARKET_FIELDS = tuple(
    field_name
    for field_name, spec in DATA_CONTRACT["market_fields"].items()
    if spec.get("required_for_scoring", False)
)
REQUIRED_FUNDAMENTAL_FIELDS = tuple(
    field_name
    for field_name, spec in DATA_CONTRACT["fundamental_fields"].items()
    if spec.get("required", False)
)
MISSINGNESS_FIELDS = tuple(
    field_name
    for section_name in (
        "identity_fields",
        "provenance_fields",
        "market_fields",
        "fundamental_fields",
        "derived_optional_fields",
    )
    for field_name in DATA_CONTRACT.get(section_name, {})
)
FUNDAMENTAL_METRIC_PERIOD_FIELDS = {
    str(metric): str(period_field)
    for metric, period_field in DATA_CONTRACT.get(
        "fundamental_metric_freshness", {}
    ).get("period_fields", {}).items()
}


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, np.ndarray)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _missing_fields(row: Mapping[str, object], fields: Iterable[str]) -> list[str]:
    return [field for field in fields if _is_missing(row.get(field))]


def _apply_fundamental_metric_freshness(
    row: Dict[str, object], as_of: date
) -> tuple[list[str], list[str]]:
    """Null unusable metric values while preserving their period for audit."""

    stale_metrics: list[str] = []
    missing_period_metrics: list[str] = []
    maximum_age = int(QUALITY_THRESHOLDS["maximum_fundamental_age_days"])
    for metric, period_field in FUNDAMENTAL_METRIC_PERIOD_FIELDS.items():
        if _is_missing(row.get(metric)):
            continue
        period = pd.to_datetime(row.get(period_field), errors="coerce")
        if pd.isna(period):
            row[metric] = None
            missing_period_metrics.append(metric)
            continue
        age_days = (pd.Timestamp(as_of) - period).days
        if age_days < 0 or age_days > maximum_age:
            row[metric] = None
            stale_metrics.append(metric)
    return stale_metrics, missing_period_metrics


def _market_quality_counts(prices: pd.DataFrame) -> Dict[str, int]:
    required_ohlcv = ["open", "high", "low", "close", "volume"]
    missing_columns = [column for column in required_ohlcv if column not in prices]
    if missing_columns:
        return {
            "duplicate_date_count": int(
                prices.get("date", pd.Series(dtype=object)).duplicated().sum()
            ),
            "missing_ohlcv_row_count": int(len(prices)),
            "nonpositive_price_row_count": 0,
            "extreme_daily_move_count": 0,
        }
    returns = pd.to_numeric(prices["close"], errors="coerce").pct_change(
        fill_method=None
    )
    return {
        "duplicate_date_count": int(prices["date"].duplicated().sum()),
        "missing_ohlcv_row_count": int(
            prices[required_ohlcv].isna().any(axis=1).sum()
        ),
        "nonpositive_price_row_count": int(
            (prices[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()
        ),
        "extreme_daily_move_count": int(
            (
                returns.abs()
                > float(QUALITY_THRESHOLDS["extreme_daily_return_threshold"])
            ).sum()
        ),
    }


def build_unified_feature_row(
    identity: Mapping[str, object],
    prices: pd.DataFrame,
    fundamentals: Mapping[str, object],
    as_of: date,
    benchmark_prices: Optional[pd.DataFrame] = None,
) -> Dict[str, object]:
    """Merge identity, adjusted market history, and normalized SEC fundamentals."""

    missing_identity = [field for field in REQUIRED_IDENTITY_FIELDS if not identity.get(field)]
    if missing_identity:
        raise ValueError(f"Missing identity fields: {missing_identity}")

    market = compute_market_features(prices, benchmark_prices)
    row: Dict[str, object] = dict(identity)
    row.update(market)
    row.update(dict(fundamentals))
    row.update(
        {
            "as_of_date": as_of.isoformat(),
            "market_data_source": "twelve_data",
            "fundamental_data_source": "sec_companyfacts",
            "market_error": None,
            "fundamental_error": None,
        }
    )
    row.update(_market_quality_counts(prices))

    price_end = pd.to_datetime(row.get("price_data_end"), errors="coerce")
    fundamental_end = pd.to_datetime(
        row.get("fundamental_period_end"), errors="coerce"
    )
    row["market_data_age_days"] = (
        (pd.Timestamp(as_of) - price_end).days if not pd.isna(price_end) else None
    )
    row["fundamental_age_days"] = (
        (pd.Timestamp(as_of) - fundamental_end).days
        if not pd.isna(fundamental_end)
        else None
    )

    stale_metrics, missing_period_metrics = _apply_fundamental_metric_freshness(
        row, as_of
    )
    row["stale_fundamental_metrics"] = stale_metrics
    metric_quality_flags = [
        *(f"stale_fundamental_metric:{metric}" for metric in stale_metrics),
        *(
            f"missing_fundamental_metric_period:{metric}"
            for metric in missing_period_metrics
        ),
    ]
    if row.get("profit_margin_quality_warning") == "absolute_value_above_1":
        row["profit_margin"] = None
        metric_quality_flags.append(
            "profit_margin_excluded_from_scoring:absolute_value_above_1"
        )

    shares = row.get("shares_outstanding")
    price = row.get("price")
    net_income = row.get("annual_net_income")
    market_cap_proxy = None
    if shares is not None and price is not None and not pd.isna(shares):
        market_cap_proxy = float(shares) * float(price)
    row["market_cap_proxy"] = market_cap_proxy
    row["annual_pe_proxy"] = (
        market_cap_proxy / float(net_income)
        if market_cap_proxy is not None
        and net_income is not None
        and float(net_income) > 0
        else None
    )

    flags: list[str] = list(metric_quality_flags)
    exclusion_reasons: list[str] = []
    adjusted_required = bool(QUALITY_THRESHOLDS["adjusted_prices_required"])
    if adjusted_required and not bool(
        prices.get("price_is_adjusted", pd.Series([False])).all()
    ):
        flags.append("price_adjustment_unconfirmed")
    if int(row.get("history_rows") or 0) < int(
        QUALITY_THRESHOLDS["minimum_market_history_rows"]
    ):
        flags.append("insufficient_market_history")
    if row.get("market_data_age_days") is None or int(
        row["market_data_age_days"]
    ) > int(QUALITY_THRESHOLDS["maximum_market_data_age_days"]):
        flags.append("stale_market_data")
    if (
        row.get("fundamental_age_days") is None
        or int(row["fundamental_age_days"])
        > int(QUALITY_THRESHOLDS["maximum_fundamental_age_days"])
    ):
        flags.append("stale_fundamentals")
    if int(row.get("duplicate_date_count") or 0) > int(
        QUALITY_THRESHOLDS["maximum_duplicate_date_count"]
    ):
        flags.append("duplicate_market_dates")
    if int(row.get("missing_ohlcv_row_count") or 0) > int(
        QUALITY_THRESHOLDS["maximum_missing_ohlcv_row_count"]
    ):
        flags.append("missing_ohlcv_rows")
    if int(row.get("nonpositive_price_row_count") or 0) > int(
        QUALITY_THRESHOLDS["maximum_nonpositive_price_row_count"]
    ):
        flags.append("nonpositive_prices")
    if int(row.get("extreme_daily_move_count") or 0) > int(
        QUALITY_THRESHOLDS["maximum_extreme_daily_move_count"]
    ):
        flags.append("extreme_daily_move")
    for warning_field in (
        "equity_quality_warning",
        "profit_margin_quality_warning",
        "revenue_basis_warning",
        "revenue_growth_quality_warning",
        "shares_quality_warning",
    ):
        warning = row.get(warning_field)
        if warning and not pd.isna(warning):
            flags.append(f"{warning_field}:{warning}")
    missing_market = _missing_fields(row, REQUIRED_MARKET_FIELDS)
    if missing_market:
        flags.append("missing_required_market:" + ",".join(missing_market))
    missing_fundamentals = _missing_fields(row, REQUIRED_FUNDAMENTAL_FIELDS)
    if missing_fundamentals:
        flags.append(
            "missing_required_fundamental:" + ",".join(missing_fundamentals)
        )

    hard_failures = {
        "price_adjustment_unconfirmed",
        "insufficient_market_history",
        "stale_market_data",
        "stale_fundamentals",
        "duplicate_market_dates",
        "missing_ohlcv_rows",
        "nonpositive_prices",
        "extreme_daily_move",
    }
    exclusion_reasons.extend(flag for flag in flags if flag in hard_failures)
    exclusion_reasons.extend(
        flag for flag in flags if flag.startswith("missing_required_market:")
    )
    row["data_quality_flags"] = flags
    row["exclusion_reasons"] = exclusion_reasons
    row["eligible_for_scoring"] = not exclusion_reasons
    for field_name in FIELD_SPECS:
        row.setdefault(field_name, None)
    row["missing_fields"] = _missing_fields(row, MISSINGNESS_FIELDS)
    return row


def _dtype_is_valid(value: object, dtype: str) -> bool:
    if _is_missing(value):
        return True
    if dtype == "string":
        return isinstance(value, str)
    if dtype == "boolean":
        return isinstance(value, (bool, np.bool_))
    if dtype == "integer":
        return (
            isinstance(value, (int, np.integer))
            and not isinstance(value, bool)
        ) or (
            isinstance(value, (float, np.floating))
            and np.isfinite(value)
            and float(value).is_integer()
        )
    if dtype == "float":
        return isinstance(
            value, (int, float, np.integer, np.floating)
        ) and not isinstance(value, bool)
    if dtype == "date":
        return not pd.isna(pd.to_datetime(value, errors="coerce"))
    if dtype == "list_string":
        return isinstance(value, (list, tuple, np.ndarray)) and all(
            isinstance(item, str) for item in value
        )
    return True


def validate_unified_feature_frame(
    frame: pd.DataFrame,
    contract: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    """Return schema, primary-key, type, nullability, and eligibility checks."""

    document = contract or DATA_CONTRACT
    field_specs = contract_field_specs(document)
    required_columns = {
        field_name
        for field_name, spec in field_specs.items()
        if bool(spec.get("required", False))
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    primary_key = list(document["contract"]["primary_key"])
    missing_key_columns = [field for field in primary_key if field not in frame]
    null_primary_key_count = (
        int(frame[primary_key].isna().any(axis=1).sum())
        if not missing_key_columns
        else int(len(frame))
    )
    duplicate_primary_key_count = (
        int(frame.duplicated(primary_key).sum()) if not missing_key_columns else 0
    )

    nullability_violations: Dict[str, int] = {}
    dtype_violations: Dict[str, int] = {}
    allowed_value_violations: Dict[str, int] = {}
    for field_name, spec in field_specs.items():
        if field_name not in frame:
            continue
        if spec.get("nullable") is False:
            invalid_nulls = int(frame[field_name].map(_is_missing).sum())
            if invalid_nulls:
                nullability_violations[field_name] = invalid_nulls
        invalid_types = int(
            (
                ~frame[field_name].map(
                    lambda value: _dtype_is_valid(
                        value, str(spec.get("dtype", ""))
                    )
                )
            ).sum()
        )
        if invalid_types:
            dtype_violations[field_name] = invalid_types
        allowed_values = spec.get("allowed_values")
        if allowed_values:
            invalid_values = int(
                frame[field_name].map(
                    lambda value: not _is_missing(value)
                    and value not in allowed_values
                ).sum()
            )
            if invalid_values:
                allowed_value_violations[field_name] = invalid_values

    eligible = frame.get("eligible_for_scoring", pd.Series(False, index=frame.index))
    eligible_mask = eligible.map(
        lambda value: bool(value) if isinstance(value, (bool, np.bool_)) else False
    )
    required_for_scoring = [
        field_name
        for field_name, spec in field_specs.items()
        if bool(spec.get("required_for_scoring", False)) and field_name in frame
    ]
    eligible_required_field_violations: Dict[str, int] = {}
    for field_name in required_for_scoring:
        invalid_count = int(frame.loc[eligible_mask, field_name].map(_is_missing).sum())
        if invalid_count:
            eligible_required_field_violations[field_name] = invalid_count

    exclusions = frame.get("exclusion_reasons", pd.Series(None, index=frame.index))
    has_exclusions = exclusions.map(
        lambda value: len(value) > 0
        if isinstance(value, (list, tuple, np.ndarray))
        else False
    )
    eligible_with_exclusions_count = int((eligible_mask & has_exclusions).sum())
    ineligible_without_exclusions_count = int(
        ((~eligible_mask) & (~has_exclusions)).sum()
    )

    schema_valid = not any(
        (
            missing_columns,
            missing_key_columns,
            null_primary_key_count,
            duplicate_primary_key_count,
            nullability_violations,
            dtype_violations,
            allowed_value_violations,
            eligible_required_field_violations,
            eligible_with_exclusions_count,
            ineligible_without_exclusions_count,
        )
    )
    return {
        "contract_version": str(document["contract"]["version"]),
        "row_count": int(len(frame)),
        "missing_columns": missing_columns,
        "null_primary_key_count": null_primary_key_count,
        "duplicate_primary_key_count": duplicate_primary_key_count,
        "nullability_violations": nullability_violations,
        "dtype_violations": dtype_violations,
        "allowed_value_violations": allowed_value_violations,
        "eligible_required_field_violations": eligible_required_field_violations,
        "eligible_with_exclusions_count": eligible_with_exclusions_count,
        "ineligible_without_exclusions_count": ineligible_without_exclusions_count,
        "eligible_count": int(eligible_mask.sum()),
        "schema_valid": schema_valid,
    }
