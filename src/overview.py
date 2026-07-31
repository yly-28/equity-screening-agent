"""Deterministic market and sector aggregates over the accepted scoring run."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from numbers import Real
from pathlib import Path

import pandas as pd

from src import scoring_contract
from src.screening import SUPPORTED_MODES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1.0.0"
RETURN_FIELDS = ("return_1d", "return_1m", "return_3m")
FACTOR_FIELDS = (
    "momentum_score",
    "quality_score",
    "valuation_score",
    "risk_score",
    "sector_strength_score",
)


class OverviewValidationError(ValueError):
    """Raised when an overview request is invalid."""


class OverviewDataError(RuntimeError):
    """Raised when accepted data cannot satisfy the overview schema."""


def _normalize_mode(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OverviewValidationError("mode must be a non-empty string")
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_MODES:
        raise OverviewValidationError(
            "Unsupported mode: "
            f"{value!r}. Supported values: {', '.join(SUPPORTED_MODES)}"
        )
    return normalized


def _normalize_sectors(
    value: object,
    known_sectors: tuple[str, ...],
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, bytes):
        raise OverviewValidationError("sectors must contain sector-name strings")
    else:
        try:
            values = list(value)  # type: ignore[arg-type]
        except TypeError as error:
            raise OverviewValidationError(
                "sectors must be a sector name or iterable of sector names"
            ) from error

    canonical = {sector.casefold(): sector for sector in known_sectors}
    selected: set[str] = set()
    unknown: set[str] = set()
    for sector in values:
        if not isinstance(sector, str) or not sector.strip():
            raise OverviewValidationError(
                "sectors must contain non-empty sector-name strings"
            )
        normalized = canonical.get(sector.strip().casefold())
        if normalized is None:
            unknown.add(sector.strip())
        else:
            selected.add(normalized)
    if unknown:
        raise OverviewValidationError(
            "Unknown sectors: "
            + ", ".join(sorted(unknown))
            + ". Available sectors: "
            + ", ".join(known_sectors)
        )
    return tuple(sorted(selected))


def _scalar(value: object) -> object:
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()  # type: ignore[union-attr]
        except (TypeError, ValueError):
            pass
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    return values.where(values.map(math.isfinite))


def _metric_summary(frame: pd.DataFrame, field_name: str) -> dict[str, object]:
    values = _numeric(frame[field_name])
    available = values.dropna()
    total_count = int(len(frame))
    available_count = int(len(available))
    summary: dict[str, object] = {
        "available_count": available_count,
        "missing_count": total_count - available_count,
        "coverage_ratio": (
            available_count / total_count if total_count else None
        ),
        "median": float(available.median()) if available_count else None,
    }
    if field_name in RETURN_FIELDS:
        positive_count = int((available > 0).sum())
        negative_count = int((available < 0).sum())
        summary.update(
            {
                "positive_count": positive_count,
                "negative_count": negative_count,
                "unchanged_count": available_count
                - positive_count
                - negative_count,
                "positive_ratio": (
                    positive_count / available_count if available_count else None
                ),
            }
        )
    return summary


def _date_summary(series: pd.Series) -> dict[str, object]:
    values = sorted(
        {
            str(scalar)
            for value in series
            if (scalar := _scalar(value)) is not None
        }
    )
    return {
        "available_count": int(series.map(lambda value: _scalar(value) is not None).sum()),
        "missing_count": int(series.map(lambda value: _scalar(value) is None).sum()),
        "earliest": values[0] if values else None,
        "latest": values[-1] if values else None,
        "distinct_dates": values,
    }


def _strict_true_count(series: pd.Series, label: str) -> int:
    valid = series.map(lambda value: isinstance(_scalar(value), bool))
    if not bool(valid.all()):
        raise OverviewDataError(f"Accepted {label} values must be boolean")
    return int(series.astype(bool).sum())


def _aggregate_scope(
    frame: pd.DataFrame,
    mode: str,
) -> dict[str, object]:
    mode_score_field = f"{mode}_score"
    mode_eligible_field = f"{mode}_eligible_for_ranking"
    mode_eligible_count = _strict_true_count(
        frame[mode_eligible_field],
        mode_eligible_field,
    )
    mode_eligible_frame = frame.loc[frame[mode_eligible_field].astype(bool)]
    return {
        "security_count": int(len(frame)),
        "base_eligible_count": _strict_true_count(
            frame["eligible_for_scoring"],
            "eligible_for_scoring",
        ),
        "mode_eligible_count": mode_eligible_count,
        "metrics": {
            field_name: _metric_summary(frame, field_name)
            for field_name in (*RETURN_FIELDS, *FACTOR_FIELDS)
        }
        | {
            mode_score_field: _metric_summary(
                mode_eligible_frame,
                mode_score_field,
            )
        },
    }


def get_market_overview(
    mode: str = "balanced",
    sectors: Iterable[str] | str | None = None,
) -> dict[str, object]:
    """Summarize stored accepted-run market and sector evidence.

    Aggregates are equal-security cross-sectional descriptions. They are not a
    capitalization-weighted index return, live quote, forecast, or advice.
    """

    normalized_mode = _normalize_mode(mode)
    accepted = scoring_contract.load_accepted_scoring_run(PROJECT_ROOT)
    frame = accepted.scored_matrix
    required_columns = {
        "ticker",
        "sector",
        "eligible_for_scoring",
        "price_data_end",
        "fundamental_filed_date",
        *RETURN_FIELDS,
        *FACTOR_FIELDS,
        f"{normalized_mode}_score",
        f"{normalized_mode}_eligible_for_ranking",
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise OverviewDataError(
            "Accepted scored matrix is missing overview columns: "
            + ", ".join(missing_columns)
        )

    known_sectors = tuple(
        sorted({str(value) for value in frame["sector"].dropna()})
    )
    selected_sectors = _normalize_sectors(sectors, known_sectors)
    scoped = (
        frame.loc[frame["sector"].astype(str).isin(selected_sectors)]
        if selected_sectors
        else frame
    ).copy(deep=False)

    sector_summaries = [
        {
            "sector": sector,
            **_aggregate_scope(
                scoped.loc[scoped["sector"].astype(str).eq(sector)],
                normalized_mode,
            ),
        }
        for sector in sorted({str(value) for value in scoped["sector"].dropna()})
    ]
    contract_header = accepted.contract.get("scoring_contract", {})
    if not isinstance(contract_header, Mapping):
        contract_header = {}

    return {
        "service": "get_market_overview",
        "schema_version": SCHEMA_VERSION,
        "accepted_run_id": _scalar(accepted.metadata.get("run_id")),
        "scoring_contract_version": _scalar(contract_header.get("version")),
        "factor_model_version": _scalar(
            accepted.metadata.get("factor_model_version")
        ),
        "screening_modes_version": _scalar(
            accepted.metadata.get("screening_modes_version")
        ),
        "as_of_date": _scalar(accepted.metadata.get("as_of_date")),
        "mode": normalized_mode,
        "selected_sectors": list(selected_sectors),
        "available_sectors": list(known_sectors),
        "data_dates": {
            "price_data_end": _date_summary(scoped["price_data_end"]),
            "fundamental_filed_date": _date_summary(
                scoped["fundamental_filed_date"]
            ),
        },
        "market": _aggregate_scope(scoped, normalized_mode),
        "sector_count": len(sector_summaries),
        "sectors": sector_summaries,
        "methodology": {
            "source": "verified accepted scored matrix",
            "weighting": "equal-security cross-sectional aggregates",
            "mode_score_population": "mode-eligible securities only",
            "sector_order": "sector name ascending",
            "limitations": [
                "Latest accepted daily snapshot; not real-time market data.",
                "Return breadth covers securities with a stored finite return.",
                "Aggregates are not capitalization-weighted index returns.",
                "A higher Risk score means lower measured risk.",
            ],
        },
    }
