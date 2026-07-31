from __future__ import annotations

import json

import pytest

import src.twelve_data as twelve_data
from src.twelve_data import TwelveDataApiKeyError, TwelveDataClient, TwelveDataError


FETCHED_AT = "2026-07-31T03:04:05+00:00"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _quote_payload(close="211.25"):
    return {
        "symbol": "MSFT",
        "name": "Microsoft Corporation",
        "exchange": "NASDAQ",
        "mic_code": "XNAS",
        "currency": "USD",
        "datetime": "2026-07-30 15:59:00",
        "timestamp": 1785441540,
        "last_quote_at": 1785441540,
        "open": "209.50",
        "high": "212.00",
        "low": "208.75",
        "close": close,
        "volume": "24000000",
        "previous_close": "209.10",
        "change": "2.15",
        "percent_change": "1.0282",
        "average_volume": "22000000",
        "is_market_open": False,
        "extended_price": None,
        "extended_timestamp": None,
    }


def _profile_payload():
    return {
        "symbol": "MSFT",
        "name": "Microsoft Corporation",
        "exchange": "NASDAQ",
        "mic_code": "XNAS",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "type": "Common Stock",
        "country": "US",
        "website": "https://www.microsoft.com",
        "description": "Develops software and cloud services.",
    }


def test_latest_quote_normalizes_audits_and_uses_cache_without_scoring(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(twelve_data, "_utc_now", lambda: FETCHED_AT)
    client = TwelveDataClient(tmp_path, api_key="test-key")
    calls = []

    def get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse(_quote_payload())

    client.session.get = get
    result = client.latest_quote(" msft ", refresh=True)

    assert calls == [
        (
            "https://api.twelvedata.com/quote",
            {"symbol": "MSFT"},
            45,
        )
    ]
    assert client.session.headers["Authorization"] == "apikey test-key"
    assert result == {
        "schema_version": "1.0.0",
        "source": "twelve_data_quote",
        "ticker": "MSFT",
        "company_name": "Microsoft Corporation",
        "exchange": "NASDAQ",
        "mic_code": "XNAS",
        "currency": "USD",
        "provider_datetime": "2026-07-30 15:59:00",
        "provider_timestamp": 1785441540,
        "last_quote_at": 1785441540,
        "price": 211.25,
        "open": 209.5,
        "high": 212.0,
        "low": 208.75,
        "close": 211.25,
        "volume": 24_000_000.0,
        "previous_close": 209.1,
        "change": 2.15,
        "percent_change": 1.0282,
        "average_volume": 22_000_000.0,
        "is_market_open": False,
        "extended_price": None,
        "extended_timestamp": None,
        "fetched_at_utc": FETCHED_AT,
        "scoring_use": "display_only_not_used_for_factor_scoring",
    }
    cache_path = tmp_path / "quote/MSFT.json"
    wrapper = json.loads(cache_path.read_text(encoding="utf-8"))
    assert wrapper["fetched_at_utc"] == FETCHED_AT
    assert wrapper["payload"] == _quote_payload()
    assert not (tmp_path / "historical").exists()

    client.session.get = lambda *args, **kwargs: pytest.fail(
        "cache-first quote must not use the network"
    )
    assert client.latest_quote("MSFT") == result


def test_latest_quote_refresh_replaces_cache(tmp_path, monkeypatch) -> None:
    timestamps = iter(
        ["2026-07-31T03:00:00+00:00", "2026-07-31T03:05:00+00:00"]
    )
    monkeypatch.setattr(twelve_data, "_utc_now", lambda: next(timestamps))
    client = TwelveDataClient(tmp_path, api_key="test-key")
    payloads = iter([_quote_payload("211.25"), _quote_payload("212.50")])
    client.session.get = lambda *args, **kwargs: FakeResponse(next(payloads))

    first = client.latest_quote("MSFT", refresh=True)
    second = client.latest_quote("MSFT", refresh=True)

    assert first["price"] == 211.25
    assert second["price"] == 212.5
    assert second["fetched_at_utc"] == "2026-07-31T03:05:00+00:00"


def test_company_profile_keeps_provider_taxonomy_raw_and_canonical_null(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(twelve_data, "_utc_now", lambda: FETCHED_AT)
    client = TwelveDataClient(tmp_path, api_key="test-key")
    client.session.get = lambda *args, **kwargs: FakeResponse(_profile_payload())

    result = client.company_profile("MSFT", refresh=True)

    assert result["provider_sector"] == "Technology"
    assert result["provider_industry"] == "Software - Infrastructure"
    assert result["sector"] is None
    assert result["industry"] is None
    assert result["classification_status"] == "unmapped_provider_taxonomy"
    assert result["warnings"] == [
        "provider_sector_not_mapped_to_project_gics",
        "provider_industry_not_mapped_to_project_gics",
    ]
    assert result["fetched_at_utc"] == FETCHED_AT


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"symbol": "OTHER", "close": "1"}, "does not match"),
        ({"symbol": "MSFT", "close": None}, "positive close"),
        ({"symbol": "MSFT", "close": "nan"}, "close is invalid"),
        (
            {"symbol": "MSFT", "close": "1", "is_market_open": "false"},
            "is_market_open",
        ),
    ],
)
def test_latest_quote_rejects_malformed_provider_payload_without_caching(
    tmp_path, monkeypatch, payload, message
) -> None:
    monkeypatch.setattr(twelve_data, "_utc_now", lambda: FETCHED_AT)
    client = TwelveDataClient(tmp_path, api_key="test-key")
    client.session.get = lambda *args, **kwargs: FakeResponse(payload)

    with pytest.raises(TwelveDataError, match=message):
        client.latest_quote("MSFT", refresh=True)

    assert not (tmp_path / "quote/MSFT.json").exists()


def test_provider_error_redacts_api_key(tmp_path) -> None:
    client = TwelveDataClient(tmp_path, api_key="highly-sensitive-key")
    client.session.get = lambda *args, **kwargs: FakeResponse(
        {
            "status": "error",
            "code": 401,
            "message": "invalid highly-sensitive-key",
        }
    )

    with pytest.raises(TwelveDataError) as captured:
        client.latest_quote("MSFT", refresh=True)

    assert "highly-sensitive-key" not in str(captured.value)
    assert "[redacted]" in str(captured.value)


def test_cache_only_miss_and_missing_api_key_never_request_network(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    client = TwelveDataClient(tmp_path)
    client.session.get = lambda *args, **kwargs: pytest.fail(
        "validation must execute before network access"
    )

    with pytest.raises(TwelveDataError, match="cache not found"):
        client.company_profile("MSFT", cache_only=True)
    with pytest.raises(TwelveDataError, match="refresh=True"):
        client.company_profile("MSFT")
    with pytest.raises(TwelveDataApiKeyError):
        client.company_profile("MSFT", refresh=True)


def test_explicit_refresh_can_replace_a_malformed_endpoint_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(twelve_data, "_utc_now", lambda: FETCHED_AT)
    cache_path = tmp_path / "quote/MSFT.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("not-json", encoding="utf-8")
    client = TwelveDataClient(tmp_path, api_key="test-key")
    client.session.get = lambda *args, **kwargs: FakeResponse(_quote_payload())

    result = client.latest_quote("MSFT", refresh=True)

    assert result["price"] == 211.25
    assert json.loads(cache_path.read_text(encoding="utf-8"))["payload"] == (
        _quote_payload()
    )
