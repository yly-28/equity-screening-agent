from __future__ import annotations

import json

import pytest
import requests

from src import research_report


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("research report attempted network access")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_network)


def _detail(
    *,
    score: float | None = 82.5,
    eligible_for_scoring: bool = True,
    eligible_for_ranking: bool = True,
) -> dict[str, object]:
    return {
        "service": "get_stock_detail",
        "accepted_run_id": "accepted_scores",
        "scoring_contract_version": "1.0.2",
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
        "as_of_date": "2026-07-13",
        "ticker": "AAA",
        "mode": "balanced",
        "identity": {
            "ticker": "AAA",
            "company_name": "Alpha",
            "cik": "0000000001",
            "sector": "Technology",
            "industry": "Software",
            "sec_entity_name": None,
        },
        "selected_mode": {
            "score": score,
            "factor_count": 5 if score is not None else 0,
            "available_factors": ["momentum", "quality"],
            "effective_factor_weights": {"momentum": 0.5, "quality": 0.5},
            "unavailable_reason": None if score is not None else "no_factors",
            "eligible_for_ranking": eligible_for_ranking,
            "ranking_exclusion_reasons": (
                [] if eligible_for_ranking else ["missing_required_factor:valuation"]
            ),
        },
        "factor_scores": {
            "momentum": 90.0,
            "quality": 75.0,
            "valuation": None,
            "risk": 55.0,
            "sector_strength": 72.0,
        },
        "quality": {
            "eligible_for_scoring": eligible_for_scoring,
            "missing_inputs": ["annual_pe_proxy"],
            "warnings": ["synthetic_warning"],
            "stale_fundamental_metrics": [],
            "base_exclusion_reasons": (
                [] if eligible_for_scoring else ["market_data_error"]
            ),
        },
        "strengths": [
            {"code": f"strength:{index}", "summary": str(index), "score": 80.0}
            for index in range(5)
        ],
        "risks": [
            {"code": f"risk:{index}", "summary": str(index), "score": 20.0}
            for index in range(4)
        ],
        "data_dates": {
            "as_of_date": "2026-07-13",
            "price_data_end": "2026-07-10",
            "fundamental_period_end": "2025-12-31",
            "fundamental_filed_date": "2026-02-15",
        },
        "next_research_questions": [f"Question {index}?" for index in range(6)],
    }


def test_report_calls_only_stock_detail_and_returns_concise_versioned_schema(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []
    detail = _detail()

    def fake_detail(**kwargs):
        calls.append(kwargs)
        return detail

    monkeypatch.setattr(research_report, "get_stock_detail_service", fake_detail)

    result = research_report.get_research_report(" aaa ", mode="balanced")

    assert calls == [{"ticker": " aaa ", "mode": "balanced"}]
    assert result["service"] == "get_research_report"
    assert result["schema_version"] == "1.0.0"
    assert result["ticker"] == "AAA"
    assert result["research_posture"]["classification"] == "strong"
    assert result["research_posture"]["selected_mode_score"] == 82.5
    assert len(result["strengths"]) == 3
    assert len(result["risks"]) == 3
    assert len(result["next_research_questions"]) == 4
    assert result["factor_scores"]["valuation"] is None
    assert result["quality"]["missing_inputs"] == ["annual_pe_proxy"]
    assert "not financial advice" in result["disclaimer"]
    assert "not a buy, sell, hold" in result["research_posture"]["meaning"]
    json.dumps(result, allow_nan=False)

    assert detail["strengths"][3]["code"] == "strength:3"


@pytest.mark.parametrize(
    ("score", "eligible_for_scoring", "eligible_for_ranking", "expected"),
    [
        (70.0, True, True, "strong"),
        (69.99, True, True, "mixed"),
        (30.01, True, True, "mixed"),
        (30.0, True, True, "weak"),
        (99.0, True, False, "insufficient_evidence"),
        (20.0, False, False, "insufficient_evidence"),
        (None, False, False, "insufficient_evidence"),
    ],
)
def test_posture_is_deterministic_and_eligibility_aware(
    monkeypatch,
    score,
    eligible_for_scoring,
    eligible_for_ranking,
    expected,
) -> None:
    monkeypatch.setattr(
        research_report,
        "get_stock_detail_service",
        lambda **kwargs: _detail(
            score=score,
            eligible_for_scoring=eligible_for_scoring,
            eligible_for_ranking=eligible_for_ranking,
        ),
    )

    result = research_report.get_research_report("AAA")

    assert result["research_posture"]["classification"] == expected
    assert "recommendation to buy or sell" in result["disclaimer"]


def test_malformed_stock_detail_fails_without_fabricating_report(monkeypatch) -> None:
    monkeypatch.setattr(
        research_report,
        "get_stock_detail_service",
        lambda **kwargs: {"identity": None},
    )

    with pytest.raises(
        research_report.ResearchReportDataError,
        match="identity must be a mapping",
    ):
        research_report.get_research_report("AAA")
