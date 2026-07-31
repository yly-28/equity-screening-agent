from __future__ import annotations

import json
from copy import deepcopy

import pytest
import requests

from src.live_analysis import (
    LiveAnalysisDataError,
    LiveAnalysisNotFoundError,
    LiveAnalysisValidationError,
    analyze_ticker,
)
from src.security_identity import SecurityIdentityNotFoundError
from src.stock_detail import StockDetailNotFoundError
from src.twelve_data import TwelveDataError


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("live analysis attempted unmocked network access")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_network)


def _accepted_report(score: float | None = 81.25) -> dict[str, object]:
    return {
        "service": "get_research_report",
        "schema_version": "1.0.0",
        "accepted_run_id": "accepted_scores",
        "as_of_date": "2026-07-13",
        "ticker": "MSFT",
        "mode": "balanced",
        "identity": {
            "ticker": "MSFT",
            "company_name": "Microsoft Corporation",
            "cik": "0000789019",
            "sector": "Information Technology",
            "industry": "Systems Software",
            "sec_entity_name": None,
        },
        "research_posture": {
            "classification": "strong" if score is not None else "insufficient_evidence",
            "label": "Strong" if score is not None else "Insufficient evidence",
            "selected_mode_score": score,
            "eligible_for_ranking": score is not None,
            "basis_codes": (
                ["eligible_for_ranking"]
                if score is not None
                else ["selected_mode_score_unavailable"]
            ),
        },
        "factor_scores": {
            "momentum": 80.0,
            "quality": 75.0,
            "valuation": None,
            "risk": 60.0,
            "sector_strength": 70.0,
        },
        "summary": "Accepted evidence summary.",
        "strengths": [],
        "risks": [],
        "quality": {"eligible_for_scoring": True, "warnings": []},
        "data_dates": {"price_data_end": "2026-07-10"},
        "next_research_questions": [],
        "disclaimer": "Research only; not financial advice.",
    }


def _quote(ticker: str = "MSFT", price: float = 999.0) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source": "twelve_data_quote",
        "ticker": ticker,
        "price": price,
        "close": price,
        "provider_datetime": "2026-07-31 09:31:00",
        "fetched_at_utc": "2026-07-31T13:31:01+00:00",
        "is_market_open": True,
        "extended_price": None,
        "scoring_use": "display_only_not_used_for_factor_scoring",
    }


def _profile(ticker: str = "OUT") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source": "twelve_data_profile",
        "ticker": ticker,
        "company_name": "Outside Corporation",
        "exchange": "NASDAQ",
        "provider_sector": "Technology",
        "provider_industry": "Software",
        "sector": None,
        "industry": None,
        "classification_status": "unmapped_provider_taxonomy",
        "warnings": [
            "provider_sector_not_mapped_to_project_gics",
            "provider_industry_not_mapped_to_project_gics",
        ],
        "fetched_at_utc": "2026-07-31T13:30:00+00:00",
    }


def _identity(ticker: str = "OUT") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source": "sec_company_tickers_exchange",
        "ticker": ticker,
        "company_name": "OUTSIDE CORP",
        "cik": "0000000123",
        "exchange": "Nasdaq",
        "sector": None,
        "industry": None,
        "classification_status": "classification_unavailable",
        "warnings": [
            "sector_classification_unavailable",
            "industry_classification_unavailable",
        ],
        "fetched_at_utc": "2026-07-31T13:29:00+00:00",
    }


class FailMarketClient:
    def latest_quote(self, *args, **kwargs):
        raise AssertionError("market client must not be used")

    def company_profile(self, *args, **kwargs):
        raise AssertionError("profile client must not be used")


class FakeMarketClient:
    def __init__(self, quote=None, profile=None):
        self.quote_result = quote if quote is not None else _quote("OUT", 42.5)
        self.profile_result = profile if profile is not None else _profile()
        self.calls: list[tuple[str, str, bool, bool]] = []

    def latest_quote(self, ticker, refresh=False, cache_only=False):
        self.calls.append(("quote", ticker, refresh, cache_only))
        if isinstance(self.quote_result, BaseException):
            raise self.quote_result
        return deepcopy(self.quote_result)

    def company_profile(self, ticker, refresh=False, cache_only=False):
        self.calls.append(("profile", ticker, refresh, cache_only))
        if isinstance(self.profile_result, BaseException):
            raise self.profile_result
        return deepcopy(self.profile_result)


class FakeResolver:
    def __init__(self, result=None):
        self.result = result if result is not None else _identity()
        self.calls: list[tuple[str, bool, bool]] = []

    def resolve(self, ticker, refresh=False, cache_only=False):
        self.calls.append((ticker, refresh, cache_only))
        if isinstance(self.result, BaseException):
            raise self.result
        return deepcopy(self.result)


