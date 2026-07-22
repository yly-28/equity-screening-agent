import numpy as np
import pandas as pd

from src.unified_data import (
    REQUIRED_MARKET_FIELDS,
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
        "annual_revenue": 100_000_000.0,
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income": 12_000_000.0,
        "annual_net_income_period_end": "2025-12-31",
        "shares_outstanding": 1_000_000.0,
        "shares_outstanding_period_end": "2026-01-31",
        "revenue_growth": 0.1,
        "profit_margin": 0.2,
        "profit_margin_raw": 0.2,
        "profit_margin_period_end": "2025-12-31",
        "roe": 0.25,
        "roe_period_end": "2025-12-31",
        "liabilities_to_equity": 1.0,
        "leverage_period_end": "2025-12-31",
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
    assert "average_volume_20d" in REQUIRED_MARKET_FIELDS
    assert isinstance(row["data_quality_flags"], list)
    assert row["stale_fundamental_metrics"] == []
    assert row["exclusion_reasons"] == []
    assert "eligible_for_scoring" not in row["missing_fields"]
    assert "market_error" not in row["missing_fields"]
    assert audit["schema_valid"] is True
    assert audit["eligible_count"] == 1


def test_build_unified_feature_row_excludes_duplicate_market_dates() -> None:
    dates = pd.bdate_range(end="2026-07-10", periods=250)
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": np.linspace(100, 120, len(dates)),
            "high": np.linspace(101, 121, len(dates)),
            "low": np.linspace(99, 119, len(dates)),
            "close": np.linspace(100, 120, len(dates)),
            "volume": 1_000_000,
            "price_is_adjusted": True,
        }
    )
    prices.loc[1, "date"] = prices.loc[0, "date"]
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
        "annual_revenue": 100_000_000.0,
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income": 12_000_000.0,
        "annual_net_income_period_end": "2025-12-31",
        "revenue_growth": 0.1,
        "profit_margin": 0.2,
        "profit_margin_raw": 0.2,
        "profit_margin_period_end": "2025-12-31",
    }

    row = build_unified_feature_row(
        identity,
        prices,
        fundamentals,
        pd.Timestamp("2026-07-11").date(),
        benchmark_prices=prices,
    )

    assert row["eligible_for_scoring"] is False
    assert "duplicate_market_dates" in row["data_quality_flags"]
    assert row["exclusion_reasons"] == ["duplicate_market_dates"]


def test_build_unified_feature_row_nulls_stale_metric_values() -> None:
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
        "annual_revenue": 100_000_000.0,
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income": 12_000_000.0,
        "annual_net_income_period_end": "2025-12-31",
        "revenue_growth": 0.1,
        "profit_margin": 0.2,
        "profit_margin_raw": 0.2,
        "profit_margin_period_end": "2012-12-31",
        "roe": 0.25,
        "roe_period_end": "2015-12-31",
        "liabilities_to_equity": 1.0,
        "leverage_period_end": "2010-12-31",
        "annual_free_cash_flow": 8_000_000.0,
        "free_cash_flow_period_end": "2011-12-31",
        "shares_outstanding": 1_000_000.0,
        "shares_outstanding_period_end": "2026-01-31",
    }

    row = build_unified_feature_row(
        identity,
        prices,
        fundamentals,
        pd.Timestamp("2026-07-11").date(),
        benchmark_prices=prices,
    )

    assert row["profit_margin"] is None
    assert row["roe"] is None
    assert row["liabilities_to_equity"] is None
    assert row["annual_free_cash_flow"] is None
    assert row["shares_outstanding"] == 1_000_000.0
    assert set(row["stale_fundamental_metrics"]) == {
        "profit_margin",
        "roe",
        "liabilities_to_equity",
        "annual_free_cash_flow",
    }
    assert "stale_fundamental_metric:profit_margin" in row["data_quality_flags"]
    assert row["eligible_for_scoring"] is True


def test_build_unified_feature_row_excludes_extreme_margin_from_scoring() -> None:
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
        "sector": "Health Care",
        "industry": "Biotechnology",
        "cik": "0000000001",
    }
    fundamentals = {
        "fundamental_period_end": "2025-12-31",
        "fundamental_filed_date": "2026-02-01",
        "annual_revenue": 100_000_000.0,
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income": -145_000_000.0,
        "annual_net_income_period_end": "2025-12-31",
        "revenue_growth": -0.4,
        "profit_margin": -1.45,
        "profit_margin_raw": -1.45,
        "profit_margin_period_end": "2025-12-31",
        "profit_margin_quality_warning": "absolute_value_above_1",
    }

    row = build_unified_feature_row(
        identity,
        prices,
        fundamentals,
        pd.Timestamp("2026-07-11").date(),
        benchmark_prices=prices,
    )

    assert row["profit_margin"] is None
    assert row["profit_margin_raw"] == -1.45
    assert (
        "profit_margin_excluded_from_scoring:absolute_value_above_1"
        in row["data_quality_flags"]
    )
    assert row["eligible_for_scoring"] is True


def test_validate_unified_feature_frame_rejects_duplicate_key_and_bad_flags() -> None:
    frame = pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-11",
                "ticker": "TEST",
                "company_name": "Test Corp",
                "sector": "Industrials",
                "industry": "Test",
                "cik": "0000000001",
                "data_quality_flags": "not-a-list",
                "missing_fields": [],
                "exclusion_reasons": [],
                "eligible_for_scoring": False,
            },
            {
                "as_of_date": "2026-07-11",
                "ticker": "TEST",
                "company_name": "Test Corp",
                "sector": "Industrials",
                "industry": "Test",
                "cik": "0000000001",
                "data_quality_flags": [],
                "missing_fields": [],
                "exclusion_reasons": [],
                "eligible_for_scoring": False,
            },
        ]
    )

    audit = validate_unified_feature_frame(frame)

    assert audit["schema_valid"] is False
    assert audit["duplicate_primary_key_count"] == 1
    assert audit["dtype_violations"]["data_quality_flags"] == 1
    assert audit["ineligible_without_exclusions_count"] == 2
    assert "price_data_end" in audit["missing_columns"]
    assert "annual_revenue" in audit["missing_columns"]
