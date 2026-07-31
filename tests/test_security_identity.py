from __future__ import annotations

import json

import pytest

import src.security_identity as security_identity
from src.security_identity import (
    SecTickerResolver,
    SecurityIdentityError,
    SecurityIdentityNotFoundError,
    parse_sec_company_tickers,
)


FETCHED_AT = "2026-07-31T03:04:05+00:00"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _exchange_payload():
    return {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        ],
    }


def test_resolver_fetches_normalizes_and_reuses_audited_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(security_identity, "_utc_now", lambda: FETCHED_AT)
    resolver = SecTickerResolver(
        tmp_path,
        user_agent="equity-screening-agent test@example.com",
    )
    calls = []

    def get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(_exchange_payload())

    resolver.session.get = get
    result = resolver.resolve(" msft ", refresh=True)

    assert calls == [
        (
            "https://www.sec.gov/files/company_tickers_exchange.json",
            45,
        )
    ]
    assert resolver.session.headers["User-Agent"] == (
        "equity-screening-agent test@example.com"
    )
    assert result == {
        "schema_version": "1.0.0",
        "source": "sec_company_tickers_exchange",
        "ticker": "MSFT",
        "company_name": "MICROSOFT CORP",
        "cik": "0000789019",
        "exchange": "Nasdaq",
        "sector": None,
        "industry": None,
        "classification_status": "classification_unavailable",
        "warnings": [
            "sector_classification_unavailable",
            "industry_classification_unavailable",
        ],
        "fetched_at_utc": FETCHED_AT,
    }
    wrapper = json.loads(resolver.cache_path.read_text(encoding="utf-8"))
    assert wrapper["provider"] == "sec"
    assert wrapper["fetched_at_utc"] == FETCHED_AT
    assert wrapper["payload"] == _exchange_payload()

    resolver.session.get = lambda *args, **kwargs: pytest.fail(
        "cache-first identity resolution must not use the network"
    )
    assert resolver.resolve("MSFT") == result


def test_resolver_refreshes_existing_cache(tmp_path, monkeypatch) -> None:
    timestamps = iter(
        ["2026-07-31T03:00:00+00:00", "2026-07-31T04:00:00+00:00"]
    )
    monkeypatch.setattr(security_identity, "_utc_now", lambda: next(timestamps))
    resolver = SecTickerResolver(tmp_path, user_agent="agent contact@example.com")
    payloads = iter(
        [
            _exchange_payload(),
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[789019, "Microsoft Corporation", "MSFT", "Nasdaq"]],
            },
        ]
    )
    resolver.session.get = lambda *args, **kwargs: FakeResponse(next(payloads))

    first = resolver.resolve("MSFT", refresh=True)
    refreshed = resolver.resolve("MSFT", refresh=True)

    assert first["company_name"] == "MICROSOFT CORP"
    assert refreshed["company_name"] == "Microsoft Corporation"
    assert refreshed["fetched_at_utc"] == "2026-07-31T04:00:00+00:00"


def test_basic_company_tickers_shape_is_supported_without_exchange() -> None:
    records = parse_sec_company_tickers(
        {
            "0": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT"},
            "1": {"cik_str": 320193, "ticker": "AAPL", "title": "APPLE"},
        }
    )

    assert records == [
        {
            "ticker": "MSFT",
            "company_name": "MICROSOFT",
            "cik": "0000789019",
            "exchange": None,
        },
        {
            "ticker": "AAPL",
            "company_name": "APPLE",
            "cik": "0000320193",
            "exchange": None,
        },
    ]


def test_unknown_and_ambiguous_tickers_fail_clearly(tmp_path) -> None:
    resolver = SecTickerResolver(tmp_path, user_agent="agent contact@example.com")
    resolver.session.get = lambda *args, **kwargs: FakeResponse(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [1, "First Company", "DUP", "NYSE"],
                [2, "Second Company", "DUP", "Nasdaq"],
            ],
        }
    )

    with pytest.raises(SecurityIdentityNotFoundError, match="UNKNOWN"):
        resolver.resolve("UNKNOWN", refresh=True)
    with pytest.raises(SecurityIdentityError, match="ambiguous"):
        resolver.resolve("DUP")


def test_missing_user_agent_and_cache_only_miss_never_access_network(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    resolver = SecTickerResolver(tmp_path)
    resolver.session.get = lambda *args, **kwargs: pytest.fail(
        "validation must execute before network access"
    )

    with pytest.raises(SecurityIdentityError, match="cache not found"):
        resolver.resolve("MSFT", cache_only=True)
    with pytest.raises(SecurityIdentityError, match="refresh=True"):
        resolver.resolve("MSFT")
    with pytest.raises(SecurityIdentityError, match="SEC_USER_AGENT"):
        resolver.resolve("MSFT", refresh=True)


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "non-empty object"),
        ({"fields": ["cik", "ticker"], "data": []}, "missing fields"),
        (
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [["not-a-cik", "Name", "TEST", "NYSE"]],
            },
            "invalid CIK",
        ),
    ],
)
def test_malformed_sec_payload_is_rejected_without_caching(
    tmp_path, payload, message
) -> None:
    resolver = SecTickerResolver(tmp_path, user_agent="agent contact@example.com")
    resolver.session.get = lambda *args, **kwargs: FakeResponse(payload)

    with pytest.raises(SecurityIdentityError, match=message):
        resolver.resolve("TEST", refresh=True)

    assert not resolver.cache_path.exists()


def test_explicit_refresh_can_replace_a_malformed_identity_cache(tmp_path) -> None:
    resolver = SecTickerResolver(tmp_path, user_agent="agent contact@example.com")
    resolver.cache_path.parent.mkdir(parents=True, exist_ok=True)
    resolver.cache_path.write_text("not-json", encoding="utf-8")
    resolver.session.get = lambda *args, **kwargs: FakeResponse(
        _exchange_payload()
    )

    result = resolver.resolve("MSFT", refresh=True)

    assert result["ticker"] == "MSFT"
    assert json.loads(resolver.cache_path.read_text(encoding="utf-8"))[
        "payload"
    ] == _exchange_payload()