def _outside_loader(**kwargs):
    raise StockDetailNotFoundError("outside accepted snapshot")


def test_accepted_ticker_uses_deterministic_report_without_provider_access() -> None:
    calls = []
    report = _accepted_report()

    def loader(**kwargs):
        calls.append(kwargs)
        return report

    result = analyze_ticker(
        " msft ",
        mode=" BALANCED ",
        accepted_report_loader=loader,
        market_client=FailMarketClient(),
    )

    assert calls == [{"ticker": "MSFT", "mode": "balanced"}]
    assert result["data_scope"] == "accepted_snapshot"
    assert result["analysis_status"] == "accepted_evidence"
    assert result["accepted_run_id"] == "accepted_scores"
    assert result["live_quote"] is None
    assert result["provider_profile"] is None
    assert result["scoring"] == {
        "available": True,
        "source": "accepted_scoring_run",
        "selected_mode_score": 81.25,
        "eligible_for_ranking": True,
        "rank": None,
        "unavailable_reasons": [],
    }
    assert result["report"] == report
    assert result["report"] is not report
    json.dumps(result, allow_nan=False)


def test_accepted_refresh_adds_display_only_quote_without_changing_score() -> None:
    client = FakeMarketClient(quote=_quote("MSFT", 999_999.0))
    result = analyze_ticker(
        "MSFT",
        refresh=True,
        accepted_report_loader=lambda **kwargs: _accepted_report(),
        market_client=client,
    )

    assert client.calls == [("quote", "MSFT", True, False)]
    assert result["live_quote"]["price"] == 999_999.0
    assert result["live_quote"]["scoring_use"] == (
        "display_only_not_used_for_factor_scoring"
    )
    assert result["scoring"]["selected_mode_score"] == 81.25
    assert result["report"]["research_posture"]["selected_mode_score"] == 81.25
    assert result["provider_profile"] is None
    assert "refresh_does_not_rescore_or_rerank_accepted_evidence" in result[
        "limitations"
    ]


def test_accepted_refresh_quote_failure_preserves_accepted_evidence() -> None:
    client = FakeMarketClient(quote=RuntimeError("provider temporarily unavailable"))
    result = analyze_ticker(
        "MSFT",
        refresh=True,
        accepted_report_loader=lambda **kwargs: _accepted_report(),
        market_client=client,
    )

    assert result["analysis_status"] == "accepted_evidence"
    assert result["live_quote"] is None
    assert result["warnings"] == ["live_quote_unavailable"]
    assert result["provider_errors"]["quote"] == "RuntimeError: operation failed"
    assert "Traceback" not in result["provider_errors"]["quote"]


def test_provider_error_redacts_secrets_paths_newlines_and_traceback_text(
    monkeypatch,
    tmp_path,
) -> None:
    secret = "sk-sensitive-provider-token"
    monkeypatch.setenv("TWELVE_DATA_API_KEY", secret)
    client = FakeMarketClient(
        quote=TwelveDataError(
            f"apikey={secret}\nTraceback at {tmp_path}/private/cache.json"
        )
    )

    result = analyze_ticker(
        "MSFT",
        refresh=True,
        accepted_report_loader=lambda **kwargs: _accepted_report(),
        market_client=client,
    )
    message = result["provider_errors"]["quote"]

    assert secret not in message
    assert str(tmp_path) not in message
    assert "Traceback" not in message
    assert "\n" not in message
    assert "[redacted]" in message
    assert "[path]" in message


def test_outside_ticker_returns_live_identity_and_insufficient_evidence() -> None:
    resolver = FakeResolver()
    client = FakeMarketClient()
    result = analyze_ticker(
        " out ",
        mode="growth",
        refresh=True,
        identity_resolver=resolver,
        market_client=client,
        accepted_report_loader=_outside_loader,
    )

    assert resolver.calls == [("OUT", True, False)]
    assert client.calls == [
        ("quote", "OUT", True, False),
        ("profile", "OUT", True, False),
    ]
    assert result["data_scope"] == "live_unscored"
    assert result["analysis_status"] == "insufficient_evidence"
    assert result["accepted_run_id"] is None
    assert result["as_of_date"] is None
    assert result["identity"]["cik"] == "0000000123"
    assert result["identity"]["sector"] is None
    assert result["provider_profile"]["provider_sector"] == "Technology"
    assert result["provider_profile"]["sector"] is None
    assert result["live_quote"]["price"] == 42.5
    assert result["scoring"] == {
        "available": False,
        "source": None,
        "selected_mode_score": None,
        "eligible_for_ranking": False,
        "rank": None,
        "unavailable_reasons": [
            "ticker_not_in_accepted_scoring_run",
            "project_gics_sector_unavailable",
            "sector_relative_scoring_not_performed",
        ],
    }
    assert set(result["report"]["factor_scores"].values()) == {None}
    assert result["report"]["research_posture"]["classification"] == (
        "insufficient_evidence"
    )
    assert "no sector-relative factor score or rank" in result["report"][
        "summary"
    ]
    assert "not a buy, sell, hold" in result["report"]["research_posture"][
        "meaning"
    ]
    json.dumps(result, allow_nan=False)


