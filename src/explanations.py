"""Deterministic structured explanations for stored screening evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional


FACTOR_FIELDS = (
    ("momentum", "Momentum"),
    ("quality", "Quality"),
    ("valuation", "Valuation"),
    ("risk", "Risk"),
    ("sector_strength", "Sector Strength"),
)


def _factor_summary(factor_name: str, label: str, high: bool) -> str:
    if factor_name == "risk":
        direction = "lower" if high else "higher"
        score_level = "higher" if high else "lower"
        return (
            f"The {score_level} Risk score indicates {direction} measured risk "
            "relative to the scoring comparison group."
        )
    score_level = "high" if high else "low"
    return f"{label} is a {score_level}-scoring factor in the accepted methodology."


def build_stock_explanations(
    factor_scores: Mapping[str, Optional[float]],
    missing_inputs: list[str],
    filed_date: object,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    """Build grounded strengths, risks, and next questions from stored evidence."""

    order = {name: index for index, (name, _) in enumerate(FACTOR_FIELDS)}
    labels = dict(FACTOR_FIELDS)
    available = [
        (name, score)
        for name, score in factor_scores.items()
        if score is not None
    ]
    high = sorted(
        ((name, score) for name, score in available if score >= 70.0),
        key=lambda item: (-item[1], order[item[0]]),
    )
    low = sorted(
        ((name, score) for name, score in available if score <= 30.0),
        key=lambda item: (item[1], order[item[0]]),
    )

    strengths = [
        {
            "code": f"high_factor_score:{factor_name}",
            "factor": labels[factor_name],
            "score": score,
            "summary": _factor_summary(
                factor_name, labels[factor_name], high=True
            ),
        }
        for factor_name, score in high[:3]
    ]
    risks = [
        {
            "code": f"low_factor_score:{factor_name}",
            "factor": labels[factor_name],
            "score": score,
            "summary": _factor_summary(
                factor_name, labels[factor_name], high=False
            ),
        }
        for factor_name, score in low[:3]
    ]
    for factor_name, label in FACTOR_FIELDS:
        if factor_scores[factor_name] is None and len(risks) < 3:
            risks.append(
                {
                    "code": f"missing_factor_score:{factor_name}",
                    "factor": label,
                    "score": None,
                    "summary": f"The {label} factor is unavailable.",
                }
            )

    questions: list[str] = []
    if missing_inputs:
        questions.append(
            "Can the missing inputs ("
            + ", ".join(missing_inputs[:5])
            + ") be verified from the latest filing or another approved source?"
        )
    if strengths:
        questions.append(
            "What underlying business and market drivers explain the current "
            f"{strengths[0]['factor']} score, and are they durable?"
        )
    if risks:
        questions.append(
            "Which underlying inputs are driving the "
            f"{risks[0]['factor']} research risk or evidence gap?"
        )
    if filed_date is not None:
        questions.append(
            "What material information has changed since the latest included "
            f"filing dated {filed_date}?"
        )
    if not questions:
        questions.append(
            "What could cause the selected-mode score to change on the next "
            "accepted data snapshot?"
        )
    if len(questions) < 2:
        questions.append(
            "How does the company compare with close industry peers beyond the "
            "stored factor scores?"
        )
    return strengths, risks, questions[:4]
