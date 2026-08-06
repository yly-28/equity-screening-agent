"""Concise deterministic research reports over accepted Stock Detail evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from numbers import Real

from src.stock_detail import get_stock_detail as get_stock_detail_service


SCHEMA_VERSION = "1.1.0"
ANALYSIS_EVIDENCE_SCHEMA_VERSION = "1.0.0"
MARKET_SNAPSHOT_FIELDS = (
    "price",
    "market_cap_proxy",
    "average_volume_20d",
)
MARKET_SIGNAL_FIELDS = (
    "return_1m",
    "return_3m",
    "return_6m",
    "relative_strength_3m",
    "volatility_20d",
    "volatility_60d",
    "max_drawdown_1y",
    "beta_1y",
)
FUNDAMENTAL_EVIDENCE_FIELDS = (
    "annual_revenue",
    "annual_net_income",
    "revenue_growth",
    "profit_margin",
    "roe",
    "annual_free_cash_flow",
    "free_cash_flow_margin",
    "liabilities_to_equity",
    "annual_pe_proxy",
)
FUNDAMENTAL_EVIDENCE_METADATA_FIELDS = (
    "source",
    "latest_period_end",
    "latest_filed_date",
    "fundamental_age_days",
)
DISCLAIMER = (
    "This output is generated for educational and research purposes only. "
    "It is not financial advice, investment advice, or a recommendation to "
    "buy or sell any security."
)


class ResearchReportDataError(RuntimeError):
    """Raised when Stock Detail cannot satisfy the report schema."""


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResearchReportDataError(f"Stock Detail {label} must be a mapping")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ResearchReportDataError(f"Stock Detail {label} must be a list")
    return list(value)


def _finite_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    score = float(value)
    return score if math.isfinite(score) else None


def _posture(
    selected_mode: Mapping[str, object],
    quality: Mapping[str, object],
) -> tuple[str, str, list[str]]:
    score = _finite_score(selected_mode.get("score"))
    ranking_eligible = selected_mode.get("eligible_for_ranking") is True
    scoring_eligible = quality.get("eligible_for_scoring") is True

    if score is None or not scoring_eligible or not ranking_eligible:
        reasons = [
            str(reason)
            for reason in _list(
                selected_mode.get("ranking_exclusion_reasons", []),
                "selected_mode.ranking_exclusion_reasons",
            )
        ]
        reasons.extend(
            str(reason)
            for reason in _list(
                quality.get("base_exclusion_reasons", []),
                "quality.base_exclusion_reasons",
            )
        )
        if score is None:
            reasons.append("selected_mode_score_unavailable")
        return (
            "insufficient_evidence",
            "Insufficient evidence",
            list(dict.fromkeys(reasons)) or ["not_eligible_for_selected_mode"],
        )
    if score >= 70.0:
        return (
            "strong",
            "Strong",
            ["eligible_for_ranking", "selected_mode_score_at_or_above_70"],
        )
    if score <= 30.0:
        return (
            "weak",
            "Weak",
            ["eligible_for_ranking", "selected_mode_score_at_or_below_30"],
        )
    return (
        "mixed",
        "Mixed",
        ["eligible_for_ranking", "selected_mode_score_between_30_and_70"],
    )


def _summary(
    ticker: str,
    mode: str,
    classification: str,
    score: float | None,
) -> str:
    mode_label = mode.replace("_", " ").title()
    if classification == "insufficient_evidence":
        return (
            f"{ticker} has insufficient accepted evidence for a {mode_label} "
            "research assessment; review its eligibility and missing inputs."
        )
    return (
        f"{ticker} shows {classification} fit with the accepted {mode_label} "
        f"screening evidence at a stored score of {score:.2f}."
    )


def _project_metric_rows(
    value: object,
    fields: Sequence[str],
    label: str,
) -> list[dict[str, object]]:
    if value is None:
        return []
    rows = _list(value, label)
    selected_fields = set(fields)
    rows_by_field: dict[str, dict[str, object]] = {}
    for index, row in enumerate(rows):
        normalized = _mapping(row, f"{label}[{index}]")
        field_name = normalized.get("field")
        if field_name not in selected_fields:
            continue
        if field_name in rows_by_field:
            raise ResearchReportDataError(
                f"Stock Detail {label} contains duplicate field {field_name}"
            )
        rows_by_field[str(field_name)] = deepcopy(dict(normalized))
    return [rows_by_field[field] for field in fields if field in rows_by_field]


def _analysis_evidence(detail: Mapping[str, object]) -> dict[str, object]:
    market_snapshot_value = detail.get("market_snapshot")
    market_snapshot: dict[str, object] = {}
    if market_snapshot_value is not None:
        source_market_snapshot = _mapping(
            market_snapshot_value,
            "market_snapshot",
        )
        market_snapshot = {
            field_name: deepcopy(
                source_market_snapshot[field_name]
            )
            for field_name in MARKET_SNAPSHOT_FIELDS
            if field_name in source_market_snapshot
        }
    market_signals = _project_metric_rows(
        detail.get("market_features"),
        MARKET_SIGNAL_FIELDS,
        "market_features",
    )

    fundamentals_value = detail.get("fundamentals")
    fundamentals: dict[str, object] = {}
    if fundamentals_value is not None:
        source_fundamentals = _mapping(fundamentals_value, "fundamentals")
        fundamentals = {
            field_name: deepcopy(source_fundamentals[field_name])
            for field_name in FUNDAMENTAL_EVIDENCE_METADATA_FIELDS
            if field_name in source_fundamentals
        }
        fundamentals["metrics"] = _project_metric_rows(
            source_fundamentals.get("metrics"),
            FUNDAMENTAL_EVIDENCE_FIELDS,
            "fundamentals.metrics",
        )

    return {
        "schema_version": ANALYSIS_EVIDENCE_SCHEMA_VERSION,
        "market_snapshot": market_snapshot,
        "market_signals": market_signals,
        "fundamentals": fundamentals,
    }


def get_research_report(
    ticker: str,
    mode: str = "balanced",
) -> dict[str, object]:
    """Build a concise report solely from ``get_stock_detail`` output.

    The posture describes fit with the selected screening mode. It is not a
    trading instruction, suitability assessment, or personalized conclusion.
    """

    detail = get_stock_detail_service(ticker=ticker, mode=mode)
    if not isinstance(detail, Mapping):
        raise ResearchReportDataError("Stock Detail result must be a mapping")

    identity = _mapping(detail.get("identity"), "identity")
    selected_mode = _mapping(detail.get("selected_mode"), "selected_mode")
    quality = _mapping(detail.get("quality"), "quality")
    factor_scores = _mapping(detail.get("factor_scores"), "factor_scores")
    data_dates = _mapping(detail.get("data_dates"), "data_dates")

    normalized_ticker = str(detail.get("ticker") or identity.get("ticker") or "")
    normalized_mode = str(detail.get("mode") or mode)
    score = _finite_score(selected_mode.get("score"))
    classification, label, basis_codes = _posture(selected_mode, quality)

    strengths = _list(detail.get("strengths", []), "strengths")[:3]
    risks = _list(detail.get("risks", []), "risks")[:3]
    questions = _list(
        detail.get("next_research_questions", []),
        "next_research_questions",
    )[:4]

    return {
        "service": "get_research_report",
        "schema_version": SCHEMA_VERSION,
        "accepted_run_id": detail.get("accepted_run_id"),
        "scoring_contract_version": detail.get("scoring_contract_version"),
        "factor_model_version": detail.get("factor_model_version"),
        "screening_modes_version": detail.get("screening_modes_version"),
        "as_of_date": detail.get("as_of_date"),
        "ticker": normalized_ticker,
        "mode": normalized_mode,
        "identity": deepcopy(dict(identity)),
        "research_posture": {
            "classification": classification,
            "label": label,
            "selected_mode_score": score,
            "eligible_for_ranking": (
                selected_mode.get("eligible_for_ranking") is True
            ),
            "basis_codes": basis_codes,
            "meaning": (
                "Fit with the selected screening mode using accepted evidence; "
                "not a buy, sell, hold, or suitability recommendation."
            ),
        },
        "summary": _summary(
            normalized_ticker,
            normalized_mode,
            classification,
            score,
        ),
        "analysis_evidence": _analysis_evidence(detail),
        "factor_scores": deepcopy(dict(factor_scores)),
        "strengths": deepcopy(strengths),
        "risks": deepcopy(risks),
        "quality": {
            "eligible_for_scoring": quality.get("eligible_for_scoring"),
            "missing_inputs": deepcopy(
                _list(quality.get("missing_inputs", []), "quality.missing_inputs")
            ),
            "warnings": deepcopy(
                _list(quality.get("warnings", []), "quality.warnings")
            ),
            "stale_fundamental_metrics": deepcopy(
                _list(
                    quality.get("stale_fundamental_metrics", []),
                    "quality.stale_fundamental_metrics",
                )
            ),
            "base_exclusion_reasons": deepcopy(
                _list(
                    quality.get("base_exclusion_reasons", []),
                    "quality.base_exclusion_reasons",
                )
            ),
        },
        "data_dates": deepcopy(dict(data_dates)),
        "next_research_questions": deepcopy(questions),
        "terminology": {
            "risk_score": "A higher Risk score means lower measured risk.",
            "market_cap_proxy": (
                "A proxy, not authoritative market capitalization."
            ),
            "average_volume_20d": "20-day average share volume.",
        },
        "disclaimer": DISCLAIMER,
    }
