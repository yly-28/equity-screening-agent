from __future__ import annotations

import json
import socket
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import src.screening as screening
from src.scoring_contract import AcceptedScoringRun
from src.screening import ScreeningValidationError, screen_stocks


MODE_NAMES = ("balanced", "growth", "value", "low_risk")
FACTOR_NAMES = ("momentum", "quality", "valuation", "risk", "sector_strength")


def _row(
    ticker: str,
    balanced_score: float,
    *,
    sector: str = "Technology",
    price: float = 50.0,
    market_cap_proxy: float = 10_000_000_000.0,
    average_volume_20d: float = 1_000_000.0,
    value_score: float | None = None,
    value_eligible: bool = True,
    eligible: bool = True,
) -> dict[str, object]:
    scores = {
        "momentum": 82.0 - balanced_score / 20.0,
        "quality": 72.0,
        "valuation": 55.0,
        "risk": 25.0 + balanced_score / 20.0,
        "sector_strength": 75.0 if sector == "Technology" else 45.0,
    }
    if not value_eligible and eligible:
        scores["valuation"] = np.nan
    if not eligible:
        scores = {factor: np.nan for factor in FACTOR_NAMES}

    row: dict[str, object] = {
        "ticker": ticker,
        "company_name": f"{ticker} Company",
        "sector": sector,
        "industry": f"{sector} Industry",
        "cik": f"{len(ticker):010d}",
        "as_of_date": "2026-07-13",
        "market_data_source": "twelve_data",
        "price_data_end": "2026-07-10",
        "fundamental_data_source": "sec_companyfacts",
        "fundamental_period_end": "2025-12-31",
        "fundamental_filed_date": "2026-02-15",
        "annual_revenue_period_end": "2025-12-31",
        "annual_net_income_period_end": "2025-12-31",
        "profit_margin_period_end": "2025-12-31",
        "roe_period_end": "2025-12-31",
        "leverage_period_end": "2025-12-31",
        "free_cash_flow_period_end": "2025-12-31",
        "shares_outstanding_period_end": "2026-01-31",
        "data_quality_flags": np.array(
            ["synthetic_quality_warning"] if ticker == "AAA" else [],
            dtype=object,
        ),
        "missing_fields": np.array(
            ["market_cap_proxy"] if pd.isna(market_cap_proxy) else [],
            dtype=object,
        ),
        "stale_fundamental_metrics": np.array([], dtype=object),
        "exclusion_reasons": np.array(
            ["synthetic_hard_exclusion"] if not eligible else [],
            dtype=object,
        ),
        "eligible_for_scoring": eligible,
        "market_error": None,
        "fundamental_error": None,
        "price": price,
        "market_cap_proxy": market_cap_proxy,
        "average_volume_20d": average_volume_20d,
        **{f"{name}_score": score for name, score in scores.items()},
    }

    for mode_name in MODE_NAMES:
        mode_score = {
            "balanced": balanced_score,
            "growth": balanced_score - 2.0,
            "value": value_score if value_score is not None else balanced_score - 4.0,
            "low_risk": balanced_score - 1.0,
        }[mode_name]
        mode_eligible = eligible and (mode_name != "value" or value_eligible)
        if not eligible:
            mode_score = np.nan
        reasons = (
            []
            if mode_eligible
            else (
                ["ineligible_for_scoring"]
                if not eligible
                else ["missing_required_factor:valuation"]
            )
        )
        available = [
            factor_name
            for factor_name in FACTOR_NAMES
            if pd.notna(scores[factor_name])
        ]
        weight = 1.0 / len(available) if available else 0.0
        weights = {factor_name: weight for factor_name in available}
        row.update(
            {
                f"{mode_name}_score": mode_score,
                f"{mode_name}_eligible_for_ranking": mode_eligible,
                f"{mode_name}_ranking_exclusion_reasons": np.array(
                    reasons, dtype=object
                ),
                f"{mode_name}_effective_factor_weights": json.dumps(weights),
                f"{mode_name}_available_factors": np.array(
                    available, dtype=object
                ),
            }
        )
    return row


def _screening_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(
                "AAA",
                88.125,
                price=100.0,
                market_cap_proxy=100_000_000_000.0,
                average_volume_20d=2_000_000.0,
                value_score=65.0,
            ),
            _row(
                "BBB",
                88.125,
                price=50.0,
                market_cap_proxy=50_000_000_000.0,
                average_volume_20d=1_000_000.0,
                value_score=70.0,
            ),
            _row(
                "CCC",
                72.5,
                sector="Financials",
                price=10.0,
                market_cap_proxy=1_000_000_000.0,
                average_volume_20d=100_000.0,
                value_score=75.0,
            ),
            _row(
                "NOVAL",
                68.0,
                price=30.0,
                market_cap_proxy=3_000_000_000.0,
                average_volume_20d=600_000.0,
                value_score=99.0,
                value_eligible=False,
            ),
            _row(
                "NOMCAP",
                64.0,
                price=40.0,
                market_cap_proxy=np.nan,
                average_volume_20d=700_000.0,
                value_score=60.0,
            ),
            _row(
                "LOWVOL",
                60.0,
                price=25.0,
                market_cap_proxy=2_000_000_000.0,
                average_volume_20d=10_000.0,
                value_score=55.0,
            ),
            _row("INEL", 0.0, eligible=False, value_eligible=False),
        ]
    )


