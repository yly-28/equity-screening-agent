"""SEC-backed ticker identity resolution without sector-classification guesses."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import requests
from dotenv import load_dotenv

from src.http_client import build_session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEC_COMPANY_TICKERS_URL = (
    "https://www.sec.gov/files/company_tickers_exchange.json"
)
SEC_CACHE_FILE = "company_tickers_exchange.json"
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,19}$")
load_dotenv(PROJECT_ROOT / ".env")


class SecurityIdentityError(RuntimeError):
    """Raised when the SEC identity dataset cannot be loaded or normalized."""


class SecurityIdentityNotFoundError(LookupError):
    """Raised when a ticker is absent from the SEC association dataset."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_ticker(value: object) -> str:
    if not isinstance(value, str):
        raise SecurityIdentityError("Ticker must be a string")
    ticker = value.strip().upper()
    if not TICKER_PATTERN.fullmatch(ticker):
        raise SecurityIdentityError(
            "Ticker must contain only letters, numbers, '.', or '-'"
        )
    return ticker


def _normalize_cik(value: object) -> str:
    if isinstance(value, bool):
        raise SecurityIdentityError("SEC ticker mapping contains an invalid CIK")
    text = str(value).strip()
    if not text.isdigit() or len(text) > 10 or int(text) <= 0:
        raise SecurityIdentityError("SEC ticker mapping contains an invalid CIK")
    return text.zfill(10)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SecurityIdentityError(
            f"SEC ticker mapping contains an invalid {field_name}"
        )
    return value.strip()


