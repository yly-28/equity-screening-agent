"""Verification for the frozen, accepted Phase 3 scoring artifact."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd
import yaml


FROZEN_STATUS = "frozen_v1"
EXPECTED_MODE_NAMES = ("balanced", "growth", "value", "low_risk")


class ScoringContractError(RuntimeError):
    """Raised when the accepted scoring artifact violates its frozen contract."""


@dataclass(frozen=True)
class AcceptedScoringRun:
    """A verified accepted scoring run ready for downstream application code."""

    scored_matrix: pd.DataFrame
    metadata: Dict[str, object]
    quality: Dict[str, object]
    contract: Dict[str, object]
    run_dir: Path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink():
        raise ScoringContractError(f"{label} may not be a symbolic link: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ScoringContractError(f"Cannot read {label}: {path}") from exc


def _load_yaml_bytes(value: bytes, path: Path) -> Dict[str, object]:
    try:
        document = yaml.safe_load(value.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ScoringContractError(f"Cannot parse YAML document: {path}") from exc
    if not isinstance(document, dict):
        raise ScoringContractError(f"YAML document must be a mapping: {path}")
    return document


def _load_json_bytes(value: bytes, path: Path) -> Dict[str, object]:
    try:
        document = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScoringContractError(f"Cannot parse JSON document: {path}") from exc
    if not isinstance(document, dict):
        raise ScoringContractError(f"JSON document must be an object: {path}")
    return document


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ScoringContractError(f"{label} must be a mapping")
    return value


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ScoringContractError(f"{label} must be a non-negative integer")
    return value


def _expected_hash(header: Mapping[str, object], field: str) -> str:
    value = str(header.get(field) or "")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ScoringContractError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_equal(actual: object, expected: object, label: str) -> None:
    if str(actual) != str(expected):
        raise ScoringContractError(f"{label} does not match the frozen scoring contract")


def _strict_eligible_mask(frame: pd.DataFrame) -> pd.Series:
    if "eligible_for_scoring" not in frame:
        raise ScoringContractError("Accepted scored matrix is missing eligible_for_scoring")
    valid = frame["eligible_for_scoring"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not bool(valid.all()):
        raise ScoringContractError(
            "Accepted scored matrix has non-boolean eligibility values"
        )
    return frame["eligible_for_scoring"].astype(bool)


def _reason_list(value: object) -> list[str]:
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise ScoringContractError("Ranking exclusion reasons must be a list")
    if any(not isinstance(item, str) for item in value):
        raise ScoringContractError("Ranking exclusion reasons must contain strings")
    return list(value)


def _contained_path(path: Path, root: Path, label: str) -> Path:
    if path.is_symlink():
        raise ScoringContractError(f"{label} may not be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ScoringContractError(f"{label} escapes the project data root") from exc
    return resolved


def _zero_violation_section(value: object, label: str) -> Mapping[str, object]:
    section = _mapping(value, label)
    count = section.get("violation_count")
    if not isinstance(count, int) or isinstance(count, bool) or count != 0:
        raise ScoringContractError(f"{label} contains quality violations")
    return section


def _validate_quality_evidence(quality: Mapping[str, object]) -> None:
    """Require the complete independent quality evidence used for acceptance."""

    independent = _mapping(
        quality.get("independent_recomputation"), "independent_recomputation"
    )
    if independent.get("executed") is not True or independent.get("error") is not None:
        raise ScoringContractError("Independent scoring recomputation was not clean")
    configuration = _zero_violation_section(
        independent.get("configuration"), "scoring configuration"
    )
    if configuration.get("executed") is not True or configuration.get(
        "valid"
    ) is not True:
        raise ScoringContractError("Scoring configuration evidence is invalid")
    for field in (
        "metric_transforms",
        "sector_strength",
        "components",
        "input_projection",
        "mode_ranking_eligibility",
        "row_provenance",
    ):
        section = _zero_violation_section(independent.get(field), field)
        if field != "row_provenance" and section.get("executed") is not True:
            raise ScoringContractError(f"{field} recomputation was not executed")

    coverage = _mapping(quality.get("coverage"), "coverage")
    integrity = _zero_violation_section(
        coverage.get("integrity"), "coverage integrity"
    )
    if integrity.get("executed") is not True or integrity.get("valid") is not True:
        raise ScoringContractError("Coverage integrity evidence is invalid")
    _zero_violation_section(quality.get("effective_weights"), "effective weights")
    _zero_violation_section(
        quality.get("aggregate_arithmetic"), "aggregate arithmetic"
    )
    score_ranges = _mapping(quality.get("score_ranges"), "score ranges")
    if score_ranges.get("range_violation_count") != 0:
        raise ScoringContractError("Accepted scoring artifact has range violations")
    numeric_evidence = _zero_violation_section(
        quality.get("numeric_evidence_schema"), "numeric evidence schema"
    )
    if (
        numeric_evidence.get("executed") is not True
        or numeric_evidence.get("valid") is not True
    ):
        raise ScoringContractError("Accepted numeric evidence schema is invalid")

    row_accounting = _mapping(quality.get("row_accounting"), "row_accounting")
    if (
        row_accounting.get("row_accounting_valid") is not True
        or row_accounting.get("primary_key_valid") is not True
        or row_accounting.get("eligibility_mismatch_count") != 0
    ):
        raise ScoringContractError("Accepted scoring row accounting is invalid")
    eligibility = _mapping(quality.get("eligibility"), "eligibility")
    ineligible_scores = _mapping(
        eligibility.get("ineligible_rows_with_scores"),
        "ineligible rows with scores",
    )
    mode_completeness = _mapping(
        eligibility.get("eligible_mode_completeness"),
        "eligible mode completeness",
    )
    if (
        ineligible_scores.get("row_count") != 0
        or mode_completeness.get("eligible_rows_missing_any_mode") != 0
    ):
        raise ScoringContractError("Accepted scoring eligibility evidence is invalid")


def load_accepted_scoring_run(
    project_root: Path,
    run_dir: Optional[Path] = None,
) -> AcceptedScoringRun:
    """Load and independently verify the frozen Phase 3 scoring artifact.

    Downstream phases should use this boundary instead of opening an arbitrary
    ``scored_matrix.parquet`` directly. The function verifies the accepted
    identity, content hashes, configuration provenance, row accounting, and
    mode-score completeness before returning any data.
    """

    project_root = Path(project_root).resolve()
    config_path = project_root / "config"
    if config_path.is_symlink():
        raise ScoringContractError("config may not be a symbolic link")
    config_root = _contained_path(config_path, project_root, "config directory")
    contract_path = _contained_path(
        config_root / "scoring_contract.yaml",
        config_root,
        "scoring contract",
    )
    contract_bytes = _read_bytes(contract_path, "scoring contract")
    contract_document = _load_yaml_bytes(contract_bytes, contract_path)
    header = _mapping(
        contract_document.get("scoring_contract"), "scoring_contract"
    )
    if str(header.get("status")) != FROZEN_STATUS:
        raise ScoringContractError("Scoring contract status must be frozen_v1")
    if not str(header.get("version") or ""):
        raise ScoringContractError("Scoring contract version is required")

    accepted_run_id = str(header.get("accepted_run_id") or "")
    if not accepted_run_id or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in accepted_run_id
    ):
        raise ScoringContractError("Accepted scoring run ID is invalid")
    processed_path = project_root / "data/processed"
    if processed_path.is_symlink():
        raise ScoringContractError("data/processed may not be a symbolic link")
    try:
        processed_root = processed_path.resolve(strict=True)
        processed_root.relative_to(project_root)
    except (OSError, ValueError) as exc:
        raise ScoringContractError("data/processed escapes the project root") from exc

    expected_relative_path = Path("data/processed") / accepted_run_id
    if str(header.get("accepted_run_path") or "") != expected_relative_path.as_posix():
        raise ScoringContractError(
            "accepted_run_path must be data/processed/<accepted_run_id>"
        )
    expected_run_dir = _contained_path(
        project_root / expected_relative_path,
        processed_root,
        "accepted scoring run directory",
    )
    requested_run_dir = project_root / expected_relative_path if run_dir is None else Path(run_dir)
    if requested_run_dir.is_symlink():
        raise ScoringContractError("Scoring run directory may not be a symbolic link")
    resolved_run_dir = requested_run_dir.resolve()
    if resolved_run_dir != expected_run_dir or resolved_run_dir.name != accepted_run_id:
        raise ScoringContractError("Scoring run directory is not the accepted run")

    artifact_paths = {
        "scored_matrix": resolved_run_dir / "scored_matrix.parquet",
        "quality": resolved_run_dir / "scoring_quality.json",
        "metadata": resolved_run_dir / "run_metadata.json",
        "metric_sector_coverage": (
            resolved_run_dir / "metric_sector_coverage.csv"
        ),
    }
    config_paths = {
        "factor_config_sha256": config_root / "factor_model.yaml",
        "modes_config_sha256": config_root / "screening_modes.yaml",
    }
    hash_paths = {
        "accepted_scored_matrix_sha256": artifact_paths["scored_matrix"],
        "accepted_scoring_quality_sha256": artifact_paths["quality"],
        "accepted_run_metadata_sha256": artifact_paths["metadata"],
        "accepted_metric_sector_coverage_sha256": artifact_paths[
            "metric_sector_coverage"
        ],
        **config_paths,
    }
    payloads: Dict[str, bytes] = {}
    for field, path in hash_paths.items():
        allowed_root = (
            expected_run_dir if field.startswith("accepted_") else project_root
        )
        resolved_path = _contained_path(path, allowed_root, field)
        if field.startswith("accepted_") and resolved_path.parent != expected_run_dir:
            raise ScoringContractError(f"{field} escapes the accepted run directory")
        payload = _read_bytes(resolved_path, field)
        expected = _expected_hash(header, field)
        if _sha256_bytes(payload) != expected:
            raise ScoringContractError(f"{field} does not match its frozen artifact")
        payloads[field] = payload

    metadata = _load_json_bytes(
        payloads["accepted_run_metadata_sha256"], artifact_paths["metadata"]
    )
    quality = _load_json_bytes(
        payloads["accepted_scoring_quality_sha256"], artifact_paths["quality"]
    )
    factor_document = _load_yaml_bytes(
        payloads["factor_config_sha256"], config_paths["factor_config_sha256"]
    )
    modes_document = _load_yaml_bytes(
        payloads["modes_config_sha256"], config_paths["modes_config_sha256"]
    )

    input_hash = _expected_hash(header, "input_feature_matrix_sha256")
    input_run_id = str(header.get("input_feature_run_id") or "")
    if not input_run_id or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in input_run_id
    ):
        raise ScoringContractError("Input feature run ID is invalid")
    input_run_dir = _contained_path(
        processed_path / input_run_id,
        processed_root,
        "accepted input feature run directory",
    )
    input_matrix_path = input_run_dir / "feature_matrix.parquet"
    resolved_input_matrix = _contained_path(
        input_matrix_path, input_run_dir, "accepted input feature matrix"
    )
    if resolved_input_matrix.parent != input_run_dir:
        raise ScoringContractError("Input feature matrix escapes its accepted run")
    input_matrix_bytes = _read_bytes(
        resolved_input_matrix, "accepted input feature matrix"
    )
    if _sha256_bytes(input_matrix_bytes) != input_hash:
        raise ScoringContractError(
            "input_feature_matrix_sha256 does not match the Phase 2 artifact"
        )
    try:
        input_matrix = pd.read_parquet(BytesIO(input_matrix_bytes))
    except (OSError, ValueError) as exc:
        raise ScoringContractError(
            "Cannot read accepted Phase 2 feature matrix"
        ) from exc

    data_contract_path = _contained_path(
        config_root / "data_contract.yaml",
        config_root,
        "data contract",
    )
    data_contract = _load_yaml_bytes(
        _read_bytes(data_contract_path, "data contract"), data_contract_path
    )
    data_header = _mapping(data_contract.get("contract"), "data contract")
    phase2_expected = {
        "status": FROZEN_STATUS,
        "version": header.get("input_contract_version"),
        "accepted_run_id": input_run_id,
        "accepted_as_of_date": header.get("accepted_as_of_date"),
        "accepted_feature_matrix_sha256": input_hash,
    }
    for field, expected in phase2_expected.items():
        _require_equal(data_header.get(field), expected, f"data contract {field}")

    if quality.get("run") != metadata:
        raise ScoringContractError("Scoring quality provenance does not match metadata")
    acceptance = _mapping(quality.get("acceptance"), "scoring quality acceptance")
    if acceptance.get("passed") is not True or acceptance.get("hard_failures") != []:
        raise ScoringContractError("Accepted scoring run did not pass all hard gates")
    accepted_warnings = header.get("accepted_warnings")
    if not isinstance(accepted_warnings, list) or acceptance.get(
        "warnings"
    ) != accepted_warnings:
        raise ScoringContractError(
            "Accepted scoring warnings do not match the frozen contract"
        )
    _validate_quality_evidence(quality)

    expected_metadata = {
        "run_id": accepted_run_id,
        "as_of_date": header.get("accepted_as_of_date"),
        "input_feature_run_id": header.get("input_feature_run_id"),
        "input_contract_version": header.get("input_contract_version"),
        "input_contract_status": FROZEN_STATUS,
        "input_feature_matrix_sha256": header.get(
            "input_feature_matrix_sha256"
        ),
        "accepted_contract_run_id": header.get("input_feature_run_id"),
        "factor_model_version": header.get("factor_model_version"),
        "factor_model_status": FROZEN_STATUS,
        "screening_modes_version": header.get("screening_modes_version"),
        "screening_modes_status": FROZEN_STATUS,
        "factor_config_sha256": header.get("factor_config_sha256"),
        "modes_config_sha256": header.get("modes_config_sha256"),
    }
    for field, expected in expected_metadata.items():
        _require_equal(metadata.get(field), expected, f"run metadata {field}")

    _require_equal(
        factor_document.get("version"),
        header.get("factor_model_version"),
        "factor model version",
    )
    _require_equal(factor_document.get("status"), FROZEN_STATUS, "factor model status")
    _require_equal(
        modes_document.get("version"),
        header.get("screening_modes_version"),
        "screening modes version",
    )
    _require_equal(modes_document.get("status"), FROZEN_STATUS, "screening modes status")

    try:
        scored = pd.read_parquet(
            BytesIO(payloads["accepted_scored_matrix_sha256"])
        )
    except (OSError, ValueError) as exc:
        raise ScoringContractError("Cannot read accepted scored matrix") from exc
    required_columns = {"as_of_date", "ticker", "eligible_for_scoring"}
    missing_columns = sorted(required_columns - set(scored.columns))
    if missing_columns:
        raise ScoringContractError(
            "Accepted scored matrix is missing contract columns: "
            + ", ".join(missing_columns)
        )
    if scored[["as_of_date", "ticker"]].isna().any(axis=None):
        raise ScoringContractError("Accepted scored matrix has null primary keys")
    if scored[["as_of_date", "ticker"]].duplicated().any():
        raise ScoringContractError("Accepted scored matrix has duplicate primary keys")
    non_numeric_score_columns = [
        column
        for column in scored
        if column.endswith("_score")
        and (
            pd.api.types.is_bool_dtype(scored[column].dtype)
            or not pd.api.types.is_numeric_dtype(scored[column].dtype)
        )
    ]
    if non_numeric_score_columns:
        raise ScoringContractError(
            "Accepted scored matrix has non-numeric score columns: "
            + ", ".join(non_numeric_score_columns)
        )

    expected_rows = _positive_int(header.get("row_count"), "row_count")
    expected_eligible = _positive_int(header.get("eligible_count"), "eligible_count")
    eligible = _strict_eligible_mask(scored)
    if len(scored) != expected_rows or int(eligible.sum()) != expected_eligible:
        raise ScoringContractError("Accepted scored matrix row accounting is invalid")
    quality_accounting = _mapping(
        quality.get("row_accounting"), "scoring quality row_accounting"
    )
    quality_eligibility = _mapping(
        quality.get("eligibility"), "scoring quality eligibility"
    )
    if (
        quality_accounting.get("input_row_count") != expected_rows
        or quality_accounting.get("scored_row_count") != expected_rows
        or quality_eligibility.get("eligible_count") != expected_eligible
        or quality_eligibility.get("ineligible_count")
        != expected_rows - expected_eligible
    ):
        raise ScoringContractError(
            "Accepted scoring quality row accounting is invalid"
        )
    as_of_values = {str(value) for value in scored["as_of_date"].dropna()}
    if as_of_values != {str(header.get("accepted_as_of_date"))}:
        raise ScoringContractError("Accepted scored matrix as-of date is invalid")

    provenance = {
        "input_feature_run_id": header.get("input_feature_run_id"),
        "input_contract_version": header.get("input_contract_version"),
        "factor_model_version": header.get("factor_model_version"),
        "screening_modes_version": header.get("screening_modes_version"),
    }
    for column, expected in provenance.items():
        if column not in scored or set(scored[column].astype(str)) != {str(expected)}:
            raise ScoringContractError(
                f"Accepted scored matrix provenance column is invalid: {column}"
            )

    mode_names = header.get("mode_names")
    if mode_names != list(EXPECTED_MODE_NAMES):
        raise ScoringContractError("Frozen scoring contract mode_names are invalid")
    ranking_counts = _mapping(
        header.get("mode_ranking_eligible_counts"),
        "mode_ranking_eligible_counts",
    )
    configured_modes = _mapping(
        modes_document.get("screening_modes"), "screening_modes"
    )
    for mode_name in EXPECTED_MODE_NAMES:
        column = f"{mode_name}_score"
        if column not in scored:
            raise ScoringContractError(f"Accepted scored matrix is missing {column}")
        numeric = pd.to_numeric(scored[column], errors="coerce")
        if not np.isfinite(numeric.loc[eligible]).all():
            raise ScoringContractError(f"Eligible rows are missing {column}")
        if numeric.loc[~eligible].notna().any():
            raise ScoringContractError(f"Ineligible rows contain {column}")
        if numeric.loc[eligible].lt(0).any() or numeric.loc[eligible].gt(100).any():
            raise ScoringContractError(f"Accepted {column} is outside 0-100")

        mode_config = _mapping(configured_modes.get(mode_name), mode_name)
        required_factors = mode_config.get("ranking_required_factors")
        if not isinstance(required_factors, list) or any(
            factor not in ("momentum", "quality", "valuation", "risk", "sector_strength")
            for factor in required_factors
        ):
            raise ScoringContractError(
                f"Frozen {mode_name} ranking requirements are invalid"
            )
        expected_ranking = eligible & numeric.notna()
        for factor_name in required_factors:
            factor_column = f"{factor_name}_score"
            if factor_column not in scored:
                raise ScoringContractError(
                    f"Accepted scored matrix is missing {factor_column}"
                )
            factor_numeric = pd.to_numeric(
                scored[factor_column], errors="coerce"
            )
            expected_ranking &= pd.Series(
                np.isfinite(factor_numeric), index=scored.index
            )

        flag_column = f"{mode_name}_eligible_for_ranking"
        reason_column = f"{mode_name}_ranking_exclusion_reasons"
        if flag_column not in scored or reason_column not in scored:
            raise ScoringContractError(
                f"Accepted scored matrix is missing {mode_name} ranking evidence"
            )
        flag_types = scored[flag_column].map(
            lambda value: isinstance(value, (bool, np.bool_))
        )
        if not bool(flag_types.all()):
            raise ScoringContractError(
                f"Accepted {flag_column} contains non-boolean values"
            )
        actual_ranking = scored[flag_column].astype(bool)
        if not actual_ranking.equals(expected_ranking.astype(bool)):
            raise ScoringContractError(
                f"Accepted {mode_name} ranking eligibility is invalid"
            )
        expected_count = _positive_int(
            ranking_counts.get(mode_name),
            f"mode_ranking_eligible_counts.{mode_name}",
        )
        if int(actual_ranking.sum()) != expected_count:
            raise ScoringContractError(
                f"Accepted {mode_name} ranking count is invalid"
            )

        for index in scored.index:
            missing_required = [
                factor_name
                for factor_name in required_factors
                if not np.isfinite(
                    pd.to_numeric(
                        pd.Series(
                            [scored.at[index, f"{factor_name}_score"]]
                        ),
                        errors="coerce",
                    ).iloc[0]
                )
            ]
            expected_reasons = (
                []
                if bool(expected_ranking.at[index])
                else (
                    ["ineligible_for_scoring"]
                    if not bool(eligible.at[index])
                    else [
                        f"missing_required_factor:{factor_name}"
                        for factor_name in missing_required
                    ]
                    or ["mode_score_unavailable"]
                )
            )
            if _reason_list(scored.at[index, reason_column]) != expected_reasons:
                raise ScoringContractError(
                    f"Accepted {mode_name} ranking reasons are invalid"
                )

    try:
        metric_sector_coverage = pd.read_csv(
            BytesIO(
                payloads["accepted_metric_sector_coverage_sha256"]
            )
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ScoringContractError(
            "Cannot read accepted metric-sector coverage"
        ) from exc

    factors = _mapping(factor_document.get("factors"), "factors")
    factor_names = [str(name) for name in factors]
    metric_names: list[str] = []
    for factor_name, factor_value in factors.items():
        factor = _mapping(factor_value, f"factor {factor_name}")
        metrics = factor.get("metrics")
        if metrics is None:
            continue
        metric_names.extend(
            str(name)
            for name in _mapping(
                metrics, f"factor {factor_name} metrics"
            )
        )

    # Re-run the independent quality gate from the frozen input and configs.
    # The persisted JSON is evidence, not an authority: a self-consistent set
    # of edited hashes must still reproduce every transform and input field.
    try:
        from src.scoring_quality import analyze_scored_matrix

        recomputed_quality = analyze_scored_matrix(
            scored,
            input_matrix,
            metadata,
            metric_names,
            factor_names,
            list(EXPECTED_MODE_NAMES),
            metric_sector_coverage,
            factor_document=factor_document,
            modes_document=modes_document,
        ).summary
    except Exception as exc:
        raise ScoringContractError(
            "Cannot independently recompute accepted scoring quality"
        ) from exc
    recorded_quality = dict(quality)
    recorded_quality.pop("artifacts", None)
    if recomputed_quality != recorded_quality:
        differing_sections = sorted(
            set(recomputed_quality) | set(recorded_quality)
        )
        differing_sections = [
            section
            for section in differing_sections
            if recomputed_quality.get(section) != recorded_quality.get(section)
        ]
        raise ScoringContractError(
            "Persisted scoring quality does not match independent recomputation: "
            + ", ".join(differing_sections)
            + "; recomputed hard failures: "
            + repr(
                _mapping(
                    recomputed_quality.get("acceptance"),
                    "recomputed scoring acceptance",
                ).get("hard_failures")
            )
            + "; configuration violations: "
            + repr(
                _mapping(
                    _mapping(
                        recomputed_quality.get("independent_recomputation"),
                        "independent recomputation",
                    ).get("configuration"),
                    "recomputed scoring configuration",
                ).get("violation_reasons")
            )
        )
    recomputed_acceptance = _mapping(
        recomputed_quality.get("acceptance"),
        "recomputed scoring acceptance",
    )
    if (
        recomputed_acceptance.get("passed") is not True
        or recomputed_acceptance.get("hard_failures") != []
    ):
        raise ScoringContractError(
            "Independent scoring recomputation did not pass all hard gates"
        )

    return AcceptedScoringRun(
        scored_matrix=scored,
        metadata=metadata,
        quality=quality,
        contract=contract_document,
        run_dir=resolved_run_dir,
    )
