from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.scoring import score_feature_matrix
from src.scoring_contract import (
    ScoringContractError,
    load_accepted_scoring_run,
)
from src.scoring_quality import analyze_scored_matrix


ROOT = Path(__file__).resolve().parents[1]
MODE_NAMES = ["balanced", "growth", "value", "low_risk"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_quality_and_contract_hash(
    project_root: Path,
    quality: dict[str, object],
) -> None:
    quality_path = (
        project_root
        / "data/processed/accepted_scores/scoring_quality.json"
    )
    quality_path.write_text(json.dumps(quality), encoding="utf-8")
    contract_path = project_root / "config/scoring_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["scoring_contract"][
        "accepted_scoring_quality_sha256"
    ] = _sha256(quality_path)
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )


def _write_synthetic_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    config_dir = project_root / "config"
    run_id = "accepted_scores"
    run_dir = project_root / "data/processed" / run_id
    config_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)

    factor_document = yaml.safe_load(
        (ROOT / "config/factor_model.yaml").read_text(encoding="utf-8")
    )
    modes_document = yaml.safe_load(
        (ROOT / "config/screening_modes.yaml").read_text(encoding="utf-8")
    )
    factor_path = config_dir / "factor_model.yaml"
    modes_path = config_dir / "screening_modes.yaml"
    factor_path.write_text(
        yaml.safe_dump(factor_document, sort_keys=False), encoding="utf-8"
    )
    modes_path.write_text(
        yaml.safe_dump(modes_document, sort_keys=False), encoding="utf-8"
    )

    input_run = project_root / "data/processed/accepted_features"
    input_run.mkdir(parents=True)
    input_matrix_path = input_run / "feature_matrix.parquet"
    row_count = 21
    values = np.arange(row_count, dtype=float)
    input_matrix = pd.DataFrame(
        {
            "as_of_date": ["2026-07-13"] * row_count,
            "ticker": [f"T{index:03d}" for index in range(row_count)],
            "company": [f"Company {index}" for index in range(row_count)],
            "sector": ["Sector A"] * 10 + ["Sector B"] * 11,
            "eligible_for_scoring": [True] * 20 + [False],
            "return_1m": 0.01 + values / 1000.0,
            "return_3m": 0.02 + values / 500.0,
            "return_6m": 0.03 + values / 250.0,
            "ma20_gap": -0.05 + values / 200.0,
            "ma50_gap": -0.10 + values / 150.0,
            "volume_trend": 0.8 + values / 20.0,
            "revenue_growth": -0.10 + values / 50.0,
            "profit_margin": 0.05 + values / 100.0,
            "roe": 0.08 + values / 80.0,
            "annual_free_cash_flow": 20.0 + values,
            "annual_revenue": 100.0 + values * 2.0,
            "free_cash_flow_period_end": ["2025-12-31"] * row_count,
            "annual_revenue_period_end": ["2025-12-31"] * row_count,
            "annual_pe_proxy": 10.0 + values,
            "volatility_20d": 0.10 + values / 200.0,
            "volatility_60d": 0.12 + values / 180.0,
            "beta_1y": 0.6 + values / 20.0,
            "liabilities_to_equity": 0.5 + values / 10.0,
            "max_drawdown_1y": -0.50 + values / 100.0,
            "relative_strength_3m": -0.10 + values / 40.0,
        }
    )
    input_matrix.to_parquet(input_matrix_path, index=False)
    input_hash = _sha256(input_matrix_path)
    (config_dir / "data_contract.yaml").write_text(
        yaml.safe_dump(
            {
                "contract": {
                    "version": "1.0.0",
                    "status": "frozen_v1",
                    "accepted_run_id": "accepted_features",
                    "accepted_as_of_date": "2026-07-13",
                    "accepted_feature_matrix_sha256": input_hash,
                }
            }
        ),
        encoding="utf-8",
    )

    metadata = {
        "run_id": run_id,
        "as_of_date": "2026-07-13",
        "input_feature_run_id": "accepted_features",
        "input_contract_version": "1.0.0",
        "input_contract_status": "frozen_v1",
        "input_feature_matrix_sha256": input_hash,
        "accepted_contract_run_id": "accepted_features",
        "factor_model_version": "1.0.0",
        "factor_model_status": "frozen_v1",
        "screening_modes_version": "1.0.0",
        "screening_modes_status": "frozen_v1",
        "factor_config_sha256": _sha256(factor_path),
        "modes_config_sha256": _sha256(modes_path),
    }
    build = score_feature_matrix(
        input_matrix, factor_document, modes_document
    )
    provenance = {
        "input_feature_run_id": "accepted_features",
        "input_contract_version": "1.0.0",
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
    }
    for column, value in provenance.items():
        build.scored[column] = value

    matrix_path = run_dir / "scored_matrix.parquet"
    build.scored.to_parquet(matrix_path, index=False)
    coverage_path = run_dir / "metric_sector_coverage.csv"
    build.metric_sector_coverage.to_csv(coverage_path, index=False)
    metadata_path = run_dir / "run_metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    quality = analyze_scored_matrix(
        build.scored,
        input_matrix,
        metadata,
        build.metric_names,
        build.factor_names,
        build.mode_names,
        build.metric_sector_coverage,
        factor_document=factor_document,
        modes_document=modes_document,
    ).summary
    assert quality["acceptance"]["passed"] is True
    quality_path = run_dir / "scoring_quality.json"
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    contract = {
        "scoring_contract": {
            "version": "1.0.0",
            "status": "frozen_v1",
            "accepted_run_id": run_id,
            "accepted_run_path": f"data/processed/{run_id}",
            "accepted_as_of_date": "2026-07-13",
            "accepted_scored_matrix_sha256": _sha256(matrix_path),
            "accepted_scoring_quality_sha256": _sha256(quality_path),
            "accepted_run_metadata_sha256": _sha256(metadata_path),
            "accepted_metric_sector_coverage_sha256": _sha256(
                coverage_path
            ),
            "input_feature_run_id": "accepted_features",
            "input_contract_version": "1.0.0",
            "input_feature_matrix_sha256": input_hash,
            "factor_model_version": "1.0.0",
            "factor_config_sha256": _sha256(factor_path),
            "screening_modes_version": "1.0.0",
            "modes_config_sha256": _sha256(modes_path),
            "row_count": row_count,
            "eligible_count": 20,
            "mode_names": MODE_NAMES,
            "mode_ranking_eligible_counts": {
                mode: int(
                    build.scored[f"{mode}_eligible_for_ranking"].sum()
                )
                for mode in MODE_NAMES
            },
            "accepted_warnings": quality["acceptance"]["warnings"],
        }
    }
    (config_dir / "scoring_contract.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )
    return project_root


def test_repository_scoring_contract_is_frozen_and_hash_addressed() -> None:
    document = yaml.safe_load(
        (ROOT / "config/scoring_contract.yaml").read_text(encoding="utf-8")
    )
    contract = document["scoring_contract"]

    assert contract["version"] == "1.0.2"
    assert contract["status"] == "frozen_v1"
    assert contract["accepted_run_id"] == "2026-07-13_sp500_scores_v1_0_2"
    assert contract["accepted_run_path"] == (
        "data/processed/2026-07-13_sp500_scores_v1_0_2"
    )
    assert contract["row_count"] == 503
    assert contract["eligible_count"] == 499
    assert contract["mode_ranking_eligible_counts"] == {
        "balanced": 499,
        "growth": 499,
        "value": 435,
        "low_risk": 499,
    }
    for field in (
        "accepted_scored_matrix_sha256",
        "accepted_scoring_quality_sha256",
        "accepted_run_metadata_sha256",
        "accepted_metric_sector_coverage_sha256",
        "input_feature_matrix_sha256",
        "factor_config_sha256",
        "modes_config_sha256",
    ):
        digest = contract[field]
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")


def test_load_accepted_scoring_run_verifies_synthetic_contract(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)

    accepted = load_accepted_scoring_run(project_root)

    assert accepted.run_dir.name == "accepted_scores"
    assert accepted.scored_matrix["ticker"].tolist() == [
        f"T{index:03d}" for index in range(21)
    ]
    assert accepted.metadata["factor_model_status"] == "frozen_v1"


def test_load_accepted_scoring_run_rejects_hash_tampering(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    matrix_path = (
        project_root / "data/processed/accepted_scores/scored_matrix.parquet"
    )
    matrix_path.write_bytes(matrix_path.read_bytes() + b"tampered")

    with pytest.raises(ScoringContractError, match="scored_matrix_sha256"):
        load_accepted_scoring_run(project_root)


def test_load_accepted_scoring_run_rejects_incomplete_quality_evidence(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    quality_path = (
        project_root
        / "data/processed/accepted_scores/scoring_quality.json"
    )
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["independent_recomputation"].pop("input_projection")
    _rewrite_quality_and_contract_hash(project_root, quality)

    with pytest.raises(ScoringContractError, match="input_projection"):
        load_accepted_scoring_run(project_root)


def test_load_accepted_scoring_run_rejects_phase2_input_tampering(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    input_path = (
        project_root
        / "data/processed/accepted_features/feature_matrix.parquet"
    )
    input_path.write_bytes(input_path.read_bytes() + b"tampered")

    with pytest.raises(ScoringContractError, match="input_feature_matrix_sha256"):
        load_accepted_scoring_run(project_root)


def test_load_accepted_scoring_run_rejects_symlinked_artifact(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    matrix_path = (
        project_root / "data/processed/accepted_scores/scored_matrix.parquet"
    )
    alternate_path = project_root / "alternate.parquet"
    alternate_path.write_bytes(matrix_path.read_bytes())
    matrix_path.unlink()
    matrix_path.symlink_to(alternate_path)

    with pytest.raises(ScoringContractError, match="symbolic link"):
        load_accepted_scoring_run(project_root)


def test_load_accepted_scoring_run_recomputes_phase2_projection(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    input_path = (
        project_root
        / "data/processed/accepted_features/feature_matrix.parquet"
    )
    input_matrix = pd.read_parquet(input_path)
    input_matrix.at[0, "company"] = "Changed after scoring"
    input_matrix.to_parquet(input_path, index=False)
    input_hash = _sha256(input_path)

    data_contract_path = project_root / "config/data_contract.yaml"
    data_contract = yaml.safe_load(
        data_contract_path.read_text(encoding="utf-8")
    )
    data_contract["contract"][
        "accepted_feature_matrix_sha256"
    ] = input_hash
    data_contract_path.write_text(
        yaml.safe_dump(data_contract, sort_keys=False), encoding="utf-8"
    )

    run_dir = project_root / "data/processed/accepted_scores"
    metadata_path = run_dir / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["input_feature_matrix_sha256"] = input_hash
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    quality_path = run_dir / "scoring_quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["run"] = metadata
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    contract_path = project_root / "config/scoring_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    header = contract["scoring_contract"]
    header["input_feature_matrix_sha256"] = input_hash
    header["accepted_run_metadata_sha256"] = _sha256(metadata_path)
    header["accepted_scoring_quality_sha256"] = _sha256(quality_path)
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ScoringContractError, match="independent recomputation"):
        load_accepted_scoring_run(project_root)


def test_load_accepted_scoring_run_rejects_forged_nested_quality(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    quality_path = (
        project_root
        / "data/processed/accepted_scores/scoring_quality.json"
    )
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["independent_recomputation"]["metric_transforms"][
        "by_metric"
    ]["return_1m"]["violation_count"] = 7
    _rewrite_quality_and_contract_hash(project_root, quality)

    with pytest.raises(ScoringContractError, match="independent recomputation"):
        load_accepted_scoring_run(project_root)


def test_load_accepted_scoring_run_recomputes_factor_scores(
    tmp_path: Path,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    matrix_path = (
        project_root / "data/processed/accepted_scores/scored_matrix.parquet"
    )
    scored = pd.read_parquet(matrix_path)
    scored.at[0, "momentum_score"] = 99.0
    scored.to_parquet(matrix_path, index=False)
    contract_path = project_root / "config/scoring_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["scoring_contract"][
        "accepted_scored_matrix_sha256"
    ] = _sha256(matrix_path)
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ScoringContractError, match="independent recomputation"):
        load_accepted_scoring_run(project_root)


@pytest.mark.parametrize(
    "column",
    ["return_1m_score", "momentum_score", "balanced_score"],
)
def test_load_accepted_scoring_run_rejects_string_score_dtype(
    tmp_path: Path,
    column: str,
) -> None:
    project_root = _write_synthetic_project(tmp_path)
    matrix_path = (
        project_root / "data/processed/accepted_scores/scored_matrix.parquet"
    )
    scored = pd.read_parquet(matrix_path)
    scored[column] = scored[column].astype("string")
    scored.to_parquet(matrix_path, index=False)
    contract_path = project_root / "config/scoring_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["scoring_contract"][
        "accepted_scored_matrix_sha256"
    ] = _sha256(matrix_path)
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ScoringContractError, match="non-numeric score"):
        load_accepted_scoring_run(project_root)