def _optional_text(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SecurityIdentityError(
            f"SEC ticker mapping contains an invalid {field_name}"
        )
    return value.strip() or None


def _validated_fetch_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise SecurityIdentityError("SEC ticker cache is missing fetched_at_utc")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SecurityIdentityError(
            "SEC ticker cache has an invalid fetched_at_utc"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SecurityIdentityError(
            "SEC ticker cache fetched_at_utc must include a timezone"
        )
    return value


def _parse_exchange_payload(payload: Mapping[str, Any]) -> List[Dict[str, object]]:
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or any(
        not isinstance(field_name, str) for field_name in fields
    ):
        raise SecurityIdentityError("SEC ticker mapping fields are invalid")
    if not isinstance(data, list):
        raise SecurityIdentityError("SEC ticker mapping data must be a list")
    required = {"cik", "name", "ticker"}
    missing = required - set(fields)
    if missing:
        raise SecurityIdentityError(
            "SEC ticker mapping is missing fields: " + ", ".join(sorted(missing))
        )
    records: List[Dict[str, object]] = []
    for row in data:
        if not isinstance(row, list) or len(row) != len(fields):
            raise SecurityIdentityError("SEC ticker mapping contains a malformed row")
        record = dict(zip(fields, row))
        records.append(
            {
                "ticker": _normalize_ticker(record["ticker"]),
                "company_name": _required_text(record["name"], "company name"),
                "cik": _normalize_cik(record["cik"]),
                "exchange": _optional_text(record.get("exchange"), "exchange"),
            }
        )
    return records


def _parse_basic_payload(payload: Mapping[str, Any]) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    for entry in payload.values():
        if not isinstance(entry, Mapping):
            raise SecurityIdentityError("SEC ticker mapping contains a malformed row")
        missing = {"cik_str", "ticker", "title"} - set(entry)
        if missing:
            raise SecurityIdentityError(
                "SEC ticker mapping row is missing fields: "
                + ", ".join(sorted(missing))
            )
        records.append(
            {
                "ticker": _normalize_ticker(entry["ticker"]),
                "company_name": _required_text(entry["title"], "company name"),
                "cik": _normalize_cik(entry["cik_str"]),
                "exchange": None,
            }
        )
    return records


def parse_sec_company_tickers(
    payload: Mapping[str, Any],
) -> List[Dict[str, object]]:
    """Normalize either official SEC company-ticker association JSON shape."""

    if not isinstance(payload, Mapping) or not payload:
        raise SecurityIdentityError("SEC ticker mapping must be a non-empty object")
    if "fields" in payload or "data" in payload:
        records = _parse_exchange_payload(payload)
    else:
        records = _parse_basic_payload(payload)
    if not records:
        raise SecurityIdentityError("SEC ticker mapping contains no rows")
    return records


@dataclass
class SecTickerResolver:
    """Resolve ticker, company name, CIK, and exchange from the SEC dataset."""

    cache_dir: Path
    user_agent: Optional[str] = None
    timeout: int = 45
    session: requests.Session = field(init=False)

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.user_agent = self.user_agent or os.getenv("SEC_USER_AGENT")
        session_agent = self.user_agent or (
            "equity-screening-agent/0.1 missing-sec-user-agent"
        )
        self.session = build_session(
            session_agent,
            {"Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
        )

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / SEC_CACHE_FILE

    def _read_cache(self) -> Optional[Tuple[Dict[str, Any], str]]:
        if not self.cache_path.exists():
            return None
        try:
            wrapper = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecurityIdentityError("Invalid SEC ticker mapping cache") from exc
        if not isinstance(wrapper, dict):
            raise SecurityIdentityError("Invalid SEC ticker mapping cache")
        if (
            wrapper.get("provider") != "sec"
            or wrapper.get("endpoint") != "company_tickers_exchange"
            or not isinstance(wrapper.get("payload"), dict)
        ):
            raise SecurityIdentityError("Invalid SEC ticker mapping cache identity")
        fetched_at = _validated_fetch_timestamp(wrapper.get("fetched_at_utc"))
        payload = dict(wrapper["payload"])
        parse_sec_company_tickers(payload)
        return payload, fetched_at

    def _write_cache(
        self,
        payload: Mapping[str, Any],
        fetched_at_utc: str,
    ) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper = {
            "provider": "sec",
            "endpoint": "company_tickers_exchange",
            "source_url": SEC_COMPANY_TICKERS_URL,
            "fetched_at_utc": fetched_at_utc,
            "payload": dict(payload),
        }
        self.cache_path.write_text(json.dumps(wrapper), encoding="utf-8")

    def _fetch(self) -> Dict[str, Any]:
        if not self.user_agent or not self.user_agent.strip():
            raise SecurityIdentityError(
                "SEC_USER_AGENT is required to refresh the SEC ticker mapping"
            )
        response = self.session.get(SEC_COMPANY_TICKERS_URL, timeout=self.timeout)
        if response.status_code != 200:
            raise SecurityIdentityError(
                "SEC returned HTTP "
                f"{response.status_code} for the company ticker mapping"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SecurityIdentityError(
                "SEC returned non-JSON company ticker data"
            ) from exc
        if not isinstance(payload, dict):
            raise SecurityIdentityError(
                "SEC returned an invalid company ticker object"
            )
        parse_sec_company_tickers(payload)
        return payload

    def load(
        self,
        refresh: bool = False,
        cache_only: bool = False,
    ) -> Tuple[List[Dict[str, object]], str]:
        """Load the normalized SEC association table and retrieval timestamp."""

        if refresh and cache_only:
            raise SecurityIdentityError(
                "refresh and cache_only are mutually exclusive"
            )
        cached = None if refresh else self._read_cache()
        if cached is not None and not refresh:
            payload, fetched_at = cached
            return parse_sec_company_tickers(payload), fetched_at
        if cache_only or not refresh:
            raise SecurityIdentityError(
                "SEC ticker mapping cache not found; pass refresh=True to "
                "permit an online request"
            )
        payload = self._fetch()
        fetched_at = _utc_now()
        records = parse_sec_company_tickers(payload)
        self._write_cache(payload, fetched_at)
        return records, fetched_at

    def resolve(
        self,
        ticker: str,
        refresh: bool = False,
        cache_only: bool = False,
    ) -> Dict[str, object]:
        """Resolve one ticker without inferring project GICS classifications."""

        symbol = _normalize_ticker(ticker)
        records, fetched_at = self.load(refresh=refresh, cache_only=cache_only)
        unique_matches = {
            (
                str(record["cik"]),
                str(record["company_name"]),
                record["exchange"],
            ): record
            for record in records
            if record["ticker"] == symbol
        }
        if not unique_matches:
            raise SecurityIdentityNotFoundError(
                f"Ticker {symbol} is not present in the SEC company ticker mapping"
            )
        if len(unique_matches) != 1:
            raise SecurityIdentityError(
                f"SEC company ticker mapping is ambiguous for {symbol}"
            )
        record = next(iter(unique_matches.values()))
        return {
            "schema_version": "1.0.0",
            "source": "sec_company_tickers_exchange",
            "ticker": symbol,
            "company_name": record["company_name"],
            "cik": record["cik"],
            "exchange": record["exchange"],
            "sector": None,
            "industry": None,
            "classification_status": "classification_unavailable",
            "warnings": [
                "sector_classification_unavailable",
                "industry_classification_unavailable",
            ],
            "fetched_at_utc": fetched_at,
        }


def resolve_security_identity(
    ticker: str,
    *,
    cache_dir: Optional[Path] = None,
    refresh: bool = False,
    cache_only: bool = False,
) -> Dict[str, object]:
    """Convenience boundary for the project's default SEC identity cache."""

    resolver = SecTickerResolver(
        cache_dir or PROJECT_ROOT / "data/cache/sec/identity"
    )
    return resolver.resolve(
        ticker,
        refresh=refresh,
        cache_only=cache_only,
    )