def test_outside_provider_failures_return_partial_evidence_without_traceback() -> None:
    resolver = FakeResolver()
    client = FakeMarketClient(
        quote=RuntimeError("quote unavailable"),
        profile=RuntimeError("profile unavailable"),
    )
    result = analyze_ticker(
        "OUT",
        cache_only=True,
        identity_resolver=resolver,
        market_client=client,
        accepted_report_loader=_outside_loader,
    )

    assert resolver.calls == [("OUT", False, True)]
    assert client.calls == [
        ("quote", "OUT", False, True),
        ("profile", "OUT", False, True),
    ]
    assert result["identity"]["ticker"] == "OUT"
    assert result["live_quote"] is None
    assert result["provider_profile"] is None
    assert set(result["provider_errors"]) == {"quote", "profile"}
    assert all(
        "Traceback" not in message for message in result["provider_errors"].values()
    )
    assert "latest_quote_unavailable" in result["report"]["research_posture"][
        "basis_codes"
    ]
    assert "company_profile_unavailable" in result["report"][
        "research_posture"
    ]["basis_codes"]


def test_outside_default_is_cache_only_and_never_implicitly_refreshes() -> None:
    resolver = FakeResolver()
    client = FakeMarketClient()

    result = analyze_ticker(
        "OUT",
        identity_resolver=resolver,
        market_client=client,
        accepted_report_loader=_outside_loader,
    )

    assert resolver.calls == [("OUT", False, True)]
    assert client.calls == [
        ("quote", "OUT", False, True),
        ("profile", "OUT", False, True),
    ]
    assert result["live_quote"]["price"] == 42.5


def test_outside_identity_cache_miss_requests_explicit_online_refresh() -> None:
    resolver = FakeResolver(result=RuntimeError("SEC ticker mapping cache not found"))

    with pytest.raises(
        LiveAnalysisDataError,
        match="online_refresh_required: cached SEC identity",
    ):
        analyze_ticker(
            "OUT",
            identity_resolver=resolver,
            market_client=FailMarketClient(),
            accepted_report_loader=_outside_loader,
        )

    assert resolver.calls == [("OUT", False, True)]


def test_unverified_profile_gics_is_rejected_not_promoted() -> None:
    invalid_profile = _profile()
    invalid_profile["sector"] = "Information Technology"
    client = FakeMarketClient(profile=invalid_profile)

    result = analyze_ticker(
        "OUT",
        identity_resolver=FakeResolver(),
        market_client=client,
        accepted_report_loader=_outside_loader,
    )

    assert result["provider_profile"] is None
    assert "profile" in result["provider_errors"]
    assert result["scoring"]["available"] is False


def test_unknown_sec_ticker_raises_clear_not_found_without_provider_calls() -> None:
    resolver = FakeResolver(
        result=SecurityIdentityNotFoundError("not in SEC mapping")
    )

    with pytest.raises(
        LiveAnalysisNotFoundError,
        match="absent from both accepted and SEC identity data",
    ):
        analyze_ticker(
            "MISS",
            identity_resolver=resolver,
            market_client=FailMarketClient(),
            accepted_report_loader=_outside_loader,
        )


@pytest.mark.parametrize(
    ("ticker", "mode", "refresh", "cache_only", "message"),
    [
        ("", "balanced", False, False, "ticker"),
        ("../BAD", "balanced", False, False, "ticker"),
        ("MSFT", "prediction", False, False, "Unsupported mode"),
        ("MSFT", "balanced", "yes", False, "must be boolean"),
        ("MSFT", "balanced", True, True, "mutually exclusive"),
    ],
)
def test_validation_fails_before_any_loader_or_provider_call(
    ticker, mode, refresh, cache_only, message
) -> None:
    def fail_loader(**kwargs):
        raise AssertionError("invalid input reached accepted loader")

    with pytest.raises(LiveAnalysisValidationError, match=message):
        analyze_ticker(
            ticker,
            mode=mode,
            refresh=refresh,
            cache_only=cache_only,
            market_client=FailMarketClient(),
            identity_resolver=FakeResolver(),
            accepted_report_loader=fail_loader,
        )


def test_malformed_accepted_report_fails_closed() -> None:
    with pytest.raises(
        LiveAnalysisDataError,
        match="accepted report ticker does not match",
    ):
        analyze_ticker(
            "MSFT",
            accepted_report_loader=lambda **kwargs: {
                **_accepted_report(),
                "ticker": "OTHER",
            },
            market_client=FailMarketClient(),
        )
