"""Provider-independent assembly of the frozen pre-model feature contract."""

from __future__ import annotations

from datetime import date
from typing import Dict, Mapping, Optional

import pandas as pd

from src.features import compute_market_features


REQUIRED_IDENTITY_FIELDS = ("ticker", "company_name", "sector", "industry", "cik")
REQUIRED_MARKET_FIELDS = (
    "price",
    "return_1m",
    "return_3m",
    "return_6m",
    "volatility_20d",
    "volatility_60d",
    "max_drawdown_1y",
    "ma20_gap",
    "ma50_gap",
    "relative_strength_3m",
    "beta_1y",
)


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
        }
    )

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

    flags = []
    if not bool(prices.get("price_is_adjusted", pd.Series([False])).all()):
        flags.append("price_adjustment_unconfirmed")
    if int(row.get("history_rows") or 0) < 180:
        flags.append("insufficient_market_history")
    if row.get("market_data_age_days") is None or int(row["market_data_age_days"]) > 5:
        flags.append("stale_market_data")
    if (
        row.get("fundamental_age_days") is None
        or int(row["fundamental_age_days"]) > 550
    ):
        flags.append("stale_fundamentals")
    if int(row.get("extreme_daily_move_count") or 0) > 0:
        flags.append("extreme_daily_move")
    for warning_field in (
        "equity_quality_warning",
        "profit_margin_quality_warning",
        "shares_quality_warning",
    ):
        warning = row.get(warning_field)
        if warning and not pd.isna(warning):
            flags.append(f"{warning_field}:{warning}")
    missing_market = [
        field
        for field in REQUIRED_MARKET_FIELDS
        if row.get(field) is None or pd.isna(row.get(field))
    ]
    if missing_market:
        flags.append("missing_required_market:" + ",".join(missing_market))

    row["data_quality_flags"] = ";".join(flags)
    hard_failures = {
        "price_adjustment_unconfirmed",
        "insufficient_market_history",
        "stale_market_data",
        "stale_fundamentals",
        "extreme_daily_move",
    }
    row["eligible_for_scoring"] = not any(
        flag in hard_failures or flag.startswith("missing_required_market:")
        for flag in flags
    )
    return row


def validate_unified_feature_frame(frame: pd.DataFrame) -> Dict[str, object]:
    """Return a compact schema and eligibility audit for a unified table."""

    required_columns = {
        *REQUIRED_IDENTITY_FIELDS,
        *REQUIRED_MARKET_FIELDS,
        "as_of_date",
        "market_data_source",
        "fundamental_data_source",
        "fundamental_period_end",
        "data_quality_flags",
        "eligible_for_scoring",
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    return {
        "row_count": int(len(frame)),
        "missing_columns": missing_columns,
        "eligible_count": int(frame.get("eligible_for_scoring", pd.Series(dtype=bool)).sum()),
        "schema_valid": not missing_columns,
    }
