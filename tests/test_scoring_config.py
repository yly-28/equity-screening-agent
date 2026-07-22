from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
FACTOR_MODEL_PATH = ROOT / "config/factor_model.yaml"
SCREENING_MODES_PATH = ROOT / "config/screening_modes.yaml"

FACTOR_NAMES = [
    "momentum",
    "quality",
    "valuation",
    "risk",
    "sector_strength",
]

METRIC_DIRECTIONS = {
    "momentum": {
        "return_1m": "higher",
        "return_3m": "higher",
        "return_6m": "higher",
        "ma20_gap": "higher",
        "ma50_gap": "higher",
        "volume_trend": "higher",
    },
    "quality": {
        "revenue_growth": "higher",
        "profit_margin": "higher",
        "roe": "higher",
        "free_cash_flow_margin": "higher",
    },
    "valuation": {"annual_pe_proxy": "lower"},
    "risk": {
        "volatility_20d": "lower",
        "volatility_60d": "lower",
        "beta_1y": "lower",
        "liabilities_to_equity": "lower",
        "max_drawdown_1y": "higher",
    },
}

MODE_WEIGHTS = {
    "balanced": {
        "momentum": 0.25,
        "quality": 0.25,
        "valuation": 0.20,
        "risk": 0.15,
        "sector_strength": 0.15,
    },
    "growth": {
        "momentum": 0.40,
        "quality": 0.30,
        "valuation": 0.10,
        "risk": 0.10,
        "sector_strength": 0.10,
    },
    "value": {
        "momentum": 0.10,
        "quality": 0.25,
        "valuation": 0.35,
        "risk": 0.20,
        "sector_strength": 0.10,
    },
    "low_risk": {
        "momentum": 0.15,
        "quality": 0.25,
        "valuation": 0.15,
        "risk": 0.35,
        "sector_strength": 0.10,
    },
}


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_factor_model_structure_and_sector_preprocessing() -> None:
    document = _load_yaml(FACTOR_MODEL_PATH)

    assert document["version"] == "1.0.0"
    assert document["status"] == "frozen_v1"
    assert document["source"] == {
        "reference": {
            "config_path": "config/data_contract.yaml",
            "run_id_field": "contract.accepted_run_id",
            "as_of_date_field": "contract.accepted_as_of_date",
        },
        "row_scope": "full_eligible_snapshot",
        "row_filter": {
            "field": "eligible_for_scoring",
            "equals": True,
        },
    }
    assert document["preprocessing"] == {
        "comparison_group": "sector",
        "winsorization": {
            "lower_percentile": 5,
            "upper_percentile": 95,
            "interpolation": "linear",
        },
        "percentile_rank": {
            "tie_method": "average",
            "endpoint_formula": "(rank - 1) / (n - 1) * 100",
            "constant_value_score": 50,
            "minimum_valid_observations": 10,
        },
    }
    assert document["factor_aggregation"] == {
        "metric_weighting": "equal",
        "minimum_available_metrics": 1,
        "missing_policy": "renormalize_over_available_metrics",
    }
    assert list(document["factors"]) == FACTOR_NAMES


def test_factor_metric_sets_weights_and_directions() -> None:
    document = _load_yaml(FACTOR_MODEL_PATH)

    assert document["factor_aggregation"]["metric_weighting"] == "equal"
    assert document["factor_aggregation"]["minimum_available_metrics"] == 1
    for factor_name, expected_directions in METRIC_DIRECTIONS.items():
        metrics = document["factors"][factor_name]["metrics"]
        assert set(metrics) == set(expected_directions)
        assert {
            metric_name: metric_config["direction"]
            for metric_name, metric_config in metrics.items()
        } == expected_directions

    risk = document["factors"]["risk"]
    assert risk["score_interpretation"] == "higher_score_means_lower_risk"
    assert risk["quality_warning_policy"] == "no_numeric_penalty"


def test_screening_modes_preserve_factor_weights_and_sum_to_one() -> None:
    document = _load_yaml(SCREENING_MODES_PATH)

    assert document["version"] == "1.0.0"
    assert document["status"] == "frozen_v1"
    assert document["factor_names"] == FACTOR_NAMES
    assert set(document["screening_modes"]) == set(MODE_WEIGHTS)
    for mode_name, expected_weights in MODE_WEIGHTS.items():
        expected_required = ["valuation"] if mode_name == "value" else []
        assert document["screening_modes"][mode_name][
            "ranking_required_factors"
        ] == expected_required
        weights = document["screening_modes"][mode_name]["weights"]
        assert weights == expected_weights
        assert set(weights) == set(FACTOR_NAMES)
        assert sum(weights.values()) == pytest.approx(1.0)


def test_free_cash_flow_margin_has_derivation_and_sector_applicability() -> None:
    document = _load_yaml(FACTOR_MODEL_PATH)
    free_cash_flow = document["factors"]["quality"]["metrics"][
        "free_cash_flow_margin"
    ]

    assert free_cash_flow["direction"] == "higher"
    assert free_cash_flow["derivation"] == {
        "operation": "ratio",
        "numerator": "annual_free_cash_flow",
        "denominator": "annual_revenue",
        "denominator_policy": "positive_only",
        "period_alignment": {
            "left": "free_cash_flow_period_end",
            "right": "annual_revenue_period_end",
            "policy": "exact",
        },
    }
    assert free_cash_flow["applicability"] == {
        "default": "applicable",
        "inapplicable_sectors": ["Financials", "Real Estate", "Utilities"],
    }


def test_sector_strength_uses_eligible_sector_medians_and_valid_sector_rank() -> None:
    document = _load_yaml(FACTOR_MODEL_PATH)
    sector_strength = document["factors"]["sector_strength"]

    assert sector_strength == {
        "display_name": "Sector Strength",
        "score_interpretation": "higher_score_means_stronger_sector",
        "source_metric": "relative_strength_3m",
        "source_rows": "eligible_only",
        "sector_aggregation": "median",
        "minimum_sector_members": 10,
        "cross_sector_ranking": {
            "universe": "valid_sectors_only",
            "method": "rank_percentile",
            "direction": "higher",
            "tie_method": "average",
            "minimum_valid_sectors": 2,
            "endpoint_formula": "(rank - 1) / (n - 1) * 100",
        },
    }
