"""Quality gates and atomic artifacts for Phase 3A scoring runs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from src.matrix_quality import (
    _atomic_write,
    atomic_write_csv,
    atomic_write_json,
    atomic_write_parquet,
)


PRIMARY_KEY = ("as_of_date", "ticker")
WEIGHT_TOLERANCE = 1e-8
TRANSFORM_TOLERANCE = 1e-8
PROVENANCE_FIELDS = (
    "input_feature_run_id",
    "input_contract_version",
    "factor_model_version",
    "screening_modes_version",
)


@dataclass
class ScoringQuality:
    """In-memory quality result and its review-oriented supporting tables."""

    summary: Dict[str, object]
    audit: pd.DataFrame
    metric_sector_coverage: pd.DataFrame
    factor_coverage: pd.DataFrame
    score_distributions: pd.DataFrame


@dataclass(frozen=True)
class ScoringArtifactPaths:
    """Filesystem paths for one persisted scoring run."""

    run_dir: Path
    scored_matrix_parquet: Path
    scoring_audit_csv: Path
    metric_sector_coverage_csv: Path
    factor_coverage_csv: Path
    score_distributions_csv: Path
    scoring_quality_json: Path
    run_metadata_json: Path
    quality_report_md: Path


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict, np.ndarray)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_strict_bool(value: object) -> bool:
    return isinstance(value, (bool, np.bool_))


def _strict_bool(value: object) -> bool:
    return bool(value) if _is_strict_bool(value) else False


def _eligible_mask(frame: pd.DataFrame) -> pd.Series:
    values = frame.get(
        "eligible_for_scoring", pd.Series(False, index=frame.index)
    )
    return values.map(_strict_bool).astype(bool)


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if _is_missing(value):
        return None
    return value


def _unique_names(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _score_columns(
    metric_names: Sequence[str],
    factor_names: Sequence[str],
    mode_names: Sequence[str],
) -> Dict[str, list[str]]:
    return {
        "metric": [f"{name}_score" for name in _unique_names(metric_names)],
        "factor": [f"{name}_score" for name in _unique_names(factor_names)],
        "mode": [f"{name}_score" for name in _unique_names(mode_names)],
    }


def _numeric_evidence_summary(
    scored: pd.DataFrame,
    input_columns: Sequence[str],
    metric_names: Sequence[str],
    factor_names: Sequence[str],
    mode_names: Sequence[str],
) -> Dict[str, object]:
    """Require generated numeric evidence to retain native numeric dtypes."""

    expected_kinds: Dict[str, str] = {}
    input_column_names = {str(column) for column in input_columns}
    for metric in _unique_names(metric_names):
        if metric not in input_column_names:
            expected_kinds[metric] = "numeric"
        for suffix in ("_scoring_input", "_winsorized", "_score"):
            expected_kinds[f"{metric}{suffix}"] = "numeric"
    for factor in _unique_names(factor_names):
        expected_kinds[f"{factor}_score"] = "numeric"
        expected_kinds[f"{factor}_component_count"] = "integer"
    expected_kinds["sector_strength_source_value"] = "numeric"
    expected_kinds["sector_strength_member_count"] = "integer"
    for mode in _unique_names(mode_names):
        expected_kinds[f"{mode}_score"] = "numeric"
        expected_kinds[f"{mode}_factor_count"] = "integer"

    by_column: Dict[str, Dict[str, object]] = {}
    invalid_columns: list[str] = []
    for column, expected_kind in expected_kinds.items():
        null_count = 0
        negative_count = 0
        if column not in scored:
            valid = False
            actual_dtype = None
        else:
            dtype = scored[column].dtype
            actual_dtype = str(dtype)
            is_bool = pd.api.types.is_bool_dtype(dtype)
            valid = bool(
                not is_bool
                and (
                    pd.api.types.is_integer_dtype(dtype)
                    if expected_kind == "integer"
                    else pd.api.types.is_numeric_dtype(dtype)
                )
            )
            if expected_kind == "integer" and valid:
                null_count = int(scored[column].isna().sum())
                negative_count = int(scored[column].lt(0).sum())
                valid = null_count == 0 and negative_count == 0
        if not valid:
            invalid_columns.append(column)
        by_column[column] = {
            "expected_kind": expected_kind,
            "actual_dtype": actual_dtype,
            "null_count": null_count,
            "negative_count": negative_count,
            "valid": valid,
        }
    return {
        "executed": True,
        "valid": not invalid_columns,
        "checked_column_count": len(expected_kinds),
        "invalid_columns": invalid_columns,
        "violation_count": len(invalid_columns),
        "by_column": by_column,
    }


def _key_tokens(frame: pd.DataFrame) -> Optional[pd.Series]:
    if any(column not in frame for column in PRIMARY_KEY):
        return None

    def token(row: pd.Series) -> str:
        values = []
        for column in PRIMARY_KEY:
            value = row[column]
            if isinstance(value, (pd.Timestamp, datetime, date)):
                values.append(value.isoformat())
            else:
                values.append("<missing>" if _is_missing(value) else str(value))
        return "|".join(values)

    return frame.loc[:, list(PRIMARY_KEY)].apply(token, axis=1)


def _primary_key_summary(
    scored: pd.DataFrame, input_matrix: pd.DataFrame
) -> Dict[str, object]:
    scored_keys = _key_tokens(scored)
    input_keys = _key_tokens(input_matrix)
    missing_columns = {
        "scored": [column for column in PRIMARY_KEY if column not in scored],
        "input": [column for column in PRIMARY_KEY if column not in input_matrix],
    }
    scored_nulls = (
        int(scored.loc[:, list(PRIMARY_KEY)].isna().any(axis=1).sum())
        if not missing_columns["scored"]
        else int(len(scored))
    )
    input_nulls = (
        int(input_matrix.loc[:, list(PRIMARY_KEY)].isna().any(axis=1).sum())
        if not missing_columns["input"]
        else int(len(input_matrix))
    )
    scored_duplicates = (
        int(scored_keys.duplicated(keep=False).sum())
        if scored_keys is not None
        else int(len(scored))
    )
    input_duplicates = (
        int(input_keys.duplicated(keep=False).sum())
        if input_keys is not None
        else int(len(input_matrix))
    )

    scored_set = set(scored_keys.tolist()) if scored_keys is not None else set()
    input_set = set(input_keys.tolist()) if input_keys is not None else set()
    missing_input_rows = sorted(input_set - scored_set)
    unexpected_scored_rows = sorted(scored_set - input_set)
    primary_key_valid = not any(
        (
            missing_columns["scored"],
            missing_columns["input"],
            scored_nulls,
            input_nulls,
            scored_duplicates,
            input_duplicates,
        )
    )
    row_accounting_valid = bool(
        len(scored) == len(input_matrix)
        and not missing_input_rows
        and not unexpected_scored_rows
    )
    return {
        "input_row_count": int(len(input_matrix)),
        "scored_row_count": int(len(scored)),
        "missing_primary_key_columns": missing_columns,
        "input_null_primary_key_rows": input_nulls,
        "scored_null_primary_key_rows": scored_nulls,
        "input_duplicate_primary_key_rows": input_duplicates,
        "scored_duplicate_primary_key_rows": scored_duplicates,
        "missing_input_rows": missing_input_rows,
        "unexpected_scored_rows": unexpected_scored_rows,
        "primary_key_valid": primary_key_valid,
        "row_accounting_valid": row_accounting_valid,
    }


def _eligibility_mismatch_count(
    scored: pd.DataFrame, input_matrix: pd.DataFrame
) -> int:
    if (
        "eligible_for_scoring" not in scored
        or "eligible_for_scoring" not in input_matrix
    ):
        return max(len(scored), len(input_matrix))
    scored_keys = _key_tokens(scored)
    input_keys = _key_tokens(input_matrix)
    if scored_keys is None or input_keys is None:
        return max(len(scored), len(input_matrix))
    if scored_keys.duplicated().any() or input_keys.duplicated().any():
        return max(len(scored), len(input_matrix))
    scored_raw = pd.Series(
        scored["eligible_for_scoring"].to_numpy(), index=scored_keys.to_numpy()
    )
    input_raw = pd.Series(
        input_matrix["eligible_for_scoring"].to_numpy(),
        index=input_keys.to_numpy(),
    )
    common = scored_raw.index.intersection(input_raw.index)
    scored_common = scored_raw.loc[common]
    input_common = input_raw.loc[common]
    invalid = ~scored_common.map(_is_strict_bool) | ~input_common.map(
        _is_strict_bool
    )
    different = scored_common.map(_strict_bool) != input_common.map(_strict_bool)
    return int((invalid | different).sum())


def _score_range_summary(
    scored: pd.DataFrame, score_columns: Mapping[str, Sequence[str]]
) -> Dict[str, object]:
    by_column: Dict[str, Dict[str, object]] = {}
    missing_columns: list[str] = []
    total_violations = 0
    for score_type, columns in score_columns.items():
        for column in columns:
            if column not in scored:
                missing_columns.append(column)
                by_column[column] = {
                    "score_type": score_type,
                    "available_count": 0,
                    "range_violation_count": int(len(scored)),
                    "minimum": None,
                    "maximum": None,
                }
                continue
            source = scored[column]
            numeric = pd.to_numeric(source, errors="coerce").astype(float)
            present = ~source.map(_is_missing)
            finite = pd.Series(np.isfinite(numeric), index=scored.index)
            violations = present & (~finite | numeric.lt(0.0) | numeric.gt(100.0))
            finite_values = numeric[finite]
            count = int(violations.sum())
            total_violations += count
            by_column[column] = {
                "score_type": score_type,
                "available_count": int(finite.sum()),
                "range_violation_count": count,
                "minimum": (
                    float(finite_values.min()) if not finite_values.empty else None
                ),
                "maximum": (
                    float(finite_values.max()) if not finite_values.empty else None
                ),
            }
    return {
        "missing_score_columns": missing_columns,
        "range_violation_count": total_violations,
        "by_column": by_column,
    }


def _as_name_list(value: object) -> tuple[list[str], bool]:
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [str(item) for item in value], False
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return [], False
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [], True
        if isinstance(parsed, list):
            return [str(item) for item in parsed], False
        return [], True
    if _is_missing(value):
        return [], False
    return [], True


def _as_weight_mapping(value: object) -> tuple[Dict[str, float], bool]:
    if not isinstance(value, str):
        return {}, True
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError:
        return {}, True
    if not isinstance(parsed, Mapping):
        return {}, True
    result: Dict[str, float] = {}
    invalid = False
    for key, weight in parsed.items():
        if isinstance(weight, (bool, np.bool_)) or not isinstance(
            weight, (int, float, np.number)
        ):
            invalid = True
            continue
        numeric = float(weight)
        if not np.isfinite(numeric) or numeric < 0:
            invalid = True
            continue
        result[str(key)] = numeric
    return result, invalid


def _effective_weight_summary(
    scored: pd.DataFrame,
    names: Sequence[str],
    available_suffix: str,
    weight_suffix: str,
    component_kind: str,
) -> Dict[str, object]:
    by_name: Dict[str, Dict[str, object]] = {}
    missing_columns: list[str] = []
    total_violations = 0

    for aggregate_name in _unique_names(names):
        score_column = f"{aggregate_name}_score"
        available_column = f"{aggregate_name}_{available_suffix}"
        weight_column = f"{aggregate_name}_{weight_suffix}"
        required = [score_column, available_column, weight_column]
        absent = [column for column in required if column not in scored]
        missing_columns.extend(absent)
        reason_counts: Dict[str, int] = {}
        violating_rows = 0

        if absent:
            violating_rows = int(len(scored))
            reason_counts["required_column_missing"] = int(len(scored))
        else:
            score_numeric = pd.to_numeric(
                scored[score_column], errors="coerce"
            ).astype(float)
            score_present = pd.Series(
                np.isfinite(score_numeric), index=scored.index
            )
            for index in scored.index:
                row_reasons: set[str] = set()
                available, available_invalid = _as_name_list(
                    scored.at[index, available_column]
                )
                weights, weights_invalid = _as_weight_mapping(
                    scored.at[index, weight_column]
                )
                if available_invalid:
                    row_reasons.add("available_components_invalid")
                if weights_invalid:
                    row_reasons.add("effective_weights_invalid")

                available_set = set(available)
                positive_keys = {
                    key for key, weight in weights.items() if weight > WEIGHT_TOLERANCE
                }
                if bool(score_present.at[index]):
                    if not available_set:
                        row_reasons.add(f"no_available_{component_kind}")
                    if positive_keys != available_set:
                        row_reasons.add("effective_weight_keys_mismatch")
                    available_weight_sum = sum(
                        weights.get(component, 0.0) for component in available_set
                    )
                    if not np.isclose(
                        available_weight_sum,
                        1.0,
                        atol=WEIGHT_TOLERANCE,
                        rtol=0.0,
                    ):
                        row_reasons.add("effective_weights_do_not_sum_to_one")

                    # Where a component has its own score column, make sure the
                    # availability list is describing a genuinely available score.
                    for component in available_set:
                        component_score = f"{component}_score"
                        if component_score not in scored:
                            continue
                        component_value = pd.to_numeric(
                            pd.Series([scored.at[index, component_score]]),
                            errors="coerce",
                        ).iloc[0]
                        if not np.isfinite(component_value):
                            row_reasons.add("available_component_score_missing")
                elif available_set or positive_keys:
                    row_reasons.add("weights_or_components_present_without_score")

                if row_reasons:
                    violating_rows += 1
                    for reason in row_reasons:
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1

        total_violations += violating_rows
        by_name[aggregate_name] = {
            "checked_row_count": int(len(scored)),
            "violation_count": violating_rows,
            "violation_reason_counts": dict(sorted(reason_counts.items())),
        }

    return {
        "tolerance": WEIGHT_TOLERANCE,
        "missing_columns": sorted(set(missing_columns)),
        "violation_count": total_violations,
        "by_name": by_name,
    }


def _aggregate_arithmetic_summary(
    scored: pd.DataFrame,
    aggregate_names: Sequence[str],
    weight_suffix: str,
    direct_aggregate_names: Sequence[str] = (),
) -> Dict[str, object]:
    """Recompute weighted aggregates so in-range score tampering cannot pass."""

    direct_names = set(_unique_names(direct_aggregate_names))
    by_name: Dict[str, Dict[str, object]] = {}
    total_violations = 0
    for aggregate_name in _unique_names(aggregate_names):
        score_column = f"{aggregate_name}_score"
        weight_column = f"{aggregate_name}_{weight_suffix}"
        if aggregate_name in direct_names:
            by_name[aggregate_name] = {
                "checked_row_count": 0,
                "violation_count": 0,
                "violation_reason_counts": {},
                "direct_aggregate": True,
            }
            continue

        reason_counts: Dict[str, int] = {}
        violating_rows = 0
        checked_rows = 0
        if score_column not in scored or weight_column not in scored:
            violating_rows = int(len(scored))
            reason_counts["required_column_missing"] = int(len(scored))
        else:
            scores = pd.to_numeric(scored[score_column], errors="coerce").astype(
                float
            )
            for index in scored.index:
                aggregate_value = scores.at[index]
                if not np.isfinite(aggregate_value):
                    continue
                checked_rows += 1
                weights, weights_invalid = _as_weight_mapping(
                    scored.at[index, weight_column]
                )
                row_reasons: set[str] = set()
                if weights_invalid or not weights:
                    row_reasons.add("effective_weights_unavailable")
                missing_components = [
                    component
                    for component in weights
                    if f"{component}_score" not in scored
                ]
                if missing_components:
                    row_reasons.add("component_score_column_missing")
                if not row_reasons:
                    component_values = {
                        component: pd.to_numeric(
                            pd.Series([scored.at[index, f"{component}_score"]]),
                            errors="coerce",
                        ).iloc[0]
                        for component in weights
                    }
                    if any(
                        not np.isfinite(value)
                        for value in component_values.values()
                    ):
                        row_reasons.add("component_score_missing")
                    else:
                        expected = sum(
                            component_values[component] * weight
                            for component, weight in weights.items()
                        )
                        if not np.isclose(
                            aggregate_value,
                            expected,
                            atol=WEIGHT_TOLERANCE,
                            rtol=0.0,
                        ):
                            row_reasons.add("aggregate_value_mismatch")
                if row_reasons:
                    violating_rows += 1
                    for reason in row_reasons:
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1

        total_violations += violating_rows
        by_name[aggregate_name] = {
            "checked_row_count": checked_rows,
            "violation_count": violating_rows,
            "violation_reason_counts": dict(sorted(reason_counts.items())),
            "direct_aggregate": False,
        }
    return {
        "tolerance": WEIGHT_TOLERANCE,
        "violation_count": total_violations,
        "by_name": by_name,
    }


def _finite_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    numeric = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return numeric.where(np.isfinite(numeric))


def _configured_metric_values(
    frame: pd.DataFrame,
    metric: str,
    spec: Mapping[str, object],
) -> pd.Series:
    """Independently materialize a direct or exact-period ratio metric."""

    derivation = spec.get("derivation")
    if not isinstance(derivation, Mapping):
        return _finite_numeric(frame, metric)
    numerator = _finite_numeric(frame, str(derivation["numerator"]))
    denominator = _finite_numeric(frame, str(derivation["denominator"]))
    left_column = str(derivation["left_period"])
    right_column = str(derivation["right_period"])
    left_period = pd.to_datetime(
        frame.get(left_column, pd.Series(None, index=frame.index)),
        errors="coerce",
    )
    right_period = pd.to_datetime(
        frame.get(right_column, pd.Series(None, index=frame.index)),
        errors="coerce",
    )
    valid = (
        numerator.notna()
        & denominator.gt(0)
        & left_period.notna()
        & right_period.notna()
        & left_period.eq(right_period)
    )
    values = (numerator / denominator).where(valid)
    return values.where(np.isfinite(values))


def _numeric_values_match(
    actual: object,
    expected: object,
    tolerance: float = TRANSFORM_TOLERANCE,
) -> bool:
    if _is_missing(actual) and _is_missing(expected):
        return True
    try:
        actual_number = float(actual)
        expected_number = float(expected)
    except (TypeError, ValueError):
        return False
    return bool(
        np.isfinite(actual_number)
        and np.isfinite(expected_number)
        and np.isclose(
            actual_number,
            expected_number,
            atol=tolerance,
            rtol=1e-12,
        )
    )


def _reason_matches(actual: object, expected: object) -> bool:
    if _is_missing(actual) and _is_missing(expected):
        return True
    return str(actual) == str(expected)


def _empirical_percentile(
    reference: np.ndarray,
    values: np.ndarray,
    constant_score: float,
) -> np.ndarray:
    """Independently reproduce the configured average-tie endpoint rank."""

    ordered = np.sort(reference.astype(float))
    if len(ordered) < 2:
        return np.full(len(values), np.nan)
    if np.isclose(ordered[0], ordered[-1], rtol=0.0, atol=1e-15):
        return np.full(len(values), constant_score, dtype=float)
    left = np.searchsorted(ordered, values, side="left")
    right = np.searchsorted(ordered, values, side="right")
    average_zero_based_rank = (left + right - 1) / 2.0
    return np.clip(
        average_zero_based_rank / (len(ordered) - 1) * 100.0,
        0.0,
        100.0,
    )


def _aligned_input_rows(
    scored: pd.DataFrame, input_matrix: pd.DataFrame
) -> Optional[pd.DataFrame]:
    """Align immutable input rows to scored primary-key order."""

    scored_reset = scored.reset_index(drop=True)
    input_reset = input_matrix.reset_index(drop=True)
    scored_keys = _key_tokens(scored_reset)
    input_keys = _key_tokens(input_reset)
    if scored_keys is None or input_keys is None:
        return None
    if scored_keys.duplicated().any() or input_keys.duplicated().any():
        return None
    positions = {key: position for position, key in enumerate(input_keys)}
    if any(key not in positions for key in scored_keys):
        return None
    return input_reset.iloc[[positions[key] for key in scored_keys]].reset_index(
        drop=True
    )


def _projection_values_equal(actual: object, expected: object) -> bool:
    """Compare one preserved input value without coercing its semantic type."""

    if _is_missing(actual) and _is_missing(expected):
        return True
    if isinstance(actual, np.generic):
        actual = actual.item()
    if isinstance(expected, np.generic):
        expected = expected.item()
    sequence_types = (list, tuple, np.ndarray)
    if isinstance(actual, sequence_types) or isinstance(expected, sequence_types):
        if not isinstance(actual, sequence_types) or not isinstance(
            expected, sequence_types
        ):
            return False
        actual_values = list(actual)
        expected_values = list(expected)
        return len(actual_values) == len(expected_values) and all(
            _projection_values_equal(left, right)
            for left, right in zip(actual_values, expected_values)
        )
    if isinstance(actual, Mapping) or isinstance(expected, Mapping):
        if not isinstance(actual, Mapping) or not isinstance(expected, Mapping):
            return False
        if list(actual) != list(expected):
            return False
        return all(
            _projection_values_equal(actual[key], expected[key])
            for key in actual
        )
    if isinstance(actual, (pd.Timestamp, datetime, date)) or isinstance(
        expected, (pd.Timestamp, datetime, date)
    ):
        try:
            return pd.Timestamp(actual) == pd.Timestamp(expected)
        except (TypeError, ValueError):
            return False
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    return type(actual) is type(expected) and actual == expected


def _input_projection_summary(
    scored: pd.DataFrame,
    aligned_input: pd.DataFrame,
) -> Dict[str, object]:
    """Require every immutable input column to survive scoring unchanged."""

    missing_columns = sorted(set(aligned_input.columns) - set(scored.columns))
    by_column: Dict[str, int] = {}
    violating_rows: set[int] = set()
    field_mismatch_count = 0
    for column in aligned_input.columns:
        if column not in scored:
            count = int(len(aligned_input))
            by_column[str(column)] = count
            field_mismatch_count += count
            violating_rows.update(range(len(aligned_input)))
            continue
        mismatch_count = 0
        for index in range(len(aligned_input)):
            if not _projection_values_equal(
                scored.at[index, column], aligned_input.at[index, column]
            ):
                mismatch_count += 1
                violating_rows.add(index)
        if mismatch_count:
            by_column[str(column)] = mismatch_count
            field_mismatch_count += mismatch_count
    return {
        "executed": True,
        "checked_row_count": int(len(aligned_input)),
        "checked_column_count": int(len(aligned_input.columns)),
        "missing_columns": missing_columns,
        "violating_row_count": len(violating_rows),
        "field_mismatch_count": field_mismatch_count,
        "violation_count": field_mismatch_count,
        "mismatch_count_by_column": dict(sorted(by_column.items())),
    }


def _configured_model(
    factor_document: Optional[Mapping[str, object]],
    modes_document: Optional[Mapping[str, object]],
    metadata: Mapping[str, object],
    metric_names: Sequence[str],
    factor_names: Sequence[str],
    mode_names: Sequence[str],
) -> tuple[Dict[str, object], Optional[Dict[str, object]]]:
    """Validate configuration shape and build a private recomputation model."""

    if factor_document is None or modes_document is None:
        missing = []
        if factor_document is None:
            missing.append("factor_document")
        if modes_document is None:
            missing.append("modes_document")
        return (
            {
                "executed": False,
                "valid": False,
                "violation_count": len(missing),
                "violation_reasons": [f"missing:{name}" for name in missing],
            },
            None,
        )

    errors: list[str] = []
    model: Dict[str, object] = {}
    try:
        factors = factor_document["factors"]
        preprocessing = factor_document["preprocessing"]
        aggregation = factor_document["factor_aggregation"]
        configured_modes = modes_document["screening_modes"]
        if not all(
            isinstance(value, Mapping)
            for value in (factors, preprocessing, aggregation, configured_modes)
        ):
            raise TypeError("configuration sections must be mappings")

        configured_factor_names = [str(name) for name in factors]
        if configured_factor_names != _unique_names(factor_names):
            errors.append("factor_names_mismatch")
        if [str(name) for name in configured_modes] != _unique_names(mode_names):
            errors.append("mode_names_mismatch")
        if [str(name) for name in modes_document.get("factor_names", [])] != (
            configured_factor_names
        ):
            errors.append("mode_factor_names_mismatch")

        metric_specs: Dict[str, Dict[str, object]] = {}
        factor_metrics: Dict[str, list[str]] = {}
        configured_metric_names: list[str] = []
        for factor_name, factor_value in factors.items():
            factor = str(factor_name)
            if not isinstance(factor_value, Mapping):
                errors.append(f"factor_not_mapping:{factor}")
                continue
            metrics = factor_value.get("metrics")
            if metrics is None:
                continue
            if not isinstance(metrics, Mapping):
                errors.append(f"factor_metrics_not_mapping:{factor}")
                continue
            factor_metrics[factor] = []
            for metric_name, metric_value in metrics.items():
                metric = str(metric_name)
                if metric in metric_specs:
                    errors.append(f"metric_has_multiple_owners:{metric}")
                    continue
                if not isinstance(metric_value, Mapping):
                    errors.append(f"metric_not_mapping:{metric}")
                    continue
                direction = str(metric_value.get("direction") or "")
                if direction not in {"higher", "lower"}:
                    errors.append(f"metric_direction_invalid:{metric}")
                derivation_value = metric_value.get("derivation")
                derivation: Optional[Dict[str, object]] = None
                if derivation_value is not None:
                    if not isinstance(derivation_value, Mapping):
                        errors.append(f"metric_derivation_invalid:{metric}")
                    else:
                        operation = str(
                            derivation_value.get("operation") or ""
                        )
                        numerator = str(
                            derivation_value.get("numerator") or ""
                        )
                        denominator = str(
                            derivation_value.get("denominator") or ""
                        )
                        alignment = derivation_value.get("period_alignment")
                        if operation != "ratio":
                            errors.append(
                                f"metric_derivation_operation_invalid:{metric}"
                            )
                        if (
                            not numerator
                            or not denominator
                            or numerator == denominator
                        ):
                            errors.append(
                                f"metric_derivation_operands_invalid:{metric}"
                            )
                        if (
                            derivation_value.get("denominator_policy")
                            != "positive_only"
                        ):
                            errors.append(
                                f"metric_derivation_denominator_policy_invalid:{metric}"
                            )
                        if not isinstance(alignment, Mapping):
                            errors.append(
                                f"metric_derivation_alignment_invalid:{metric}"
                            )
                            alignment = {}
                        left_period = str(alignment.get("left") or "")
                        right_period = str(alignment.get("right") or "")
                        if (
                            not left_period
                            or not right_period
                            or left_period == right_period
                            or alignment.get("policy") != "exact"
                        ):
                            errors.append(
                                f"metric_derivation_alignment_invalid:{metric}"
                            )
                        derivation = {
                            "operation": operation,
                            "numerator": numerator,
                            "denominator": denominator,
                            "denominator_policy": "positive_only",
                            "left_period": left_period,
                            "right_period": right_period,
                            "period_policy": str(
                                alignment.get("policy") or ""
                            ),
                        }
                inapplicable: list[str] = []
                applicability = metric_value.get("applicability")
                if applicability is not None:
                    if not isinstance(applicability, Mapping) or not isinstance(
                        applicability.get("inapplicable_sectors", []), list
                    ):
                        errors.append(f"metric_applicability_invalid:{metric}")
                    else:
                        inapplicable = [
                            str(value)
                            for value in applicability.get(
                                "inapplicable_sectors", []
                            )
                        ]
                metric_specs[metric] = {
                    "factor": factor,
                    "direction": direction,
                    "inapplicable_sectors": inapplicable,
                    "derivation": derivation,
                }
                factor_metrics[factor].append(metric)
                configured_metric_names.append(metric)

        if configured_metric_names != _unique_names(metric_names):
            errors.append("metric_names_mismatch")

        winsorization = preprocessing["winsorization"]
        percentile = preprocessing["percentile_rank"]
        if not isinstance(winsorization, Mapping) or not isinstance(
            percentile, Mapping
        ):
            raise TypeError("preprocessing subsections must be mappings")
        lower = float(winsorization["lower_percentile"])
        upper = float(winsorization["upper_percentile"])
        minimum = int(percentile["minimum_valid_observations"])
        constant_score = float(percentile["constant_value_score"])
        if not 0 <= lower < upper <= 100:
            errors.append("winsor_percentiles_invalid")
        if winsorization.get("interpolation") != "linear":
            errors.append("winsor_interpolation_not_linear")
        if percentile.get("tie_method") != "average":
            errors.append("percentile_tie_method_not_average")
        if minimum < 2:
            errors.append("minimum_valid_observations_invalid")
        if aggregation.get("metric_weighting") != "equal":
            errors.append("metric_weighting_not_equal")
        minimum_components = int(aggregation["minimum_available_metrics"])
        if minimum_components < 1:
            errors.append("minimum_available_metrics_invalid")

        sector_strength = factors.get("sector_strength")
        if not isinstance(sector_strength, Mapping):
            errors.append("sector_strength_missing")
            sector_strength = {}
        cross_sector = sector_strength.get("cross_sector_ranking", {})
        if not isinstance(cross_sector, Mapping):
            errors.append("sector_strength_ranking_invalid")
            cross_sector = {}
        if sector_strength.get("source_rows") != "eligible_only":
            errors.append("sector_strength_source_rows_invalid")
        if sector_strength.get("sector_aggregation") != "median":
            errors.append("sector_strength_aggregation_invalid")
        if cross_sector.get("method") != "rank_percentile":
            errors.append("sector_strength_rank_method_invalid")
        if cross_sector.get("tie_method") != "average":
            errors.append("sector_strength_tie_method_invalid")
        sector_source_metric = str(sector_strength.get("source_metric") or "")
        sector_minimum = int(sector_strength.get("minimum_sector_members", 0))
        minimum_valid_sectors = int(cross_sector.get("minimum_valid_sectors", 0))
        if not sector_source_metric:
            errors.append("sector_strength_source_metric_missing")
        if sector_minimum < 2 or minimum_valid_sectors < 2:
            errors.append("sector_strength_minimum_invalid")

        mode_weights: Dict[str, Dict[str, float]] = {}
        mode_required_factors: Dict[str, list[str]] = {}
        for mode_name, mode_value in configured_modes.items():
            mode = str(mode_name)
            if not isinstance(mode_value, Mapping) or not isinstance(
                mode_value.get("weights"), Mapping
            ):
                errors.append(f"mode_weights_invalid:{mode}")
                continue
            weights = {
                str(factor): float(weight)
                for factor, weight in mode_value["weights"].items()
            }
            if list(weights) != configured_factor_names:
                errors.append(f"mode_weight_factors_mismatch:{mode}")
            if any(not np.isfinite(value) or value < 0 for value in weights.values()):
                errors.append(f"mode_weight_value_invalid:{mode}")
            if not np.isclose(sum(weights.values()), 1.0, atol=1e-12):
                errors.append(f"mode_weights_do_not_sum_to_one:{mode}")
            mode_weights[mode] = weights
            required_factors = mode_value.get("ranking_required_factors")
            if (
                not isinstance(required_factors, list)
                or any(
                    not isinstance(factor, str)
                    or factor not in configured_factor_names
                    for factor in required_factors
                )
                or len(required_factors) != len(set(required_factors))
            ):
                errors.append(f"mode_ranking_required_factors_invalid:{mode}")
                required_factors = []
            mode_required_factors[mode] = [
                str(factor) for factor in required_factors
            ]

        factor_version = str(factor_document.get("version") or "")
        modes_version = str(modes_document.get("version") or "")
        if str(metadata.get("factor_model_version") or "") != factor_version:
            errors.append("factor_model_metadata_version_mismatch")
        if str(metadata.get("screening_modes_version") or "") != modes_version:
            errors.append("screening_modes_metadata_version_mismatch")

        model = {
            "factor_names": configured_factor_names,
            "metric_specs": metric_specs,
            "factor_metrics": factor_metrics,
            "mode_weights": mode_weights,
            "mode_required_factors": mode_required_factors,
            "lower_quantile": lower / 100.0,
            "upper_quantile": upper / 100.0,
            "minimum_observations": minimum,
            "constant_score": constant_score,
            "minimum_components": minimum_components,
            "sector_source_metric": sector_source_metric,
            "sector_minimum": sector_minimum,
            "minimum_valid_sectors": minimum_valid_sectors,
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        errors.append(f"configuration_parse_error:{type(exc).__name__}")

    summary = {
        "executed": True,
        "valid": not errors,
        "violation_count": len(errors),
        "violation_reasons": sorted(set(errors)),
    }
    return summary, model if not errors else None


def _recompute_expectations(
    input_matrix: pd.DataFrame,
    aligned_input: pd.DataFrame,
    model: Mapping[str, object],
) -> tuple[Dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """Recompute metric transforms, Sector Strength, and coverage from raw input."""

    reference = input_matrix.reset_index(drop=True)
    target = aligned_input.reset_index(drop=True)
    reference_eligible = _eligible_mask(reference)
    target_eligible = _eligible_mask(target)
    reference_sectors = reference["sector"].astype("string")
    target_sectors = target["sector"].astype("string")
    sectors = sorted(
        {
            str(value)
            for value in pd.concat([reference_sectors, target_sectors]).dropna()
        }
    )
    minimum = int(model["minimum_observations"])
    metric_expectations: Dict[str, pd.DataFrame] = {}
    coverage_records: list[Dict[str, object]] = []

    for metric, raw_spec in model["metric_specs"].items():
        spec = dict(raw_spec)
        inapplicable_sectors = set(spec["inapplicable_sectors"])
        reference_values = _configured_metric_values(
            reference, metric, spec
        )
        target_values = _configured_metric_values(target, metric, spec)
        target_inapplicable = target_sectors.isin(inapplicable_sectors)
        expected = pd.DataFrame(index=target.index)
        expected["raw_feature"] = target_values
        expected["scoring_input"] = target_values
        expected["winsorized"] = np.nan
        expected["score"] = np.nan
        expected["available"] = False
        expected["reason"] = pd.Series(None, index=target.index, dtype=object)
        expected.loc[~target_eligible, "reason"] = "ineligible_for_scoring"
        expected.loc[
            target_eligible & target_inapplicable, "reason"
        ] = "inapplicable_sector"
        expected.loc[
            target_eligible & ~target_inapplicable & target_values.isna(),
            "reason",
        ] = "missing_value"

        for sector in sectors:
            sector_inapplicable = sector in inapplicable_sectors
            reference_mask = (
                reference_eligible
                & reference_sectors.eq(sector)
                & reference_values.notna()
                & ~reference_sectors.isin(inapplicable_sectors)
            )
            sector_reference = reference_values.loc[reference_mask]
            valid_count = int(len(sector_reference))
            target_mask = (
                target_eligible
                & target_sectors.eq(sector)
                & ~target_inapplicable
                & target_values.notna()
            )
            sufficient = bool(
                not sector_inapplicable and valid_count >= minimum
            )
            record: Dict[str, object] = {
                "factor": spec["factor"],
                "metric": metric,
                "sector": sector,
                "valid_reference_count": valid_count,
                "minimum_required": minimum,
                "sufficient_observations": sufficient,
                "inapplicable_sector": sector_inapplicable,
                "lower_cutoff": None,
                "upper_cutoff": None,
                "scored_target_count": 0,
                "sector_source_value": None,
            }
            if sector_inapplicable:
                coverage_records.append(record)
                continue
            if not sufficient:
                expected.loc[target_mask, "reason"] = (
                    f"insufficient_sector_observations:{valid_count}"
                )
                coverage_records.append(record)
                continue

            lower_cutoff = float(
                sector_reference.quantile(
                    float(model["lower_quantile"]), interpolation="linear"
                )
            )
            upper_cutoff = float(
                sector_reference.quantile(
                    float(model["upper_quantile"]), interpolation="linear"
                )
            )
            winsorized_reference = sector_reference.clip(
                lower=lower_cutoff, upper=upper_cutoff
            ).to_numpy(dtype=float)
            target_winsorized = target_values.loc[target_mask].clip(
                lower=lower_cutoff, upper=upper_cutoff
            )
            scores = _empirical_percentile(
                winsorized_reference,
                target_winsorized.to_numpy(dtype=float),
                float(model["constant_score"]),
            )
            if spec["direction"] == "lower":
                scores = 100.0 - scores
            expected.loc[target_mask, "winsorized"] = target_winsorized
            expected.loc[target_mask, "score"] = scores
            expected.loc[target_mask, "available"] = True
            expected.loc[target_mask, "reason"] = None
            record["lower_cutoff"] = lower_cutoff
            record["upper_cutoff"] = upper_cutoff
            record["scored_target_count"] = int(target_mask.sum())
            coverage_records.append(record)
        metric_expectations[metric] = expected

    source_metric = str(model["sector_source_metric"])
    source_values = _finite_numeric(reference, source_metric)
    counts: Dict[str, int] = {}
    medians: Dict[str, float] = {}
    for sector, group in reference.loc[reference_eligible].groupby(
        "sector", dropna=False, sort=True
    ):
        sector_name = str(sector)
        values = source_values.loc[group.index].dropna()
        counts[sector_name] = int(len(values))
        if len(values) >= int(model["sector_minimum"]):
            medians[sector_name] = float(values.median())

    sector_scores: Dict[str, float] = {}
    if len(medians) >= int(model["minimum_valid_sectors"]):
        names = list(medians)
        values = np.array([medians[name] for name in names], dtype=float)
        scores = _empirical_percentile(
            values, values, float(model["constant_score"])
        )
        sector_scores = dict(zip(names, scores))

    target_sector_strings = target["sector"].astype(str)
    sector_expected = pd.DataFrame(index=target.index)
    sector_expected["source_value"] = target_sector_strings.map(medians)
    sector_expected["member_count"] = target_sector_strings.map(counts)
    sector_expected["score"] = target_sector_strings.map(sector_scores).where(
        target_eligible
    )
    sector_expected["reason"] = None
    sector_expected.loc[~target_eligible, "reason"] = "ineligible_for_scoring"
    missing_reason = (
        "insufficient_valid_sectors"
        if len(medians) < int(model["minimum_valid_sectors"])
        else "insufficient_sector_observations"
    )
    sector_expected.loc[
        target_eligible & sector_expected["score"].isna(), "reason"
    ] = missing_reason

    label = f"sector_median:{source_metric}"
    for sector in sorted(counts):
        has_score = sector in sector_scores
        coverage_records.append(
            {
                "factor": "sector_strength",
                "metric": label,
                "sector": sector,
                "valid_reference_count": counts[sector],
                "minimum_required": int(model["sector_minimum"]),
                "sufficient_observations": has_score,
                "inapplicable_sector": False,
                "lower_cutoff": None,
                "upper_cutoff": None,
                "scored_target_count": (
                    int(
                        (
                            target_eligible
                            & target_sector_strings.eq(sector)
                        ).sum()
                    )
                    if has_score
                    else 0
                ),
                "sector_source_value": medians.get(sector),
            }
        )

    expected_coverage = pd.DataFrame(coverage_records)
    return metric_expectations, sector_expected, expected_coverage


def _metric_transform_summary(
    scored: pd.DataFrame,
    expectations: Mapping[str, pd.DataFrame],
) -> Dict[str, object]:
    by_metric: Dict[str, Dict[str, object]] = {}
    total_violations = 0
    for metric, expected in expectations.items():
        columns = {
            "raw_feature": metric,
            "scoring_input": f"{metric}_scoring_input",
            "winsorized": f"{metric}_winsorized",
            "score": f"{metric}_score",
            "available": f"{metric}_available",
            "reason": f"{metric}_unavailable_reason",
        }
        missing_columns = [column for column in columns.values() if column not in scored]
        reason_counts: Dict[str, int] = {}
        violating_rows: set[int] = set()
        for missing in missing_columns:
            reason_counts[f"required_column_missing:{missing}"] = int(len(scored))
            violating_rows.update(range(len(scored)))
        if not missing_columns:
            for index in range(len(scored)):
                row_reasons: set[str] = set()
                for label in ("raw_feature", "scoring_input", "winsorized", "score"):
                    if not _numeric_values_match(
                        scored.at[index, columns[label]], expected.at[index, label]
                    ):
                        row_reasons.add(f"{label}_mismatch")
                actual_available = scored.at[index, columns["available"]]
                if not _is_strict_bool(actual_available) or bool(
                    actual_available
                ) != bool(expected.at[index, "available"]):
                    row_reasons.add("availability_mismatch")
                if not _reason_matches(
                    scored.at[index, columns["reason"]],
                    expected.at[index, "reason"],
                ):
                    row_reasons.add("unavailable_reason_mismatch")
                if row_reasons:
                    violating_rows.add(index)
                    for reason in row_reasons:
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        violation_count = len(violating_rows)
        total_violations += violation_count
        by_metric[metric] = {
            "checked_row_count": int(len(scored)),
            "violation_count": violation_count,
            "violation_reason_counts": dict(sorted(reason_counts.items())),
        }
    return {
        "tolerance": TRANSFORM_TOLERANCE,
        "violation_count": total_violations,
        "by_metric": by_metric,
    }


def _sector_strength_summary(
    scored: pd.DataFrame, expected: pd.DataFrame
) -> Dict[str, object]:
    columns = {
        "source_value": "sector_strength_source_value",
        "member_count": "sector_strength_member_count",
        "score": "sector_strength_score",
        "reason": "sector_strength_unavailable_reason",
    }
    missing_columns = [column for column in columns.values() if column not in scored]
    reason_counts: Dict[str, int] = {}
    violating_rows: set[int] = set()
    for missing in missing_columns:
        reason_counts[f"required_column_missing:{missing}"] = int(len(scored))
        violating_rows.update(range(len(scored)))
    if not missing_columns:
        for index in range(len(scored)):
            row_reasons: set[str] = set()
            for label in ("source_value", "member_count", "score"):
                if not _numeric_values_match(
                    scored.at[index, columns[label]], expected.at[index, label]
                ):
                    row_reasons.add(f"{label}_mismatch")
            if not _reason_matches(
                scored.at[index, columns["reason"]], expected.at[index, "reason"]
            ):
                row_reasons.add("unavailable_reason_mismatch")
            if row_reasons:
                violating_rows.add(index)
                for reason in row_reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "tolerance": TRANSFORM_TOLERANCE,
        "checked_row_count": int(len(scored)),
        "violation_count": len(violating_rows),
        "violation_reason_counts": dict(sorted(reason_counts.items())),
    }


def _strict_coverage_summary(
    actual: pd.DataFrame, expected: pd.DataFrame
) -> Dict[str, object]:
    key_columns = ["factor", "metric", "sector"]
    value_columns = [
        "valid_reference_count",
        "minimum_required",
        "sufficient_observations",
        "inapplicable_sector",
        "lower_cutoff",
        "upper_cutoff",
        "scored_target_count",
        "sector_source_value",
    ]
    required_columns = key_columns + value_columns
    missing_columns = [column for column in required_columns if column not in actual]
    reason_counts: Dict[str, int] = {}
    if missing_columns:
        reason_counts["required_columns_missing"] = len(missing_columns)
    if actual.empty:
        reason_counts["coverage_empty"] = 1
    actual_normalized = actual.copy().reset_index(drop=True)
    expected_normalized = expected.copy().reset_index(drop=True)
    if not missing_columns and not actual.empty:
        for column in key_columns:
            actual_normalized[column] = actual_normalized[column].astype(str)
            expected_normalized[column] = expected_normalized[column].astype(str)
        duplicate_count = int(
            actual_normalized.duplicated(key_columns, keep=False).sum()
        )
        if duplicate_count:
            reason_counts["duplicate_coverage_rows"] = duplicate_count
        actual_keys = {
            tuple(row)
            for row in actual_normalized[key_columns].itertuples(
                index=False, name=None
            )
        }
        expected_keys = {
            tuple(row)
            for row in expected_normalized[key_columns].itertuples(
                index=False, name=None
            )
        }
        missing_keys = expected_keys - actual_keys
        unexpected_keys = actual_keys - expected_keys
        if missing_keys:
            reason_counts["expected_coverage_rows_missing"] = len(missing_keys)
        if unexpected_keys:
            reason_counts["unexpected_coverage_rows"] = len(unexpected_keys)

        if not duplicate_count:
            actual_by_key = actual_normalized.set_index(key_columns)
            expected_by_key = expected_normalized.set_index(key_columns)
            for key in sorted(actual_keys & expected_keys):
                actual_row = actual_by_key.loc[key]
                expected_row = expected_by_key.loc[key]
                row_mismatch = False
                for column in (
                    "valid_reference_count",
                    "minimum_required",
                    "scored_target_count",
                ):
                    if not _numeric_values_match(
                        actual_row[column], expected_row[column], tolerance=0.0
                    ):
                        reason_counts[f"{column}_mismatch"] = (
                            reason_counts.get(f"{column}_mismatch", 0) + 1
                        )
                        row_mismatch = True
                for column in (
                    "sufficient_observations",
                    "inapplicable_sector",
                ):
                    if not _is_strict_bool(actual_row[column]) or bool(
                        actual_row[column]
                    ) != bool(expected_row[column]):
                        reason_counts[f"{column}_mismatch"] = (
                            reason_counts.get(f"{column}_mismatch", 0) + 1
                        )
                        row_mismatch = True
                for column in (
                    "lower_cutoff",
                    "upper_cutoff",
                    "sector_source_value",
                ):
                    if not _numeric_values_match(
                        actual_row[column], expected_row[column]
                    ):
                        reason_counts[f"{column}_mismatch"] = (
                            reason_counts.get(f"{column}_mismatch", 0) + 1
                        )
                        row_mismatch = True
                if row_mismatch:
                    reason_counts["coverage_rows_with_value_mismatch"] = (
                        reason_counts.get("coverage_rows_with_value_mismatch", 0)
                        + 1
                    )
    return {
        "valid": not reason_counts,
        "violation_count": int(sum(reason_counts.values())),
        "violation_reason_counts": dict(sorted(reason_counts.items())),
        "expected_row_count": int(len(expected)),
        "actual_row_count": int(len(actual)),
        "required_columns_missing": missing_columns,
    }


def _weight_mappings_match(
    actual: object, expected: Mapping[str, float]
) -> bool:
    weights, invalid = _as_weight_mapping(actual)
    if invalid or set(weights) != set(expected):
        return False
    return all(
        np.isclose(
            weights[name], expected[name], atol=WEIGHT_TOLERANCE, rtol=0.0
        )
        for name in expected
    )


def _component_contract_summary(
    scored: pd.DataFrame,
    model: Mapping[str, object],
) -> Dict[str, object]:
    eligible = _eligible_mask(scored)
    by_aggregate: Dict[str, Dict[str, object]] = {}
    total_violations = 0

    def validate_aggregate(
        name: str,
        expected_components_by_row: list[list[str]],
        expected_weights_by_row: list[Dict[str, float]],
        expected_scores: pd.Series,
        expected_reasons: list[Optional[str]],
        count_suffix: str,
        list_suffix: str,
        weight_suffix: str,
    ) -> None:
        nonlocal total_violations
        columns = {
            "score": f"{name}_score",
            "count": f"{name}_{count_suffix}",
            "components": f"{name}_{list_suffix}",
            "weights": f"{name}_{weight_suffix}",
            "reason": f"{name}_unavailable_reason",
        }
        missing = [column for column in columns.values() if column not in scored]
        reasons: Dict[str, int] = {}
        violating_rows: set[int] = set()
        for column in missing:
            reasons[f"required_column_missing:{column}"] = int(len(scored))
            violating_rows.update(range(len(scored)))
        if not missing:
            for index in range(len(scored)):
                row_reasons: set[str] = set()
                expected_components = expected_components_by_row[index]
                actual_components, list_invalid = _as_name_list(
                    scored.at[index, columns["components"]]
                )
                if list_invalid or actual_components != expected_components:
                    row_reasons.add("available_components_mismatch")
                if not _numeric_values_match(
                    scored.at[index, columns["count"]],
                    len(expected_components),
                    tolerance=0.0,
                ):
                    row_reasons.add("component_count_mismatch")
                if not _weight_mappings_match(
                    scored.at[index, columns["weights"]],
                    expected_weights_by_row[index],
                ):
                    row_reasons.add("effective_weights_mismatch")
                if not _numeric_values_match(
                    scored.at[index, columns["score"]], expected_scores.at[index]
                ):
                    row_reasons.add("aggregate_score_mismatch")
                if not _reason_matches(
                    scored.at[index, columns["reason"]],
                    expected_reasons[index],
                ):
                    row_reasons.add("unavailable_reason_mismatch")
                if row_reasons:
                    violating_rows.add(index)
                    for reason in row_reasons:
                        reasons[reason] = reasons.get(reason, 0) + 1
        count = len(violating_rows)
        total_violations += count
        by_aggregate[name] = {
            "checked_row_count": int(len(scored)),
            "violation_count": count,
            "violation_reason_counts": dict(sorted(reasons.items())),
        }

    minimum_components = int(model["minimum_components"])
    for factor in model["factor_names"]:
        if factor == "sector_strength":
            label = f"sector_median:{model['sector_source_metric']}"
            factor_scores = _finite_numeric(scored, "sector_strength_score")
            components = [
                [label] if np.isfinite(factor_scores.at[index]) else []
                for index in range(len(scored))
            ]
            weights = [
                {label: 1.0} if row_components else {}
                for row_components in components
            ]
            expected_scores = factor_scores
        else:
            metric_names = model["factor_metrics"].get(factor, [])
            metric_scores = pd.DataFrame(
                {
                    metric: _finite_numeric(scored, f"{metric}_score")
                    for metric in metric_names
                }
            )
            components = [
                [
                    metric
                    for metric in metric_names
                    if np.isfinite(metric_scores.at[index, metric])
                ]
                if bool(eligible.at[index])
                else []
                for index in range(len(scored))
            ]
            weights = [
                {
                    metric: 1.0 / len(row_components)
                    for metric in row_components
                }
                if len(row_components) >= minimum_components
                else {}
                for row_components in components
            ]
            expected_scores = pd.Series(np.nan, index=scored.index, dtype=float)
            for index, row_components in enumerate(components):
                if len(row_components) >= minimum_components:
                    expected_scores.at[index] = float(
                        metric_scores.loc[index, row_components].mean()
                    )
        reasons = [
            "ineligible_for_scoring"
            if not bool(eligible.at[index])
            else (
                "no_available_components"
                if len(components[index]) < minimum_components
                else None
            )
            for index in range(len(scored))
        ]
        if factor == "sector_strength":
            source_values = _finite_numeric(
                scored, "sector_strength_source_value"
            )
            valid_sector_count = int(
                scored.loc[eligible & source_values.notna(), "sector"].nunique()
            )
            missing_reason = (
                "insufficient_valid_sectors"
                if valid_sector_count < int(model["minimum_valid_sectors"])
                else "insufficient_sector_observations"
            )
            reasons = [
                "ineligible_for_scoring"
                if not bool(eligible.at[index])
                else (
                    None
                    if np.isfinite(expected_scores.at[index])
                    else missing_reason
                )
                for index in range(len(scored))
            ]
        validate_aggregate(
            factor,
            components,
            weights,
            expected_scores,
            reasons,
            "component_count",
            "available_components",
            "effective_metric_weights",
        )

    for mode, base_weights in model["mode_weights"].items():
        factor_scores = {
            factor: _finite_numeric(scored, f"{factor}_score")
            for factor in model["factor_names"]
        }
        components = [
            [
                factor
                for factor in model["factor_names"]
                if np.isfinite(factor_scores[factor].at[index])
            ]
            if bool(eligible.at[index])
            else []
            for index in range(len(scored))
        ]
        weights: list[Dict[str, float]] = []
        expected_scores = pd.Series(np.nan, index=scored.index, dtype=float)
        for index, row_components in enumerate(components):
            denominator = sum(base_weights[factor] for factor in row_components)
            effective = (
                {
                    factor: base_weights[factor] / denominator
                    for factor in row_components
                }
                if denominator > 0
                else {}
            )
            weights.append(effective)
            if effective:
                expected_scores.at[index] = sum(
                    factor_scores[factor].at[index] * weight
                    for factor, weight in effective.items()
                )
        reasons = [
            "ineligible_for_scoring"
            if not bool(eligible.at[index])
            else ("no_available_factors" if not components[index] else None)
            for index in range(len(scored))
        ]
        validate_aggregate(
            mode,
            components,
            weights,
            expected_scores,
            reasons,
            "factor_count",
            "available_factors",
            "effective_factor_weights",
        )

    return {
        "tolerance": WEIGHT_TOLERANCE,
        "violation_count": total_violations,
        "by_aggregate": by_aggregate,
    }


def _row_provenance_summary(
    scored: pd.DataFrame, metadata: Mapping[str, object]
) -> Dict[str, object]:
    reason_counts: Dict[str, int] = {}
    by_field: Dict[str, Dict[str, object]] = {}
    total_violations = 0
    for field in PROVENANCE_FIELDS:
        expected = metadata.get(field)
        if expected is None:
            count = int(len(scored))
            by_field[field] = {
                "expected_value": None,
                "violation_count": count,
                "reason": "metadata_value_missing",
            }
            reason_counts["metadata_value_missing"] = (
                reason_counts.get("metadata_value_missing", 0) + count
            )
            total_violations += count
            continue
        if field not in scored:
            count = int(len(scored))
            by_field[field] = {
                "expected_value": str(expected),
                "violation_count": count,
                "reason": "row_column_missing",
            }
            reason_counts["row_column_missing"] = (
                reason_counts.get("row_column_missing", 0) + count
            )
            total_violations += count
            continue
        mismatch = scored[field].map(
            lambda value: _is_missing(value) or str(value) != str(expected)
        )
        count = int(mismatch.sum())
        by_field[field] = {
            "expected_value": str(expected),
            "violation_count": count,
            "reason": "row_value_mismatch" if count else None,
        }
        if count:
            reason_counts["row_value_mismatch"] = (
                reason_counts.get("row_value_mismatch", 0) + count
            )
        total_violations += count
    return {
        "violation_count": total_violations,
        "violation_reason_counts": dict(sorted(reason_counts.items())),
        "by_field": by_field,
    }


def _mode_ranking_eligibility_summary(
    scored: pd.DataFrame, model: Mapping[str, object]
) -> Dict[str, object]:
    """Recompute ranking eligibility without altering diagnostic mode scores."""

    eligible = _eligible_mask(scored)
    by_mode: Dict[str, Dict[str, object]] = {}
    total_violations = 0
    for mode, required_factors in model["mode_required_factors"].items():
        eligibility_column = f"{mode}_eligible_for_ranking"
        reasons_column = f"{mode}_ranking_exclusion_reasons"
        score = _finite_numeric(scored, f"{mode}_score")
        expected_eligible = eligible & score.notna()
        factor_scores = {
            factor: _finite_numeric(scored, f"{factor}_score")
            for factor in required_factors
        }
        for factor in required_factors:
            expected_eligible &= factor_scores[factor].notna()

        expected_reasons: list[list[str]] = []
        for index in range(len(scored)):
            if bool(expected_eligible.at[index]):
                expected_reasons.append([])
            elif not bool(eligible.at[index]):
                expected_reasons.append(["ineligible_for_scoring"])
            else:
                missing_required = [
                    f"missing_required_factor:{factor}"
                    for factor in required_factors
                    if not np.isfinite(factor_scores[factor].at[index])
                ]
                expected_reasons.append(
                    missing_required or ["mode_score_unavailable"]
                )

        reason_counts: Dict[str, int] = {}
        violating_rows: set[int] = set()
        missing_columns = [
            column
            for column in (eligibility_column, reasons_column)
            if column not in scored
        ]
        for column in missing_columns:
            reason_counts[f"required_column_missing:{column}"] = int(len(scored))
            violating_rows.update(range(len(scored)))
        if not missing_columns:
            for index in range(len(scored)):
                row_reasons: set[str] = set()
                actual_eligibility = scored.at[index, eligibility_column]
                if not _is_strict_bool(actual_eligibility) or bool(
                    actual_eligibility
                ) != bool(expected_eligible.at[index]):
                    row_reasons.add("ranking_eligibility_mismatch")
                actual_reasons, invalid = _as_name_list(
                    scored.at[index, reasons_column]
                )
                if invalid or actual_reasons != expected_reasons[index]:
                    row_reasons.add("ranking_exclusion_reasons_mismatch")
                if row_reasons:
                    violating_rows.add(index)
                    for reason in row_reasons:
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        count = len(violating_rows)
        total_violations += count
        by_mode[mode] = {
            "checked_row_count": int(len(scored)),
            "ranking_eligible_count": int(expected_eligible.sum()),
            "ranking_excluded_count": int((~expected_eligible).sum()),
            "required_factors": list(required_factors),
            "violation_count": count,
            "violation_reason_counts": dict(sorted(reason_counts.items())),
        }
    return {
        "violation_count": total_violations,
        "by_mode": by_mode,
    }


def _coverage_integrity_summary(
    coverage: pd.DataFrame,
    scored: pd.DataFrame,
    metric_names: Sequence[str],
    factor_names: Sequence[str],
) -> Dict[str, object]:
    """Require one coverage row per configured metric and sector."""

    required_columns = {
        "factor",
        "metric",
        "sector",
        "valid_reference_count",
        "minimum_required",
        "sufficient_observations",
        "inapplicable_sector",
        "scored_target_count",
    }
    missing_columns = sorted(required_columns - set(coverage.columns))
    sectors = sorted(
        {
            str(value)
            for value in scored.get("sector", pd.Series(dtype=object)).dropna()
        }
    )
    expected_metrics = set(_unique_names(metric_names))
    violation_reasons: Dict[str, int] = {}
    if coverage.empty:
        violation_reasons["coverage_empty"] = 1
    if missing_columns:
        violation_reasons["required_columns_missing"] = len(missing_columns)
    if not sectors:
        violation_reasons["scored_sectors_missing"] = 1

    duplicate_rows = 0
    missing_regular_pairs: list[str] = []
    unexpected_regular_pairs: list[str] = []
    missing_sector_strength_sectors: list[str] = []
    unexpected_sector_strength_sectors: list[str] = []
    sector_strength_metric_count = 0
    if not missing_columns and not coverage.empty and sectors:
        normalized = coverage.copy()
        for column in ("factor", "metric", "sector"):
            normalized[column] = normalized[column].astype(str)
        duplicate_rows = int(
            normalized.duplicated(["factor", "metric", "sector"], keep=False).sum()
        )
        if duplicate_rows:
            violation_reasons["duplicate_coverage_rows"] = duplicate_rows

        regular = normalized[normalized["factor"] != "sector_strength"]
        actual_regular = {
            (row.metric, row.sector)
            for row in regular[["metric", "sector"]].itertuples(index=False)
        }
        expected_regular = {
            (metric, sector) for metric in expected_metrics for sector in sectors
        }
        missing_regular_pairs = sorted(
            f"{metric}|{sector}"
            for metric, sector in expected_regular - actual_regular
        )
        unexpected_regular_pairs = sorted(
            f"{metric}|{sector}"
            for metric, sector in actual_regular - expected_regular
        )
        if missing_regular_pairs:
            violation_reasons["metric_sector_pairs_missing"] = len(
                missing_regular_pairs
            )
        if unexpected_regular_pairs:
            violation_reasons["unexpected_metric_sector_pairs"] = len(
                unexpected_regular_pairs
            )

        if "sector_strength" in set(_unique_names(factor_names)):
            sector_rows = normalized[normalized["factor"] == "sector_strength"]
            sector_strength_metric_count = int(sector_rows["metric"].nunique())
            actual_sector_strength = set(sector_rows["sector"])
            missing_sector_strength_sectors = sorted(
                set(sectors) - actual_sector_strength
            )
            unexpected_sector_strength_sectors = sorted(
                actual_sector_strength - set(sectors)
            )
            if sector_strength_metric_count != 1:
                violation_reasons["sector_strength_metric_count_invalid"] = abs(
                    sector_strength_metric_count - 1
                ) or 1
            if missing_sector_strength_sectors:
                violation_reasons["sector_strength_sectors_missing"] = len(
                    missing_sector_strength_sectors
                )
            if unexpected_sector_strength_sectors:
                violation_reasons["unexpected_sector_strength_sectors"] = len(
                    unexpected_sector_strength_sectors
                )

    return {
        "valid": not violation_reasons,
        "violation_count": int(sum(violation_reasons.values())),
        "violation_reason_counts": dict(sorted(violation_reasons.items())),
        "required_columns_missing": missing_columns,
        "expected_sector_count": len(sectors),
        "expected_regular_metric_count": len(expected_metrics),
        "duplicate_row_count": duplicate_rows,
        "missing_regular_pairs": missing_regular_pairs,
        "unexpected_regular_pairs": unexpected_regular_pairs,
        "sector_strength_metric_count": sector_strength_metric_count,
        "missing_sector_strength_sectors": missing_sector_strength_sectors,
        "unexpected_sector_strength_sectors": unexpected_sector_strength_sectors,
    }


def _ineligible_score_summary(
    scored: pd.DataFrame, columns: Sequence[str]
) -> Dict[str, object]:
    eligible = _eligible_mask(scored)
    by_column: Dict[str, int] = {}
    offending_rows = pd.Series(False, index=scored.index)
    for column in columns:
        if column not in scored:
            continue
        present = ~scored[column].map(_is_missing)
        offending = ~eligible & present
        if offending.any():
            by_column[column] = int(offending.sum())
            offending_rows |= offending
    return {
        "row_count": int(offending_rows.sum()),
        "by_column": by_column,
    }


def _eligible_mode_summary(
    scored: pd.DataFrame, mode_names: Sequence[str]
) -> Dict[str, object]:
    eligible = _eligible_mask(scored)
    missing_by_mode: Dict[str, int] = {}
    missing_rows = pd.Series(False, index=scored.index)
    for mode_name in _unique_names(mode_names):
        column = f"{mode_name}_score"
        if column not in scored:
            missing = eligible.copy()
        else:
            numeric = pd.to_numeric(scored[column], errors="coerce").astype(float)
            missing = eligible & ~pd.Series(
                np.isfinite(numeric), index=scored.index
            )
        missing_by_mode[mode_name] = int(missing.sum())
        missing_rows |= missing
    return {
        "eligible_row_count": int(eligible.sum()),
        "eligible_rows_missing_any_mode": int(missing_rows.sum()),
        "missing_by_mode": missing_by_mode,
    }


def _factor_coverage(
    scored: pd.DataFrame,
    factor_names: Sequence[str],
    weight_summary: Mapping[str, object],
) -> pd.DataFrame:
    eligible = _eligible_mask(scored)
    eligible_count = int(eligible.sum())
    records = []
    by_name = weight_summary.get("by_name", {})
    for factor_name in _unique_names(factor_names):
        score_column = f"{factor_name}_score"
        count_column = f"{factor_name}_component_count"
        reason_column = f"{factor_name}_unavailable_reason"
        if score_column in scored:
            numeric = pd.to_numeric(scored[score_column], errors="coerce").astype(float)
            available = eligible & pd.Series(
                np.isfinite(numeric), index=scored.index
            )
        else:
            available = pd.Series(False, index=scored.index)
        component_counts = pd.to_numeric(
            scored.get(count_column, pd.Series(np.nan, index=scored.index)),
            errors="coerce",
        )[eligible].dropna()
        reasons: Dict[str, int] = {}
        if reason_column in scored:
            for value in scored.loc[eligible & ~available, reason_column]:
                reason = "<missing>" if _is_missing(value) else str(value)
                reasons[reason] = reasons.get(reason, 0) + 1
        available_count = int(available.sum())
        records.append(
            {
                "factor": factor_name,
                "eligible_row_count": eligible_count,
                "score_available_count": available_count,
                "score_missing_count": eligible_count - available_count,
                "score_missing_rate": (
                    float((eligible_count - available_count) / eligible_count)
                    if eligible_count
                    else 0.0
                ),
                "zero_component_count": int((component_counts == 0).sum()),
                "minimum_component_count": (
                    int(component_counts.min()) if not component_counts.empty else None
                ),
                "median_component_count": (
                    float(component_counts.median())
                    if not component_counts.empty
                    else None
                ),
                "maximum_component_count": (
                    int(component_counts.max()) if not component_counts.empty else None
                ),
                "effective_weight_violation_count": int(
                    by_name.get(factor_name, {}).get("violation_count", 0)
                ),
                "unavailable_reason_counts_json": json.dumps(
                    dict(sorted(reasons.items())), separators=(",", ":")
                ),
            }
        )
    return pd.DataFrame(records)


def _score_distributions(
    scored: pd.DataFrame,
    score_columns: Mapping[str, Sequence[str]],
) -> pd.DataFrame:
    eligible = _eligible_mask(scored)
    records = []
    for score_type, columns in score_columns.items():
        for column in columns:
            values = (
                pd.to_numeric(scored.loc[eligible, column], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                if column in scored
                else pd.Series(dtype=float)
            )
            eligible_count = int(eligible.sum())
            records.append(
                {
                    "scope": "eligible",
                    "score_type": score_type,
                    "score_name": column.removesuffix("_score"),
                    "score_column": column,
                    "eligible_row_count": eligible_count,
                    "available_count": int(len(values)),
                    "missing_count": eligible_count - int(len(values)),
                    "minimum": float(values.min()) if not values.empty else None,
                    "p05": (
                        float(values.quantile(0.05)) if not values.empty else None
                    ),
                    "p25": (
                        float(values.quantile(0.25)) if not values.empty else None
                    ),
                    "median": float(values.median()) if not values.empty else None,
                    "mean": float(values.mean()) if not values.empty else None,
                    "p75": (
                        float(values.quantile(0.75)) if not values.empty else None
                    ),
                    "p95": (
                        float(values.quantile(0.95)) if not values.empty else None
                    ),
                    "maximum": float(values.max()) if not values.empty else None,
                    "standard_deviation": (
                        float(values.std(ddof=0)) if not values.empty else None
                    ),
                }
            )
    return pd.DataFrame(records)


def _insufficient_coverage_count(coverage: pd.DataFrame) -> int:
    if coverage.empty:
        return 0
    if "sufficient_observations" in coverage:
        sufficient = coverage["sufficient_observations"].map(_strict_bool)
    elif {"valid_reference_count", "minimum_required"}.issubset(coverage):
        valid = pd.to_numeric(coverage["valid_reference_count"], errors="coerce")
        minimum = pd.to_numeric(coverage["minimum_required"], errors="coerce")
        sufficient = valid.ge(minimum) & valid.notna() & minimum.notna()
    else:
        return 0
    inapplicable = (
        coverage["inapplicable_sector"].map(_strict_bool)
        if "inapplicable_sector" in coverage
        else pd.Series(False, index=coverage.index)
    )
    return int((~sufficient & ~inapplicable).sum())


def _list_to_text(value: object) -> str:
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return ";".join(str(item) for item in value)
    if isinstance(value, str):
        parsed, invalid = _as_name_list(value)
        if not invalid and value.lstrip().startswith("["):
            return ";".join(parsed)
        return value
    return "" if _is_missing(value) else str(value)


def _build_audit(
    scored: pd.DataFrame,
    metric_names: Sequence[str],
    factor_names: Sequence[str],
    mode_names: Sequence[str],
) -> pd.DataFrame:
    columns: list[str] = [
        "as_of_date",
        "ticker",
        "company_name",
        "sector",
        "eligible_for_scoring",
        "input_feature_run_id",
        "input_contract_version",
        "factor_model_version",
        "screening_modes_version",
    ]
    columns.extend(f"{name}_score" for name in _unique_names(metric_names))
    for factor_name in _unique_names(factor_names):
        columns.extend(
            [
                f"{factor_name}_score",
                f"{factor_name}_component_count",
                f"{factor_name}_available_components",
                f"{factor_name}_effective_metric_weights",
                f"{factor_name}_unavailable_reason",
            ]
        )
    for mode_name in _unique_names(mode_names):
        columns.extend(
            [
                f"{mode_name}_score",
                f"{mode_name}_factor_count",
                f"{mode_name}_available_factors",
                f"{mode_name}_effective_factor_weights",
                f"{mode_name}_unavailable_reason",
                f"{mode_name}_eligible_for_ranking",
                f"{mode_name}_ranking_exclusion_reasons",
            ]
        )
    list_fields = [
        "data_quality_flags",
        "missing_fields",
        "stale_fundamental_metrics",
        "exclusion_reasons",
    ]
    columns.extend(list_fields)
    columns = list(dict.fromkeys(columns))
    audit = scored.reindex(columns=columns).copy()

    detail_list_columns = [
        f"{name}_available_components" for name in _unique_names(factor_names)
    ] + [
        f"{name}_available_factors" for name in _unique_names(mode_names)
    ] + [
        f"{name}_ranking_exclusion_reasons"
        for name in _unique_names(mode_names)
    ]
    for column in detail_list_columns + list_fields:
        if column not in audit:
            continue
        audit[f"{column}_text"] = audit[column].map(_list_to_text)
        audit = audit.drop(columns=column)
    sort_columns = [column for column in PRIMARY_KEY if column in audit]
    if sort_columns:
        audit = audit.sort_values(sort_columns, kind="stable")
    return audit.reset_index(drop=True)


def analyze_scored_matrix(
    scored: pd.DataFrame,
    input_matrix: pd.DataFrame,
    metadata: Mapping[str, object],
    metric_names: Sequence[str],
    factor_names: Sequence[str],
    mode_names: Sequence[str],
    metric_sector_coverage: pd.DataFrame,
    *,
    factor_document: Optional[Mapping[str, object]] = None,
    modes_document: Optional[Mapping[str, object]] = None,
) -> ScoringQuality:
    """Analyze a scored snapshot and apply the Phase 3A hard gates."""

    scored_analysis = scored.reset_index(drop=True)
    score_columns = _score_columns(metric_names, factor_names, mode_names)
    all_score_columns = list(
        dict.fromkeys(
            column for columns in score_columns.values() for column in columns
        )
    )
    row_accounting = _primary_key_summary(scored_analysis, input_matrix)
    eligibility_mismatches = _eligibility_mismatch_count(
        scored_analysis, input_matrix
    )
    row_accounting["eligibility_mismatch_count"] = eligibility_mismatches
    if eligibility_mismatches:
        row_accounting["row_accounting_valid"] = False

    ranges = _score_range_summary(scored_analysis, score_columns)
    numeric_evidence = _numeric_evidence_summary(
        scored_analysis,
        input_matrix.columns,
        metric_names,
        factor_names,
        mode_names,
    )
    ineligible_scores = _ineligible_score_summary(
        scored_analysis, all_score_columns
    )
    eligible_modes = _eligible_mode_summary(scored_analysis, mode_names)
    factor_weights = _effective_weight_summary(
        scored_analysis,
        factor_names,
        available_suffix="available_components",
        weight_suffix="effective_metric_weights",
        component_kind="metrics",
    )
    mode_weights = _effective_weight_summary(
        scored_analysis,
        mode_names,
        available_suffix="available_factors",
        weight_suffix="effective_factor_weights",
        component_kind="factors",
    )
    effective_weight_violations = int(
        factor_weights["violation_count"] + mode_weights["violation_count"]
    )
    factor_arithmetic = _aggregate_arithmetic_summary(
        scored_analysis,
        factor_names,
        weight_suffix="effective_metric_weights",
        direct_aggregate_names=("sector_strength",),
    )
    mode_arithmetic = _aggregate_arithmetic_summary(
        scored_analysis,
        mode_names,
        weight_suffix="effective_factor_weights",
    )
    aggregate_arithmetic_violations = int(
        factor_arithmetic["violation_count"]
        + mode_arithmetic["violation_count"]
    )

    coverage = metric_sector_coverage.copy(deep=True)
    sort_columns = [
        column for column in ("factor", "metric", "sector") if column in coverage
    ]
    if sort_columns:
        coverage = coverage.sort_values(sort_columns, kind="stable").reset_index(
            drop=True
        )
    configuration, model = _configured_model(
        factor_document,
        modes_document,
        metadata,
        metric_names,
        factor_names,
        mode_names,
    )
    aligned_input = _aligned_input_rows(scored_analysis, input_matrix)
    metric_recomputation: Dict[str, object] = {
        "executed": False,
        "violation_count": 0,
        "by_metric": {},
    }
    sector_recomputation: Dict[str, object] = {
        "executed": False,
        "violation_count": 0,
        "violation_reason_counts": {},
    }
    coverage_integrity: Dict[str, object] = {
        "valid": False,
        "executed": False,
        "violation_count": 0,
        "violation_reason_counts": {},
        "expected_row_count": None,
        "actual_row_count": int(len(coverage)),
        "required_columns_missing": [],
    }
    component_contract: Dict[str, object] = {
        "executed": False,
        "violation_count": 0,
        "by_aggregate": {},
    }
    mode_ranking: Dict[str, object] = {
        "executed": False,
        "violation_count": 0,
        "by_mode": {},
    }
    input_projection: Dict[str, object] = {
        "executed": False,
        "checked_row_count": 0,
        "checked_column_count": 0,
        "missing_columns": [],
        "violating_row_count": 0,
        "field_mismatch_count": 0,
        "violation_count": 0,
        "mismatch_count_by_column": {},
    }
    recomputation_error: Optional[str] = None
    if aligned_input is not None:
        input_projection = _input_projection_summary(
            scored_analysis, aligned_input
        )
    if model is not None and aligned_input is not None:
        try:
            metric_expected, sector_expected, expected_coverage = (
                _recompute_expectations(input_matrix, aligned_input, model)
            )
            metric_recomputation = _metric_transform_summary(
                scored_analysis, metric_expected
            )
            metric_recomputation["executed"] = True
            sector_recomputation = _sector_strength_summary(
                scored_analysis, sector_expected
            )
            sector_recomputation["executed"] = True
            coverage_integrity = _strict_coverage_summary(
                coverage, expected_coverage
            )
            coverage_integrity["executed"] = True
            component_contract = _component_contract_summary(
                scored_analysis, model
            )
            component_contract["executed"] = True
            mode_ranking = _mode_ranking_eligibility_summary(
                scored_analysis, model
            )
            mode_ranking["executed"] = True
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            recomputation_error = f"{type(exc).__name__}:{exc}"
    elif model is not None:
        recomputation_error = "input_alignment_unavailable"

    independent_recomputation_executed = bool(
        model is not None
        and aligned_input is not None
        and recomputation_error is None
        and metric_recomputation["executed"]
        and sector_recomputation["executed"]
        and coverage_integrity["executed"]
        and component_contract["executed"]
        and input_projection["executed"]
        and mode_ranking["executed"]
    )
    provenance = _row_provenance_summary(scored_analysis, metadata)
    insufficient_coverage_count = _insufficient_coverage_count(coverage)
    factor_coverage = _factor_coverage(
        scored_analysis, factor_names, factor_weights
    )
    distributions = _score_distributions(scored_analysis, score_columns)
    audit = _build_audit(
        scored_analysis, metric_names, factor_names, mode_names
    )

    hard_failures: list[str] = []
    if not row_accounting["row_accounting_valid"]:
        hard_failures.append("row_accounting_failed")
    if not row_accounting["primary_key_valid"]:
        hard_failures.append("primary_key_validation_failed")
    if ranges["missing_score_columns"]:
        hard_failures.append("score_columns_missing")
    if ranges["range_violation_count"]:
        hard_failures.append("score_range_validation_failed")
    if numeric_evidence["violation_count"]:
        hard_failures.append("numeric_evidence_dtype_validation_failed")
    if ineligible_scores["row_count"]:
        hard_failures.append("ineligible_scores_present")
    if eligible_modes["eligible_rows_missing_any_mode"]:
        hard_failures.append("eligible_mode_scores_missing")
    if effective_weight_violations:
        hard_failures.append("effective_weight_validation_failed")
    if aggregate_arithmetic_violations:
        hard_failures.append("aggregate_arithmetic_validation_failed")
    if not configuration["executed"] or not independent_recomputation_executed:
        hard_failures.append("independent_recomputation_not_executed")
    if configuration["executed"] and not configuration["valid"]:
        hard_failures.append("scoring_configuration_validation_failed")
    if metric_recomputation["violation_count"]:
        hard_failures.append("metric_transform_validation_failed")
    if sector_recomputation["violation_count"]:
        hard_failures.append("sector_strength_validation_failed")
    if coverage_integrity["executed"] and not coverage_integrity["valid"]:
        hard_failures.append("metric_sector_coverage_validation_failed")
    if component_contract["violation_count"]:
        hard_failures.append("component_contract_validation_failed")
    if input_projection["violation_count"]:
        hard_failures.append("input_projection_validation_failed")
    if mode_ranking["violation_count"]:
        hard_failures.append(
            "mode_ranking_eligibility_validation_failed"
        )
    if provenance["violation_count"]:
        hard_failures.append("row_provenance_validation_failed")

    warnings: list[str] = []
    if int(factor_coverage["score_missing_count"].sum()):
        warnings.append("eligible_factor_missingness_present")
    if insufficient_coverage_count:
        warnings.append("insufficient_sector_metric_coverage")

    eligible = _eligible_mask(scored_analysis)
    summary: Dict[str, object] = {
        "run": _json_safe(dict(metadata)),
        "acceptance": {
            "passed": not hard_failures,
            "hard_failures": hard_failures,
            "warnings": warnings,
        },
        "row_accounting": row_accounting,
        "eligibility": {
            "eligible_count": int(eligible.sum()),
            "ineligible_count": int((~eligible).sum()),
            "ineligible_rows_with_scores": ineligible_scores,
            "eligible_mode_completeness": eligible_modes,
        },
        "score_ranges": ranges,
        "numeric_evidence_schema": numeric_evidence,
        "effective_weights": {
            "violation_count": effective_weight_violations,
            "factor": factor_weights,
            "mode": mode_weights,
        },
        "aggregate_arithmetic": {
            "violation_count": aggregate_arithmetic_violations,
            "factor": factor_arithmetic,
            "mode": mode_arithmetic,
        },
        "independent_recomputation": {
            "executed": independent_recomputation_executed,
            "error": recomputation_error,
            "configuration": configuration,
            "metric_transforms": metric_recomputation,
            "sector_strength": sector_recomputation,
            "components": component_contract,
            "input_projection": input_projection,
            "mode_ranking_eligibility": mode_ranking,
            "row_provenance": provenance,
        },
        "mode_ranking_eligibility": mode_ranking,
        "coverage": {
            "metric_sector_row_count": int(len(coverage)),
            "insufficient_sector_metric_count": insufficient_coverage_count,
            "eligible_factor_missing_count": int(
                factor_coverage["score_missing_count"].sum()
            ),
            "integrity": coverage_integrity,
        },
    }
    return ScoringQuality(
        summary=summary,
        audit=audit,
        metric_sector_coverage=coverage,
        factor_coverage=factor_coverage,
        score_distributions=distributions,
    )


def _artifact_paths(output_root: Path, run_id: str) -> ScoringArtifactPaths:
    run_dir = Path(output_root) / run_id
    return ScoringArtifactPaths(
        run_dir=run_dir,
        scored_matrix_parquet=run_dir / "scored_matrix.parquet",
        scoring_audit_csv=run_dir / "scoring_audit.csv",
        metric_sector_coverage_csv=run_dir / "metric_sector_coverage.csv",
        factor_coverage_csv=run_dir / "factor_coverage.csv",
        score_distributions_csv=run_dir / "score_distributions.csv",
        scoring_quality_json=run_dir / "scoring_quality.json",
        run_metadata_json=run_dir / "run_metadata.json",
        quality_report_md=run_dir / "quality_report.md",
    )


def _quality_report(summary: Mapping[str, object]) -> str:
    acceptance = summary["acceptance"]
    accounting = summary["row_accounting"]
    eligibility = summary["eligibility"]
    coverage = summary["coverage"]
    weights = summary["effective_weights"]
    arithmetic = summary["aggregate_arithmetic"]
    independent = summary["independent_recomputation"]
    lines = [
        "# Scoring Quality Report",
        "",
        f"- Acceptance passed: `{acceptance['passed']}`",
        f"- Input rows: `{accounting['input_row_count']}`",
        f"- Scored rows: `{accounting['scored_row_count']}`",
        f"- Eligible rows: `{eligibility['eligible_count']}`",
        "- Eligible rows missing any mode: "
        f"`{eligibility['eligible_mode_completeness']['eligible_rows_missing_any_mode']}`",
        f"- Score-range violations: `{summary['score_ranges']['range_violation_count']}`",
        "- Numeric-evidence dtype violations: "
        f"`{summary['numeric_evidence_schema']['violation_count']}`",
        f"- Effective-weight violations: `{weights['violation_count']}`",
        f"- Aggregate-arithmetic violations: `{arithmetic['violation_count']}`",
        f"- Independent recomputation executed: `{independent['executed']}`",
        "- Metric-transform violations: "
        f"`{independent['metric_transforms']['violation_count']}`",
        "- Sector-strength violations: "
        f"`{independent['sector_strength']['violation_count']}`",
        "- Component-contract violations: "
        f"`{independent['components']['violation_count']}`",
        "- Input-projection violations: "
        f"`{independent['input_projection']['violation_count']}`",
        "- Mode-ranking-eligibility violations: "
        f"`{summary['mode_ranking_eligibility']['violation_count']}`",
        "- Row-provenance violations: "
        f"`{independent['row_provenance']['violation_count']}`",
        "- Coverage-integrity violations: "
        f"`{coverage['integrity']['violation_count']}`",
        "- Insufficient sector-metric rows: "
        f"`{coverage['insufficient_sector_metric_count']}`",
        "",
        "## Hard Failures",
        "",
    ]
    failures = acceptance["hard_failures"]
    lines.extend(f"- {failure}" for failure in failures)
    if not failures:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    warnings = acceptance["warnings"]
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Supporting Tables",
            "",
            "See the scoring audit, metric-sector coverage, factor coverage, "
            "and score-distribution CSV files in this run directory.",
            "",
        ]
    )
    return "\n".join(lines)


def write_scoring_artifacts(
    scored: pd.DataFrame,
    quality: ScoringQuality,
    output_root: Path,
    run_id: str,
) -> ScoringArtifactPaths:
    """Atomically create one immutable, whole-run scoring artifact bundle."""

    if (
        not run_id
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
    ):
        raise ValueError("run_id must be one non-empty filesystem-safe name")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    paths = _artifact_paths(output_root, run_id)
    if os.path.lexists(paths.run_dir):
        raise FileExistsError(
            f"Scoring run directory already exists: {paths.run_dir}"
        )

    quality.summary["artifacts"] = {
        field_name: path.name
        for field_name, path in paths.__dict__.items()
        if field_name != "run_dir"
    }
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{run_id}.", dir=output_root)
    )
    staging_paths = _artifact_paths(staging_dir.parent, staging_dir.name)
    try:
        atomic_write_parquet(staging_paths.scored_matrix_parquet, scored)
        atomic_write_csv(staging_paths.scoring_audit_csv, quality.audit)
        atomic_write_csv(
            staging_paths.metric_sector_coverage_csv,
            quality.metric_sector_coverage,
        )
        atomic_write_csv(
            staging_paths.factor_coverage_csv, quality.factor_coverage
        )
        atomic_write_csv(
            staging_paths.score_distributions_csv,
            quality.score_distributions,
        )
        atomic_write_json(
            staging_paths.run_metadata_json, quality.summary["run"]
        )
        atomic_write_json(
            staging_paths.scoring_quality_json, quality.summary
        )
        _atomic_write(
            staging_paths.quality_report_md,
            lambda temporary_path: temporary_path.write_text(
                _quality_report(quality.summary), encoding="utf-8"
            ),
        )
        if os.path.lexists(paths.run_dir):
            raise FileExistsError(
                f"Scoring run directory already exists: {paths.run_dir}"
            )
        os.rename(staging_dir, paths.run_dir)
    except Exception:
        if os.path.lexists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return paths
