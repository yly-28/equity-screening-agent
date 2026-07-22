"""Documented Twelve Data daily-price provider."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv

from src.http_client import build_session


TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class TwelveDataError(RuntimeError):
    """Raised when Twelve Data cannot return a valid time series."""


class TwelveDataApiKeyError(TwelveDataError):
    """Raised when a non-demo request is attempted without an API key."""


def _safe_cache_name(ticker: str) -> str:
    return ticker.replace("/", "_").replace(".", "_")


def parse_time_series_payload(payload: Dict[str, Any], ticker: str) -> pd.DataFrame:
    """Normalize one Twelve Data `/time_series` payload to project OHLCV fields."""

    if payload.get("status") == "error" or payload.get("code"):
        raise TwelveDataError(str(payload.get("message") or payload))
    values = payload.get("values") or []
    if not values:
        raise TwelveDataError(f"Twelve Data returned no daily rows for {ticker}")

    frame = pd.DataFrame(values).rename(columns={"datetime": "date"})
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise TwelveDataError(
            f"Twelve Data schema changed for {ticker}: missing {sorted(missing)}"
        )

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    frame["ticker"] = ticker
    frame["price_is_adjusted"] = True
    frame["market_data_source"] = "twelve_data"
    return frame.reset_index(drop=True)


@dataclass
class TwelveDataClient:
    """Fetch adjusted daily OHLCV with local JSON caching."""

    cache_dir: Path
    api_key: Optional[str] = None
    timeout: int = 45
    session: requests.Session = field(init=False)

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.api_key = self.api_key or os.getenv("TWELVE_DATA_API_KEY")
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"apikey {self.api_key}"
        self.session = build_session(
            "equity-screening-agent/0.1 academic-data-validation",
            headers,
        )

    def _cache_path(
        self,
        ticker: str,
        start: date,
        end: date,
        adjustment: str,
    ) -> Path:
        return (
            self.cache_dir
            / "historical"
            / (
                f"{_safe_cache_name(ticker)}_{start.isoformat()}_"
                f"{end.isoformat()}_{adjustment}.json"
            )
        )

    def _read_cached_payload(
        self,
        ticker: str,
        start: date,
        end: date,
        adjustment: str,
    ) -> Optional[Dict[str, Any]]:
        path = self._cache_path(ticker, start, end, adjustment)
        if not path.exists():
            return None
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        return wrapper.get("payload", wrapper)

    def is_cached(
        self,
        ticker: str,
        start: date,
        end: date,
        adjustment: str = "all",
    ) -> bool:
        """Return whether a usable cache file exists for this exact request."""

        return self._cache_path(ticker, start, end, adjustment).exists()

    def historical_cached(
        self,
        ticker: str,
        start: date,
        end: date,
        adjustment: str = "all",
    ) -> pd.DataFrame:
        """Read one exact request from cache without a network fallback."""

        payload = self._read_cached_payload(ticker, start, end, adjustment)
        if payload is None:
            raise TwelveDataError(
                f"Exact-date market cache not found for {ticker}: {start} to {end}"
            )
        return parse_time_series_payload(payload, ticker)

    def _write_cached_payload(
        self,
        ticker: str,
        start: date,
        end: date,
        adjustment: str,
        payload: Dict[str, Any],
    ) -> None:
        path = self._cache_path(ticker, start, end, adjustment)
        path.parent.mkdir(parents=True, exist_ok=True)
        wrapper = {
            "provider": "twelve_data",
            "ticker": ticker,
            "adjustment": adjustment,
            "fetched_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "payload": payload,
        }
        path.write_text(json.dumps(wrapper), encoding="utf-8")

    def _require_key(self, tickers: Sequence[str]) -> str:
        if self.api_key:
            return self.api_key
        if list(tickers) == ["AAPL"]:
            return "demo"
        raise TwelveDataApiKeyError(
            "TWELVE_DATA_API_KEY is required for non-demo symbols. "
            "Create a personal key and export it before the full-universe run."
        )

    def historical(
        self,
        ticker: str,
        start: date,
        end: date,
        adjustment: str = "all",
        refresh: bool = False,
    ) -> pd.DataFrame:
        """Return one ticker's ascending adjusted daily OHLCV data."""

        cached = self._read_cached_payload(ticker, start, end, adjustment)
        if cached is not None and not refresh:
            return parse_time_series_payload(cached, ticker)

        api_key = self._require_key([ticker])
        params: Dict[str, object] = {
            "symbol": ticker,
            "interval": "1day",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "outputsize": 5000,
            "adjust": adjustment,
        }
        if api_key == "demo":
            params["apikey"] = api_key
        response = self.session.get(
            f"{TWELVE_DATA_BASE_URL}/time_series",
            params=params,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise TwelveDataError(
                f"Twelve Data returned HTTP {response.status_code} for {ticker}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TwelveDataError("Twelve Data returned non-JSON data") from exc
        frame = parse_time_series_payload(payload, ticker)
        self._write_cached_payload(ticker, start, end, adjustment, payload)
        return frame

    def historical_batch(
        self,
        tickers: Sequence[str],
        start: date,
        end: date,
        adjustment: str = "all",
        refresh: bool = False,
    ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str]]:
        """Fetch a documented batch request and cache each symbol separately."""

        requested = list(dict.fromkeys(str(ticker) for ticker in tickers))
        frames: Dict[str, pd.DataFrame] = {}
        errors: Dict[str, str] = {}
        missing: List[str] = []
        for ticker in requested:
            cached = self._read_cached_payload(ticker, start, end, adjustment)
            if cached is not None and not refresh:
                try:
                    frames[ticker] = parse_time_series_payload(cached, ticker)
                except TwelveDataError as exc:
                    errors[ticker] = str(exc)
            else:
                missing.append(ticker)

        if not missing:
            return frames, errors
        if len(missing) == 1:
            ticker = missing[0]
            try:
                frames[ticker] = self.historical(
                    ticker, start, end, adjustment=adjustment, refresh=True
                )
            except TwelveDataError as exc:
                errors[ticker] = str(exc)
            return frames, errors

        self._require_key(missing)
        response = self.session.get(
            f"{TWELVE_DATA_BASE_URL}/time_series",
            params={
                "symbol": ",".join(missing),
                "interval": "1day",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "outputsize": 5000,
                "adjust": adjustment,
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise TwelveDataError(
                f"Twelve Data returned HTTP {response.status_code} for batch request"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TwelveDataError("Twelve Data returned non-JSON batch data") from exc
        if payload.get("status") == "error" or payload.get("code"):
            raise TwelveDataError(str(payload.get("message") or payload))

        for ticker in missing:
            ticker_payload = payload.get(ticker)
            if ticker_payload is None:
                errors[ticker] = "Ticker missing from Twelve Data batch response"
                continue
            try:
                frames[ticker] = parse_time_series_payload(ticker_payload, ticker)
                self._write_cached_payload(
                    ticker, start, end, adjustment, ticker_payload
                )
            except TwelveDataError as exc:
                errors[ticker] = str(exc)
        return frames, errors