def _accepted(frame: pd.DataFrame) -> AcceptedScoringRun:
    return AcceptedScoringRun(
        scored_matrix=frame,
        metadata={
            "run_id": "accepted_scores",
            "as_of_date": "2026-07-13",
            "factor_model_version": "1.0.0",
            "screening_modes_version": "1.0.0",
        },
        quality={},
        contract={"scoring_contract": {"version": "1.0.2"}},
        run_dir=Path("/synthetic/accepted_scores"),
    )


def _install_loader(monkeypatch, *frames: pd.DataFrame) -> list[Path]:
    calls: list[Path] = []
    call_index = 0

    def load(project_root: Path) -> AcceptedScoringRun:
        nonlocal call_index
        calls.append(project_root)
        frame = frames[min(call_index, len(frames) - 1)]
        call_index += 1
        return _accepted(frame)

    monkeypatch.setattr(
        screening.scoring_contract, "load_accepted_scoring_run", load
    )
    return calls


def _stock(result: dict[str, object], ticker: str) -> dict[str, object]:
    return next(
        stock
        for stock in result["stocks"]  # type: ignore[union-attr]
        if stock["ticker"] == ticker
    )


def _exclusion(result: dict[str, object], ticker: str) -> dict[str, object]:
    return next(
        exclusion
        for exclusion in result["exclusions"]  # type: ignore[union-attr]
        if exclusion["ticker"] == ticker
    )


def test_normal_ranking_returns_structured_stored_evidence(monkeypatch) -> None:
    frame = _screening_frame()
    calls = _install_loader(monkeypatch, frame)

    result = screen_stocks(top_n=3)

    assert [stock["ticker"] for stock in result["stocks"]] == ["AAA", "BBB", "CCC"]
    assert [stock["rank"] for stock in result["stocks"]] == [1, 2, 3]
    assert result["candidate_count"] == 7
    assert result["ranking_eligible_count"] == 6
    assert result["candidate_count_before_top_n"] == 6
    assert result["truncated_count"] == 3
    assert result["top_n_excluded_count"] == 3
    assert result["excluded_count"] == 4
    assert result["mode_ineligible_count"] == 1
    assert calls == [screening.PROJECT_ROOT]

    stock = result["stocks"][0]
    required_stock_fields = {
        "rank",
        "ticker",
        "company_name",
        "cik",
        "sector",
        "industry",
        "screening_mode",
        "mode_score",
        "factor_scores",
        "effective_factor_weights",
        "available_factors",
        "price",
        "market_cap_proxy",
        "average_volume_20d",
        "average_volume_20d_label",
        "data_sources",
        "data_dates",
        "missing_inputs",
        "warnings",
        "strengths",
        "risks",
        "reason_codes",
        "next_research_questions",
    }
    assert required_stock_fields <= set(stock)
    assert stock["mode_score"] == 88.125
    assert set(stock["factor_scores"]) == set(FACTOR_NAMES)
    assert sum(stock["effective_factor_weights"].values()) == pytest.approx(1.0)
    assert stock["screening_mode"] == "balanced"
    assert set(stock["data_dates"]) == set(screening.DATE_FIELDS)
    assert stock["data_dates"]["price_data_end"] == "2026-07-10"
    assert stock["missing_inputs"] == []
    assert stock["warnings"] == ["synthetic_quality_warning"]
    assert isinstance(stock["strengths"], list)
    assert isinstance(stock["risks"], list)
    assert "ranked_by_stored_score:balanced" in stock["reason_codes"]
    assert stock["next_research_questions"]


@pytest.mark.parametrize(
    ("kwargs", "expected_tickers", "reason_ticker", "expected_reason"),
    [
        (
            {"minimum_price": 60.0},
            ["AAA"],
            "BBB",
            "below_minimum:price",
        ),
        (
            {"minimum_market_cap_proxy": 60_000_000_000.0},
            ["AAA"],
            "NOMCAP",
            "missing_filter_value:market_cap_proxy",
        ),
        (
            {"minimum_average_volume_20d": 1_500_000.0},
            ["AAA"],
            "LOWVOL",
            "below_minimum:average_volume_20d",
        ),
    ],
)
def test_all_numeric_filters(
    monkeypatch,
    kwargs: dict[str, float],
    expected_tickers: list[str],
    reason_ticker: str,
    expected_reason: str,
) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(top_n=20, **kwargs)

    assert [stock["ticker"] for stock in result["stocks"]] == expected_tickers
    assert expected_reason in _exclusion(result, reason_ticker)["reasons"]


