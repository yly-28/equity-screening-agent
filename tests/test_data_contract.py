from pathlib import Path

import yaml


def test_data_contract_has_approved_providers_and_missing_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    document = yaml.safe_load((root / "config/data_contract.yaml").read_text())

    assert document["contract"]["status"] == "frozen_v1"
    assert document["contract"]["accepted_run_id"] == (
        "2026-07-13_sp500_v1_0_0"
    )
    assert document["contract"]["accepted_as_of_date"] == "2026-07-13"
    accepted_hash = document["contract"]["accepted_feature_matrix_sha256"]
    assert len(accepted_hash) == 64
    assert set(accepted_hash) <= set("0123456789abcdef")
    assert document["providers"]["market"] == "twelve_data_time_series"
    assert document["providers"]["fundamentals"] == "sec_companyfacts"
    assert document["missing_data_policy"]["required_market_field"] == (
        "exclude_security_from_ranking"
    )
    assert document["quality_fields"]["eligible_for_scoring"] == {
        "dtype": "boolean",
        "required": True,
        "nullable": False,
    }
    assert document["quality_fields"]["data_quality_flags"]["dtype"] == (
        "list_string"
    )
    assert document["quality_fields"]["stale_fundamental_metrics"] == {
        "dtype": "list_string",
        "required": True,
        "nullable": False,
    }
    assert document["quality_thresholds"]["minimum_market_history_rows"] == 180
    assert document["quality_thresholds"]["maximum_market_data_age_days"] == 5
    assert document["quality_thresholds"]["maximum_fundamental_age_days"] == 550
    assert document["quality_thresholds"]["minimum_eligible_rate"] == 0.95
    assert document["fundamental_metric_freshness"]["period_fields"][
        "profit_margin"
    ] == "profit_margin_period_end"
    assert document["fundamental_fields"]["profit_margin"][
        "invalid_for_scoring_if"
    ] == "absolute_value_above_1"
    assert document["derived_optional_fields"]["annual_pe_proxy"][
        "score_direction"
    ] == "lower"
    assert document["derived_optional_fields"]["annual_pe_proxy"][
        "comparison_group"
    ] == "sector"
    assert document["model_preprocessing"]["grouping"] == "sector"
