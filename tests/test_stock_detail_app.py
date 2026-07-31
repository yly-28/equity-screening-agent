from __future__ import annotations

import socket
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from app import stock_screener
from src import ai_report, comparison, live_analysis, overview, scoring_contract
from src.research_report import DISCLAIMER


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app/stock_screener.py"


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("research workspace UI attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


def _report(ticker: str = "ZZZ") -> dict[str, object]:
    return {
        "service": "get_research_report",
        "schema_version": "1.0.0",
        "accepted_run_id": "accepted_scores",
        "scoring_contract_version": "1.0.2",
        "factor_model_version": "1.0.0",
        "screening_modes_version": "1.0.0",
        "as_of_date": "2026-07-13",
        "ticker": ticker,
        "mode": "balanced",
        "identity": {
            "ticker": ticker,
            "company_name": f"{ticker} Company",
            "cik": "0000000001",
            "sector": "Information Technology",
            "industry": "Systems Software",
            "sec_entity_name": None,
        },
        "research_posture": {
            "classification": "strong",
            "label": "Strong",
            "selected_mode_score": 81.25,
            "eligible_for_ranking": True,
            "basis_codes": ["eligible_for_ranking"],
            "meaning": (
                "Fit with the selected screening mode using accepted evidence; "
                "not a buy, sell, hold, or suitability recommendation."
            ),
        },
        "summary": "ZZZ has a strong fit with the accepted evidence.",
        "factor_scores": {
            "momentum": 90.0,
            "quality": 80.0,
            "valuation": None,
            "risk": 70.0,
            "sector_strength": 60.0,
        },
        "strengths": [
            {
                "code": "high_factor_score:momentum",
                "score": 90.0,
                "summary": "Momentum is strong in the accepted snapshot.",
            }
        ],
        "risks": [
            {
                "code": "missing_factor_score:valuation",
                "score": None,
                "summary": "Valuation evidence is unavailable.",
            }
        ],
        "quality": {
            "eligible_for_scoring": True,
            "missing_inputs": ["annual_pe_proxy"],
            "warnings": ["synthetic_warning"],
            "stale_fundamental_metrics": [],
            "base_exclusion_reasons": [],
        },
        "data_dates": {
            "as_of_date": "2026-07-13",
            "price_data_end": "2026-07-10",
            "fundamental_filed_date": None,
        },
        "next_research_questions": [
            "What changed after the accepted snapshot?"
        ],
        "terminology": {
            "risk_score": "A higher Risk score means lower measured risk.",
            "market_cap_proxy": "A proxy, not authoritative market capitalization.",
            "average_volume_20d": "20-day average share volume.",
        },
        "disclaimer": DISCLAIMER,
    }


def _accepted_analysis(*, quote: bool = True) -> dict[str, object]:
    report = _report()
    return {
        "service": "analyze_ticker",
        "schema_version": "1.0.0",
        "ticker": "ZZZ",
        "mode": "balanced",
        "data_scope": "accepted_snapshot",
        "analysis_status": "accepted_evidence",
        "accepted_run_id": "accepted_scores",
        "as_of_date": "2026-07-13",
        "identity": deepcopy(report["identity"]),
        "live_quote": (
            {
                "ticker": "ZZZ",
                "price": 125.5,
                "change": -1.25,
                "percent_change": -0.99,
                "provider_datetime": "2026-07-31 09:31:00",
                "fetched_at_utc": "2026-07-31T13:31:01+00:00",
                "scoring_use": "display_only_not_used_for_factor_scoring",
            }
            if quote
            else None
        ),
        "provider_profile": None,
        "scoring": {
            "available": True,
            "source": "accepted_scoring_run",
            "selected_mode_score": 81.25,
            "eligible_for_ranking": True,
            "rank": None,
            "unavailable_reasons": [],
        },
        "report": report,
        "provider_errors": {},
        "warnings": [],
        "limitations": ["live_quote_display_only_not_used_for_factor_scoring"],
        "disclaimer": DISCLAIMER,
    }


def _outside_analysis() -> dict[str, object]:
    result = _accepted_analysis()
    result.update(
        {
            "ticker": "OUT",
            "data_scope": "live_unscored",
            "analysis_status": "insufficient_evidence",
            "accepted_run_id": None,
            "as_of_date": None,
            "identity": {
                "ticker": "OUT",
                "company_name": "Outside Corporation",
                "cik": "0000000002",
                "sector": None,
                "industry": None,
            },
            "provider_profile": {
                "provider_sector": "Technology",
                "provider_industry": "Software",
                "sector": None,
                "industry": None,
            },
            "scoring": {
                "available": False,
                "source": None,
                "selected_mode_score": None,
                "eligible_for_ranking": False,
                "rank": None,
                "unavailable_reasons": ["ticker_not_in_accepted_scoring_run"],
            },
            "provider_errors": {"profile": "subscription tier unavailable"},
            "warnings": ["project_gics_sector_unavailable"],
        }
    )
    report = deepcopy(_report("OUT"))
    report.update(
        {
            "service": "live_research_report",
            "accepted_run_id": None,
            "as_of_date": None,
            "identity": deepcopy(result["identity"]),
            "summary": "OUT is outside the accepted scoring snapshot.",
            "factor_scores": {name: None for name in stock_screener.FACTOR_LABELS},
            "research_posture": {
                "classification": "insufficient_evidence",
                "label": "Insufficient evidence",
                "selected_mode_score": None,
                "eligible_for_ranking": False,
                "basis_codes": ["ticker_not_in_accepted_scoring_run"],
                "meaning": "Provider evidence only; no accepted score or rank.",
            },
            "quality": {
                "eligible_for_scoring": False,
                "missing_inputs": ["accepted_scoring_row"],
                "warnings": ["project_gics_sector_unavailable"],
                "stale_fundamental_metrics": [],
                "base_exclusion_reasons": ["ticker_not_in_accepted_scoring_run"],
            },
        }
    )
    result["report"] = report
    return result


def _app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=10).run()