def test_sector_filtering_is_case_insensitive_and_canonical(monkeypatch) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(sectors=[" technology ", "TECHNOLOGY"], top_n=20)

    assert result["filters"]["sectors"] == ["Technology"]
    assert {stock["sector"] for stock in result["stocks"]} == {"Technology"}
    assert _exclusion(result, "CCC")["reasons"] == ["sector_not_selected"]


def test_value_mode_applies_stored_ranking_eligibility_before_score(monkeypatch) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(mode="value", top_n=20)

    assert "NOVAL" not in [stock["ticker"] for stock in result["stocks"]]
    exclusion = _exclusion(result, "NOVAL")
    assert exclusion["mode_score"] == 99.0
    assert exclusion["stage"] == "mode_eligibility"
    assert exclusion["reasons"] == ["missing_required_factor:valuation"]
    assert [stock["ticker"] for stock in result["stocks"]][:3] == [
        "CCC",
        "BBB",
        "AAA",
    ]


def test_equal_scores_use_ticker_ascending_tie_break(monkeypatch) -> None:
    frame = _screening_frame().sample(frac=1.0, random_state=7)
    _install_loader(monkeypatch, frame)

    result = screen_stocks(top_n=2)

    assert [(stock["rank"], stock["ticker"]) for stock in result["stocks"]] == [
        (1, "AAA"),
        (2, "BBB"),
    ]


@pytest.mark.parametrize(
    ("field_name", "minimum_argument"),
    [
        ("price", "minimum_price"),
        ("market_cap_proxy", "minimum_market_cap_proxy"),
        ("average_volume_20d", "minimum_average_volume_20d"),
    ],
)
def test_missing_active_filter_values_are_excluded_even_at_zero(
    monkeypatch,
    field_name: str,
    minimum_argument: str,
) -> None:
    frame = _screening_frame()
    index = frame.index[frame["ticker"].eq("AAA")][0]
    frame.at[index, field_name] = np.nan
    _install_loader(monkeypatch, frame)

    unfiltered = screen_stocks(top_n=20)
    filtered = screen_stocks(**{minimum_argument: 0.0}, top_n=20)

    assert "AAA" in [stock["ticker"] for stock in unfiltered["stocks"]]
    assert "AAA" not in [stock["ticker"] for stock in filtered["stocks"]]
    assert _exclusion(filtered, "AAA")["reasons"] == [
        f"missing_filter_value:{field_name}"
    ]


def test_mode_eligibility_precedes_and_short_circuits_filters(monkeypatch) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(mode="value", minimum_price=80.0, top_n=20)

    exclusion = _exclusion(result, "NOVAL")
    assert exclusion["stage"] == "mode_eligibility"
    assert exclusion["reasons"] == ["missing_required_factor:valuation"]
    assert "below_minimum:price" not in exclusion["reasons"]


def test_custom_tickers_are_stripped_uppercased_sorted_and_deduplicated(
    monkeypatch,
) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(
        universe=" CUSTOM ",
        custom_tickers=[" bbb ", "AAA", "aaa", ""],
        top_n=20,
    )

    assert result["requested_tickers"] == ["AAA", "BBB"]
    assert result["unknown_tickers"] == []
    assert [stock["ticker"] for stock in result["stocks"]] == ["AAA", "BBB"]


def test_unknown_custom_tickers_are_reported_separately(monkeypatch) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(
        universe="custom",
        custom_tickers=[" zzz ", "AAA", "missing"],
        top_n=20,
    )

    assert result["unknown_tickers"] == ["MISSING", "ZZZ"]
    assert result["unknown_ticker_count"] == 2
    assert result["candidate_count"] == 1
    assert [stock["ticker"] for stock in result["stocks"]] == ["AAA"]
    assert not any(
        exclusion["ticker"] in {"MISSING", "ZZZ"}
        for exclusion in result["exclusions"]
    )


