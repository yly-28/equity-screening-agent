import json

import numpy as np
import pandas as pd

from src.matrix_quality import analyze_feature_matrix, write_quality_artifacts
from src.unified_data import build_unified_feature_row, validate_unified_feature_frame


def _clean_matrix() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range(end="2026-07-10", periods=250)
    close = np.linspace(100.0, 120.0, len(dates))
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000.0,
            "price_is_adjusted": True,
        }
    )
    identity = {
        "ticker": "TEST",
        "company_name": "Test Corp",
        "sector": "Industrials",
        "industry": "Testing",
        "cik": "0000000001",
    }
    fundamentals = {
        "fundamental_period_end": "2025-12-31",
        "fundamental_filed_date": "2026-02-01",
        "annual_revenue": 100_000_000.0,
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income": 10_000_000.0,
        "annual_net_income_period_end": "2025-12-31",
        "revenue_growth": 0.1,
        "profit_margin": 0.1,
        "profit_margin_raw": 0.1,
        "profit_margin_period_end": "2025-12-31",
        "roe": 0.2,
        "roe_period_end": "2025-12-31",
        "liabilities_to_equity": 1.0,
        "leverage_period_end": "2025-12-31",
        "annual_free_cash_flow": 8_000_000.0,
        "free_cash_flow_period_end": "2025-12-31",
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
    universe = pd.DataFrame([identity])
    return pd.DataFrame([row]), universe


def test_analyze_feature_matrix_passes_clean_contract_matrix() -> None:
    matrix, universe = _clean_matrix()

    quality = analyze_feature_matrix(
        matrix,
        universe,
        {"run_id": "clean", "contract_version": "1.0.0"},
    )

    assert quality.summary["acceptance"]["passed"] is True
    assert quality.summary["schema"]["schema_valid"] is True
    assert quality.summary["row_accounting"]["matrix_row_count"] == 1
    assert quality.summary["eligibility"]["eligible_rate"] == 1.0
    assert quality.summary["freshness"]["metric_period_violation_count"] == 0
    assert quality.summary["freshness"]["stale_metric_value_violation_count"] == 0
    assert quality.audit.loc[0, "data_quality_flags_text"] == ""
    assert set(quality.sector_missingness["sector"]) == {"Industrials"}


def test_analyze_feature_matrix_rejects_duplicate_primary_key() -> None:
    matrix, universe = _clean_matrix()
    duplicated = pd.concat([matrix, matrix], ignore_index=True)

    quality = analyze_feature_matrix(
        duplicated,
        universe,
        {"run_id": "duplicate", "contract_version": "1.0.0"},
    )

    assert quality.summary["acceptance"]["passed"] is False
    assert "schema_validation_failed" in quality.summary["acceptance"][
        "hard_failures"
    ]
    assert quality.summary["schema"]["duplicate_primary_key_count"] == 1


def test_write_quality_artifacts_preserves_lists_in_parquet(tmp_path) -> None:
    matrix, universe = _clean_matrix()
    quality = analyze_feature_matrix(
        matrix,
        universe,
        {"run_id": "artifact_test", "contract_version": "1.0.0"},
    )

    paths = write_quality_artifacts(
        matrix,
        quality,
        tmp_path,
        "artifact_test",
    )

    for field_name, path in paths.__dict__.items():
        if field_name != "run_dir":
            assert path.exists()
    restored = pd.read_parquet(paths.matrix_parquet)
    assert restored["ticker"].tolist() == ["TEST"]
    assert list(restored.loc[0, "data_quality_flags"]) == []
    assert validate_unified_feature_frame(restored)["schema_valid"] is True
    summary = json.loads(paths.quality_json.read_text(encoding="utf-8"))
    assert summary["acceptance"]["passed"] is True
    assert summary["artifacts"]["matrix_parquet"] == "feature_matrix.parquet"
    assert not list(paths.run_dir.glob(".*.tmp"))


def test_analyze_feature_matrix_rejects_nonnull_stale_metric() -> None:
    matrix, universe = _clean_matrix()
    matrix.loc[0, "profit_margin"] = 0.1
    matrix.loc[0, "profit_margin_period_end"] = "2012-12-31"
    matrix.at[0, "stale_fundamental_metrics"] = []

    quality = analyze_feature_matrix(
        matrix,
        universe,
        {"run_id": "stale", "contract_version": "1.0.0"},
    )

    assert quality.summary["acceptance"]["passed"] is False
    assert "fundamental_metric_freshness_failed" in quality.summary["acceptance"][
        "hard_failures"
    ]
    assert quality.summary["freshness"]["stale_metric_value_violation_count"] == 1
