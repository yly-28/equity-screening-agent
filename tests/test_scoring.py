from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.scoring import (
    CORE_FACTORS,
    ScoringError,
    _validate_frozen_scoring_reproduction,
    aggregate_modes,
    load_yaml_document,
    score_feature_matrix,
    transform_sector_metric,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def scoring_configs() -> tuple[dict, dict]:
    return (
        load_yaml_document(ROOT / "config/factor_model.yaml"),
        load_yaml_document(ROOT / "config/screening_modes.yaml"),
    )


def _configured_metric_names(factor_document: dict) -> list[str]:
    return [
        str(metric_name)
        for factor in factor_document["factors"].values()
        for metric_name, metric_spec in factor.get("metrics", {}).items()
        if "derivation" not in metric_spec
    ]


def _synthetic_matrix(
    factor_document: dict,
    *,
    sectors: tuple[str, ...] = ("Alpha", "Beta", "Gamma"),
    rows_per_sector: int = 11,
    ineligible_keys: tuple[tuple[str, int], ...] = (("Alpha", 10),),
) -> pd.DataFrame:
    metrics = _configured_metric_names(factor_document)
    ineligible = set(ineligible_keys)
    rows = []
    for sector_number, sector in enumerate(sectors):
        for row_number in range(rows_per_sector):
            row = {
                "as_of_date": "2026-07-13",
                "ticker": f"T{sector_number:02d}{row_number:02d}",
                "sector": sector,
                "eligible_for_scoring": (sector, row_number) not in ineligible,
            }
            for metric_number, metric_name in enumerate(metrics):
                row[metric_name] = float(
                    sector_number * 100 + row_number + metric_number / 100
                )
            row["relative_strength_3m"] = float(
                sector_number * 100 + row_number
            )
            row["profit_margin"] = float(
                0.10 + sector_number / 100 + row_number / 1000
            )
            row["profit_margin_raw"] = float(
                10_000 - sector_number * 100 - row_number
            )
            row["annual_revenue"] = float(
                1_000 + sector_number * 100 + row_number * 10
            )
            row["annual_free_cash_flow"] = float(
                row["annual_revenue"]
                * (0.05 + sector_number / 100 + row_number / 1000)
            )
            row["annual_revenue_period_end"] = "2025-12-31"
            row["free_cash_flow_period_end"] = "2025-12-31"
            if not row["eligible_for_scoring"]:
                row["relative_strength_3m"] = 1_000_000.0
            rows.append(row)
    return pd.DataFrame(rows)


def _metric_frame(
    values: list[float],
    *,
    sector: str = "Technology",
    metric_name: str = "metric",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector": [sector] * len(values),
            "eligible_for_scoring": [True] * len(values),
            metric_name: values,
        }
    )