def _submit_analysis(at: AppTest) -> AppTest:
    return at.button(key="run_analysis").click().run()


def _dataframe_with_column(at: AppTest, column: str):
    return next(
        element.value for element in at.dataframe if column in element.value.columns
    )


def test_default_navigation_is_ticker_analysis_and_calls_no_service(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        live_analysis,
        "analyze_ticker",
        lambda **kwargs: calls.append(kwargs),
    )

    at = _app()

    assert not at.exception
    assert at.radio(key="view").value == "Analyze Ticker"
    assert "run_analysis" in [button.key for button in at.button]
    assert calls == []


def test_analysis_controls_forward_raw_values_exactly_once(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_analysis(**kwargs):
        calls.append(kwargs)
        return _accepted_analysis(quote=False)

    monkeypatch.setattr(live_analysis, "analyze_ticker", fake_analysis)
    at = _app()
    at.text_input(key="analysis_ticker").set_value(" brk.b ").run()
    at.selectbox(key="analysis_mode").set_value("value").run()
    at.checkbox(key="analysis_refresh").check().run()
    at = _submit_analysis(at)

    assert not at.exception
    assert calls == [{"ticker": " brk.b ", "mode": "value", "refresh": True}]


def test_analysis_ui_uses_only_unified_service_boundary(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fail(*args, **kwargs):
        raise AssertionError("analysis UI bypassed its service")

    monkeypatch.setattr(scoring_contract, "load_accepted_scoring_run", fail)
    monkeypatch.setattr(pd, "read_parquet", fail)

    def fake_analysis(**kwargs):
        calls.append(kwargs)
        return _accepted_analysis()

    monkeypatch.setattr(live_analysis, "analyze_ticker", fake_analysis)
    at = _app()
    at.text_input(key="analysis_ticker").set_value("ZZZ").run()
    at = _submit_analysis(at)

    assert not at.exception
    assert calls == [{"ticker": "ZZZ", "mode": "balanced", "refresh": False}]


def test_accepted_analysis_renders_scores_nulls_quote_and_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        live_analysis, "analyze_ticker", lambda **kwargs: _accepted_analysis()
    )

    at = _submit_analysis(_app())

    assert not at.exception
    metrics = {item.label: item.value for item in at.metric}
    assert metrics["Evidence scope"] == "accepted_snapshot"
    assert metrics["Selected mode score"] == "81.25"
    assert metrics["Latest provider price"] == "$125.50"
    factors = _dataframe_with_column(at, "Factor")
    assert factors["Score"].iloc[[0, 1, 3, 4]].tolist() == [
        90.0,
        80.0,
        70.0,
        60.0,
    ]
    assert pd.isna(factors["Score"].iloc[2])
    markdown = "\n".join(str(item.value) for item in at.markdown)
    assert "Momentum is strong" in markdown
    assert "Valuation evidence is unavailable" in markdown
    captions = "\n".join(str(item.value) for item in at.caption)
    assert "display-only" in captions
    assert "higher Risk score means lower measured risk" in captions


def test_ai_renderer_is_explicit_and_receives_only_accepted_report(monkeypatch) -> None:
    source = _accepted_analysis()
    ai_calls: list[object] = []
    monkeypatch.setattr(live_analysis, "analyze_ticker", lambda **kwargs: source)

    def fake_ai(report):
        ai_calls.append(report)
        return {
            "renderer": {
                "status": "openai",
                "model": "gpt-5.6-terra",
                "fallback_reason": None,
            },
            "headline": "ZZZ — grounded report",
            "analysis": "ZZZ has a strong fit with the accepted evidence.",
        }

    monkeypatch.setattr(ai_report, "render_ai_research_report", fake_ai)
    at = _app()
    at.checkbox(key="analysis_use_ai").check().run()
    at = _submit_analysis(at)

    assert not at.exception
    assert ai_calls == [source["report"]]
    assert any("grounded report" in str(item.value) for item in at.markdown)
    assert sum(
        str(item.value) == source["report"]["summary"]
        for item in at.markdown
    ) == 1


def test_outside_ticker_is_unscored_and_skips_ai(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        live_analysis, "analyze_ticker", lambda **kwargs: _outside_analysis()
    )
    monkeypatch.setattr(
        ai_report,
        "render_ai_research_report",
        lambda report: calls.append(report),
    )
    at = _app()
    at.checkbox(key="analysis_use_ai").check().run()
    at = _submit_analysis(at)

    assert not at.exception
    assert calls == []
    metrics = {item.label: item.value for item in at.metric}
    assert metrics["Evidence scope"] == "live_unscored"
    assert metrics["Selected mode score"] == "Unavailable"
    warning_text = "\n".join(str(item.value) for item in at.warning)
    assert "outside the accepted scoring run" in warning_text
    caption_text = "\n".join(str(item.value) for item in at.caption)
    assert "Provider taxonomy" in caption_text


@pytest.mark.parametrize(
    "error",
    [
        live_analysis.LiveAnalysisValidationError("bad ticker"),
        live_analysis.LiveAnalysisNotFoundError("UNKNOWN is absent"),
        live_analysis.LiveAnalysisDataError("accepted evidence invalid"),
    ],
)
def test_analysis_errors_are_clear_without_traceback(monkeypatch, error) -> None:
    def fail(**kwargs):
        raise error

    monkeypatch.setattr(live_analysis, "analyze_ticker", fail)
    at = _submit_analysis(_app())

    assert not at.exception
    assert [item.value for item in at.error] == [f"Ticker analysis failed: {error}"]
    assert "Traceback" not in at.error[0].value


def _comparison_result() -> dict[str, object]:
    return {
        "service": "compare_stocks",
        "schema_version": "1.0.0",
        "accepted_run_id": "accepted_scores",
        "as_of_date": "2026-07-13",
        "mode": "value",
        "available_count": 1,
        "unknown_count": 1,
        "comparison_available": False,
        "unknown_tickers": ["MISS"],
        "items": [
            {
                "request_position": 1,
                "status": "available",
                "ticker": "ZZZ",
                "identity": {"company_name": "ZZZ Company"},
                "selected_mode": {"score": 10.0, "eligible_for_ranking": True},
                "factor_scores": {
                    "momentum": 20.0,
                    "quality": 30.0,
                    "valuation": 40.0,
                    "risk": 50.0,
                    "sector_strength": 60.0,
                },
                "market_snapshot": {"price": 100.0},
                "data_dates": {
                    "price_data_end": "2026-07-10",
                    "fundamental_filed_date": "2026-02-15",
                },
                "strengths": [{"summary": "First requested item."}],
                "risks": [],
            },
            {
                "request_position": 2,
                "status": "unknown",
                "ticker": "MISS",
                "reason_code": "ticker_not_in_accepted_snapshot",
            },
        ],
    }


def test_comparison_view_maps_inputs_and_preserves_requested_order(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_compare(**kwargs):
        calls.append(kwargs)
        return _comparison_result()

    monkeypatch.setattr(comparison, "compare_stocks", fake_compare)
    at = _app().radio(key="view").set_value("Compare Stocks").run()
    at.text_area(key="comparison_tickers").set_value(" zzz \nMISS").run()
    at.selectbox(key="comparison_mode").set_value("value").run()
    at = at.button(key="run_comparison").click().run()

    assert not at.exception
    assert calls == [{"tickers": [" zzz ", "MISS"], "mode": "value"}]
    table = _dataframe_with_column(at, "Position")
    assert table["Ticker"].tolist() == ["ZZZ", "MISS"]
    assert table["Selected mode score"].iloc[0] == 10.0
    assert pd.isna(table["Selected mode score"].iloc[1])
    assert pd.isna(table["Ranking eligible"].iloc[1])
    assert table["Market data date"].iloc[0] == "2026-07-10"
    assert pd.isna(table["Market data date"].iloc[1])
    assert any(
        "at least two available" in str(item.value) for item in at.info
    )


def _overview_result() -> dict[str, object]:
    metric = {
        "available_count": 2,
        "missing_count": 0,
        "coverage_ratio": 1.0,
        "median": 0.1,
        "positive_ratio": 0.5,
    }
    metrics = {
        name: deepcopy(metric)
        for name in (
            "return_1d",
            "return_1m",
            "return_3m",
            "momentum_score",
            "quality_score",
            "valuation_score",
            "risk_score",
            "sector_strength_score",
            "growth_score",
        )
    }
    return {
        "service": "get_market_overview",
        "schema_version": "1.0.0",
        "accepted_run_id": "accepted_scores",
        "as_of_date": "2026-07-13",
        "mode": "growth",
        "data_dates": {
            "price_data_end": {
                "available_count": 2,
                "missing_count": 0,
                "earliest": "2026-07-10",
                "latest": "2026-07-11",
                "distinct_dates": ["2026-07-10", "2026-07-11"],
            },
            "fundamental_filed_date": {
                "available_count": 1,
                "missing_count": 1,
                "earliest": "2026-02-15",
                "latest": "2026-02-15",
                "distinct_dates": ["2026-02-15"],
            },
        },
        "market": {
            "security_count": 2,
            "base_eligible_count": 2,
            "mode_eligible_count": 2,
            "metrics": metrics,
        },
        "sector_count": 1,
        "sectors": [
            {
                "sector": "Financials",
                "security_count": 2,
                "base_eligible_count": 2,
                "mode_eligible_count": 2,
                "metrics": deepcopy(metrics),
            }
        ],
    }


def test_overview_view_maps_scope_and_renders_equal_security_summary(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_overview(**kwargs):
        calls.append(kwargs)
        return _overview_result()

    monkeypatch.setattr(overview, "get_market_overview", fake_overview)
    at = _app().radio(key="view").set_value("Market / Sector").run()
    at.selectbox(key="overview_mode").set_value("growth").run()
    at.multiselect(key="overview_sectors").set_value(["Financials"]).run()
    at = at.button(key="run_overview").click().run()

    assert not at.exception
    assert calls == [{"mode": "growth", "sectors": ["Financials"]}]
    sector_table = _dataframe_with_column(at, "Sector")
    assert sector_table["Sector"].tolist() == ["Financials"]
    captions = "\n".join(str(item.value) for item in at.caption)
    assert "Equal-security" in captions
    assert "Market data through 2026-07-11 (2/2 securities)" in captions
    assert "fundamental filings through 2026-02-15 (1/2 securities)" in captions
