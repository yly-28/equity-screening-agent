"""Documented Twelve Data daily-price provider."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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


EQUITY_TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,19}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_equity_ticker(value: object) -> str:
    if not isinstance(value, str):
        raise TwelveDataError("Ticker must be a string")
    ticker = value.strip().upper()
    if not EQUITY_TICKER_PATTERN.fullmatch(ticker):
        raise TwelveDataError(
            "Ticker must contain only letters, numbers, '.', or '-'"
        )
    return ticker


def _optional_text(payload: Mapping[str, Any], field_name: str) -> Optional[str]:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TwelveDataError(
            f"Twelve Data field {field_name} must be a string or null"
        )
    normalized = value.strip()
    return normalized or None


def _optional_number(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    minimum: Optional[float] = None,
) -> Optional[float]:
    value = payload.get(field_name)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TwelveDataError(
            f"Twelve Data field {field_name} must be numeric or null"
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TwelveDataError(
            f"Twelve Data field {field_name} must be numeric or null"
        ) from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise TwelveDataError(f"Twelve Data field {field_name} is invalid")
    return number


def _optional_integer(
    payload: Mapping[str, Any], field_name: str
) -> Optional[int]:
    number = _optional_number(payload, field_name, minimum=0.0)
    if number is None:
        return None
    if not number.is_integer():
        raise TwelveDataError(
            f"Twelve Data field {field_name} must be an integer or null"
        )
    return int(number)


def _validated_fetch_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise TwelveDataError("Twelve Data cache is missing fetched_at_utc")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TwelveDataError(
            "Twelve Data cache has an invalid fetched_at_utc"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TwelveDataError(
            "Twelve Data cache fetched_at_utc must include a timezone"
        )
    return value


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
            "fetched_at_utc": _utc_now(),
            "payload": payload,
        }
        path.write_text(json.dumps(wrapper), encoding="utf-8")

    def _endpoint_cache_path(self, endpoint: str, ticker: str) -> Path:
        return self.cache_dir / endpoint / f"{_safe_cache_name(ticker)}.json"

    def _read_endpoint_cache(
        self,
        endpoint: str,
        ticker: str,
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        path = self._endpoint_cache_path(endpoint, ticker)
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TwelveDataError(
                f"Invalid Twelve Data {endpoint} cache for {ticker}"
            ) from exc
        if not isinstance(wrapper, dict):
            raise TwelveDataError(
                f"Invalid Twelve Data {endpoint} cache for {ticker}"
            )
        if (
            wrapper.get("provider") != "twelve_data"
            or wrapper.get("endpoint") != endpoint
            or wrapper.get("ticker") != ticker
            or not isinstance(wrapper.get("payload"), dict)
        ):
            raise TwelveDataError(
                f"Invalid Twelve Data {endpoint} cache identity for {ticker}"
            )
        fetched_at = _validated_fetch_timestamp(wrapper.get("fetched_at_utc"))
        return dict(wrapper["payload"]), fetched_at

    def _write_endpoint_cache(
        self,
        endpoint: str,
        ticker: str,
        payload: Mapping[str, Any],
        fetched_at_utc: str,
    ) -> None:
        path = self._endpoint_cache_path(endpoint, ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        wrapper = {
            "provider": "twelve_data",
            "endpoint": endpoint,
            "ticker": ticker,
            "fetched_at_utc": fetched_at_utc,
            "payload": dict(payload),
        }
        path.write_text(json.dumps(wrapper), encoding="utf-8")

    def _provider_error_message(
        self,
        payload: Mapping[str, Any],
        endpoint: str,
        ticker: str,
    ) -> None:
        if payload.get("status") != "error" and not payload.get("code"):
            return
        detail = str(payload.get("message") or "provider request failed").strip()
        if self.api_key:
            detail = detail.replace(self.api_key, "[redacted]")
        raise TwelveDataError(
            f"Twelve Data {endpoint} failed for {ticker}: {detail[:300]}"
        )

    def _fetch_endpoint_payload(
        self,
        endpoint: str,
        ticker: str,
    ) -> Dict[str, Any]:
        api_key = self._require_key([ticker])
        params: Dict[str, object] = {"symbol": ticker}
        if api_key == "demo":
            params["apikey"] = api_key
        response = self.session.get(
            f"{TWELVE_DATA_BASE_URL}/{endpoint}",
            params=params,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise TwelveDataError(
                f"Twelve Data returned HTTP {response.status_code} "
                f"for {endpoint} {ticker}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TwelveDataError(
                f"Twelve Data returned non-JSON data for {endpoint} {ticker}"
            ) from exc
        if not isinstance(payload, dict):
            raise TwelveDataError(
                f"Twelve Data returned an invalid {endpoint} object for {ticker}"
            )
        self._provider_error_message(payload, endpoint, ticker)
        return payload

    def _normalize_quote(
        self,
        payload: Mapping[str, Any],
        ticker: str,
        fetched_at_utc: str,
    ) -> Dict[str, object]:
        provider_symbol = _optional_text(payload, "symbol")
        if provider_symbol is None:
            raise TwelveDataError("Twelve Data quote is missing symbol")
        if _normalize_equity_ticker(provider_symbol) != ticker:
            raise TwelveDataError(
                f"Twelve Data quote symbol does not match requested ticker {ticker}"
            )
        close = _optional_number(payload, "close", minimum=0.0)
        if close is None or close <= 0:
            raise TwelveDataError("Twelve Data quote is missing a positive close")
        is_market_open = payload.get("is_market_open")
        if is_market_open is not None and not isinstance(is_market_open, bool):
            raise TwelveDataError(
                "Twelve Data field is_market_open must be boolean or null"
            )
        return {
            "schema_version": "1.0.0",
            "source": "twelve_data_quote",
            "ticker": ticker,
            "company_name": _optional_text(payload, "name"),
            "exchange": _optional_text(payload, "exchange"),
            "mic_code": _optional_text(payload, "mic_code"),
            "currency": _optional_text(payload, "currency"),
            "provider_datetime": _optional_text(payload, "datetime"),
            "provider_timestamp": _optional_integer(payload, "timestamp"),
            "last_quote_at": _optional_integer(payload, "last_quote_at"),
            "price": close,
            "open": _optional_number(payload, "open", minimum=0.0),
            "high": _optional_number(payload, "high", minimum=0.0),
            "low": _optional_number(payload, "low", minimum=0.0),
            "close": close,
            "volume": _optional_number(payload, "volume", minimum=0.0),
            "previous_close": _optional_number(
                payload, "previous_close", minimum=0.0
            ),
            "change": _optional_number(payload, "change"),
            "percent_change": _optional_number(payload, "percent_change"),
            "average_volume": _optional_number(
                payload, "average_volume", minimum=0.0
            ),
            "is_market_open": is_market_open,
            "extended_price": _optional_number(
                payload, "extended_price", minimum=0.0
            ),
            "extended_timestamp": _optional_integer(
                payload, "extended_timestamp"
            ),
            "fetched_at_utc": fetched_at_utc,
            "scoring_use": "display_only_not_used_for_factor_scoring",
        }

    def _normalize_profile(
        self,
        payload: Mapping[str, Any],
        ticker: str,
        fetched_at_utc: str,
    ) -> Dict[str, object]:
        provider_symbol = _optional_text(payload, "symbol")
        if provider_symbol is None:
            raise TwelveDataError("Twelve Data profile is missing symbol")
        if _normalize_equity_ticker(provider_symbol) != ticker:
            raise TwelveDataError(
                f"Twelve Data profile symbol does not match requested ticker {ticker}"
            )
        company_name = _optional_text(payload, "name")
        if company_name is None:
            raise TwelveDataError("Twelve Data profile is missing company name")
        provider_sector = _optional_text(payload, "sector")
        provider_industry = _optional_text(payload, "industry")
        warnings: List[str] = []
        if provider_sector is None:
            warnings.append("provider_sector_missing")
        else:
            warnings.append("provider_sector_not_mapped_to_project_gics")
        if provider_industry is None:
            warnings.append("provider_industry_missing")
        else:
            warnings.append("provider_industry_not_mapped_to_project_gics")
        return {
            "schema_version": "1.0.0",
            "source": "twelve_data_profile",
            "ticker": ticker,
            "company_name": company_name,
            "exchange": _optional_text(payload, "exchange"),
            "mic_code": _optional_text(payload, "mic_code"),
            "issue_type": _optional_text(payload, "type"),
            "country": _optional_text(payload, "country"),
            "website": _optional_text(payload, "website"),
            "description": _optional_text(payload, "description"),
            "provider_sector": provider_sector,
            "provider_industry": provider_industry,
            "sector": None,
            "industry": None,
            "classification_status": "unmapped_provider_taxonomy",
            "warnings": warnings,
            "fetched_at_utc": fetched_at_utc,
        }

    def latest_quote(
        self,
        ticker: str,
        refresh: bool = False,
        cache_only: bool = False,
    ) -> Dict[str, object]:
        """Return a normalized latest quote that is never used for scoring."""

        symbol = _normalize_equity_ticker(ticker)
        if refresh and cache_only:
            raise TwelveDataError("refresh and cache_only are mutually exclusive")
        cached = None if refresh else self._read_endpoint_cache("quote", symbol)
        if cached is not None and not refresh:
            payload, fetched_at = cached
            self._provider_error_message(payload, "quote", symbol)
            return self._normalize_quote(payload, symbol, fetched_at)
        if cache_only or not refresh:
            raise TwelveDataError(
                f"Twelve Data quote cache not found for {symbol}; "
                "pass refresh=True to permit an online request"
            )
        payload = self._fetch_endpoint_payload("quote", symbol)
        fetched_at = _utc_now()
        result = self._normalize_quote(payload, symbol, fetched_at)
        self._write_endpoint_cache("quote", symbol, payload, fetched_at)
        return result

    def company_profile(
        self,
        ticker: str,
        refresh: bool = False,
        cache_only: bool = False,
    ) -> Dict[str, object]:
        """Return provider identity fields without guessing project GICS values."""

        symbol = _normalize_equity_ticker(ticker)
        if refresh and cache_only:
            raise TwelveDataError("refresh and cache_only are mutually exclusive")
        cached = None if refresh else self._read_endpoint_cache("profile", symbol)
        if cached is not None and not refresh:
            payload, fetched_at = cached
            self._provider_error_message(payload, "profile", symbol)
            return self._normalize_profile(payload, symbol, fetched_at)
        if cache_only or not refresh:
            raise TwelveDataError(
                f"Twelve Data profile cache not found for {symbol}; "
                "pass refresh=True to permit an online request"
            )
        payload = self._fetch_endpoint_payload("profile", symbol)
        fetched_at = _utc_now()
        result = self._normalize_profile(payload, symbol, fetched_at)
        self._write_endpoint_cache("profile", symbol, payload, fetched_at)
        return result

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
