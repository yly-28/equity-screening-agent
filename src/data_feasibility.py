"""Reproduce the initial cached data-feasibility experiment.

This module retains the original 22-symbol evidence. It must not issue new
Nasdaq website requests; current market validation lives in market_coverage.py.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
import requests

from src.features import compute_market_features
from src.fundamentals import (
    FundamentalDataError,
    SecCompanyFactsClient,
    extract_sec_fundamentals,
)
from src.market_data import MarketDataError, NasdaqClient
from src.universe import SP500_WIKIPEDIA_URL, load_sp500_universe


DEFAULT_SAMPLE_TICKERS = (
    "GOOGL",
    "META",
    "AMZN",
    "TSLA",
    "COST",
    "PG",
    "XOM",
    "CVX",
    "JPM",
    "BRK.B",
    "JNJ",
    "UNH",
    "CAT",
    "GE",
    "AAPL",
    "MSFT",
    "LIN",
    "SHW",
    "AMT",
    "PLD",
    "NEE",
    "DUK",
)

FIELD_GROUPS: Dict[str, Sequence[str]] = {
    "universe": ("ticker", "company_name", "sector", "industry", "cik"),
    "market": (
        "price",
        "return_1m",
        "return_3m",
        "return_6m",
        "volatility_20d",
        "volatility_60d",
        "max_drawdown_1y",
        "ma20_gap",
        "volume_trend",
        "relative_strength_3m",
        "beta_1y",
        "market_cap",
    ),
    "fundamental": (
        "annual_revenue",
        "annual_net_income",
        "annual_free_cash_flow",
        "revenue_growth",
        "profit_margin",
        "roe",
        "liabilities_to_equity",
        "annual_pe_proxy",
    ),
}


@dataclass
class FeasibilityResult:
    """In-memory and on-disk outputs from one feasibility run."""

    universe: pd.DataFrame
    features: pd.DataFrame
    coverage: pd.DataFrame
    source_probe: pd.DataFrame
    summary: Dict[str, object]
    summary_path: Path


def _probe_optional_sources(
    as_of: date,
    timeout: int = 20,
) -> List[Dict[str, object]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/126 Safari/537.36"
        )
    }
    probes = [
        (
            "yahoo_chart",
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
            "?range=1y&interval=1d&events=div%2Csplits&formatted=false",
        ),
        (
            "stooq_csv",
            "https://stooq.com/q/d/l/?s=aapl.us&i=d"
            f"&d1={(as_of - timedelta(days=365)).strftime('%Y%m%d')}"
            f"&d2={as_of.strftime('%Y%m%d')}",
        ),
    ]
    results: List[Dict[str, object]] = []
    for source, url in probes:
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            body_prefix = response.text[:1000]
            if source == "yahoo_chart":
                usable = response.status_code == 200 and '"chart"' in body_prefix
                observation = (
                    "usable"
                    if usable
                    else f"HTTP {response.status_code}; anonymous requests are rate limited"
                )
            else:
                browser_challenge = "requires JavaScript to verify your browser" in body_prefix
                usable = response.status_code == 200 and not browser_challenge and "Date," in body_prefix
                observation = (
                    "usable"
                    if usable
                    else "browser verification returned instead of CSV"
                    if browser_challenge
                    else f"HTTP {response.status_code}; no CSV payload"
                )
            results.append(
                {
                    "source": source,
                    "role": "optional_market_fallback",
                    "success_count": int(usable),
                    "attempt_count": 1,
                    "success_rate": float(usable),
                    "observation": observation,
                }
            )
        except requests.RequestException as exc:
            results.append(
                {
                    "source": source,
                    "role": "optional_market_fallback",
                    "success_count": 0,
                    "attempt_count": 1,
                    "success_rate": 0.0,
                    "observation": f"request failed: {type(exc).__name__}",
                }
            )
    return results


def _coverage_table(features: pd.DataFrame) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
    for group, fields in FIELD_GROUPS.items():
        for field in fields:
            series = features[field] if field in features else pd.Series(dtype="object")
            available = int(series.notna().sum())
            total = int(len(features))
            missing_rate = 1 - available / total if total else 1.0
            status = "strong" if missing_rate <= 0.10 else "usable" if missing_rate <= 0.30 else "weak"
            records.append(
                {
                    "group": group,
                    "field": field,
                    "available_count": available,
                    "sample_count": total,
                    "missing_rate": missing_rate,
                    "status": status,
                }
            )
    return pd.DataFrame(records)


def run_data_feasibility(
    project_root: Optional[Path] = None,
    sample_tickers: Sequence[str] = DEFAULT_SAMPLE_TICKERS,
    as_of: Optional[date] = None,
    refresh: bool = False,
) -> FeasibilityResult:
    """Fetch a cross-sector sample, calculate features, and write quality outputs."""

    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    data_dir = root / "data"
    output_dir = root / "outputs" / "data_feasibility"
    output_dir.mkdir(parents=True, exist_ok=True)

    run_date = as_of or date.today()
    market_start = run_date - timedelta(days=400)
    market_end = run_date

    universe = load_sp500_universe(
        data_dir / "raw" / "sp500_universe.csv",
        refresh=refresh,
    )
    universe_by_ticker = universe.set_index("ticker", drop=False)
    selected = [ticker for ticker in sample_tickers if ticker in universe_by_ticker.index]
    missing_from_universe = sorted(set(sample_tickers) - set(selected))
    if missing_from_universe:
        raise ValueError(f"Sample tickers missing from current S&P 500: {missing_from_universe}")

    nasdaq = NasdaqClient(data_dir / "cache" / "nasdaq")
    sec = SecCompanyFactsClient(data_dir / "cache" / "sec")

    benchmark = pd.DataFrame()
    benchmark_error: Optional[str] = None
    try:
        benchmark = nasdaq.historical(
            "SPY",
            start=market_start,
            end=market_end,
            asset_class="etf",
            refresh=refresh,
        )
    except MarketDataError as exc:
        benchmark_error = str(exc)

    rows: List[Dict[str, object]] = []
    all_prices: List[pd.DataFrame] = []
    for ticker in selected:
        universe_row = universe_by_ticker.loc[ticker]
        row: Dict[str, object] = {
            "ticker": ticker,
            "company_name": universe_row["company_name"],
            "sector": universe_row["sector"],
            "industry": universe_row["industry"],
            "cik": universe_row["cik"],
            "universe": universe_row["universe"],
            "market_data_source": "nasdaq_web_json",
            "fundamental_data_source": "sec_companyfacts",
            "market_data_ok": False,
            "market_summary_ok": False,
            "sec_fetch_ok": False,
            "fundamental_core_ok": False,
            "market_error": None,
            "market_summary_error": None,
            "fundamental_error": None,
        }

        try:
            prices = nasdaq.historical(
                ticker,
                start=market_start,
                end=market_end,
                refresh=refresh,
            )
            all_prices.append(prices)
            row.update(compute_market_features(prices, benchmark))
            row["market_data_ok"] = True
        except (MarketDataError, ValueError) as exc:
            row["market_error"] = str(exc)

        try:
            row.update(nasdaq.summary(ticker, refresh=refresh))
            row["market_summary_ok"] = True
        except MarketDataError as exc:
            row["market_summary_error"] = str(exc)

        try:
            company_facts = sec.company_facts(str(universe_row["cik"]), refresh=refresh)
            row["sec_fetch_ok"] = True
            fundamentals = extract_sec_fundamentals(company_facts)
            row.update(fundamentals)
            row["fundamental_core_ok"] = bool(
                fundamentals.get("annual_net_income") is not None
                and fundamentals.get("stockholders_equity") is not None
            )
        except FundamentalDataError as exc:
            row["fundamental_error"] = str(exc)

        market_cap = row.get("market_cap")
        net_income = row.get("annual_net_income")
        if (
            market_cap is not None
            and net_income is not None
            and not pd.isna(market_cap)
            and float(net_income) > 0
        ):
            row["annual_pe_proxy"] = float(market_cap) / float(net_income)
        else:
            row["annual_pe_proxy"] = np.nan
        rows.append(row)

    features = pd.DataFrame(rows).sort_values(["sector", "ticker"]).reset_index(drop=True)
    as_of_timestamp = pd.Timestamp(run_date)
    features["market_data_age_days"] = (
        as_of_timestamp - pd.to_datetime(features["price_data_end"], errors="coerce")
    ).dt.days
    features["fundamental_age_days"] = (
        as_of_timestamp
        - pd.to_datetime(features["fundamental_period_end"], errors="coerce")
    ).dt.days
    coverage = _coverage_table(features)

    source_records = [
        {
            "source": "wikipedia_sp500",
            "role": "universe",
            "success_count": 1,
            "attempt_count": 1,
            "success_rate": 1.0,
            "observation": f"{len(universe)} rows with GICS sector, industry, and CIK",
        },
        {
            "source": "nasdaq_web_json",
            "role": "daily_market_data",
            "success_count": int(features["market_data_ok"].sum()),
            "attempt_count": int(len(features)),
            "success_rate": float(features["market_data_ok"].mean()),
            "observation": "daily OHLCV available; endpoint is undocumented and closes are not labeled adjusted",
        },
        {
            "source": "nasdaq_web_json",
            "role": "market_summary",
            "success_count": int(features["market_summary_ok"].sum()),
            "attempt_count": int(len(features)),
            "success_rate": float(features["market_summary_ok"].mean()),
            "observation": "market cap and classification fields tested",
        },
        {
            "source": "sec_companyfacts",
            "role": "annual_fundamentals",
            "success_count": int(features["sec_fetch_ok"].sum()),
            "attempt_count": int(len(features)),
            "success_rate": float(features["sec_fetch_ok"].mean()),
            "observation": "authoritative filings; cross-company tags require normalization",
        },
    ]
    source_records.extend(_probe_optional_sources(run_date))
    source_probe = pd.DataFrame(source_records)

    market_dates = features.get("price_data_end", pd.Series(dtype="object")).dropna()
    summary: Dict[str, object] = {
        "run_timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "as_of": run_date.isoformat(),
        "market_start": market_start.isoformat(),
        "market_end": market_end.isoformat(),
        "universe_source": SP500_WIKIPEDIA_URL,
        "universe_count": int(len(universe)),
        "universe_sector_count": int(universe["sector"].nunique()),
        "sample_size": int(len(features)),
        "sample_sector_count": int(features["sector"].nunique()),
        "market_success_count": int(features["market_data_ok"].sum()),
        "market_summary_success_count": int(features["market_summary_ok"].sum()),
        "sec_fetch_success_count": int(features["sec_fetch_ok"].sum()),
        "fundamental_core_success_count": int(features["fundamental_core_ok"].sum()),
        "latest_market_data_date": market_dates.max() if not market_dates.empty else None,
        "median_fundamental_age_days": int(features["fundamental_age_days"].median()),
        "max_fundamental_age_days": int(features["fundamental_age_days"].max()),
        "fcf_missing_tickers": features.loc[
            features["annual_free_cash_flow"].isna(), "ticker"
        ].tolist(),
        "benchmark_error": benchmark_error,
    }

    processed_dir = data_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    features.to_csv(processed_dir / "data_feasibility_unified_features.csv", index=False)
    features.to_parquet(processed_dir / "data_feasibility_unified_features.parquet", index=False)
    if all_prices:
        price_frame = pd.concat(all_prices, ignore_index=True)
        price_frame.to_parquet(processed_dir / "data_feasibility_market_prices.parquet", index=False)

    coverage.to_csv(output_dir / "field_coverage.csv", index=False)
    source_probe.to_csv(output_dir / "source_probe.csv", index=False)
    features.to_csv(output_dir / "unified_features_sample.csv", index=False)
    summary_path = output_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )

    return FeasibilityResult(
        universe=universe,
        features=features,
        coverage=coverage,
        source_probe=source_probe,
        summary=summary,
        summary_path=summary_path,
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Ignore local response caches")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Validation date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(DEFAULT_SAMPLE_TICKERS),
        help="Cross-sector sample tickers",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_data_feasibility(
        sample_tickers=args.tickers,
        as_of=args.as_of,
        refresh=args.refresh,
    )
    print(json.dumps(result.summary, indent=2, default=str))
    print(f"Summary: {result.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
