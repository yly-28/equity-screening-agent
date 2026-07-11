import math
from datetime import date

import pytest

from src.market_data import MarketDataError, NasdaqClient, parse_number


def test_parse_number_handles_nasdaq_display_values() -> None:
    assert parse_number("$1,234.50") == 1234.5
    assert parse_number("(25.00)") == -25.0
    assert parse_number("0.34%", percent_as_decimal=True) == pytest.approx(0.0034)
    assert math.isnan(parse_number("N/A"))


def test_nasdaq_network_requests_are_disabled(tmp_path) -> None:
    client = NasdaqClient(tmp_path)

    with pytest.raises(MarketDataError, match="disabled"):
        client.historical("AAPL", date(2025, 1, 1), date(2026, 1, 1))