@pytest.mark.parametrize(
    ("kwargs", "expected_message"),
    [
        ({"universe": "nasdaq100"}, "Unsupported universe"),
        (
            {"universe": "custom", "custom_tickers": []},
            "custom_tickers must contain at least one",
        ),
        ({"custom_tickers": ["AAA"]}, "custom_tickers may only be supplied"),
        (
            {"universe": "custom", "custom_tickers": "AAA"},
            "custom_tickers must be an iterable",
        ),
        ({"mode": "high_opportunity"}, "Unsupported mode"),
        ({"sectors": ["Unknown Sector"]}, "Unknown sectors"),
        ({"sectors": [""]}, "sectors must contain non-empty"),
        ({"minimum_price": -1.0}, "minimum_price"),
        ({"minimum_price": float("nan")}, "minimum_price"),
        ({"minimum_price": True}, "minimum_price"),
        ({"minimum_price": "5"}, "minimum_price"),
        (
            {"minimum_market_cap_proxy": float("inf")},
            "minimum_market_cap_proxy",
        ),
        (
            {"minimum_average_volume_20d": -1.0},
            "minimum_average_volume_20d",
        ),
        ({"top_n": 0}, "top_n"),
        ({"top_n": True}, "top_n"),
        ({"top_n": 1.5}, "top_n"),
    ],
)
def test_invalid_inputs_raise_clear_validation_errors(
    monkeypatch,
    kwargs,
    expected_message: str,
) -> None:
    _install_loader(monkeypatch, _screening_frame())

    with pytest.raises(ScreeningValidationError, match=expected_message):
        screen_stocks(**kwargs)


def test_ordering_uses_stored_mode_scores_not_factor_scores(monkeypatch) -> None:
    frame = _screening_frame()
    low_factor_index = frame.index[frame["ticker"].eq("LOWVOL")][0]
    high_factor_index = frame.index[frame["ticker"].eq("AAA")][0]
    frame.at[low_factor_index, "balanced_score"] = 99.75
    frame.at[high_factor_index, "balanced_score"] = 40.25
    for factor_name in FACTOR_NAMES:
        frame.at[low_factor_index, f"{factor_name}_score"] = 0.0
        frame.at[high_factor_index, f"{factor_name}_score"] = 100.0
    _install_loader(monkeypatch, frame)

    result = screen_stocks(minimum_price=20.0, top_n=2)

    assert [stock["ticker"] for stock in result["stocks"]] == ["LOWVOL", "BBB"]
    assert result["stocks"][0]["mode_score"] == 99.75


def test_top_n_omissions_have_explicit_reasons(monkeypatch) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(top_n=1)

    exclusion = _exclusion(result, "BBB")
    assert exclusion["stage"] == "top_n"
    assert exclusion["reasons"] == ["outside_top_n"]
    assert result["top_n_excluded_count"] == 5
    assert result["candidate_count"] == result["returned_count"] + result[
        "excluded_count"
    ]


def test_output_is_invariant_to_accepted_frame_row_order(monkeypatch) -> None:
    frame = _screening_frame()
    shuffled = frame.sample(frac=1.0, random_state=42).reset_index(drop=True)
    _install_loader(monkeypatch, frame, shuffled)

    baseline = screen_stocks(
        sectors=["Technology"],
        minimum_price=20.0,
        minimum_average_volume_20d=100_000.0,
        top_n=3,
    )
    reordered = screen_stocks(
        sectors=["Technology"],
        minimum_price=20.0,
        minimum_average_volume_20d=100_000.0,
        top_n=3,
    )

    assert baseline == reordered


def test_screening_has_no_network_or_direct_parquet_dependency(
    monkeypatch,
) -> None:
    calls = _install_loader(monkeypatch, _screening_frame())

    def fail(*args, **kwargs):
        raise AssertionError("screening attempted an external data read")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(pd, "read_parquet", fail)

    result = screen_stocks(top_n=1)

    assert result["stocks"][0]["ticker"] == "AAA"
    assert calls == [screening.PROJECT_ROOT]


def test_filtering_preserves_source_scores_weights_and_frame(monkeypatch) -> None:
    frame = _screening_frame()
    original = frame.copy(deep=True)
    _install_loader(monkeypatch, frame)

    baseline = screen_stocks(top_n=20)
    filtered = screen_stocks(sectors=["Technology"], minimum_price=60.0, top_n=20)

    baseline_aaa = _stock(baseline, "AAA")
    filtered_aaa = _stock(filtered, "AAA")
    source_aaa = frame.set_index("ticker").loc["AAA"]
    assert baseline_aaa["mode_score"] == filtered_aaa["mode_score"] == 88.125
    assert filtered_aaa["mode_score"] == source_aaa["balanced_score"]
    assert baseline_aaa["effective_factor_weights"] == (
        filtered_aaa["effective_factor_weights"]
    )
    assert filtered_aaa["effective_factor_weights"] == json.loads(
        source_aaa["balanced_effective_factor_weights"]
    )
    pd.testing.assert_frame_equal(frame, original)


def test_average_volume_is_labeled_as_share_volume(monkeypatch) -> None:
    _install_loader(monkeypatch, _screening_frame())

    result = screen_stocks(top_n=1)

    assert result["field_labels"]["average_volume_20d"] == (
        "20-day average share volume"
    )
    assert result["stocks"][0]["average_volume_20d_label"] == (
        "20-day average share volume"
    )
    assert "dollar" not in json.dumps(result).lower()
