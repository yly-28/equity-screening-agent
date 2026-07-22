"""Quality analysis and atomic persistence for feature-matrix runs."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional

import numpy as np
import pandas as pd

from src.unified_data import (
    DATA_CONTRACT,
    validate_unified_feature_frame,
)


REPORT_FIELD_SECTIONS = (
    "identity_fields",
    "provenance_fields",
    "market_fields",
    "fundamental_fields",
    "derived_optional_fields",
)


@dataclass
class MatrixQuality:
    summary: Dict[str, object]
    audit: pd.DataFrame
    field_missingness: pd.DataFrame
    sector_missingness: pd.DataFrame
    flag_counts: pd.DataFrame
    exclusions: pd.DataFrame
    freshness: pd.DataFrame


@dataclass(frozen=True)
class ArtifactPaths:
    run_dir: Path
    matrix_parquet: Path
    audit_csv: Path
    quality_json: Path
    field_missingness_csv: Path
    sector_missingness_csv: Path
    flag_counts_csv: Path
    exclusions_csv: Path
    freshness_csv: Path
    run_metadata_json: Path
    quality_report_md: Path


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, np.ndarray)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _missing_mask(series: pd.Series) -> pd.Series:
    return series.map(_is_missing).astype(bool)


def _safe_rate(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, np.ndarray)):
        return [str(item) for item in value]
    return []


def _eligible_mask(matrix: pd.DataFrame) -> pd.Series:
    values = matrix.get(
        "eligible_for_scoring", pd.Series(False, index=matrix.index)
    )
    return values.map(
        lambda value: bool(value) if isinstance(value, (bool, np.bool_)) else False
    )


def _report_field_specs(
    contract: Mapping[str, object],
) -> Dict[str, tuple[str, Mapping[str, object]]]:
    fields: Dict[str, tuple[str, Mapping[str, object]]] = {}
    for section_name in REPORT_FIELD_SECTIONS:
        section = contract.get(section_name, {})
        if not isinstance(section, Mapping):
            continue
        for field_name, spec in section.items():
            if isinstance(spec, Mapping):
                fields[str(field_name)] = (section_name, spec)
    return fields


def build_field_missingness(
    matrix: pd.DataFrame,
    contract: Mapping[str, object] = DATA_CONTRACT,
) -> pd.DataFrame:
    """Report overall and eligible-row missingness for contract data fields."""

    eligible = _eligible_mask(matrix)
    records = []
    for field_name, (section_name, spec) in _report_field_specs(contract).items():
        if field_name in matrix:
            missing = _missing_mask(matrix[field_name])
        else:
            missing = pd.Series(True, index=matrix.index)
        missing_count = int(missing.sum())
        eligible_missing_count = int(missing[eligible].sum())
        records.append(
            {
                "field": field_name,
                "section": section_name,
                "dtype": spec.get("dtype"),
                "required": bool(spec.get("required", False)),
                "required_for_scoring": bool(
                    spec.get("required_for_scoring", False)
                ),
                "row_count": int(len(matrix)),
                "missing_count": missing_count,
                "missing_rate": _safe_rate(missing_count, len(matrix)),
                "eligible_row_count": int(eligible.sum()),
                "eligible_missing_count": eligible_missing_count,
                "eligible_missing_rate": _safe_rate(
                    eligible_missing_count, int(eligible.sum())
                ),
            }
        )
    return pd.DataFrame(records).sort_values(["section", "field"]).reset_index(
        drop=True
    )


def build_sector_missingness(
    matrix: pd.DataFrame,
    contract: Mapping[str, object] = DATA_CONTRACT,
) -> pd.DataFrame:
    """Report field missingness by sector for coverage and applicability review."""

    records = []
    fields = list(_report_field_specs(contract))
    if "sector" not in matrix:
        return pd.DataFrame(
            columns=["sector", "field", "row_count", "missing_count", "missing_rate"]
        )
    for sector, group in matrix.groupby("sector", dropna=False, sort=True):
        sector_name = str(sector) if not _is_missing(sector) else "<missing>"
        for field_name in fields:
            missing_count = (
                int(_missing_mask(group[field_name]).sum())
                if field_name in group
                else int(len(group))
            )
            records.append(
                {
                    "sector": sector_name,
                    "field": field_name,
                    "row_count": int(len(group)),
                    "missing_count": missing_count,
                    "missing_rate": _safe_rate(missing_count, len(group)),
                }
            )
    return pd.DataFrame(records).sort_values(["sector", "field"]).reset_index(
        drop=True
    )


def build_flag_counts(matrix: pd.DataFrame) -> pd.DataFrame:
    """Count quality flags and show their eligibility split."""

    counts: Dict[str, Dict[str, int]] = {}
    for row in matrix.itertuples(index=False):
        flags = _as_string_list(getattr(row, "data_quality_flags", None))
        eligible = bool(getattr(row, "eligible_for_scoring", False))
        for flag in flags:
            record = counts.setdefault(
                str(flag),
                {"count": 0, "eligible_count": 0, "ineligible_count": 0},
            )
            record["count"] += 1
            record["eligible_count" if eligible else "ineligible_count"] += 1
    records = [{"flag": flag, **values} for flag, values in counts.items()]
    if not records:
        return pd.DataFrame(
            columns=["flag", "count", "eligible_count", "ineligible_count"]
        )
    return pd.DataFrame(records).sort_values(
        ["count", "flag"], ascending=[False, True]
    ).reset_index(drop=True)


def _join_list(value: object) -> str:
    if isinstance(value, (list, tuple, np.ndarray)):
        return ";".join(str(item) for item in value)
    return "" if _is_missing(value) else str(value)


def build_compact_audit(matrix: pd.DataFrame) -> pd.DataFrame:
    """Create the review-oriented CSV projection of the matrix."""

    columns = [
        "as_of_date",
        "ticker",
        "company_name",
        "sector",
        "industry",
        "cik",
        "eligible_for_scoring",
        "price_data_end",
        "market_data_age_days",
        "fundamental_period_end",
        "fundamental_filed_date",
        "fundamental_age_days",
        "data_quality_flags",
        "missing_fields",
        "exclusion_reasons",
        "market_error",
        "fundamental_error",
    ]
    audit = matrix.reindex(columns=columns).copy()
    for field_name in ("data_quality_flags", "missing_fields", "exclusion_reasons"):
        audit[f"{field_name}_text"] = audit[field_name].map(_join_list)
        audit = audit.drop(columns=field_name)
    return audit.sort_values(["as_of_date", "ticker"]).reset_index(drop=True)


def build_exclusions(matrix: pd.DataFrame) -> pd.DataFrame:
    """Create one row per ineligible security with diagnostic context."""

    eligible = _eligible_mask(matrix)
    columns = [
        "as_of_date",
        "ticker",
        "sector",
        "price_data_end",
        "fundamental_period_end",
        "exclusion_reasons",
        "data_quality_flags",
        "market_error",
        "fundamental_error",
    ]
    exclusions = matrix.loc[~eligible].reindex(columns=columns).copy()
    exclusions["exclusion_reasons_text"] = exclusions["exclusion_reasons"].map(
        _join_list
    )
    exclusions["data_quality_flags_text"] = exclusions["data_quality_flags"].map(
        _join_list
    )
    return exclusions.drop(
        columns=["exclusion_reasons", "data_quality_flags"]
    ).sort_values(["as_of_date", "ticker"]).reset_index(drop=True)


def _fundamental_metric_period_fields(
    contract: Mapping[str, object],
) -> Dict[str, str]:
    return {
        str(metric): str(period_field)
        for metric, period_field in contract.get(
            "fundamental_metric_freshness", {}
        ).get("period_fields", {}).items()
    }


def build_freshness(
    matrix: pd.DataFrame,
    contract: Mapping[str, object] = DATA_CONTRACT,
) -> pd.DataFrame:
    columns = [
        "as_of_date",
        "ticker",
        "sector",
        "eligible_for_scoring",
        "price_data_end",
        "market_data_age_days",
        "fundamental_period_end",
        "fundamental_filed_date",
        "fundamental_age_days",
    ]
    period_fields = _fundamental_metric_period_fields(contract)
    columns.extend(
        period_field
        for period_field in dict.fromkeys(period_fields.values())
        if period_field not in columns
    )
    freshness = matrix.reindex(columns=columns).copy()
    as_of_dates = pd.to_datetime(freshness["as_of_date"], errors="coerce")
    for metric, period_field in period_fields.items():
        period_dates = pd.to_datetime(freshness[period_field], errors="coerce")
        freshness[f"{metric}_age_days"] = (as_of_dates - period_dates).dt.days
    return freshness.sort_values(
        ["as_of_date", "ticker"]
    ).reset_index(drop=True)


def build_metric_freshness_summary(
    matrix: pd.DataFrame,
    contract: Mapping[str, object] = DATA_CONTRACT,
) -> Dict[str, Dict[str, object]]:
    """Audit non-null metric values against their own fiscal period."""

    maximum_age = int(
        contract["quality_thresholds"]["maximum_fundamental_age_days"]
    )
    as_of_dates = pd.to_datetime(
        matrix.get("as_of_date", pd.Series(index=matrix.index)), errors="coerce"
    )
    stale_lists = matrix.get(
        "stale_fundamental_metrics", pd.Series([[]] * len(matrix), index=matrix.index)
    ).map(_as_string_list)
    summary: Dict[str, Dict[str, object]] = {}
    for metric, period_field in _fundamental_metric_period_fields(contract).items():
        values = matrix.get(metric, pd.Series(None, index=matrix.index))
        value_present = ~_missing_mask(values)
        periods = pd.to_datetime(
            matrix.get(period_field, pd.Series(None, index=matrix.index)),
            errors="coerce",
        )
        ages = (as_of_dates - periods).dt.days
        missing_period_violation = value_present & periods.isna()
        stale_value_violation = value_present & (
            (ages < 0) | (ages > maximum_age)
        )
        stale_nullified = stale_lists.map(lambda items: metric in items)
        usable_ages = ages[value_present & ~periods.isna()]
        summary[metric] = {
            "value_available_count": int(value_present.sum()),
            "value_missing_count": int((~value_present).sum()),
            "period_missing_violation_count": int(missing_period_violation.sum()),
            "stale_value_violation_count": int(stale_value_violation.sum()),
            "stale_value_nullified_count": int(stale_nullified.sum()),
            "minimum_value_age_days": (
                int(usable_ages.min()) if not usable_ages.empty else None
            ),
            "maximum_value_age_days": (
                int(usable_ages.max()) if not usable_ages.empty else None
            ),
        }
    return summary


def _age_summary(series: pd.Series) -> Dict[str, object]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return {
        "available_count": int(len(numeric)),
        "missing_count": int(len(series) - len(numeric)),
        "minimum_days": int(numeric.min()) if not numeric.empty else None,
        "median_days": float(numeric.median()) if not numeric.empty else None,
        "p95_days": float(numeric.quantile(0.95)) if not numeric.empty else None,
        "maximum_days": int(numeric.max()) if not numeric.empty else None,
    }


def analyze_feature_matrix(
    matrix: pd.DataFrame,
    universe: pd.DataFrame,
    run_metadata: Mapping[str, object],
    contract: Mapping[str, object] = DATA_CONTRACT,
) -> MatrixQuality:
    """Build the complete quality bundle and Phase 2 acceptance decision."""

    schema = validate_unified_feature_frame(matrix, contract=contract)
    expected_tickers = set(universe.get("ticker", pd.Series(dtype=str)).astype(str))
    actual_tickers = set(matrix.get("ticker", pd.Series(dtype=str)).astype(str))
    missing_requested = sorted(expected_tickers - actual_tickers)
    unexpected = sorted(actual_tickers - expected_tickers)
    eligible = _eligible_mask(matrix)
    eligible_count = int(eligible.sum())
    row_count = int(len(matrix))
    eligible_rate = _safe_rate(eligible_count, row_count)
    minimum_eligible_rate = float(
        contract["quality_thresholds"]["minimum_eligible_rate"]
    )

    field_missingness = build_field_missingness(matrix, contract)
    sector_missingness = build_sector_missingness(matrix, contract)
    flag_counts = build_flag_counts(matrix)
    exclusions = build_exclusions(matrix)
    freshness = build_freshness(matrix, contract)
    metric_freshness = build_metric_freshness_summary(matrix, contract)
    audit = build_compact_audit(matrix)

    metric_period_violations = sum(
        int(values["period_missing_violation_count"])
        for values in metric_freshness.values()
    )
    stale_metric_violations = sum(
        int(values["stale_value_violation_count"])
        for values in metric_freshness.values()
    )
    stale_metrics_nullified = sum(
        int(values["stale_value_nullified_count"])
        for values in metric_freshness.values()
    )

    hard_failures = []
    if not schema["schema_valid"]:
        hard_failures.append("schema_validation_failed")
    if row_count == 0:
        hard_failures.append("matrix_is_empty")
    if row_count != len(universe) or missing_requested or unexpected:
        hard_failures.append("row_accounting_failed")
    if eligible_rate < minimum_eligible_rate:
        hard_failures.append("eligible_rate_below_threshold")
    if metric_period_violations or stale_metric_violations:
        hard_failures.append("fundamental_metric_freshness_failed")

    warnings = []
    if not exclusions.empty:
        warnings.append("ineligible_securities_present")
    if matrix.get("market_error", pd.Series(dtype=object)).notna().any():
        warnings.append("market_provider_errors_present")
    if matrix.get("fundamental_error", pd.Series(dtype=object)).notna().any():
        warnings.append("fundamental_provider_errors_present")
    required_fundamental_missing = field_missingness[
        (field_missingness["section"] == "fundamental_fields")
        & field_missingness["required"]
        & (field_missingness["eligible_missing_count"] > 0)
    ]
    if not required_fundamental_missing.empty:
        warnings.append("required_fundamental_missingness_present")
    optional_missing = field_missingness[
        (~field_missingness["required"])
        & (~field_missingness["required_for_scoring"])
        & (field_missingness["missing_count"] > 0)
    ]
    if not optional_missing.empty:
        warnings.append("optional_field_missingness_present")
    if stale_metrics_nullified:
        warnings.append("stale_fundamental_metrics_nullified")

    flag_summary = {
        str(row.flag): int(row.count)
        for row in flag_counts.itertuples(index=False)
    }
    exclusion_summary: Dict[str, int] = {}
    for reasons in matrix.get("exclusion_reasons", pd.Series(dtype=object)):
        for reason in _as_string_list(reasons):
            exclusion_summary[str(reason)] = exclusion_summary.get(str(reason), 0) + 1

    summary: Dict[str, object] = {
        "run": dict(run_metadata),
        "acceptance": {
            "passed": not hard_failures,
            "hard_failures": hard_failures,
            "warnings": warnings,
            "minimum_eligible_rate": minimum_eligible_rate,
        },
        "schema": schema,
        "row_accounting": {
            "requested_count": int(len(universe)),
            "matrix_row_count": row_count,
            "missing_requested_tickers": missing_requested,
            "unexpected_tickers": unexpected,
        },
        "eligibility": {
            "eligible_count": eligible_count,
            "ineligible_count": row_count - eligible_count,
            "eligible_rate": eligible_rate,
        },
        "provider_status": {
            "market_error_count": int(
                matrix.get("market_error", pd.Series(dtype=object)).notna().sum()
            ),
            "fundamental_error_count": int(
                matrix.get(
                    "fundamental_error", pd.Series(dtype=object)
                ).notna().sum()
            ),
        },
        "freshness": {
            "market": _age_summary(
                matrix.get("market_data_age_days", pd.Series(index=matrix.index))
            ),
            "fundamentals": _age_summary(
                matrix.get("fundamental_age_days", pd.Series(index=matrix.index))
            ),
            "fundamental_metrics": metric_freshness,
            "metric_period_violation_count": metric_period_violations,
            "stale_metric_value_violation_count": stale_metric_violations,
            "stale_metric_value_nullified_count": stale_metrics_nullified,
        },
        "missingness": {
            "fields_with_missing_values": int(
                (field_missingness["missing_count"] > 0).sum()
            ),
            "eligible_required_field_violations": schema[
                "eligible_required_field_violations"
            ],
        },
        "quality_flag_counts": flag_summary,
        "exclusion_reason_counts": dict(sorted(exclusion_summary.items())),
    }
    return MatrixQuality(
        summary=summary,
        audit=audit,
        field_missingness=field_missingness,
        sector_missingness=sector_missingness,
        flag_counts=flag_counts,
        exclusions=exclusions,
        freshness=freshness,
    )


def artifact_paths(output_root: Path, run_id: str) -> ArtifactPaths:
    run_dir = Path(output_root) / run_id
    return ArtifactPaths(
        run_dir=run_dir,
        matrix_parquet=run_dir / "feature_matrix.parquet",
        audit_csv=run_dir / "feature_audit.csv",
        quality_json=run_dir / "matrix_quality.json",
        field_missingness_csv=run_dir / "field_missingness.csv",
        sector_missingness_csv=run_dir / "sector_missingness.csv",
        flag_counts_csv=run_dir / "quality_flag_counts.csv",
        exclusions_csv=run_dir / "exclusions.csv",
        freshness_csv=run_dir / "freshness.csv",
        run_metadata_json=run_dir / "run_metadata.json",
        quality_report_md=run_dir / "quality_report.md",
    )


def _atomic_write(path: Path, writer: Callable[[Path], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=path.suffix,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        writer(temporary_path)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    _atomic_write(
        path,
        lambda temporary_path: temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        ),
    )


def atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    _atomic_write(
        path,
        lambda temporary_path: frame.to_csv(temporary_path, index=False),
    )


def atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    _atomic_write(
        path,
        lambda temporary_path: frame.to_parquet(temporary_path, index=False),
    )


def _quality_report(summary: Mapping[str, object]) -> str:
    acceptance = summary["acceptance"]
    row_accounting = summary["row_accounting"]
    eligibility = summary["eligibility"]
    freshness = summary["freshness"]
    lines = [
        "# Feature Matrix Quality Report",
        "",
        f"- Acceptance passed: `{acceptance['passed']}`",
        f"- Requested rows: `{row_accounting['requested_count']}`",
        f"- Matrix rows: `{row_accounting['matrix_row_count']}`",
        f"- Eligible rows: `{eligibility['eligible_count']}` "
        f"(`{eligibility['eligible_rate']:.2%}`)",
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
            "## Freshness",
            "",
            f"- Market median age: `{freshness['market']['median_days']}` days",
            "- Fundamental median age: "
            f"`{freshness['fundamentals']['median_days']}` days",
            "- Metric-period violations: "
            f"`{freshness['metric_period_violation_count']}`",
            "- Stale non-null metric violations: "
            f"`{freshness['stale_metric_value_violation_count']}`",
            "- Stale metric values nullified: "
            f"`{freshness['stale_metric_value_nullified_count']}`",
            "",
            "## Supporting Tables",
            "",
            "See the field missingness, sector missingness, quality flag, "
            "exclusion, freshness, and compact audit CSV files in this run directory.",
            "",
        ]
    )
    return "\n".join(lines)


def write_quality_artifacts(
    matrix: pd.DataFrame,
    quality: MatrixQuality,
    output_root: Path,
    run_id: str,
) -> ArtifactPaths:
    """Atomically persist the matrix and every quality artifact."""

    paths = artifact_paths(output_root, run_id)
    quality.summary["artifacts"] = {
        field_name: path.name
        for field_name, path in paths.__dict__.items()
        if field_name != "run_dir"
    }
    atomic_write_parquet(paths.matrix_parquet, matrix)
    atomic_write_csv(paths.audit_csv, quality.audit)
    atomic_write_csv(paths.field_missingness_csv, quality.field_missingness)
    atomic_write_csv(paths.sector_missingness_csv, quality.sector_missingness)
    atomic_write_csv(paths.flag_counts_csv, quality.flag_counts)
    atomic_write_csv(paths.exclusions_csv, quality.exclusions)
    atomic_write_csv(paths.freshness_csv, quality.freshness)
    atomic_write_json(paths.run_metadata_json, quality.summary["run"])
    atomic_write_json(paths.quality_json, quality.summary)
    _atomic_write(
        paths.quality_report_md,
        lambda temporary_path: temporary_path.write_text(
            _quality_report(quality.summary), encoding="utf-8"
        ),
    )
    return paths