def test_transform_sector_metric_requires_exact_minimum_with_reason(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, _ = scoring_configs
    reference = pd.concat(
        [
            _metric_frame(list(map(float, range(10))), sector="Ten"),
            _metric_frame(list(map(float, range(9))), sector="Nine"),
        ],
        ignore_index=True,
    )
    target = pd.DataFrame(
        {
            "sector": ["Ten", "Nine"],
            "eligible_for_scoring": [True, True],
            "metric": [4.0, 4.0],
        },
        index=["ten", "nine"],
    )

    transformed, coverage = transform_sector_metric(
        reference,
        target,
        "example",
        "metric",
        {"direction": "higher"},
        factor_document["preprocessing"],
    )

    assert transformed.at["ten", "metric_available"]
    assert pd.notna(transformed.at["ten", "metric_score"])
    assert transformed.at["ten", "metric_unavailable_reason"] is None
    assert not transformed.at["nine", "metric_available"]
    assert pd.isna(transformed.at["nine", "metric_score"])
    assert transformed.at["nine", "metric_unavailable_reason"] == (
        "insufficient_sector_observations:9"
    )
    by_sector = {record["sector"]: record for record in coverage}
    assert by_sector["Ten"]["valid_reference_count"] == 10
    assert by_sector["Ten"]["sufficient_observations"] is True
    assert by_sector["Nine"]["valid_reference_count"] == 9
    assert by_sector["Nine"]["sufficient_observations"] is False


def test_transform_sector_metric_math_contract(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, _ = scoring_configs
    preprocessing = factor_document["preprocessing"]

    reference = _metric_frame(list(map(float, range(10))))
    targets = _metric_frame([-10.0, 4.5, 20.0])
    transformed, coverage = transform_sector_metric(
        reference,
        targets,
        "example",
        "metric",
        {"direction": "higher"},
        preprocessing,
    )
    assert transformed["metric_winsorized"].tolist() == pytest.approx(
        [0.45, 4.5, 8.55]
    )
    assert transformed["metric_score"].tolist() == pytest.approx(
        [0.0, 50.0, 100.0]
    )
    assert coverage[0]["lower_cutoff"] == pytest.approx(0.45)
    assert coverage[0]["upper_cutoff"] == pytest.approx(8.55)

    tied_reference = _metric_frame([0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    tied_target = _metric_frame([0.0])
    tied, _ = transform_sector_metric(
        tied_reference,
        tied_target,
        "example",
        "metric",
        {"direction": "higher"},
        preprocessing,
    )
    assert tied.at[0, "metric_score"] == pytest.approx(0.5 / 9 * 100)

    constant, _ = transform_sector_metric(
        _metric_frame([7.0] * 10),
        _metric_frame([7.0, 100.0]),
        "example",
        "metric",
        {"direction": "higher"},
        preprocessing,
    )
    assert constant["metric_score"].tolist() == [50.0, 50.0]

    reversed_scores, _ = transform_sector_metric(
        reference,
        _metric_frame([-10.0, 20.0]),
        "example",
        "metric",
        {"direction": "lower"},
        preprocessing,
    )
    assert reversed_scores["metric_score"].tolist() == pytest.approx(
        [100.0, 0.0]
    )


def test_score_feature_matrix_preserves_rows_and_nulls_ineligible_scores(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    matrix = _synthetic_matrix(factor_document)

    build = score_feature_matrix(matrix, factor_document, modes_document)

    assert len(build.scored) == len(matrix)
    assert build.scored["ticker"].tolist() == matrix["ticker"].tolist()
    ineligible = build.scored.loc[~build.scored["eligible_for_scoring"]].iloc[0]
    score_columns = [
        *[f"{metric}_score" for metric in build.metric_names],
        *[f"{factor}_score" for factor in build.factor_names],
        *[f"{mode}_score" for mode in build.mode_names],
    ]
    assert ineligible[score_columns].isna().all()
    reason_columns = [
        *[f"{metric}_unavailable_reason" for metric in build.metric_names],
        *[f"{factor}_unavailable_reason" for factor in build.factor_names],
        *[f"{mode}_unavailable_reason" for mode in build.mode_names],
    ]
    assert set(ineligible[reason_columns]) == {"ineligible_for_scoring"}


def test_missing_metrics_renormalize_factor_and_mode_weights(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    reference = _synthetic_matrix(factor_document)
    target = reference.copy(deep=True)
    target_index = target.index[
        target["sector"].eq("Beta") & target["eligible_for_scoring"]
    ][0]
    target.loc[
        target_index,
        ["revenue_growth", "roe", "annual_free_cash_flow", "annual_pe_proxy"],
    ] = np.nan

    build = score_feature_matrix(
        target,
        factor_document,
        modes_document,
        reference_matrix=reference,
    )
    row = build.scored.loc[target_index]

    assert row["quality_component_count"] == 1
    assert row["quality_available_components"] == ["profit_margin"]
    assert row["quality_score"] == pytest.approx(row["profit_margin_score"])
    assert json.loads(row["quality_effective_metric_weights"]) == {
        "profit_margin": 1.0
    }
    assert pd.isna(row["valuation_score"])
    assert row["annual_pe_proxy_unavailable_reason"] == "missing_value"

    for factor_name in build.factor_names:
        if pd.notna(row[f"{factor_name}_score"]):
            weights = json.loads(
                row[f"{factor_name}_effective_metric_weights"]
            )
            assert sum(weights.values()) == pytest.approx(1.0)

    for mode_name in build.mode_names:
        effective = json.loads(row[f"{mode_name}_effective_factor_weights"])
        assert "valuation" not in effective
        assert sum(effective.values()) == pytest.approx(1.0)
        expected = sum(
            row[f"{factor_name}_score"] * weight
            for factor_name, weight in effective.items()
        )
        assert row[f"{mode_name}_score"] == pytest.approx(expected)


def test_free_cash_flow_margin_is_derived_and_inapplicable_for_configured_sectors(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    matrix = _synthetic_matrix(
        factor_document,
        sectors=("Financials", "Real Estate", "Utilities", "Technology"),
        rows_per_sector=10,
        ineligible_keys=(),
    )

    scored = score_feature_matrix(
        matrix, factor_document, modes_document
    ).scored

    inapplicable = scored["sector"].isin(
        ["Financials", "Real Estate", "Utilities"]
    )
    assert scored.loc[inapplicable, "free_cash_flow_margin"].notna().all()
    assert scored.loc[
        inapplicable, "free_cash_flow_margin_scoring_input"
    ].notna().all()
    assert scored.loc[inapplicable, "free_cash_flow_margin_score"].isna().all()
    assert not scored.loc[
        inapplicable, "free_cash_flow_margin_available"
    ].any()
    assert set(
        scored.loc[inapplicable, "free_cash_flow_margin_unavailable_reason"]
    ) == {"inapplicable_sector"}
    assert scored.loc[
        scored["sector"].eq("Technology"), "free_cash_flow_margin_score"
    ].notna().all()


def test_free_cash_flow_margin_requires_positive_same_period_revenue(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    matrix = _synthetic_matrix(
        factor_document,
        rows_per_sector=10,
        ineligible_keys=(),
    )
    mismatched = matrix.index[0]
    nonpositive = matrix.index[1]
    matrix.at[mismatched, "free_cash_flow_period_end"] = "2024-12-31"
    matrix.at[nonpositive, "annual_revenue"] = 0.0

    scored = score_feature_matrix(
        matrix, factor_document, modes_document
    ).scored

    assert pd.isna(scored.at[mismatched, "free_cash_flow_margin"])
    assert pd.isna(scored.at[nonpositive, "free_cash_flow_margin"])
    assert scored.at[
        mismatched, "free_cash_flow_margin_unavailable_reason"
    ] == "missing_value"
    assert scored.at[
        nonpositive, "free_cash_flow_margin_unavailable_reason"
    ] == "missing_value"


def test_sector_strength_uses_eligible_medians_and_cross_sector_rank(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    matrix = _synthetic_matrix(factor_document)

    scored = score_feature_matrix(
        matrix, factor_document, modes_document
    ).scored

    expected = {
        "Alpha": (4.5, 10, 0.0),
        "Beta": (105.0, 11, 50.0),
        "Gamma": (205.0, 11, 100.0),
    }
    for sector, (median, count, score) in expected.items():
        eligible_rows = scored["sector"].eq(sector) & scored[
            "eligible_for_scoring"
        ]
        assert scored.loc[
            eligible_rows, "sector_strength_source_value"
        ].unique().tolist() == [median]
        assert scored.loc[
            eligible_rows, "sector_strength_member_count"
        ].unique().tolist() == [count]
        assert scored.loc[
            eligible_rows, "sector_strength_score"
        ].unique().tolist() == [score]

    ineligible = scored.loc[~scored["eligible_for_scoring"]].iloc[0]
    assert ineligible["relative_strength_3m"] == 1_000_000.0
    assert ineligible["sector_strength_source_value"] == 4.5
    assert ineligible["sector_strength_member_count"] == 10
    assert pd.isna(ineligible["sector_strength_score"])
    assert ineligible["sector_strength_unavailable_reason"] == (
        "ineligible_for_scoring"
    )


def test_profit_margin_scoring_never_uses_raw_audit_field(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    reference = _synthetic_matrix(
        factor_document,
        rows_per_sector=10,
        ineligible_keys=(),
    )
    changed_raw = reference.copy(deep=True)
    changed_raw["profit_margin_raw"] = -changed_raw["profit_margin_raw"] * 99

    original = score_feature_matrix(
        reference,
        factor_document,
        modes_document,
        reference_matrix=reference,
    )
    changed = score_feature_matrix(
        changed_raw,
        factor_document,
        modes_document,
        reference_matrix=reference,
    )

    assert original.scored["profit_margin_scoring_input"].tolist() == (
        reference["profit_margin"].tolist()
    )
    assert not original.scored["profit_margin_scoring_input"].equals(
        reference["profit_margin_raw"]
    )
    assert changed.scored["profit_margin_score"].tolist() == pytest.approx(
        original.scored["profit_margin_score"].tolist()
    )
    assert "profit_margin_raw" not in original.metric_names
    assert "profit_margin_raw_score" not in original.scored


def test_mode_aggregation_handles_one_or_zero_available_factors(
    scoring_configs: tuple[dict, dict],
) -> None:
    _, modes_document = scoring_configs
    scored = pd.DataFrame(
        {
            "eligible_for_scoring": [True, True],
            "momentum_score": [75.0, np.nan],
            "quality_score": [np.nan, np.nan],
            "valuation_score": [np.nan, np.nan],
            "risk_score": [np.nan, np.nan],
            "sector_strength_score": [np.nan, np.nan],
        }
    )

    aggregate_modes(scored, modes_document["screening_modes"], CORE_FACTORS)

    for mode_name in modes_document["screening_modes"]:
        assert scored.at[0, f"{mode_name}_score"] == 75.0
        assert scored.at[0, f"{mode_name}_factor_count"] == 1
        assert json.loads(
            scored.at[0, f"{mode_name}_effective_factor_weights"]
        ) == {"momentum": 1.0}
        assert scored.at[0, f"{mode_name}_unavailable_reason"] is None
        expected_ranking = mode_name != "value"
        assert bool(
            scored.at[0, f"{mode_name}_eligible_for_ranking"]
        ) is expected_ranking
        assert scored.at[0, f"{mode_name}_ranking_exclusion_reasons"] == (
            []
            if expected_ranking
            else ["missing_required_factor:valuation"]
        )

        assert pd.isna(scored.at[1, f"{mode_name}_score"])
        assert scored.at[1, f"{mode_name}_factor_count"] == 0
        assert scored.at[1, f"{mode_name}_available_factors"] == []
        assert scored.at[1, f"{mode_name}_effective_factor_weights"] == "{}"
        assert scored.at[1, f"{mode_name}_unavailable_reason"] == (
            "no_available_factors"
        )
        assert not scored.at[1, f"{mode_name}_eligible_for_ranking"]
        expected_reason = (
            ["missing_required_factor:valuation"]
            if mode_name == "value"
            else ["mode_score_unavailable"]
        )
        assert scored.at[1, f"{mode_name}_ranking_exclusion_reasons"] == (
            expected_reason
        )


def test_value_ranking_requires_valuation_but_keeps_diagnostic_score(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    matrix = _synthetic_matrix(factor_document)
    target_index = matrix.index[
        matrix["sector"].eq("Beta") & matrix["eligible_for_scoring"]
    ][0]
    matrix.at[target_index, "annual_pe_proxy"] = np.nan

    scored = score_feature_matrix(
        matrix, factor_document, modes_document
    ).scored
    row = scored.loc[target_index]

    assert pd.notna(row["value_score"])
    assert not row["value_eligible_for_ranking"]
    assert row["value_ranking_exclusion_reasons"] == [
        "missing_required_factor:valuation"
    ]
    for mode_name in ("balanced", "growth", "low_risk"):
        assert row[f"{mode_name}_eligible_for_ranking"]
        assert row[f"{mode_name}_ranking_exclusion_reasons"] == []


def test_scoring_is_row_order_and_dataframe_index_invariant(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    matrix = _synthetic_matrix(
        factor_document,
        rows_per_sector=10,
        ineligible_keys=(),
    )
    baseline = score_feature_matrix(matrix, factor_document, modes_document)
    shuffled_target = matrix.sample(frac=1.0, random_state=17)
    shuffled_reference = matrix.sample(frac=1.0, random_state=29)
    shuffled_target.index = [0] * len(shuffled_target)
    shuffled_reference.index = [1] * len(shuffled_reference)

    shuffled = score_feature_matrix(
        shuffled_target,
        factor_document,
        modes_document,
        reference_matrix=shuffled_reference,
    )

    detail_columns = [
        column
        for column in baseline.scored.columns
        if column.endswith(
            (
                "_score",
                "_available",
                "_unavailable_reason",
                "_available_components",
                "_effective_metric_weights",
                "_available_factors",
                "_effective_factor_weights",
                "_eligible_for_ranking",
                "_ranking_exclusion_reasons",
            )
        )
    ]
    expected = baseline.scored.set_index("ticker")[detail_columns].sort_index()
    actual = shuffled.scored.set_index("ticker")[detail_columns].sort_index()
    pd.testing.assert_frame_equal(expected, actual)
    pd.testing.assert_frame_equal(
        baseline.metric_sector_coverage,
        shuffled.metric_sector_coverage,
    )


def test_sector_strength_constant_and_single_valid_sector_contract(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    constant = _synthetic_matrix(
        factor_document,
        rows_per_sector=10,
        ineligible_keys=(),
    )
    constant["relative_strength_3m"] = 1.0
    constant_scores = score_feature_matrix(
        constant, factor_document, modes_document
    ).scored
    assert set(constant_scores["sector_strength_score"]) == {50.0}

    single_sector = constant.copy(deep=True)
    single_sector.loc[
        ~single_sector["sector"].eq("Alpha"), "relative_strength_3m"
    ] = np.nan
    single_scores = score_feature_matrix(
        single_sector, factor_document, modes_document
    ).scored
    assert single_scores["sector_strength_score"].isna().all()
    assert set(single_scores["sector_strength_unavailable_reason"]) == {
        "insufficient_valid_sectors"
    }


def test_quality_flags_do_not_create_numeric_penalties(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    matrix = _synthetic_matrix(
        factor_document,
        rows_per_sector=10,
        ineligible_keys=(),
    )
    matrix["data_quality_flags"] = [[] for _ in range(len(matrix))]
    flagged = matrix.copy(deep=True)
    flagged["data_quality_flags"] = [
        ["arbitrary_audit_warning"] for _ in range(len(flagged))
    ]

    baseline = score_feature_matrix(matrix, factor_document, modes_document)
    changed = score_feature_matrix(flagged, factor_document, modes_document)
    numeric_score_columns = [
        column for column in baseline.scored if column.endswith("_score")
    ]
    pd.testing.assert_frame_equal(
        baseline.scored[numeric_score_columns],
        changed.scored[numeric_score_columns],
    )


def test_frozen_reproduction_is_bound_to_accepted_contract(
    scoring_configs: tuple[dict, dict],
) -> None:
    factor_document, modes_document = scoring_configs
    factor_path = ROOT / "config/factor_model.yaml"
    modes_path = ROOT / "config/screening_modes.yaml"
    input_hash = "a" * 64
    input_metadata = {
        "run_id": "accepted_features",
        "contract_version": "1.0.0",
        "as_of_date": "2026-07-13",
    }
    header = {
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
        "factor_config_sha256": hashlib.sha256(
            factor_path.read_bytes()
        ).hexdigest(),
        "modes_config_sha256": hashlib.sha256(
            modes_path.read_bytes()
        ).hexdigest(),
        "input_feature_run_id": "accepted_features",
        "input_contract_version": "1.0.0",
        "input_feature_matrix_sha256": input_hash,
        "accepted_as_of_date": "2026-07-13",
    }

    _validate_frozen_scoring_reproduction(
        header,
        factor_document,
        modes_document,
        factor_path,
        modes_path,
        input_metadata,
        input_hash,
    )

    drifted = dict(header, factor_config_sha256="b" * 64)
    with pytest.raises(ScoringError, match="factor_config_sha256"):
        _validate_frozen_scoring_reproduction(
            drifted,
            factor_document,
            modes_document,
            factor_path,
            modes_path,
            input_metadata,
            input_hash,
        )
