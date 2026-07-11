"""Legacy parser for cached Nasdaq feasibility responses.

New network requests are disabled because Nasdaq's website terms prohibit
automated data capture. Use :mod:`src.twelve_data` for current market data.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests

from src.http_client import build_session


NASDAQ_BASE_URL = "https://api.nasdaq.com/api"
NASDAQ_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


class MarketDataError(RuntimeError):
    """Raised when a market-data response is unavailable or malformed."""


def parse_number(value: object, percent_as_decimal: bool = False) -> float:
    """Parse Nasdaq display values such as ``$1,234.50`` or ``0.34%``."""

    if value is None:
        return float("nan")
    text = str(value).strip()
    if text in {"", "N/A", "NA", "--", "-"}:
        return float("nan")

    negative = text.startswith("(") and text.endswith(")")
    is_percent = text.endswith("%")
    cleaned = (
        text.replace("$", "")
        .replace(",", "")
        .replace("%", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )
    try:
        number = float(cleaned)
    except ValueError:
        return float("nan")
    if negative:
        number *= -1
    if is_percent and percent_as_decimal:
        number /= 100
    return number


def _safe_cache_name(ticker: str) -> str:
    return ticker.replace("/", "_").replace(".", "_")


@dataclass
class NasdaqClient:
    """Read cached Nasdaq responses from the initial feasibility experiment."""

    cache_dir: Path
    timeout: int = 30
    pause_seconds: float = 0.15
    allow_network: bool = False
    session: requests.Session = field(init=False)

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.session = build_session(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/126 Safari/537.36",
            NASDAQ_HEADERS,
        )

    def _get_json(
        self,
        endpoint: str,
        params: Dict[str, object],
        cache_path: Path,
        refresh: bool,
    ) -> Dict[str, Any]:
        if cache_path.exists() and not refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        if not self.allow_network:
            raise MarketDataError(
                "New Nasdaq website requests are disabled. Use TwelveDataClient."
            )

        url = f"{NASDAQ_BASE_URL}/{endpoint.lstrip('/')}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        time.sleep(self.pause_seconds)
        if response.status_code != 200:
            raise MarketDataError(
                f"Nasdaq returned HTTP {response.status_code} for {endpoint}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketDataError(f"Nasdaq returned non-JSON data for {endpoint}") from exc

        if payload.get("data") is None:
            status = payload.get("status") or {}
            messages = status.get("bCodeMessage") or []
            detail = "; ".join(
                str(message.get("errorMessage", message)) for message in messages
            )
            raise MarketDataError(detail or f"Nasdaq returned no data for {endpoint}")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def historical(
        self,
        ticker: str,
        start: date,
        end: date,
        asset_class: str = "stocks",
        refresh: bool = False,
    ) -> pd.DataFrame:
        """Return ascending daily OHLCV rows for a ticker."""

        cache_path = (
            self.cache_dir
            / "historical"
            / f"{_safe_cache_name(ticker)}_{start.isoformat()}_{end.isoformat()}.json"
        )
        payload = self._get_json(
            endpoint=f"quote/{ticker}/historical",
            params={
                "assetclass": asset_class,
                "fromdate": start.isoformat(),
                "todate": end.isoformat(),
                "limit": 5000,
            },
            cache_path=cache_path,
            refresh=refresh,
        )
        table = ((payload.get("data") or {}).get("tradesTable") or {})
        rows = table.get("rows") or []
        if not rows:
            raise MarketDataError(f"Nasdaq returned no historical rows for {ticker}")

        frame = pd.DataFrame(rows).rename(
            columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
        )
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(frame.columns)
        if missing:
            raise MarketDataError(
                f"Nasdaq historical schema changed for {ticker}: {sorted(missing)}"
            )

        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = frame[column].map(parse_number)
        frame = frame.dropna(subset=["date", "close"]).sort_values("date")
        frame["ticker"] = ticker
        frame["price_is_adjusted"] = False
        return frame.reset_index(drop=True)

    def summary(self, ticker: str, refresh: bool = False) -> Dict[str, object]:
        """Return normalized headline market and classification fields."""

        cache_path = self.cache_dir / "summary" / f"{_safe_cache_name(ticker)}.json"
        payload = self._get_json(
            endpoint=f"quote/{ticker}/summary",
            params={"assetclass": "stocks"},
            cache_path=cache_path,
            refresh=refresh,
        )
        data = payload.get("data") or {}
        summary = data.get("summaryData") or {}

        def value(key: str) -> Optional[str]:
            item = summary.get(key) or {}
            return item.get("value")

        return {
            "nasdaq_symbol": data.get("symbol"),
            "exchange": value("Exchange"),
            "nasdaq_sector": value("Sector"),
            "nasdaq_industry": value("Industry"),
            "market_cap": parse_number(value("MarketCap")),
            "average_volume_nasdaq": parse_number(value("AverageVolume")),
            "previous_close_nasdaq": parse_number(value("PreviousClose")),
        }
