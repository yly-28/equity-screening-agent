import numpy as np
import pandas as pd

from src.unified_data import (
    build_unified_feature_row,
    validate_unified_feature_frame,
)


def test_build_unified_feature_row_derives_optional_valuation_proxies() -> None:
    dates = pd.bdate_range(end="2026-07-10", periods=250)
    close = np.linspace(100, 120, len(dates))
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000,
            "price_is_adjusted": True,
        }
    )
    identity = {
        "ticker": "TEST",
        "company_name": "Test Corp",
        "sector": "Industrials",
        "industry": "Test",
        "cik": "0000000001",
    }
    fundamentals = {
        "fundamental_period_end": "2025-12-31",
        "fundamental_filed_date": "2026-02-01",
        "annual_net_income": 12_000_000.0,
        "shares_outstanding": 1_000_000.0,
        "revenue_growth": 0.1,
        "profit_margin": 0.2,
        "roe": 0.25,
        "liabilities_to_equity": 1.0,
    }

    row = build_unified_feature_row(
        identity,
        prices,
        fundamentals,
        pd.Timestamp("2026-07-11").date(),
        benchmark_prices=prices,
    )
    audit = validate_unified_feature_frame(pd.DataFrame([row]))

    assert row["market_cap_proxy"] == 120_000_000.0
    assert row["annual_pe_proxy"] == 10.0
    assert row["eligible_for_scoring"] is True
    assert audit["schema_valid"] is True
    assert audit["eligible_count"] == 1
