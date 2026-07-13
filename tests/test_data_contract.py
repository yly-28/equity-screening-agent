from pathlib import Path

import yaml


def test_data_contract_has_approved_providers_and_missing_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    document = yaml.safe_load((root / "config/data_contract.yaml").read_text())

    assert document["contract"]["status"] == "validated_pending_feature_matrix"
    assert document["providers"]["market"] == "twelve_data_time_series"
    assert document["providers"]["fundamentals"] == "sec_companyfacts"
    assert document["missing_data_policy"]["required_market_field"] == (
        "exclude_security_from_ranking"
    )
    assert document["model_preprocessing"]["grouping"] == "sector"
