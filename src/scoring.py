"""Deterministic, sector-relative Phase 3A scoring kernel and CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pyarrow
import yaml

from src.scoring_quality import (
    ScoringArtifactPaths,
    ScoringQuality,
    analyze_scored_matrix,
    write_scoring_artifacts,
)


CORE_FACTORS = (
    "momentum",
    "quality",
    "valuation",
    "risk",
    "sector_strength",
)
EXPECTED_MODES = ("balanced", "growth", "value", "low_risk")
SUPPORTED_MODEL_STATUSES = ("phase3a_candidate", "frozen_v1")
RANK_ENDPOINT_FORMULA = "(rank - 1) / (n - 1) * 100"


class ScoringError(RuntimeError):
    """Raised when scoring inputs or configuration are invalid."""


@dataclass
class ScoringBuild:
    """In-memory result of applying the Phase 3A scoring model."""

    scored: pd.DataFrame
    metric_sector_coverage: pd.DataFrame
    metric_names: List[str]
    factor_names: List[str]
    mode_names: List[str]


@dataclass
class ScoringRunResult:
    """Persisted scoring result and its quality assessment."""

    build: ScoringBuild
    quality: ScoringQuality
    artifacts: ScoringArtifactPaths


def load_yaml_document(path: Path) -> Dict[str, object]:
    """Load one YAML mapping with a useful failure message."""

    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScoringError(f"Cannot read YAML configuration: {path}") from exc
    if not isinstance(document, dict):
        raise ScoringError(f"YAML configuration must contain a mapping: {path}")
    return document


def _ordered_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not value:
        raise ScoringError(f"{label} must be a non-empty mapping")
    return value


def _as_float(value: object, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoringError(f"{label} must be numeric") from exc
    if not np.isfinite(numeric):
        raise ScoringError(f"{label} must be finite")
    return numeric


def validate_scoring_configs(
    factor_document: Mapping[str, object],
    modes_document: Mapping[str, object],
    input_columns: Optional[Sequence[str]] = None,
) -> None:
    """Validate the Phase 3A model and mode configuration as one contract."""

    factor_status = str(factor_document.get("status") or "")
    modes_status = str(modes_document.get("status") or "")
    if factor_status not in SUPPORTED_MODEL_STATUSES:
        raise ScoringError(
            "factor model status must be phase3a_candidate or frozen_v1"
        )
    if modes_status != factor_status:
        raise ScoringError("factor model and screening modes statuses must match")
    factor_version = str(factor_document.get("version") or "")
    modes_version = str(modes_document.get("version") or "")
    if not factor_version:
        raise ScoringError("factor model version is required")
    if not modes_version:
        raise ScoringError("screening modes version is required")
    if modes_version != factor_version:
        raise ScoringError("factor model and screening modes versions must match")

    source = _ordered_mapping(factor_document.get("source"), "source")
    reference = _ordered_mapping(source.get("reference"), "source.reference")
    if reference.get("config_path") != "config/data_contract.yaml":
        raise ScoringError("factor model must reference config/data_contract.yaml")
    if reference.get("run_id_field") != "contract.accepted_run_id":
        raise ScoringError("factor model accepted-run reference is invalid")
    if reference.get("as_of_date_field") != "contract.accepted_as_of_date":
        raise ScoringError("factor model accepted-date reference is invalid")
    row_filter = _ordered_mapping(source.get("row_filter"), "source.row_filter")
    if source.get("row_scope") != "full_eligible_snapshot":
        raise ScoringError("factor model reference must be the full eligible snapshot")
    if row_filter.get("field") != "eligible_for_scoring" or row_filter.get(
        "equals"
    ) is not True:
        raise ScoringError("factor model row filter must select eligible rows")

    factors = _ordered_mapping(factor_document.get("factors"), "factors")
    factor_names = [str(name) for name in factors]
    if factor_names != list(CORE_FACTORS):
        raise ScoringError(
            "factor model must define factors in this order: "
            + ", ".join(CORE_FACTORS)
        )

    configured_factor_names = modes_document.get("factor_names")
    if configured_factor_names != list(CORE_FACTORS):
        raise ScoringError("screening mode factor_names must match the factor model")
    preprocessing = _ordered_mapping(
        factor_document.get("preprocessing"), "preprocessing"
    )
    if preprocessing.get("comparison_group") != "sector":
        raise ScoringError("Phase 3 requires sector comparison groups")
    winsorization = _ordered_mapping(
        preprocessing.get("winsorization"), "preprocessing.winsorization"
    )
    lower = _as_float(
        winsorization.get("lower_percentile"), "lower winsor percentile"
    )
    upper = _as_float(
        winsorization.get("upper_percentile"), "upper winsor percentile"
    )
    if not 0 <= lower < upper <= 100:
        raise ScoringError("winsor percentiles must satisfy 0 <= lower < upper <= 100")
    if winsorization.get("interpolation") != "linear":
        raise ScoringError("Phase 3A requires linear winsor interpolation")

    percentile = _ordered_mapping(
        preprocessing.get("percentile_rank"), "preprocessing.percentile_rank"
    )
    if percentile.get("tie_method") != "average":
        raise ScoringError("Phase 3A requires average percentile ties")
    if percentile.get("endpoint_formula") != RANK_ENDPOINT_FORMULA:
        raise ScoringError("Phase 3A percentile endpoint formula is invalid")
    minimum = percentile.get("minimum_valid_observations")
    if not isinstance(minimum, int) or minimum < 2:
        raise ScoringError("minimum_valid_observations must be an integer >= 2")
    constant_score = _as_float(
        percentile.get("constant_value_score"), "constant value score"
    )
    if not 0 <= constant_score <= 100:
        raise ScoringError("constant value score must be between 0 and 100")

    aggregation = _ordered_mapping(
        factor_document.get("factor_aggregation"), "factor_aggregation"
    )
    if aggregation.get("metric_weighting") != "equal":
        raise ScoringError("Phase 3A supports equal metric weighting only")
    if aggregation.get("missing_policy") != "renormalize_over_available_metrics":
        raise ScoringError("factor metrics must renormalize over available inputs")
    if aggregation.get("minimum_available_metrics") != 1:
        raise ScoringError("Phase 3A factor minimum must be one available metric")

    required_input_columns = {
        "as_of_date",
        "ticker",
        "sector",
        "eligible_for_scoring",
    }
    metric_owners: Dict[str, str] = {}
    derived_metric_names: set[str] = set()
    for factor_name in CORE_FACTORS[:-1]:
        factor = _ordered_mapping(factors[factor_name], f"factor {factor_name}")
        metrics = _ordered_mapping(
            factor.get("metrics"), f"factor {factor_name}.metrics"
        )
        for metric_name, metric_value in metrics.items():
            metric_name = str(metric_name)
            if metric_name in metric_owners:
                raise ScoringError(
                    f"metric {metric_name} is owned by both "
                    f"{metric_owners[metric_name]} and {factor_name}"
                )
            metric_owners[metric_name] = factor_name
            metric = _ordered_mapping(
                metric_value, f"factor {factor_name}.{metric_name}"
            )
            if metric.get("direction") not in {"higher", "lower"}:
                raise ScoringError(
                    f"{factor_name}.{metric_name} must define higher/lower direction"
                )
            derivation = metric.get("derivation")
            if derivation is None:
                required_input_columns.add(metric_name)
            else:
                derived_metric_names.add(metric_name)
                derivation = _ordered_mapping(
                    derivation, f"{factor_name}.{metric_name}.derivation"
                )
                if derivation.get("operation") != "ratio":
                    raise ScoringError(
                        f"{factor_name}.{metric_name} supports ratio derivation only"
                    )
                numerator = str(derivation.get("numerator") or "")
                denominator = str(derivation.get("denominator") or "")
                if not numerator or not denominator or numerator == denominator:
                    raise ScoringError(
                        f"{factor_name}.{metric_name} ratio operands are invalid"
                    )
                if derivation.get("denominator_policy") != "positive_only":
                    raise ScoringError(
                        f"{factor_name}.{metric_name} denominator must be positive_only"
                    )
                alignment = _ordered_mapping(
                    derivation.get("period_alignment"),
                    f"{factor_name}.{metric_name}.period_alignment",
                )
                left_period = str(alignment.get("left") or "")
                right_period = str(alignment.get("right") or "")
                if (
                    not left_period
                    or not right_period
                    or left_period == right_period
                    or alignment.get("policy") != "exact"
                ):
                    raise ScoringError(
                        f"{factor_name}.{metric_name} period alignment is invalid"
                    )
                required_input_columns.update(
                    {numerator, denominator, left_period, right_period}
                )
            applicability = metric.get("applicability")
            if applicability is not None:
                applicability = _ordered_mapping(
                    applicability, f"{factor_name}.{metric_name}.applicability"
                )
                if applicability.get("default") != "applicable":
                    raise ScoringError(
                        f"{factor_name}.{metric_name} applicability default must be applicable"
                    )
                sectors = applicability.get("inapplicable_sectors")
                if not isinstance(sectors, list) or any(
                    not isinstance(sector, str) or not sector for sector in sectors
                ):
                    raise ScoringError(
                        f"{factor_name}.{metric_name} inapplicable_sectors must be strings"
                    )
                if len(sectors) != len(set(sectors)):
                    raise ScoringError(
                        f"{factor_name}.{metric_name} inapplicable_sectors has duplicates"
                    )

    risk = _ordered_mapping(factors["risk"], "factor risk")
    if risk.get("score_interpretation") != "higher_score_means_lower_risk":
        raise ScoringError("risk score must use a higher-is-safer interpretation")
    if risk.get("quality_warning_policy") != "no_numeric_penalty":
        raise ScoringError("Phase 3A quality warnings may not create numeric penalties")

    sector_strength = _ordered_mapping(
        factors["sector_strength"], "factor sector_strength"
    )
    if sector_strength.get("source_rows") != "eligible_only":
        raise ScoringError("sector strength must use eligible rows only")
    if sector_strength.get("sector_aggregation") != "median":
        raise ScoringError("sector strength aggregation must be median")
    if sector_strength.get("minimum_sector_members") != minimum:
        raise ScoringError(
            "sector strength and metric transforms must use the same minimum count"
        )
    cross_sector = _ordered_mapping(
        sector_strength.get("cross_sector_ranking"),
        "sector_strength.cross_sector_ranking",
    )
    expected_cross_sector = {
        "universe": "valid_sectors_only",
        "method": "rank_percentile",
        "direction": "higher",
        "tie_method": "average",
        "endpoint_formula": RANK_ENDPOINT_FORMULA,
    }
    for field, expected in expected_cross_sector.items():
        if cross_sector.get(field) != expected:
            raise ScoringError(
                f"sector strength cross-sector {field} must be {expected}"
            )
    minimum_valid_sectors = cross_sector.get("minimum_valid_sectors")
    if not isinstance(minimum_valid_sectors, int) or minimum_valid_sectors < 2:
        raise ScoringError("sector strength requires at least two valid sectors")
    source_metric = str(sector_strength.get("source_metric") or "")
    if not source_metric:
        raise ScoringError("sector strength source_metric is required")
    required_input_columns.add(source_metric)

    screening_modes = _ordered_mapping(
        modes_document.get("screening_modes"), "screening_modes"
    )
    if list(screening_modes) != list(EXPECTED_MODES):
        raise ScoringError(
            "screening modes must be ordered: " + ", ".join(EXPECTED_MODES)
        )
    for mode_name, mode_value in screening_modes.items():
        mode = _ordered_mapping(mode_value, f"screening mode {mode_name}")
        weights = _ordered_mapping(mode.get("weights"), f"{mode_name}.weights")
        if list(weights) != list(CORE_FACTORS):
            raise ScoringError(f"{mode_name} weights must match factor_names")
        numeric_weights = [
            _as_float(weight, f"{mode_name}.{factor_name}")
            for factor_name, weight in weights.items()
        ]
        if any(weight < 0 for weight in numeric_weights):
            raise ScoringError(f"{mode_name} weights may not be negative")
        if not np.isclose(sum(numeric_weights), 1.0, atol=1e-12):
            raise ScoringError(f"{mode_name} weights must sum to 1")
        ranking_required = mode.get("ranking_required_factors")
        if not isinstance(ranking_required, list) or any(
            not isinstance(factor_name, str)
            or factor_name not in CORE_FACTORS
            for factor_name in ranking_required
        ):
            raise ScoringError(
                f"{mode_name}.ranking_required_factors must list configured factors"
            )
        if len(ranking_required) != len(set(ranking_required)):
            raise ScoringError(
                f"{mode_name}.ranking_required_factors has duplicates"
            )

    if input_columns is not None:
        supplied_derived = sorted(derived_metric_names & set(input_columns))
        if supplied_derived:
            raise ScoringError(
                "Input feature matrix may not supply scoring-derived columns: "
                + ", ".join(supplied_derived)
            )
        missing = sorted(required_input_columns - set(input_columns))
        if missing:
            raise ScoringError(
                "Input feature matrix is missing scoring columns: "
                + ", ".join(missing)
            )


def _eligible_mask(frame: pd.DataFrame) -> pd.Series:
    values = frame.get("eligible_for_scoring", pd.Series(False, index=frame.index))
    return values.map(lambda value: value is True or isinstance(value, np.bool_) and bool(value))


def _finite_numeric(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    return numeric.where(np.isfinite(numeric))


def _derived_metric_values(
    frame: pd.DataFrame,
    metric_name: str,
    metric_spec: Mapping[str, object],
) -> pd.Series:
    """Materialize one configured scoring-only metric from immutable inputs."""

    derivation = metric_spec.get("derivation")
    if not isinstance(derivation, Mapping):
        return _finite_numeric(frame[metric_name])
    if derivation.get("operation") != "ratio":
        raise ScoringError(f"Unsupported derivation for metric {metric_name}")

    numerator = _finite_numeric(frame[str(derivation["numerator"])])
    denominator = _finite_numeric(frame[str(derivation["denominator"])])
    valid = numerator.notna() & denominator.gt(0)
    alignment = derivation["period_alignment"]
    left_period = pd.to_datetime(
        frame[str(alignment["left"])], errors="coerce"
    )
    right_period = pd.to_datetime(
        frame[str(alignment["right"])], errors="coerce"
    )
    valid &= left_period.notna() & right_period.notna() & left_period.eq(right_period)
    values = (numerator / denominator).where(valid)
    return values.where(np.isfinite(values))


def _materialize_configured_metrics(
    frame: pd.DataFrame,
    factor_document: Mapping[str, object],
) -> pd.DataFrame:
    """Return a copy containing all direct and scoring-only derived metrics."""

    materialized = frame.copy(deep=True)
    for factor_name in CORE_FACTORS[:-1]:
        for metric_name, metric_spec in factor_document["factors"][factor_name][
            "metrics"
        ].items():
            if isinstance(metric_spec, Mapping) and metric_spec.get("derivation"):
                materialized[str(metric_name)] = _derived_metric_values(
                    frame, str(metric_name), metric_spec
                )
    return materialized


def _empirical_percentile(
    reference: np.ndarray,
    values: np.ndarray,
    constant_score: float,
) -> np.ndarray:
    """Map values to average-tie rank endpoints fitted on reference values."""

    ordered = np.sort(reference.astype(float))
    if len(ordered) < 2:
        return np.full(len(values), np.nan)
    if np.isclose(ordered[0], ordered[-1], rtol=0.0, atol=1e-15):
        return np.full(len(values), constant_score, dtype=float)
    left = np.searchsorted(ordered, values, side="left")
    right = np.searchsorted(ordered, values, side="right")
    average_zero_based_rank = (left + right - 1) / 2.0
    percentiles = average_zero_based_rank / (len(ordered) - 1) * 100.0
    return np.clip(percentiles, 0.0, 100.0)


def _metric_applicability(metric_spec: Mapping[str, object]) -> set[str]:
    applicability = metric_spec.get("applicability")
    if not isinstance(applicability, Mapping):
        return set()
    sectors = applicability.get("inapplicable_sectors", [])
    if not isinstance(sectors, list):
        raise ScoringError("inapplicable_sectors must be a list")
    return {str(sector) for sector in sectors}


def transform_sector_metric(
    reference: pd.DataFrame,
    target: pd.DataFrame,
    factor_name: str,
    metric_name: str,
    metric_spec: Mapping[str, object],
    preprocessing: Mapping[str, object],
) -> Tuple[pd.DataFrame, List[Dict[str, object]]]:
    """Fit sector cutoffs on eligible reference rows and score target rows."""

    winsorization = preprocessing["winsorization"]
    percentile = preprocessing["percentile_rank"]
    lower_quantile = float(winsorization["lower_percentile"]) / 100.0
    upper_quantile = float(winsorization["upper_percentile"]) / 100.0
    interpolation = str(winsorization["interpolation"])
    minimum = int(percentile["minimum_valid_observations"])
    constant_score = float(percentile["constant_value_score"])
    direction = str(metric_spec["direction"])
    inapplicable_sectors = _metric_applicability(metric_spec)

    raw_column = f"{metric_name}_scoring_input"
    winsorized_column = f"{metric_name}_winsorized"
    score_column = f"{metric_name}_score"
    available_column = f"{metric_name}_available"
    reason_column = f"{metric_name}_unavailable_reason"

    transformed = pd.DataFrame(index=target.index)
    transformed[raw_column] = _finite_numeric(target[metric_name])
    transformed[winsorized_column] = np.nan
    transformed[score_column] = np.nan
    transformed[available_column] = False
    transformed[reason_column] = pd.Series(None, index=target.index, dtype=object)

    target_eligible = _eligible_mask(target)
    target_sectors = target["sector"].astype("string")
    target_inapplicable = target_sectors.isin(inapplicable_sectors)
    target_valid_raw = transformed[raw_column].notna()
    transformed.loc[~target_eligible, reason_column] = "ineligible_for_scoring"
    transformed.loc[target_eligible & target_inapplicable, reason_column] = (
        "inapplicable_sector"
    )
    transformed.loc[
        target_eligible & ~target_inapplicable & ~target_valid_raw,
        reason_column,
    ] = "missing_value"

    reference_eligible = _eligible_mask(reference)
    reference_sectors = reference["sector"].astype("string")
    reference_values = _finite_numeric(reference[metric_name])
    coverage: List[Dict[str, object]] = []
    sectors = sorted(
        {
            str(sector)
            for sector in pd.concat([reference_sectors, target_sectors]).dropna()
        }
    )

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
            & target_valid_raw
        )

        record: Dict[str, object] = {
            "factor": factor_name,
            "metric": metric_name,
            "sector": sector,
            "valid_reference_count": valid_count,
            "minimum_required": minimum,
            "sufficient_observations": bool(
                not sector_inapplicable and valid_count >= minimum
            ),
            "inapplicable_sector": sector_inapplicable,
            "lower_cutoff": None,
            "upper_cutoff": None,
            "scored_target_count": 0,
        }
        if sector_inapplicable:
            coverage.append(record)
            continue
        if valid_count < minimum:
            transformed.loc[target_mask, reason_column] = (
                f"insufficient_sector_observations:{valid_count}"
            )
            coverage.append(record)
            continue

        lower_cutoff = float(
            sector_reference.quantile(lower_quantile, interpolation=interpolation)
        )
        upper_cutoff = float(
            sector_reference.quantile(upper_quantile, interpolation=interpolation)
        )
        winsorized_reference = sector_reference.clip(
            lower=lower_cutoff, upper=upper_cutoff
        ).to_numpy(dtype=float)
        target_values = transformed.loc[target_mask, raw_column].clip(
            lower=lower_cutoff, upper=upper_cutoff
        )
        scores = _empirical_percentile(
            winsorized_reference,
            target_values.to_numpy(dtype=float),
            constant_score,
        )
        if direction == "lower":
            scores = 100.0 - scores

        transformed.loc[target_mask, winsorized_column] = target_values
        transformed.loc[target_mask, score_column] = scores
        transformed.loc[target_mask, available_column] = True
        transformed.loc[target_mask, reason_column] = None
        record["lower_cutoff"] = lower_cutoff
        record["upper_cutoff"] = upper_cutoff
        record["scored_target_count"] = int(target_mask.sum())
        coverage.append(record)

    return transformed, coverage


def _stable_weight_json(values: Mapping[str, float]) -> str:
    return json.dumps(
        {key: round(float(value), 12) for key, value in values.items()},
        separators=(",", ":"),
    )


def aggregate_factor(
    scored: pd.DataFrame,
    factor_name: str,
    metric_names: Sequence[str],
    minimum_available: int,
) -> None:
    """Add one missing-aware, equal-metric factor score in place."""

    eligible = _eligible_mask(scored)
    score_columns = [f"{metric_name}_score" for metric_name in metric_names]
    score_frame = scored[score_columns].apply(pd.to_numeric, errors="coerce")
    available = score_frame.notna()
    counts = available.sum(axis=1).astype(int)
    denominator = counts.replace(0, np.nan).astype(float)
    factor_score = score_frame.fillna(0.0).sum(axis=1) / denominator
    factor_score = factor_score.where(eligible & counts.ge(minimum_available))

    scored[f"{factor_name}_score"] = factor_score
    scored[f"{factor_name}_component_count"] = counts.where(eligible, 0)
    scored[f"{factor_name}_available_components"] = [
        [metric for metric in metric_names if bool(available.at[index, f"{metric}_score"])]
        if bool(eligible.at[index])
        else []
        for index in scored.index
    ]
    scored[f"{factor_name}_effective_metric_weights"] = [
        _stable_weight_json(
            {
                metric: 1.0 / int(counts.at[index])
                for metric in metric_names
                if bool(available.at[index, f"{metric}_score"])
            }
        )
        if bool(eligible.at[index]) and int(counts.at[index]) >= minimum_available
        else "{}"
        for index in scored.index
    ]
    reason_column = f"{factor_name}_unavailable_reason"
    scored[reason_column] = None
    scored.loc[~eligible, reason_column] = "ineligible_for_scoring"
    scored.loc[eligible & counts.lt(minimum_available), reason_column] = (
        "no_available_components"
    )


def build_sector_strength(
    reference: pd.DataFrame,
    target: pd.DataFrame,
    specification: Mapping[str, object],
    constant_score: float,
) -> Tuple[pd.DataFrame, List[Dict[str, object]]]:
    """Compute median sector relative strength and rank valid sectors."""

    source_metric = str(specification["source_metric"])
    minimum = int(specification["minimum_sector_members"])
    minimum_valid_sectors = int(
        specification["cross_sector_ranking"]["minimum_valid_sectors"]
    )
    reference_eligible = _eligible_mask(reference)
    reference_values = _finite_numeric(reference[source_metric])
    reference_sectors = reference["sector"].astype("string")

    records: List[Dict[str, object]] = []
    medians: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for sector, group in reference.loc[reference_eligible].groupby(
        "sector", dropna=False, sort=True
    ):
        sector_name = str(sector)
        values = reference_values.loc[group.index].dropna()
        count = int(len(values))
        counts[sector_name] = count
        if count >= minimum:
            medians[sector_name] = float(values.median())

    sector_scores: Dict[str, float] = {}
    if len(medians) >= minimum_valid_sectors:
        names = list(medians)
        values = np.array([medians[name] for name in names], dtype=float)
        scores = _empirical_percentile(values, values, constant_score)
        sector_scores = dict(zip(names, scores))

    for sector in sorted(counts):
        records.append(
            {
                "factor": "sector_strength",
                "metric": f"sector_median:{source_metric}",
                "sector": sector,
                "valid_reference_count": counts[sector],
                "minimum_required": minimum,
                "sufficient_observations": sector in sector_scores,
                "inapplicable_sector": False,
                "lower_cutoff": None,
                "upper_cutoff": None,
                "scored_target_count": int(
                    (_eligible_mask(target) & target["sector"].astype(str).eq(sector)).sum()
                )
                if sector in sector_scores
                else 0,
                "sector_source_value": medians.get(sector),
            }
        )

    result = pd.DataFrame(index=target.index)
    target_sectors = target["sector"].astype(str)
    target_eligible = _eligible_mask(target)
    result["sector_strength_source_value"] = target_sectors.map(medians)
    result["sector_strength_member_count"] = target_sectors.map(counts)
    result["sector_strength_score"] = target_sectors.map(sector_scores).where(
        target_eligible
    )
    result["sector_strength_component_count"] = (
        result["sector_strength_score"].notna().astype(int)
    )
    component_label = f"sector_median:{source_metric}"
    result["sector_strength_available_components"] = [
        [component_label] if pd.notna(score) else []
        for score in result["sector_strength_score"]
    ]
    result["sector_strength_effective_metric_weights"] = [
        _stable_weight_json({component_label: 1.0}) if pd.notna(score) else "{}"
        for score in result["sector_strength_score"]
    ]
    result["sector_strength_unavailable_reason"] = None
    result.loc[~target_eligible, "sector_strength_unavailable_reason"] = (
        "ineligible_for_scoring"
    )
    eligible_missing = target_eligible & result["sector_strength_score"].isna()
    missing_reason = (
        "insufficient_valid_sectors"
        if len(medians) < minimum_valid_sectors
        else "insufficient_sector_observations"
    )
    result.loc[eligible_missing, "sector_strength_unavailable_reason"] = missing_reason
    return result, records


def aggregate_modes(
    scored: pd.DataFrame,
    modes: Mapping[str, object],
    factor_names: Sequence[str],
) -> None:
    """Add all mode scores with row-level factor-weight renormalization."""

    eligible = _eligible_mask(scored)
    factor_score_columns = [f"{factor_name}_score" for factor_name in factor_names]
    factor_scores = scored[factor_score_columns].apply(pd.to_numeric, errors="coerce")

    for mode_name, mode_value in modes.items():
        weights = {
            str(factor): float(weight)
            for factor, weight in mode_value["weights"].items()
        }
        available = factor_scores.notna()
        denominator = sum(
            available[f"{factor_name}_score"].astype(float) * weights[factor_name]
            for factor_name in factor_names
        )
        numerator = sum(
            factor_scores[f"{factor_name}_score"].fillna(0.0)
            * weights[factor_name]
            for factor_name in factor_names
        )
        mode_score = (numerator / denominator.replace(0.0, np.nan)).where(eligible)
        scored[f"{mode_name}_score"] = mode_score
        scored[f"{mode_name}_factor_count"] = available.sum(axis=1).where(
            eligible, 0
        ).astype(int)
        scored[f"{mode_name}_available_factors"] = [
            [
                factor_name
                for factor_name in factor_names
                if bool(available.at[index, f"{factor_name}_score"])
            ]
            if bool(eligible.at[index])
            else []
            for index in scored.index
        ]
        scored[f"{mode_name}_effective_factor_weights"] = [
            _stable_weight_json(
                {
                    factor_name: weights[factor_name] / float(denominator.at[index])
                    for factor_name in factor_names
                    if bool(available.at[index, f"{factor_name}_score"])
                }
            )
            if bool(eligible.at[index]) and float(denominator.at[index]) > 0
            else "{}"
            for index in scored.index
        ]
        reason_column = f"{mode_name}_unavailable_reason"
        scored[reason_column] = None
        scored.loc[~eligible, reason_column] = "ineligible_for_scoring"
        scored.loc[eligible & denominator.eq(0.0), reason_column] = (
            "no_available_factors"
        )

        required_factors = [
            str(factor)
            for factor in mode_value.get("ranking_required_factors", [])
        ]
        ranking_eligible = eligible & mode_score.notna()
        for factor_name in required_factors:
            ranking_eligible &= factor_scores[f"{factor_name}_score"].notna()
        scored[f"{mode_name}_eligible_for_ranking"] = ranking_eligible.astype(bool)
        scored[f"{mode_name}_ranking_exclusion_reasons"] = [
            []
            if bool(ranking_eligible.at[index])
            else (
                ["ineligible_for_scoring"]
                if not bool(eligible.at[index])
                else [
                    f"missing_required_factor:{factor_name}"
                    for factor_name in required_factors
                    if pd.isna(
                        factor_scores.at[index, f"{factor_name}_score"]
                    )
                ]
                or ["mode_score_unavailable"]
            )
            for index in scored.index
        ]


def score_feature_matrix(
    matrix: pd.DataFrame,
    factor_document: Mapping[str, object],
    modes_document: Mapping[str, object],
    reference_matrix: Optional[pd.DataFrame] = None,
) -> ScoringBuild:
    """Score a target matrix against a full eligible reference snapshot."""

    reference = matrix if reference_matrix is None else reference_matrix
    validate_scoring_configs(factor_document, modes_document, matrix.columns)
    validate_scoring_configs(factor_document, modes_document, reference.columns)
    if matrix[["as_of_date", "ticker"]].duplicated().any():
        raise ScoringError("Target matrix primary key contains duplicates")
    if reference[["as_of_date", "ticker"]].duplicated().any():
        raise ScoringError("Reference matrix primary key contains duplicates")

    # DataFrame index values are not part of the contract. Normalize them so
    # row-wise `.at` access remains unambiguous even after caller-side slicing
    # or concatenation has produced duplicate indexes.
    matrix = _materialize_configured_metrics(
        matrix.reset_index(drop=True), factor_document
    )
    reference = _materialize_configured_metrics(
        reference.reset_index(drop=True), factor_document
    )

    scored = matrix.copy(deep=True)
    factors = factor_document["factors"]
    preprocessing = factor_document["preprocessing"]
    minimum_available = int(
        factor_document["factor_aggregation"]["minimum_available_metrics"]
    )
    metric_names: List[str] = []
    coverage_records: List[Dict[str, object]] = []

    for factor_name in CORE_FACTORS[:-1]:
        metrics = factors[factor_name]["metrics"]
        factor_metric_names = [str(metric_name) for metric_name in metrics]
        for metric_name, metric_spec in metrics.items():
            if metric_name not in metric_names:
                transformed, coverage = transform_sector_metric(
                    reference,
                    matrix,
                    factor_name,
                    str(metric_name),
                    metric_spec,
                    preprocessing,
                )
                scored = pd.concat([scored, transformed], axis=1)
                metric_names.append(str(metric_name))
                coverage_records.extend(coverage)
        aggregate_factor(
            scored,
            factor_name,
            factor_metric_names,
            minimum_available,
        )

    constant_score = float(
        preprocessing["percentile_rank"]["constant_value_score"]
    )
    sector_strength, sector_coverage = build_sector_strength(
        reference,
        matrix,
        factors["sector_strength"],
        constant_score,
    )
    scored = pd.concat([scored, sector_strength], axis=1)
    coverage_records.extend(sector_coverage)

    mode_names = [str(mode) for mode in modes_document["screening_modes"]]
    aggregate_modes(scored, modes_document["screening_modes"], CORE_FACTORS)
    coverage_frame = pd.DataFrame(coverage_records).sort_values(
        ["factor", "metric", "sector"]
    ).reset_index(drop=True)
    return ScoringBuild(
        scored=scored,
        metric_sector_coverage=coverage_frame,
        metric_names=metric_names,
        factor_names=list(CORE_FACTORS),
        mode_names=mode_names,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_accepted_input(
    project_root: Path,
    input_run: Path,
) -> Tuple[pd.DataFrame, Dict[str, object], Dict[str, object], str]:
    contract_path = project_root / "config/data_contract.yaml"
    contract = load_yaml_document(contract_path)
    contract_header = contract.get("contract", {})
    if not isinstance(contract_header, Mapping):
        raise ScoringError("data contract header is invalid")

    matrix_path = input_run / "feature_matrix.parquet"
    metadata_path = input_run / "run_metadata.json"
    quality_path = input_run / "matrix_quality.json"
    if not matrix_path.exists() or not metadata_path.exists() or not quality_path.exists():
        raise ScoringError(
            "Input run must contain feature_matrix.parquet, run_metadata.json, "
            "and matrix_quality.json"
        )
    try:
        matrix = pd.read_parquet(matrix_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        input_quality = json.loads(quality_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ScoringError(f"Cannot read accepted input run: {input_run}") from exc
    if not isinstance(metadata, dict) or not isinstance(input_quality, dict):
        raise ScoringError("Input run metadata and quality must be JSON objects")

    accepted_run_id = str(contract_header.get("accepted_run_id") or "")
    accepted_as_of = str(contract_header.get("accepted_as_of_date") or "")
    if str(contract_header.get("status")) != "frozen_v1":
        raise ScoringError("Phase 3 requires a frozen_v1 data contract")
    if str(metadata.get("contract_status")) != "frozen_v1":
        raise ScoringError("Phase 3 input run metadata is not frozen_v1")
    if str(metadata.get("contract_version")) != str(contract_header.get("version")):
        raise ScoringError("Input run contract version does not match frozen contract")
    if str(metadata.get("run_id")) != accepted_run_id:
        raise ScoringError(
            f"Phase 3 input must be accepted run {accepted_run_id}"
        )
    if input_run.name != accepted_run_id:
        raise ScoringError("Input directory name must match the accepted run ID")
    if str(metadata.get("as_of_date")) != accepted_as_of:
        raise ScoringError("Input run as-of date does not match the frozen contract")
    if input_quality.get("run") != metadata:
        raise ScoringError("Input matrix quality metadata does not match run metadata")
    input_acceptance = input_quality.get("acceptance")
    input_schema = input_quality.get("schema")
    if not isinstance(input_acceptance, Mapping) or input_acceptance.get(
        "passed"
    ) is not True:
        raise ScoringError("Input feature matrix did not pass its quality gate")
    if not isinstance(input_schema, Mapping) or input_schema.get(
        "schema_valid"
    ) is not True:
        raise ScoringError("Input feature matrix schema was not valid")

    accepted_hash = str(
        contract_header.get("accepted_feature_matrix_sha256") or ""
    )
    actual_hash = _sha256(matrix_path)
    if len(accepted_hash) != 64 or actual_hash != accepted_hash:
        raise ScoringError("Input feature matrix hash does not match frozen contract")
    return matrix, metadata, contract, actual_hash


def _validate_frozen_scoring_reproduction(
    scoring_header: Optional[Mapping[str, object]],
    factor_document: Mapping[str, object],
    modes_document: Mapping[str, object],
    factor_config_path: Path,
    modes_config_path: Path,
    input_metadata: Mapping[str, object],
    input_feature_matrix_hash: str,
) -> None:
    """Bind frozen reproductions to the already accepted scoring contract."""

    if scoring_header is None:
        return
    if (
        str(factor_document.get("status")) != "frozen_v1"
        or str(modes_document.get("status")) != "frozen_v1"
    ):
        return
    expected = {
        "factor_model_version": factor_document.get("version"),
        "screening_modes_version": modes_document.get("version"),
        "factor_config_sha256": _sha256(factor_config_path),
        "modes_config_sha256": _sha256(modes_config_path),
        "input_feature_run_id": input_metadata.get("run_id"),
        "input_contract_version": input_metadata.get("contract_version"),
        "input_feature_matrix_sha256": input_feature_matrix_hash,
        "accepted_as_of_date": input_metadata.get("as_of_date"),
    }
    for field, actual in expected.items():
        if str(scoring_header.get(field) or "") != str(actual or ""):
            raise ScoringError(
                f"Frozen scoring reproduction does not match contract field {field}"
            )


def run_scoring_pipeline(
    project_root: Path,
    input_run: Path,
    factor_config_path: Path,
    modes_config_path: Path,
    output_dir: Path,
    run_id: str,
) -> ScoringRunResult:
    """Load the accepted feature run, score it, validate it, and persist artifacts."""

    project_root = Path(project_root).resolve()
    input_run = Path(input_run).resolve()
    output_dir = Path(output_dir).resolve()
    if not run_id or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in run_id
    ):
        raise ScoringError(
            "run_id may contain only letters, numbers, '.', '_', and '-'"
        )
    if output_dir / run_id == input_run:
        raise ScoringError("Scoring output may not overwrite the accepted input run")
    target_run_dir = output_dir / run_id
    if target_run_dir.exists():
        raise ScoringError(
            f"Scoring run directory already exists; refusing overwrite: {target_run_dir}"
        )

    scoring_header: Optional[Mapping[str, object]] = None
    scoring_contract_path = project_root / "config/scoring_contract.yaml"
    if scoring_contract_path.exists():
        scoring_contract = load_yaml_document(scoring_contract_path)
        scoring_header = _ordered_mapping(
            scoring_contract.get("scoring_contract"), "scoring_contract"
        )
        if (
            str(scoring_header.get("status")) == "frozen_v1"
            and str(scoring_header.get("accepted_run_id")) == run_id
        ):
            raise ScoringError(
                f"Accepted frozen scoring run {run_id} may not be regenerated"
            )

    matrix, input_metadata, contract, input_feature_matrix_hash = _load_accepted_input(
        project_root, input_run
    )
    factor_document = load_yaml_document(factor_config_path)
    modes_document = load_yaml_document(modes_config_path)
    _validate_frozen_scoring_reproduction(
        scoring_header,
        factor_document,
        modes_document,
        factor_config_path,
        modes_config_path,
        input_metadata,
        input_feature_matrix_hash,
    )
    started_at = datetime.now(timezone.utc)
    build = score_feature_matrix(matrix, factor_document, modes_document)
    completed_at = datetime.now(timezone.utc)

    row_provenance = {
        "input_feature_run_id": str(input_metadata["run_id"]),
        "input_contract_version": str(input_metadata["contract_version"]),
        "factor_model_version": str(factor_document["version"]),
        "screening_modes_version": str(modes_document["version"]),
    }
    for column, value in row_provenance.items():
        build.scored[column] = value

    try:
        input_run_metadata_path = str(input_run.relative_to(project_root))
    except ValueError:
        input_run_metadata_path = str(input_run)

    metadata: Dict[str, object] = {
        "run_id": run_id,
        "started_at_utc": started_at.replace(microsecond=0).isoformat(),
        "completed_at_utc": completed_at.replace(microsecond=0).isoformat(),
        "input_feature_run_id": input_metadata["run_id"],
        "input_feature_run_path": input_run_metadata_path,
        "input_feature_matrix_sha256": input_feature_matrix_hash,
        "as_of_date": input_metadata["as_of_date"],
        "input_contract_version": input_metadata["contract_version"],
        "input_contract_status": input_metadata["contract_status"],
        "factor_model_version": str(factor_document["version"]),
        "factor_model_status": str(factor_document["status"]),
        "screening_modes_version": str(modes_document["version"]),
        "screening_modes_status": str(modes_document["status"]),
        "factor_config_sha256": _sha256(factor_config_path),
        "modes_config_sha256": _sha256(modes_config_path),
        "input_row_count": int(len(matrix)),
        "eligible_input_count": int(_eligible_mask(matrix).sum()),
        "scored_mode_count": int(len(build.mode_names)),
        "runtime_versions": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
        },
        "accepted_contract_run_id": contract["contract"]["accepted_run_id"],
    }
    quality = analyze_scored_matrix(
        build.scored,
        matrix,
        metadata,
        build.metric_names,
        build.factor_names,
        build.mode_names,
        build.metric_sector_coverage,
        factor_document=factor_document,
        modes_document=modes_document,
    )
    artifacts = write_scoring_artifacts(
        build.scored,
        quality,
        output_dir,
        run_id,
    )
    return ScoringRunResult(build=build, quality=quality, artifacts=artifacts)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-run", required=True, type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--factor-config", type=Path)
    parser.add_argument("--modes-config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = args.project_root.resolve()
    factor_config = (
        args.factor_config or project_root / "config/factor_model.yaml"
    ).resolve()
    modes_config = (
        args.modes_config or project_root / "config/screening_modes.yaml"
    ).resolve()
    output_dir = (args.output_dir or project_root / "data/processed").resolve()

    try:
        factor_document = load_yaml_document(factor_config)
        version = str(factor_document.get("version") or "unknown").replace(".", "_")
        run_id = args.run_id or f"{args.input_run.name}_scores_v{version}"
        result = run_scoring_pipeline(
            project_root=project_root,
            input_run=args.input_run,
            factor_config_path=factor_config,
            modes_config_path=modes_config,
            output_dir=output_dir,
            run_id=run_id,
        )
    except Exception as exc:
        detail = str(exc).strip() or "No detail available"
        print(f"Scoring failed: {type(exc).__name__}: {detail}")
        return 2

    acceptance = result.quality.summary["acceptance"]
    print(
        json.dumps(
            {
                "run_id": result.quality.summary["run"]["run_id"],
                "acceptance_passed": acceptance["passed"],
                "hard_failures": acceptance["hard_failures"],
                "warnings": acceptance["warnings"],
                "input_rows": len(result.build.scored),
                "eligible_rows": int(_eligible_mask(result.build.scored).sum()),
                "run_directory": str(result.artifacts.run_dir),
            },
            indent=2,
        )
    )
    return 0 if acceptance["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
