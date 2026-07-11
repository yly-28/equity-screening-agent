from datetime import date

import pytest

from src.twelve_data import (
    TwelveDataApiKeyError,
    TwelveDataClient,
    parse_time_series_payload,
)


def test_parse_time_series_payload_normalizes_and_sorts_rows() -> None:
    payload = {
        "meta": {"symbol": "TEST", "interval": "1day"},
        "values": [
            {
                "datetime": "2026-01-03",
                "open": "11",
                "high": "12",
                "low": "10",
                "close": "11.5",
                "volume": "1100",
            },
            {
                "datetime": "2026-01-02",
                "open": "10",
                "high": "11",
                "low": "9",
                "close": "10.5",
                "volume": "1000",
            },
        ],
        "status": "ok",
    }

    frame = parse_time_series_payload(payload, "TEST")

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-02",
        "2026-01-03",
    ]
    assert frame["close"].tolist() == [10.5, 11.5]
    assert frame["price_is_adjusted"].all()
    assert frame["market_data_source"].eq("twelve_data").all()


def test_non_demo_symbol_requires_personal_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    client = TwelveDataClient(tmp_path)

    with pytest.raises(TwelveDataApiKeyError):
        client.historical("MSFT", date(2025, 1, 1), date(2026, 1, 1))
