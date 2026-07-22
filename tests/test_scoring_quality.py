from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

import src.scoring_quality as scoring_quality
from src.scoring import (
    ScoringError,
    _load_accepted_input,
    load_yaml_document,
    main,
    score_feature_matrix,
)
from src.scoring_quality import analyze_scored_matrix, write_scoring_artifacts


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ARTIFACTS = {
    "scored_matrix.parquet",
    "scoring_audit.csv",
    "metric_sector_coverage.csv",
    "factor_coverage.csv",
    "score_distributions.csv",
    "scoring_quality.json",
    "run_metadata.json",
    "quality_report.md",
}


def _synthetic_input(factor_document: dict) -> pd.DataFrame:
    metric_names = list(
        dict.fromkeys(
            metric_name
            for factor in factor_document["factors"].values()
            for metric_name, metric_spec in factor.get("metrics", {}).items()
            if "derivation" not in metric_spec
        )
    )
    rows = []
    for sector_number, sector in enumerate(("Alpha", "Beta")):
        for row_number in range(10):
            row = {
                "as_of_date": "2026-07-13",
                "ticker": f"T{sector_number}{row_number:02d}",
                "company_name": f"Company {sector_number}-{row_number}",
                "sector": sector,
                "eligible_for_scoring": True,
                "data_quality_flags": [],
                "missing_fields": [],
                "stale_fundamental_metrics": [],
                "exclusion_reasons": [],
            }
            for metric_number, metric_name in enumerate(metric_names):
                row[metric_name] = float(
                    sector_number * 20 + row_number + metric_number / 100
                )
            row["relative_strength_3m"] = float(
                sector_number * 20 + row_number
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
            rows.append(row)
    ineligible = dict(rows[0])
    ineligible.update(
        ticker="INEL",
        company_name="Ineligible Company",
        eligible_for_scoring=False,
        exclusion_reasons=["synthetic_exclusion"],
    )
    rows.append(ineligible)
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def clean_build():
    factor_document = load_yaml_document(ROOT / "config/factor_model.yaml")
    modes_document = load_yaml_document(ROOT / "config/screening_modes.yaml")
    matrix = _synthetic_input(factor_document)
    build = score_feature_matrix(matrix, factor_document, modes_document)
    metadata = {
        "run_id": "synthetic_scoring",
        "as_of_date": "2026-07-13",
        "input_feature_run_id": "synthetic_features",
        "input_contract_version": "1.0.0",
        "factor_model_version": str(factor_document["version"]),
        "screening_modes_version": str(modes_document["version"]),
    }
    for column in (
        "input_feature_run_id",
        "input_contract_version",
        "factor_model_version",
        "screening_modes_version",
    ):
        build.scored[column] = metadata[column]
    return matrix, build, metadata, factor_document, modes_document


def _analyze(
    scored,
    matrix,
    build,
    metadata,
    factor_document,
    modes_document,
    metric_sector_coverage=None,
):
    return analyze_scored_matrix(
        scored,
        matrix,
        metadata,
        build.metric_names,
        build.factor_names,
        build.mode_names,
        (
            build.metric_sector_coverage
            if metric_sector_coverage is None
            else metric_sector_coverage
        ),
        factor_document=factor_document,
        modes_document=modes_document,
    )


def test_clean_scored_build_passes_all_hard_gates(clean_build) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build

    quality = _analyze(
        build.scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert quality.summary["acceptance"] == {
        "passed": True,
        "hard_failures": [],
        "warnings": [],
    }
    assert quality.summary["effective_weights"]["violation_count"] == 0
    assert quality.summary["numeric_evidence_schema"]["valid"] is True
    assert quality.summary["numeric_evidence_schema"][
        "checked_column_count"
    ] == 69
    assert quality.summary["eligibility"]["ineligible_rows_with_scores"][
        "row_count"
    ] == 0


def test_scoring_quality_fails_closed_without_recomputation_configs(clean_build) -> None:
    matrix, build, metadata, _, _ = clean_build

    quality = analyze_scored_matrix(
        build.scored,
        matrix,
        metadata,
        build.metric_names,
        build.factor_names,
        build.mode_names,
        build.metric_sector_coverage,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "independent_recomputation_not_executed" in quality.summary["acceptance"][
        "hard_failures"
    ]


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        ("score_above_100", "score_range_validation_failed"),
        ("ineligible_score", "ineligible_scores_present"),
        ("eligible_mode_missing", "eligible_mode_scores_missing"),
        ("invalid_effective_weights", "effective_weight_validation_failed"),
        ("duplicate_primary_key", "primary_key_validation_failed"),
        ("aggregate_tamper", "aggregate_arithmetic_validation_failed"),
        ("nonboolean_eligibility", "row_accounting_failed"),
    ],
)
def test_scoring_quality_hard_gate_regressions(
    clean_build, mutation: str, expected_failure: str
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    scored = build.scored.copy(deep=True)
    eligible_index = scored.index[scored["eligible_for_scoring"]][0]
    ineligible_index = scored.index[~scored["eligible_for_scoring"]][0]

    if mutation == "score_above_100":
        scored.at[eligible_index, "return_1m_score"] = 100.01
    elif mutation == "ineligible_score":
        scored.at[ineligible_index, "balanced_score"] = 50.0
    elif mutation == "eligible_mode_missing":
        scored.at[eligible_index, "balanced_score"] = np.nan
    elif mutation == "invalid_effective_weights":
        scored.at[eligible_index, "momentum_effective_metric_weights"] = (
            '{"return_1m":0.25}'
        )
    elif mutation == "duplicate_primary_key":
        scored.at[scored.index[1], "ticker"] = scored.at[scored.index[0], "ticker"]
    elif mutation == "aggregate_tamper":
        scored.at[eligible_index, "balanced_score"] = 42.0
    elif mutation == "nonboolean_eligibility":
        scored["eligible_for_scoring"] = scored[
            "eligible_for_scoring"
        ].astype(object)
        scored.at[ineligible_index, "eligible_for_scoring"] = "false"

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert expected_failure in quality.summary["acceptance"]["hard_failures"]


@pytest.mark.parametrize(
    "column",
    ["return_1m_score", "momentum_score", "balanced_score"],
)
def test_numeric_score_string_dtype_fails_quality_gate(
    clean_build, column: str
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    scored = build.scored.copy(deep=True)
    scored[column] = scored[column].astype("string")

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "numeric_evidence_dtype_validation_failed" in quality.summary[
        "acceptance"
    ]["hard_failures"]
    assert column in quality.summary["numeric_evidence_schema"][
        "invalid_columns"
    ]


@pytest.mark.parametrize(
    "column", ["momentum_component_count", "balanced_factor_count"]
)
def test_numeric_count_string_dtype_fails_quality_gate(
    clean_build, column: str
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    scored = build.scored.copy(deep=True)
    scored[column] = scored[column].astype("string")

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert "numeric_evidence_dtype_validation_failed" in quality.summary[
        "acceptance"
    ]["hard_failures"]
    assert column in quality.summary["numeric_evidence_schema"][
        "invalid_columns"
    ]


def test_effective_weight_numeric_string_fails_quality_gate(clean_build) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[scored["eligible_for_scoring"]][0]
    column = "momentum_effective_metric_weights"
    weights = json.loads(scored.at[index, column])
    first_key = next(iter(weights))
    weights[first_key] = str(weights[first_key])
    scored.at[index, column] = json.dumps(weights)

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert "effective_weight_validation_failed" in quality.summary[
        "acceptance"
    ]["hard_failures"]


@pytest.mark.parametrize(
    "mutation",
    ["score", "available", "reason", "winsorized", "nonboolean_false"],
)
def test_metric_transform_tampering_fails_independent_recomputation(
    clean_build, mutation: str
) -> None:
    (
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    ) = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[scored["eligible_for_scoring"]][0]

    if mutation == "score":
        scored.at[index, "return_1m_score"] += 0.25
    elif mutation == "available":
        scored.at[index, "return_1m_available"] = False
    elif mutation == "reason":
        scored.at[index, "return_1m_unavailable_reason"] = "missing_value"
    elif mutation == "winsorized":
        scored.at[index, "return_1m_winsorized"] += 0.25
    elif mutation == "nonboolean_false":
        ineligible = scored.index[~scored["eligible_for_scoring"]][0]
        scored["return_1m_available"] = scored[
            "return_1m_available"
        ].astype(object)
        scored.at[ineligible, "return_1m_available"] = "false"

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "metric_transform_validation_failed" in quality.summary["acceptance"][
        "hard_failures"
    ]


def test_derived_metric_tampering_fails_independent_recomputation(
    clean_build,
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[
        scored["eligible_for_scoring"]
        & scored["free_cash_flow_margin"].notna()
    ][0]
    scored.at[index, "free_cash_flow_margin"] += 0.01

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "metric_transform_validation_failed" in quality.summary["acceptance"][
        "hard_failures"
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "sector",
        "company_name",
        "raw_numerator",
        "period",
        "quality_list",
        "missing_column",
    ],
)
def test_input_projection_tampering_fails_closed(
    clean_build, mutation: str
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[scored["eligible_for_scoring"]][0]
    if mutation == "sector":
        scored.at[index, "sector"] = "Tampered Sector"
    elif mutation == "company_name":
        scored.at[index, "company_name"] = "Tampered Company"
    elif mutation == "raw_numerator":
        scored.at[index, "annual_free_cash_flow"] += 1.0
    elif mutation == "period":
        scored.at[index, "free_cash_flow_period_end"] = "2024-12-31"
    elif mutation == "quality_list":
        scored.at[index, "data_quality_flags"] = ["tampered"]
    else:
        scored = scored.drop(columns="company_name")

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "input_projection_validation_failed" in quality.summary[
        "acceptance"
    ]["hard_failures"]


@pytest.mark.parametrize(
    "mutation",
    ["source_value", "member_count", "score"],
)
def test_sector_strength_tampering_fails_independent_recomputation(
    clean_build, mutation: str
) -> None:
    (
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    ) = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[scored["eligible_for_scoring"]][0]

    if mutation == "source_value":
        scored.at[index, "sector_strength_source_value"] += 0.25
    elif mutation == "member_count":
        scored.at[index, "sector_strength_member_count"] += 1
    elif mutation == "score":
        scored.at[index, "sector_strength_score"] += 0.25

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "sector_strength_validation_failed" in quality.summary["acceptance"][
        "hard_failures"
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "factor_ownership",
        "valid_reference_count",
        "cutoff",
        "applicability",
        "nonboolean_applicability",
        "scored_target_count",
    ],
)
def test_metric_sector_coverage_tampering_fails_independent_recomputation(
    clean_build, mutation: str
) -> None:
    (
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    ) = clean_build
    coverage = build.metric_sector_coverage.copy(deep=True)
    index = coverage.index[
        coverage["metric"].eq("return_1m") & coverage["sector"].eq("Alpha")
    ][0]

    if mutation == "factor_ownership":
        coverage.at[index, "factor"] = "risk"
    elif mutation == "valid_reference_count":
        coverage.at[index, "valid_reference_count"] += 1
    elif mutation == "cutoff":
        coverage.at[index, "lower_cutoff"] += 0.25
    elif mutation == "applicability":
        coverage.at[index, "inapplicable_sector"] = True
    elif mutation == "nonboolean_applicability":
        coverage["inapplicable_sector"] = coverage[
            "inapplicable_sector"
        ].astype(object)
        coverage.at[index, "inapplicable_sector"] = "false"
    elif mutation == "scored_target_count":
        coverage.at[index, "scored_target_count"] += 1

    quality = _analyze(
        build.scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
        metric_sector_coverage=coverage,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "metric_sector_coverage_validation_failed" in quality.summary[
        "acceptance"
    ]["hard_failures"]


@pytest.mark.parametrize(
    "column",
    ["momentum_component_count", "balanced_factor_count"],
)
def test_component_count_tampering_fails_independent_recomputation(
    clean_build, column: str
) -> None:
    (
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    ) = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[scored["eligible_for_scoring"]][0]
    scored.at[index, column] += 1

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "component_contract_validation_failed" in quality.summary["acceptance"][
        "hard_failures"
    ]


@pytest.mark.parametrize(
    "mutation", ["eligibility", "reason", "nonboolean_false"]
)
def test_mode_ranking_eligibility_tampering_fails_independent_recomputation(
    clean_build, mutation: str
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[scored["value_eligible_for_ranking"]][0]
    if mutation == "eligibility":
        scored.at[index, "value_eligible_for_ranking"] = False
    elif mutation == "reason":
        scored.at[index, "value_ranking_exclusion_reasons"] = [
            "missing_required_factor:valuation"
        ]
    else:
        ineligible = scored.index[~scored["eligible_for_scoring"]][0]
        scored["value_eligible_for_ranking"] = scored[
            "value_eligible_for_ranking"
        ].astype(object)
        scored.at[ineligible, "value_eligible_for_ranking"] = "false"

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "mode_ranking_eligibility_validation_failed" in quality.summary[
        "acceptance"
    ]["hard_failures"]


@pytest.mark.parametrize(
    "column",
    [
        "input_feature_run_id",
        "input_contract_version",
        "factor_model_version",
        "screening_modes_version",
    ],
)
def test_row_provenance_tampering_fails_independent_recomputation(
    clean_build, column: str
) -> None:
    (
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    ) = clean_build
    scored = build.scored.copy(deep=True)
    index = scored.index[scored["eligible_for_scoring"]][0]
    scored.at[index, column] = "tampered"

    quality = _analyze(
        scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "row_provenance_validation_failed" in quality.summary["acceptance"][
        "hard_failures"
    ]


def test_empty_metric_sector_coverage_fails_closed(clean_build) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build

    quality = _analyze(
        build.scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
        metric_sector_coverage=build.metric_sector_coverage.iloc[0:0],
    )

    assert not quality.summary["acceptance"]["passed"]
    assert "metric_sector_coverage_validation_failed" in quality.summary[
        "acceptance"
    ]["hard_failures"]


def test_write_scoring_artifacts_is_complete_and_atomic(
    clean_build, tmp_path: Path
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    quality = _analyze(
        build.scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    paths = write_scoring_artifacts(
        build.scored, quality, tmp_path, metadata["run_id"]
    )

    assert {path.name for path in paths.run_dir.iterdir()} == EXPECTED_ARTIFACTS
    assert not [path for path in tmp_path.rglob(".*") if path.is_file()]
    persisted_quality = json.loads(paths.scoring_quality_json.read_text())
    persisted_metadata = json.loads(paths.run_metadata_json.read_text())
    assert persisted_quality["run"] == metadata
    assert persisted_metadata == metadata


def test_write_scoring_artifacts_rejects_existing_run_directory(
    clean_build, tmp_path: Path
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    quality = _analyze(
        build.scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )
    run_dir = tmp_path / metadata["run_id"]
    run_dir.mkdir()
    marker = run_dir / "existing.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        write_scoring_artifacts(
            build.scored,
            quality,
            tmp_path,
            metadata["run_id"],
        )

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert {path.name for path in run_dir.iterdir()} == {"existing.txt"}
    assert not [
        path
        for path in tmp_path.iterdir()
        if path.name.startswith(f".{metadata['run_id']}.")
    ]


def test_write_scoring_artifacts_rolls_back_staging_on_failure(
    clean_build, tmp_path: Path, monkeypatch
) -> None:
    matrix, build, metadata, factor_document, modes_document = clean_build
    quality = _analyze(
        build.scored,
        matrix,
        build,
        metadata,
        factor_document,
        modes_document,
    )

    def fail_csv_write(*args, **kwargs):
        raise OSError("synthetic artifact failure")

    monkeypatch.setattr(scoring_quality, "atomic_write_csv", fail_csv_write)

    with pytest.raises(OSError, match="synthetic artifact failure"):
        write_scoring_artifacts(
            build.scored,
            quality,
            tmp_path,
            metadata["run_id"],
        )

    assert not (tmp_path / metadata["run_id"]).exists()
    assert list(tmp_path.iterdir()) == []


def test_local_accepted_input_runs_end_to_end_without_network(
    clean_build, tmp_path: Path
) -> None:
    matrix, _, _, _, _ = clean_build
    project_root = tmp_path / "project"
    config_dir = project_root / "config"
    input_run = tmp_path / "accepted"
    output_root = tmp_path / "output"
    config_dir.mkdir(parents=True)
    input_run.mkdir()
    matrix.to_parquet(input_run / "feature_matrix.parquet", index=False)
    matrix_hash = hashlib.sha256(
        (input_run / "feature_matrix.parquet").read_bytes()
    ).hexdigest()
    (config_dir / "data_contract.yaml").write_text(
        yaml.safe_dump(
            {
                "contract": {
                    "version": "1.0.0",
                    "status": "frozen_v1",
                    "accepted_run_id": "accepted",
                    "accepted_as_of_date": "2026-07-13",
                    "accepted_feature_matrix_sha256": matrix_hash,
                }
            }
        ),
        encoding="utf-8",
    )
    input_metadata = {
        "run_id": "accepted",
        "as_of_date": "2026-07-13",
        "contract_version": "1.0.0",
        "contract_status": "frozen_v1",
    }
    (input_run / "run_metadata.json").write_text(
        json.dumps(input_metadata), encoding="utf-8"
    )
    (input_run / "matrix_quality.json").write_text(
        json.dumps(
            {
                "run": input_metadata,
                "acceptance": {"passed": True},
                "schema": {"schema_valid": True},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--project-root",
            str(project_root),
            "--input-run",
            str(input_run),
            "--factor-config",
            str(ROOT / "config/factor_model.yaml"),
            "--modes-config",
            str(ROOT / "config/screening_modes.yaml"),
            "--output-dir",
            str(output_root),
            "--run-id",
            "end_to_end",
        ]
    )

    run_dir = output_root / "end_to_end"
    assert exit_code == 0
    assert {path.name for path in run_dir.iterdir()} == EXPECTED_ARTIFACTS
    scored = pd.read_parquet(run_dir / "scored_matrix.parquet")
    score_columns = [column for column in scored if column.endswith("_score")]
    assert scored.loc[~scored["eligible_for_scoring"], score_columns].isna().all().all()
    assert set(scored["input_feature_run_id"]) == {"accepted"}
    assert set(scored["input_contract_version"]) == {"1.0.0"}
    assert set(scored["factor_model_version"]) == {
        str(load_yaml_document(ROOT / "config/factor_model.yaml")["version"])
    }
    assert set(scored["screening_modes_version"]) == {
        str(load_yaml_document(ROOT / "config/screening_modes.yaml")["version"])
    }
    metadata = json.loads((run_dir / "run_metadata.json").read_text())
    assert metadata["input_feature_matrix_sha256"] == matrix_hash


def test_accepted_input_fails_closed_on_quality_version_or_hash(
    clean_build, tmp_path: Path
) -> None:
    matrix, _, _, _, _ = clean_build
    project_root = tmp_path / "project"
    input_run = tmp_path / "accepted"
    (project_root / "config").mkdir(parents=True)
    input_run.mkdir()
    matrix_path = input_run / "feature_matrix.parquet"
    matrix.to_parquet(matrix_path, index=False)
    matrix_hash = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    contract = {
        "contract": {
            "version": "1.0.0",
            "status": "frozen_v1",
            "accepted_run_id": "accepted",
            "accepted_as_of_date": "2026-07-13",
            "accepted_feature_matrix_sha256": matrix_hash,
        }
    }
    (project_root / "config/data_contract.yaml").write_text(
        yaml.safe_dump(contract), encoding="utf-8"
    )
    metadata = {
        "run_id": "accepted",
        "as_of_date": "2026-07-13",
        "contract_version": "1.0.0",
        "contract_status": "frozen_v1",
    }
    (input_run / "run_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    def write_quality(passed: object, schema_valid: object = True) -> None:
        (input_run / "matrix_quality.json").write_text(
            json.dumps(
                {
                    "run": metadata,
                    "acceptance": {"passed": passed},
                    "schema": {"schema_valid": schema_valid},
                }
            ),
            encoding="utf-8",
        )

    write_quality(False)
    with pytest.raises(ScoringError, match="did not pass"):
        _load_accepted_input(project_root, input_run)

    write_quality("false")
    with pytest.raises(ScoringError, match="did not pass"):
        _load_accepted_input(project_root, input_run)

    write_quality(True, schema_valid="false")
    with pytest.raises(ScoringError, match="schema was not valid"):
        _load_accepted_input(project_root, input_run)

    write_quality(True)
    metadata["contract_version"] = "0.9.0"
    (input_run / "run_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    write_quality(True)
    with pytest.raises(ScoringError, match="contract version"):
        _load_accepted_input(project_root, input_run)

    metadata["contract_version"] = "1.0.0"
    (input_run / "run_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    write_quality(True)
    tampered = matrix.copy()
    tampered.loc[0, "return_1m"] += 0.01
    tampered.to_parquet(matrix_path, index=False)
    with pytest.raises(ScoringError, match="hash"):
        _load_accepted_input(project_root, input_run)
