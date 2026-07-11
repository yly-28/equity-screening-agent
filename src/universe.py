"""Stock-universe loaders and normalization."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from src.http_client import build_session


SP500_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UNIVERSE_COLUMNS = [
    "ticker",
    "company_name",
    "sector",
    "industry",
    "cik",
    "yahoo_ticker",
    "universe",
]


class UniverseDataError(RuntimeError):
    """Raised when a universe source cannot produce the required schema."""


def _format_cik(value: object) -> str:
    if pd.isna(value):
        return ""
    try:
        return f"{int(value):010d}"
    except (TypeError, ValueError) as exc:
        raise UniverseDataError(f"Invalid CIK value: {value!r}") from exc


def load_sp500_universe(
    cache_path: Path,
    refresh: bool = False,
    session: Optional[requests.Session] = None,
    timeout: int = 30,
) -> pd.DataFrame:
    """Load the current S&P 500 table and normalize it to the project schema."""

    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        cached = pd.read_csv(cache_path, dtype={"cik": "string"})
        missing = set(UNIVERSE_COLUMNS) - set(cached.columns)
        if not missing:
            return cached[UNIVERSE_COLUMNS].copy()

    session = session or build_session(
        "equity-screening-agent/0.1 academic-data-feasibility"
    )
    response = session.get(SP500_WIKIPEDIA_URL, timeout=timeout)
    response.raise_for_status()

    tables = pd.read_html(StringIO(response.text), attrs={"id": "constituents"})
    if not tables:
        raise UniverseDataError("Wikipedia did not return the S&P 500 constituents table")

    raw = tables[0]
    rename_map = {
        "Symbol": "ticker",
        "Security": "company_name",
        "GICS Sector": "sector",
        "GICS Sub-Industry": "industry",
        "CIK": "cik",
    }
    missing_source_columns = set(rename_map) - set(raw.columns)
    if missing_source_columns:
        raise UniverseDataError(
            f"Wikipedia schema changed; missing columns: {sorted(missing_source_columns)}"
        )

    universe = raw.rename(columns=rename_map)[list(rename_map.values())].copy()
    for column in ("ticker", "company_name", "sector", "industry"):
        universe[column] = universe[column].astype("string").str.strip()
    universe["cik"] = universe["cik"].map(_format_cik).astype("string")
    universe["yahoo_ticker"] = universe["ticker"].str.replace(".", "-", regex=False)
    universe["universe"] = "sp500"
    universe = universe.drop_duplicates(subset=["ticker"]).sort_values("ticker")
    universe = universe.reset_index(drop=True)[UNIVERSE_COLUMNS]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    universe.to_csv(cache_path, index=False)
    return universe
