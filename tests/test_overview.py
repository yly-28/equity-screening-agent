from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from src import overview


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("overview attempted network access")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_network)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "sector": "Technology",
                "eligible_for_scoring": True,
                "balanced_eligible_for_ranking": True,
                "value_eligible_for_ranking": True,
                "price_data_end": "2026-07-10",
                "fundamental_filed_date": "2026-02-15",
                "return_1d": 0.02,
                "return_1m": 0.10,
                "return_3m": 0.20,
                "momentum_score": 90.0,
                "quality_score": 80.0,
                "valuation_score": 40.0,
                "risk_score": 60.0,
                "sector_strength_score": 75.0,
                "balanced_score": 70.0,
                "value_score": 55.0,
            },
            {
                "ticker": "BBB",
                "sector": "Technology",
                "eligible_for_scoring": True,
                "balanced_eligible_for_ranking": True,
                "value_eligible_for_ranking": False,
                "price_data_end": "2026-07-11",
                "fundamental_filed_date": None,
                "return_1d": -0.01,
                "return_1m": 0.00,
                "return_3m": None,
                "momentum_score": 50.0,
                "quality_score": 60.0,
                "valuation_score": None,
                "risk_score": 40.0,
                "sector_strength_score": 75.0,
                "balanced_score": 50.0,
                "value_score": 42.0,
            },
            {
                "ticker": "CCC",
                "sector": "Energy",
                "eligible_for_scoring": False,
                "balanced_eligible_for_ranking": False,
                "value_eligible_for_ranking": False,
                "price_data_end": None,
                "fundamental_filed_date": "2026-03-01",
                "return_1d": None,
                "return_1m": None,
                "return_3m": None,
                "momentum_score": None,
                "quality_score": None,
                "valuation_score": None,
                "risk_score": None,
                "sector_strength_score": None,
                "balanced_score": None,
                "value_score": None,
            },
        ]
    )


def _accepted(frame: pd.DataFrame | None = None):
    return SimpleNamespace(
        scored_matrix=_frame() if frame is None else frame,
        metadata={
            "run_id": "accepted_scores",
            "as_of_date": "2026-07-13",
            "factor_model_version": "1.0.0",
            "screening_modes_version": "1.0.0",
        },
        contract={"scoring_contract": {"version": "1.0.2"}},
    )


def test_overview_aggregates_accepted_values_with_dates_and_coverage(
    monkeypatch,
) -> None:
    calls = []

    def fake_loader(project_root):
        calls.append(project_root)
        return _accepted()

    monkeypatch.setattr(
        overview.scoring_contract,
        "load_accepted_scoring_run",
        fake_loader,
    )

    result = overview.get_market_overview()

    assert calls == [overview.PROJECT_ROOT]
    assert result["schema_version"] == "1.0.0"
    assert result["accepted_run_id"] == "accepted_scores"
    assert result["as_of_date"] == "2026-07-13"
    assert result["market"]["security_count"] == 3
    assert result["market"]["base_eligible_count"] == 2
    assert result["market"]["mode_eligible_count"] == 2

    one_day = result["market"]["metrics"]["return_1d"]
    assert one_day == {
        "available_count": 2,
        "missing_count": 1,
        "coverage_ratio": pytest.approx(2 / 3),
        "median": pytest.approx(0.005),
        "positive_count": 1,
        "negative_count": 1,
        "unchanged_count": 0,
        "positive_ratio": 0.5,
    }
    assert result["market"]["metrics"]["return_3m"]["median"] == 0.2
    assert result["market"]["metrics"]["valuation_score"]["missing_count"] == 2
    assert result["data_dates"]["price_data_end"] == {
        "available_count": 2,
        "missing_count": 1,
        "earliest": "2026-07-10",
        "latest": "2026-07-11",
        "distinct_dates": ["2026-07-10", "2026-07-11"],
    }
    assert [sector["sector"] for sector in result["sectors"]] == [
        "Energy",
        "Technology",
    ]
    assert result["methodology"]["weighting"] == (
        "equal-security cross-sectional aggregates"
    )
    json.dumps(result, allow_nan=False)


def test_sector_filter_is_canonical_and_value_eligibility_is_preserved(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        overview.scoring_contract,
        "load_accepted_scoring_run",
        lambda project_root: _accepted(),
    )

    result = overview.get_market_overview(
        mode=" VALUE ",
        sectors=[" technology ", "TECHNOLOGY"],
    )

    assert result["mode"] == "value"
    assert result["selected_sectors"] == ["Technology"]
    assert result["market"]["security_count"] == 2
    assert result["market"]["mode_eligible_count"] == 1
    assert result["market"]["metrics"]["value_score"] == {
        "available_count": 1,
        "missing_count": 0,
        "coverage_ratio": 1.0,
        "median": 55.0,
    }
    assert result["methodology"]["mode_score_population"] == (
        "mode-eligible securities only"
    )
    assert result["sector_count"] == 1
    assert result["sectors"][0]["sector"] == "Technology"


def test_overview_rejects_unknown_sector_after_verified_load(monkeypatch) -> None:
    monkeypatch.setattr(
        overview.scoring_contract,
        "load_accepted_scoring_run",
        lambda project_root: _accepted(),
    )

    with pytest.raises(overview.OverviewValidationError, match="Unknown sectors"):
        overview.get_market_overview(sectors=["Unknown Sector"])


def test_overview_validates_mode_before_loading(monkeypatch) -> None:
    monkeypatch.setattr(
        overview.scoring_contract,
        "load_accepted_scoring_run",
        lambda project_root: pytest.fail("accepted loader should not be called"),
    )

    with pytest.raises(overview.OverviewValidationError, match="Unsupported mode"):
        overview.get_market_overview(mode="aggressive")


def test_overview_fails_closed_on_missing_accepted_columns(monkeypatch) -> None:
    malformed = _frame().drop(columns=["return_1d"])
    monkeypatch.setattr(
        overview.scoring_contract,
        "load_accepted_scoring_run",
        lambda project_root: _accepted(malformed),
    )

    with pytest.raises(overview.OverviewDataError, match="return_1d"):
        overview.get_market_overview()
